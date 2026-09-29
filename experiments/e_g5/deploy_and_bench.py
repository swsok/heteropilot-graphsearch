#!/usr/bin/env python
"""P3.2: one E-G5 condition, end to end. Plan, deploy, load, collect.

**REAL HARDWARE when it runs.** `--dry-run` writes every config file and the
exact commands and launches nothing, which is how the harness is checked
without spending device time.

    python experiments/e_g5/deploy_and_bench.py \\
        --condition llama31-8b__normal__T2__knee --rep 42 --dry-run

Four stages, in order, and the first one can stop the other three:

  0. **preconditions** -- no other tenant on any GPU, the load average, the
     node's accel serials, and `git -C vendor/heteropilot status --porcelain`
     empty. Refused rather than warned about. A figure measured beside another
     tenant is not wrong; it is measured under a condition the `REAL HARDWARE`
     banner does not state, and a result produced against an edited submodule
     is not a result about heteropilot.
  1. **plan** -- `python -m graphsearch plan --predictor sim` on
     `fixtures/clusters/real-a40x8.v2.yaml`, giving the recommendation and the
     boundary alternative.
  2. **deploy** -- heteropilot's own `build_serve_command`, with one override.
  3. **load** -- `python -m bench run`, then per-request logs and provenance
     into `experiments/e_g5/raw/<condition>/<rep>/`.

**The one override, and why it is the experiment rather than a workaround.**
`planner/deploy/base.py::resolve_devices` maps an island to *all* of its
accelerator ids, so a TP=2 plan on this node's single 8-GPU island launches
with `CUDA_VISIBLE_DEVICES=0,1,...,7` and vLLM silently takes the first two.
heteropilot names a *template*; it cannot name a *placement*. T1 and T2 run the
same template on devices (0,1) and (0,2) -- an NVLink pair measured at 52.64
GB/s and a PCIe bridge measured at 25.12 -- and the planner cannot tell them
apart. Whether that difference shows up in served TTFT is the question E-G5
exists to answer, so the harness sets the device list and records that it did.

Nothing is monkeypatched. `build_serve_command` is called as it stands and the
env it returns is overridden afterwards, in this repository, which is the same
boundary every other script here keeps.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

sys.path.insert(0, str(Path(__file__).parent))
import conditions as C  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
HETEROPILOT = ROOT / "vendor" / "heteropilot"
CLUSTER = ROOT / "fixtures" / "clusters" / "real-a40x8.v2.yaml"
RAW = ROOT / "experiments" / "e_g5" / "raw"
WORK = ROOT / "outputs" / "e_g5"

#: The interpreter with torch+CUDA and vLLM. Not this repo's `.venv` (no
#: torch) and not the simulator's (`vendor/heteropilot/.venv`, also no torch).
VLLM_PY = Path(
    os.environ.get("E_G5_VLLM_PYTHON", "/home/swsok/heteropilot/.venv-vllm/bin/python")
)


def say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


# --- stage 0: the preconditions ------------------------------------------

def gpu_tenants(exclude_pid: int | None = None) -> list[dict]:
    """Every compute process on every GPU except ours, with its owner."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-compute-apps=pid,process_name,used_gpu_memory",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    tenants = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or (exclude_pid and parts[0] == str(exclude_pid)):
            continue
        owner = subprocess.run(
            ["ps", "-o", "user=", "-p", parts[0]],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
        tenants.append({"pid": parts[0], "process": parts[1],
                        "used_mib": parts[2], "user": owner})
    return tenants


def node_serials() -> str:
    script = HETEROPILOT / "scripts" / "whichnode.sh"
    if not script.exists():
        return "unknown"
    out = subprocess.run(["bash", str(script)], capture_output=True,
                         text=True, timeout=120, check=False).stdout
    for line in out.splitlines():
        if "accel serials" in line:
            return line.split(":", 1)[1].strip()
    return "unknown"


def submodule_is_pristine() -> tuple[bool, str]:
    out = subprocess.run(
        ["git", "-C", str(HETEROPILOT), "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    return (not out), out


def preconditions(args) -> dict:
    """Refuse, rather than warn. Every one of these is in `MATRIX.md` §4."""
    tenants = gpu_tenants(os.getpid())
    pristine, dirt = submodule_is_pristine()
    record = {
        "gpu_tenants_before": tenants,
        "loadavg_before": [round(x, 2) for x in os.getloadavg()],
        "node_serials": node_serials(),
        "submodule_pristine": pristine,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    problems = []
    if tenants and not args.allow_tenants:
        who = "; ".join(f"{t['user']} pid {t['pid']} {t['process']} "
                        f"({t['used_mib']})" for t in tenants)
        problems.append(
            f"another tenant holds a GPU: {who}. A figure measured beside it "
            f"is measured under a condition the REAL HARDWARE banner does not "
            f"state. Wait, or pass --allow-tenants and accept that every row "
            f"of this run is labelled contaminated."
        )
    if not pristine:
        problems.append(
            f"vendor/heteropilot is not pristine:\n{dirt}\nA result produced "
            f"against an edited submodule is not a result about heteropilot."
        )
    if not VLLM_PY.exists():
        problems.append(
            f"{VLLM_PY} does not exist. Set E_G5_VLLM_PYTHON to an interpreter "
            f"with torch+CUDA and vLLM."
        )
    record["problems"] = problems
    return record


# --- stage 1: the plan ----------------------------------------------------

def service_spec(model: str, pattern: str, level: str, rps: float, out: Path) -> Path:
    """One spec per (model, pattern, level). Generated, never hand-edited."""
    info = C.MODELS[model]
    text = f"""\
# E-G5 condition spec. GENERATED by experiments/e_g5/deploy_and_bench.py.
#
# model {model} / pattern {pattern} / level {level}
#
# The traffic shape is heteropilot's own ShareGPT trace statistics, which is
# what `python -m bench run` will actually replay. `arrival_rate_rps` is the
# level's multiple of this model's measured knee, so the axis means the same
# thing for both models.
#
# The SLO limits are the ones the planner is asked to meet. They are NOT
# measurements and nothing here calibrates them.
service:
  model: {info['planner_id']}
  dtype: bfloat16
  kv_cache_dtype: auto

traffic:
  arrival_rate_rps: {rps}
  input_tokens:
    p50: 731
    p95: 2470
    p99: 2884
  output_tokens:
    p50: 632
    p95: 780
  burstiness: {C.PATTERNS[pattern]}
  prefix_share_ratio: 0.0

slo:
  ttft:
    percentile: 99
    max_ms: 2000
  tpot:
    percentile: 99
    max_ms: 50

objective:
  primary: minimize_active_accelerators
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return out


def run_plan(spec_path: Path, work: Path, args):
    """Plan IN PROCESS, because the deploy stage needs objects, not JSON.

    `python -m graphsearch plan` writes a YAML summary, and a summary cannot be
    launched: `VllmCudaBackend.launch` wants a `DeploymentPlan`. Re-deriving one
    by parsing the summary would be a second, quietly different code path, and
    the first time the two disagreed the deployment would not match the plan it
    claims to be.

    So this calls the same pipeline `cmd_plan` calls, with the same arguments,
    and `tests/test_e_g5_harness.py` pins that the flags stay in step.
    """
    from types import SimpleNamespace

    from graphsearch.__main__ import cmd_plan_objects

    args_for_plan = SimpleNamespace(
        service=str(spec_path), cluster=str(CLUSTER),
        profiles_root=str(ROOT), predictor=args.predictor,
        no_enable_pd=False, ranker="service_margin",
        num_requests=args.num_requests, seed=args.rep,
        cache_dir=str(WORK / "cache"), work_dir=str(work / "sim"),
        timeout=args.sim_timeout, max_workers=args.max_workers,
        contention="fluid", k_schedule=[4, 8, 16],
        search_mode="budget", budget_sims=args.budget_sims,
        budget_seconds=None, epsilon=0.0,
        max_embeddings_per_template=None, compression="exact",
        bounds="all", diversity=False, oracle=False, output=None,
        # The topology condition names a placement, and a placement has a fixed
        # device count -- so the planner is asked "what is the best plan using
        # at most this many devices", and its answer is what gets placed. Left
        # unbounded, the search on an eight-GPU node recommends an eight-device
        # plan, which has exactly ONE placement and therefore no contrast to
        # measure (GS-27). This is `excluded_by_scope`, recorded in every raw
        # file, never a judgement that larger plans are worse.
        max_devices=len(C.TOPOLOGIES[args.topology_key].devices),
    )
    return cmd_plan_objects(args_for_plan)


def candidates_of_size(objects, devices: int) -> list:
    """Ranked candidates that use exactly `devices` accelerators, best first.

    **A topology condition names a PLACEMENT, and a placement has a fixed
    device count.** T2 is "this template, on gpu0 and gpu2"; it is not a
    template of its own. So the condition can only be applied to a candidate
    that uses two devices, and asking for the recommendation regardless
    produced the command the first dry run emitted:

        CUDA_VISIBLE_DEVICES=0,2 vllm serve ... --tensor-parallel-size 8

    -- two devices visible, eight ranks requested. vLLM would refuse it
    instantly, and a harness that emits it has not been checked. Selecting by
    device count is what makes T1 and T2 two placements of ONE template, which
    is the comparison E-G5 exists to make: the planner cannot tell them apart,
    and everything else about them is equal by construction.
    """
    out = []
    recommended = objects.output.recommended
    for entry in [recommended, *(getattr(objects.output, "alternatives", []) or [])]:
        if entry is None:
            continue
        plan_obj = getattr(entry, "plan", entry)
        if plan_obj.candidate.total_devices == devices:
            out.append(entry)
    return out


def boundary_alternative(objects) -> tuple[object | None, str]:
    """The second deployment, and the kind of question it asks.

    `MATRIX.md` §2. The tightest `impossible_proven` is preferred when one
    exists, because it is the real-hardware test of `false_infeasible`: deploy
    the candidate the lower bound rejected by the smallest margin, and if it
    meets the SLO then the bound rejected something that worked. The registered
    response to that is to stop and report, never to relax the test.
    """
    rejections = list(getattr(objects, "rejections", []) or [])
    proven = [
        r for r in rejections
        if getattr(r, "state", None) == "impossible_proven"
        and getattr(r, "margin", None) is not None
    ]
    if proven:
        return min(proven, key=lambda r: abs(r.margin)), "impossible_proven (tightest)"

    alternatives = list(getattr(objects.output, "alternatives", []) or [])
    if alternatives:
        return alternatives[0], "feasible-marginal (Pareto alternative)"
    return None, "none available"


# --- stage 2: the deployment ---------------------------------------------

def serve_command(plan_obj, islands, topo: C.Topology, port: int):
    """heteropilot's own builder, then the placement override.

    `build_serve_command` is imported and called unmodified; only the env it
    returns is changed, and only `CUDA_VISIBLE_DEVICES`. Both values go into
    the raw record so a reader sees what heteropilot would have done and what
    was done instead.
    """
    from planner.deploy.vllm_cuda import build_serve_command

    assignment = plan_obj.candidate.assignments[0]
    island = islands[assignment.island_id]
    command = build_serve_command(plan_obj, assignment, island, port=port)
    placed = ",".join(str(d) for d in topo.devices)
    override = {
        "heteropilot_would_use": command.env.get("CUDA_VISIBLE_DEVICES", ""),
        "this_harness_uses": placed,
        "why": (
            "planner/deploy/base.py::resolve_devices maps an island to ALL of "
            "its accelerator ids, so heteropilot names a TEMPLATE and cannot "
            "name a PLACEMENT. "
            f"{topo.key} is the placement under test: {topo.link}."
        ),
    }
    return list(command.argv), dict(command.env, CUDA_VISIBLE_DEVICES=placed), override


def wait_for_health(port: int, timeout: float, process) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=5
            ) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(5)
    return False


# --- stage 3: the load ----------------------------------------------------

def background_load(topo: C.Topology, args):
    """T3's 60 % background, from the E-G4 harness. Target, not achieved.

    `run_pair.py` records what it actually sustained and the analysis uses
    that: a generator that missed its target and a model that missed its
    prediction are different failures and must not cancel.
    """
    if topo.background is None or args.dry_run:
        return None
    src, dst = topo.background
    argv = [
        str(VLLM_PY), str(ROOT / "experiments" / "microbench" / "run_pair.py"),
        "--condition", "single", "--pairs", f"{src}-{dst}",
        "--share", "independent", "--binding", "unpinned",
        "--background-util", "0.6", "--background-pair", f"{src}-{dst}",
        "--iters", "1000000", "--sizes", "256",
        "--label", f"e_g5-background-{src}-{dst}",
        "--out-root", str(WORK / "background"),
    ]
    say(f"background: 60 % target on gpu{src}-gpu{dst}")
    return subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def run_bench(model: str, workload: Path, out_dir: Path, topo: C.Topology,
              seed: int, port: int, args) -> dict:
    info = C.MODELS[model]
    argv = [
        str(VLLM_PY), "-m", "bench", "run",
        "--model", info["hf_id"],
        "--dataset", str(workload),
        "--output-dir", str(out_dir),
        "--tensor-parallel-size", str(topo.tp),
        "--seed", str(seed),
    ]
    (out_dir.parent / "bench.cmd").write_text(
        " ".join(shlex.quote(a) for a in argv) + "\n"
    )
    if args.dry_run:
        return {"dry_run": True, "argv": argv}
    env = dict(os.environ,
               PYTHONPATH=str(HETEROPILOT),
               CUDA_VISIBLE_DEVICES=",".join(str(d) for d in topo.devices))
    say("bench: " + " ".join(shlex.quote(a) for a in argv[2:8]))
    result = subprocess.run(argv, cwd=HETEROPILOT, env=env,
                            capture_output=True, text=True,
                            timeout=args.bench_timeout)
    (out_dir.parent / "bench.log").write_text(result.stdout + result.stderr)
    return {"returncode": result.returncode, "argv": argv}


def deploy_and_measure(objects, plan_obj, label: str, topo: C.Topology,
                       model: str, workload: Path, out_dir: Path,
                       args) -> dict:
    """One deployment: serve, wait, load, tear down. Always tears down."""
    out_dir.mkdir(parents=True, exist_ok=True)
    argv, env, override = serve_command(
        plan_obj, objects.islands_by_id, topo, args.port
    )
    (out_dir / "serve.cmd").write_text(
        " ".join(f"{k}={v}" for k, v in sorted(env.items()))
        + " " + " ".join(shlex.quote(a) for a in argv) + "\n"
    )
    record: dict = {"label": label, "placement_override": override,
                    "serve_argv": argv}
    if args.dry_run:
        record["dry_run"] = True
        return record

    say(f"{label}: serving on devices {override['this_harness_uses']}")
    log = (out_dir / "vllm.log").open("w")
    background = background_load(topo, args)
    process = subprocess.Popen(
        argv, cwd=HETEROPILOT, env=dict(os.environ, **env),
        stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        healthy = wait_for_health(args.port, args.health_timeout, process)
        record["healthy"] = healthy
        if not healthy:
            record["error"] = (
                "the engine never became healthy. This is recorded as a "
                "failed deployment, not retried until it passes: a condition "
                "that only works on the third attempt is a condition that "
                "does not work."
            )
            return record
        record["bench"] = run_bench(
            model, workload, out_dir / "bench", topo, args.rep, args.port, args
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
        if background is not None:
            background.terminate()
        log.close()
    return record


# --- the driver -----------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", required=True,
                        help="model__pattern__topology__level, e.g. "
                             "llama31-8b__normal__T2__knee")
    parser.add_argument("--rep", type=int, default=C.REPS[0])
    parser.add_argument("--rps", type=float, default=None,
                        help="absolute arrival rate; default is the level's "
                             "multiple of --knee-rps")
    parser.add_argument("--knee-rps", type=float, default=None,
                        help="this model's MEASURED knee. Required unless "
                             "--rps is given: there is no defensible default, "
                             "and a guessed one would put every level's label "
                             "on the wrong load.")
    parser.add_argument("--workload", type=Path, default=None)
    parser.add_argument("--predictor", choices=("mock", "sim"), default="sim")
    parser.add_argument("--num-requests", type=int, default=30)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--budget-sims", type=int, default=16)
    parser.add_argument("--sim-timeout", type=float, default=1800)
    parser.add_argument("--health-timeout", type=float, default=900)
    parser.add_argument("--bench-timeout", type=float, default=1800)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dry-run", action="store_true",
                        help="write every config file and command; launch "
                             "nothing and touch no GPU")
    parser.add_argument("--allow-tenants", action="store_true",
                        help="proceed although another tenant holds a GPU. "
                             "Every row is then labelled contaminated.")
    args = parser.parse_args(argv)

    model, pattern, topo_key, level = C.parse(args.condition)
    topo = C.TOPOLOGIES[topo_key]
    info = C.MODELS[model]
    args.topology_key = topo_key

    if topo.tp < info["min_tp"]:
        raise SystemExit(
            f"{model} needs tp>={info['min_tp']} ({info['weights_gb']} GB of "
            f"bf16 weights on 45 GB usable devices) and {topo_key} is tp="
            f"{topo.tp}. impossible_proven, not a budget: the combination is "
            f"excluded from the grid rather than merely unattempted."
        )
    if args.rps is None and args.knee_rps is None:
        raise SystemExit(
            "pass --rps, or --knee-rps from the pilot. There is no defensible "
            "default: a guessed knee puts 'low', 'knee' and 'high' on three "
            "loads that are not those things, and every row would then be "
            "labelled with a condition it was not run under."
        )

    out_dir = RAW / args.condition / str(args.rep)
    work = WORK / args.condition / str(args.rep)
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    say(f"condition {args.condition} rep {args.rep}"
        + ("  [DRY RUN]" if args.dry_run else ""))

    pre = preconditions(args)
    if pre["problems"] and not args.dry_run:
        for problem in pre["problems"]:
            print(f"REFUSED: {problem}", file=sys.stderr)
        (out_dir / "refused.json").write_text(json.dumps(pre, indent=2) + "\n")
        return 1
    for problem in pre["problems"]:
        say("(dry run) would refuse: " + problem.splitlines()[0])

    rps = args.rps if args.rps is not None else args.knee_rps * C.LEVELS[level]
    spec_path = service_spec(model, pattern, level, rps, work / "service.yaml")

    say(f"planning ({args.predictor}) at {rps:.2f} rps")
    objects = run_plan(spec_path, work, args)
    alternative, alternative_kind = boundary_alternative(objects)

    workload = args.workload or (
        HETEROPILOT / "workloads" /
        ("sharegpt-llama-3.1-8b-300-sps10.jsonl" if model == "llama31-8b"
         else "sharegpt-qwen3-32b-300-sps10.jsonl")
    )

    # The condition names a placement, so only candidates with that many
    # devices can carry it. See `candidates_of_size`.
    sized = candidates_of_size(objects, len(topo.devices))
    chosen = [
        ("recommendation", sized[0] if sized else None),
        ("boundary", alternative if alternative in sized else
                     (sized[1] if len(sized) > 1 else None)),
    ]

    deployments = []
    for label, entry in chosen:
        if entry is None:
            deployments.append({
                "label": label,
                "state": "not applicable to this topology",
                "why": (
                    f"{topo.key} places {len(topo.devices)} devices, and the "
                    f"search returned no candidate of that size for the "
                    f"{label} slot. Recorded rather than forced: a TP=8 plan "
                    f"launched on two visible devices is not this condition "
                    f"measured badly, it is a different condition that does "
                    f"not run."
                ),
                "boundary_kind": alternative_kind if label == "boundary" else None,
            })
            continue
        plan_obj = getattr(entry, "plan", entry)
        assignment = plan_obj.candidate.assignments[0]
        if assignment.total_devices != len(topo.devices):   # pragma: no cover
            raise SystemExit(
                f"internal: selected a {assignment.total_devices}-device "
                f"candidate for {topo.key}, which places {len(topo.devices)}"
            )
        deployments.append(deploy_and_measure(
            objects, plan_obj, label, topo, model, workload,
            out_dir / label, args,
        ))

    record = {
        "banner": (
            "DRY RUN -- nothing was launched and no number here is a "
            "measurement. Configs and commands are recorded exactly as they "
            "would run."
            if args.dry_run else
            "REAL HARDWARE -- node serials in `preconditions`."
        ),
        "condition": args.condition,
        "model": model, "pattern": pattern, "topology_key": topo_key,
        "level": level, "rep": args.rep,
        "arrival_rate_rps": rps,
        "hf_model": info["hf_id"], "planner_model": info["planner_id"],
        "model_substitution_note": (
            "the planner is given the gated `meta-llama/...` id that "
            "heteropilot's profiles name; the engine serves the ungated "
            "NousResearch mirror of the same weights"
            if info["hf_id"] != info["planner_id"] else None
        ),
        "has_accuracy_domain": info["accuracy_domain"],
        "calibration": (
            "existing a40.accuracy.yaml only; no new domain may be created "
            "from this run"
            if info["accuracy_domain"] else
            "UNCALIBRATED -- no A40 accuracy domain exists for this model, "
            "and creating one from this run is the circular evaluation the "
            "work order forbids"
        ),
        "scope_cut": {
            "max_devices": len(topo.devices),
            "state": "excluded_by_scope",
            "why": (
                "the topology condition places this many devices, so the "
                "planner was asked for the best plan of that size. Larger "
                "plans were not considered -- not considered and rejected "
                "(GS-27)."
            ),
        },
        "topology": {
            "key": topo.key, "devices": list(topo.devices), "tp": topo.tp,
            "link": topo.link, "substitutes": topo.substitutes,
            "background_pair": list(topo.background) if topo.background else None,
        },
        "boundary_alternative_kind": alternative_kind,
        "deployments": deployments,
        "preconditions": pre,
        "gpu_tenants_after": gpu_tenants(os.getpid()),
        "loadavg_after": [round(x, 2) for x in os.getloadavg()],
        "dry_run": args.dry_run,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "provenance.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str) + "\n"
    )
    say(f"wrote {out_dir / 'provenance.json'}")
    if args.dry_run:
        say("dry run complete: nothing was launched, no GPU was touched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
