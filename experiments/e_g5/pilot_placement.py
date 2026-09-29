#!/usr/bin/env python
"""E-G5 pilot: the same engine, the same trace, three placements.

**REAL HARDWARE.** Every number this writes is measured on the node whose
serials the record carries.

This is the part of E-G5 that needs **no planner at all**, which is why it runs
first. The question is the research design's counterexample, asked directly:

    T1  TP=2 on devices (0,1)      NVLink NV4, measured 52.64 GB/s p2p
    T2  TP=2 on devices (0,2)      PCIe bridge, measured 25.12 GB/s p2p
    T3  TP=4 on devices (0,1,2,3)  two NVLink pairs bridged; all-reduce busbw
                                   measured 8.71 GB/s at world 4 vs 19.34 at 2

Same model, same trace, same engine knobs, same seed. **The only difference is
which wires the tensor-parallel all-reduce runs over** -- and heteropilot
cannot express that difference at all: `planner/deploy/base.py::resolve_devices`
maps an island to ALL of its accelerator ids, so a TP=2 plan on this node's
single 8-GPU island launches with `CUDA_VISIBLE_DEVICES=0,...,7` and vLLM takes
the first two. It names a TEMPLATE; T1 and T2 are two PLACEMENTS of that one
template.

If T1 and T2 differ in served p99 TTFT, a planner that cannot tell them apart
cannot have chosen between them, and that is the whole argument.

It also produces the **knee**, which the main harness refuses to run without:
`--knee-rps` has no defensible default, because a guessed knee puts `low`,
`knee` and `high` on three loads that are not those things.

    python experiments/e_g5/pilot_placement.py --reps 42 43 44
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import conditions as C

ROOT = Path(__file__).resolve().parents[2]
HETEROPILOT = ROOT / "vendor" / "heteropilot"
VLLM_PY = Path(os.environ.get(
    "E_G5_VLLM_PYTHON", "/home/swsok/heteropilot/.venv-vllm/bin/python"
))
OUT = ROOT / "outputs" / "e_g5" / "pilot"


def say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def tenants() -> list[dict]:
    out = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory",
         "--format=csv,noheader"],
        capture_output=True, text=True, timeout=30, check=False,
    ).stdout
    rows = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or parts[0] == str(os.getpid()):
            continue
        owner = subprocess.run(["ps", "-o", "user=", "-p", parts[0]],
                               capture_output=True, text=True,
                               check=False).stdout.strip()
        rows.append({"pid": parts[0], "process": parts[1],
                     "used_mib": parts[2], "user": owner})
    return rows


def serials() -> str:
    script = HETEROPILOT / "scripts" / "whichnode.sh"
    out = subprocess.run(["bash", str(script)], capture_output=True,
                         text=True, check=False).stdout
    for line in out.splitlines():
        if "accel serials" in line:
            return line.split(":", 1)[1].strip()
    return "unknown"


def one_run(topo: C.Topology, rep: int, args) -> dict:
    """One bench replay at one placement. Records who else was on the node."""
    # `--tag` instead of moving the directory afterwards. An earlier sweep
    # shelled out `mv outputs/.../T1/42 outputs/.../knee-rps$r` per rate: the
    # first pass failed, moved the PREVIOUS run's directory instead, and the
    # second pass then nested each result one level deeper. A failed run's
    # provenance.json also overwrote a good run's, which cost that cell its
    # record of node serials, tenants and load -- so the cell had to be
    # measured again. The destination is chosen before anything runs now.
    out_dir = OUT / (args.tag or topo.key) / str(rep)
    out_dir.mkdir(parents=True, exist_ok=True)
    devices = ",".join(str(d) for d in topo.devices)

    before, load_before = tenants(), os.getloadavg()
    if before and not args.allow_tenants:
        return {"placement": topo.key, "rep": rep, "refused": True,
                "gpu_tenants": before,
                "why": "another tenant holds a GPU; a REAL HARDWARE figure "
                       "taken beside one is measured under a condition the "
                       "banner does not state"}

    argv = [
        str(VLLM_PY), "-u", "-m", "bench", "run",
        "--model", C.MODELS["llama31-8b"]["hf_id"],
        "--dataset", str(args.dataset),
        "--output-dir", str(out_dir / "bench"),
        "--tensor-parallel-size", str(topo.tp),
        "--seed", str(rep),
    ]
    if args.num_reqs:
        argv += ["--num-reqs", str(args.num_reqs)]

    say(f"{topo.key} rep {rep}: TP={topo.tp} on devices {devices}")
    started = time.time()
    result = subprocess.run(
        argv, cwd=HETEROPILOT,
        env=dict(os.environ, CUDA_VISIBLE_DEVICES=devices,
                 PYTHONPATH=str(HETEROPILOT), HF_HUB_OFFLINE="1"),
        capture_output=True, text=True, timeout=args.timeout,
    )
    (out_dir / "bench.log").write_text(result.stdout + result.stderr)
    record = {
        "banner": "REAL HARDWARE",
        "placement": topo.key,
        "devices": list(topo.devices),
        "tp": topo.tp,
        "link": topo.link,
        "rep": rep,
        "returncode": result.returncode,
        "wall_s": round(time.time() - started, 2),
        "node_serials": serials(),
        "gpu_tenants_before": before,
        "gpu_tenants_after": tenants(),
        "loadavg_before": [round(x, 2) for x in load_before],
        "loadavg_after": [round(x, 2) for x in os.getloadavg()],
        "cuda_visible_devices": devices,
        "heteropilot_would_use": "0,1,2,3,4,5,6,7",
        "why_overridden": (
            "resolve_devices() maps an island to ALL of its accelerator ids, "
            "so heteropilot names a template and cannot name a placement. "
            "This placement is the variable under test."
        ),
        "dataset": str(args.dataset),
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "provenance.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    say(f"{topo.key} rep {rep}: rc={result.returncode} in {record['wall_s']}s")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placements", nargs="+", default=["T1", "T2", "T3"])
    parser.add_argument("--reps", type=int, nargs="+", default=list(C.REPS))
    parser.add_argument(
        "--dataset", type=Path,
        default=HETEROPILOT / "workloads" / "sharegpt-llama-3.1-8b-300-sps10.jsonl",
    )
    parser.add_argument("--num-reqs", type=int, default=0)
    parser.add_argument("--tag", default=None,
                        help="output subdirectory instead of the placement "
                             "key, e.g. knee-rps2")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--allow-tenants", action="store_true")
    args = parser.parse_args(argv)
    # `bench run` is launched with cwd=vendor/heteropilot so it can import
    # `bench`, which means a repo-relative --dataset resolves against the wrong
    # directory and fails six seconds in with FileNotFoundError. Resolved here,
    # once, rather than left for every caller to remember.
    args.dataset = args.dataset.resolve()
    if not args.dataset.exists():
        raise SystemExit(f"--dataset {args.dataset} does not exist")

    records = []
    for key in args.placements:
        for rep in args.reps:
            records.append(one_run(C.TOPOLOGIES[key], rep, args))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"pilot{'-' + args.tag if args.tag else ''}.json").write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n"
    )
    failed = [r for r in records if r.get("returncode") not in (0, None)
              or r.get("refused")]
    say(f"pilot complete: {len(records)} runs, {len(failed)} failed/refused")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
