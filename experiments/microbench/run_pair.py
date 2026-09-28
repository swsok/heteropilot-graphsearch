#!/usr/bin/env python
"""E-G4 P2.2: time two transfers that want the same wire, and one that does not.

heteropilot's `experiments/p2_evidence/p2p_probe.py` times **one** peer copy at
a time. That is the right instrument for "how fast is this link", and the wrong
one for E-G4, whose entire question is what happens when two transfers overlap.
This imports that module for its timing primitives and adds the only thing
missing: concurrency.

    --concurrent 2 --share same          two copies over ONE shared bridge
    --concurrent 2 --share independent   two copies over disjoint bridges
    --background-util 0.6                a third process holding the resource

**Nothing here is edited into `vendor/heteropilot`.** The probe is imported by
path and used as it stands; the boundary rule is that only hook PRs reach that
repository, and a benchmark is not a hook.

**Every run records who else was on the node.** A bandwidth figure measured
while another tenant drives half the machine is not wrong -- it is measured
under a condition the `REAL HARDWARE` banner does not state. So the raw file
carries `nvidia-smi --query-compute-apps` from before and after, and the
analysis refuses a run whose occupancy changed mid-flight. The measurement
labels itself; nobody has to remember.

This produces RAW DATA and no verdict. `analyze.py` (P2.4) compares it against
the two contention models, and only after the raw files are committed.

    python experiments/microbench/run_pair.py \\
        --condition two-same --pairs 0-2,1-3 --label a40-same-bridge

Read `experiments/microbench/PLAN.md` first: it says which device pairs mean
what on this node, and why GPUs 0-3 are preferred while a tenant holds 4-7.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HETEROPILOT = REPO / "vendor" / "heteropilot"
PROBE = HETEROPILOT / "experiments" / "p2_evidence" / "p2p_probe.py"

#: 1 MiB to 256 MiB, doubling. The grid PLAN.md registers, and it crosses
#: heteropilot's `small`/`mid`/`bulk` boundaries on purpose -- each figure is
#: filed under the class its OWN bytes fall in, never one label for the sweep.
SIZES_MIB = [1, 2, 4, 8, 16, 32, 64, 128, 256]

CONDITIONS = {
    "single": "one transfer, nothing else running (the control)",
    "two-same": "two concurrent transfers over the SAME shared resource",
    "two-independent": "two concurrent transfers over DISJOINT resources",
    "bidirectional": "A->B and B->A at once over the same resource",
    "collective": "all-reduce, varying world size (delegated to link_probe.py)",
}


def load_probe():
    """heteropilot's p2p probe, imported by path and not modified.

    By path because `experiments/` is not a package there either, and a
    `sys.path` insert would put the whole of that tree on the import path.
    """
    if not PROBE.exists():
        raise SystemExit(
            f"{PROBE} is missing. Run `git submodule update --init` first."
        )
    spec = importlib.util.spec_from_file_location("hp_p2p_probe", PROBE)
    if spec is None or spec.loader is None:      # pragma: no cover - defensive
        raise SystemExit(f"could not load {PROBE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["hp_p2p_probe"] = module
    spec.loader.exec_module(module)
    return module


# --- who else is on this node -------------------------------------------

def gpu_occupancy(exclude_pid: int | None = None) -> list[dict]:
    """Every compute process on every GPU **except this one**, with its owner.

    Not a nicety. `docs/nodes/PREP.md` and PLAN.md both say a figure measured
    beside another tenant holds under a condition the banner does not state,
    and the only way that survives into the analysis is if the raw file carries
    it. Returns [] when nvidia-smi is absent, which is itself recorded.

    **`exclude_pid` is the whole reason this takes an argument.** The `after`
    snapshot is taken while this process still holds a CUDA context on every
    device it touched, so without it the run always finds itself in `after`
    and never in `before`, `occupancy_stable` is False on every run, and the
    analysis refuses data that was measured on a perfectly quiet node. A check
    that can never pass is worse than no check: it reads as vigilance and
    throws away good measurements.
    """
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv,noheader",
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    processes = []
    for line in out.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        pid = parts[0]
        if exclude_pid is not None and pid == str(exclude_pid):
            continue
        owner = ""
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            owner = subprocess.run(
                ["ps", "-o", "user=", "-p", pid],
                capture_output=True, text=True, timeout=10, check=False,
            ).stdout.strip()
        processes.append(
            {"pid": pid, "process": parts[1], "used_mib": parts[2], "user": owner}
        )
    return processes


def observed_affinity() -> dict:
    """The CPU and memory nodes this process is ACTUALLY allowed to use.

    `--binding` is what the operator claims; this is what the kernel says. They
    are recorded side by side so a `numa_pinned` label can be checked rather
    than trusted -- the mistake PLAN.md warns about is passing
    `--binding numa_pinned` without having wrapped the command in `numactl`,
    and a claim nobody can check is the one that survives longest.
    """
    out: dict = {}
    try:
        for line in pathlib.Path("/proc/self/status").read_text().splitlines():
            for field in ("Cpus_allowed_list", "Mems_allowed_list"):
                if line.startswith(field):
                    out[field] = line.split(":", 1)[1].strip()
    except OSError:                                  # pragma: no cover
        return {"available": False}
    out["available"] = bool(out)
    total = os.cpu_count() or 0
    # An unrestricted list is the signature of "not pinned". Compared against
    # the CPU count rather than parsed, because the formats vary (`0-63`,
    # `0-15,32-47`) and a parser that got it subtly wrong would be worse than
    # this.
    out["looks_unrestricted"] = bool(total) and out.get(
        "Cpus_allowed_list"
    ) == f"0-{total - 1}"
    out["mempolicy"] = mempolicy()
    out["mem_is_bound"] = out["mempolicy"].startswith(("bind:", "prefer:"))
    return out


def mempolicy() -> str:
    """The NUMA memory policy, read where `numactl --membind` actually lands.

    **`Mems_allowed_list` cannot see `--membind`** and PLAN.md's first
    verification recipe said to check it there. The two are different
    mechanisms: `Mems_allowed_list` is the *cpuset* allowance, while
    `--membind` installs a *mempolicy*. Under
    `numactl --cpunodebind=0 --membind=0` on this node the kernel still
    reports `Mems_allowed_list: 0-1`, so an operator following that recipe
    would conclude the pin failed when it had not.

    `/proc/self/numa_maps` is where it shows: `bind:0` against every mapping
    under `--membind=0`, `default` without it. The first mapping's policy is
    the process policy for anything allocated afterwards, which is what a
    transfer buffer is.

    Returns `"unknown"` when the file cannot be read, which is not the same
    claim as `default`.
    """
    try:
        with open("/proc/self/numa_maps") as handle:
            first = handle.readline().split()
    except OSError:                                  # pragma: no cover
        return "unknown"
    return first[1] if len(first) > 1 else "unknown"


def node_serials() -> str:
    """The `accel serials` string -- what identifies the MACHINE.

    The node KIND does not: any box with an RNGD reads `npu`. Taken from
    `whichnode.sh` so there is one definition of it in the project.
    """
    script = HETEROPILOT / "scripts" / "whichnode.sh"
    if not script.exists():
        return "unknown"
    try:
        out = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True,
            timeout=120, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    for line in out.splitlines():
        if "accel serials" in line:
            return line.split(":", 1)[1].strip()
    return "unknown"


# --- the background load ------------------------------------------------

class BackgroundLoad:
    """A thread holding a device pair at a target occupancy.

    Duty-cycled rather than rate-limited: it copies, then sleeps for
    `(1 - util) / util` of the time the copy took. That targets a fraction of
    the *achievable* bandwidth without needing to know what that is, which
    matters because the achievable figure is what this whole experiment is
    trying to establish.

    **It records what it actually sustained**, and the analysis uses that
    rather than the target. A generator that missed its target and a model that
    missed its prediction are different failures and must not cancel.
    """

    def __init__(self, probe, src: int, dst: int, nbytes: int, util: float):
        self.probe = probe
        self.src, self.dst, self.nbytes, self.util = src, dst, nbytes, util
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.bytes_moved = 0
        self.busy_s = 0.0
        self.wall_s = 0.0

    def _run(self) -> None:
        import torch

        source = torch.ones(
            self.nbytes // 2, dtype=torch.bfloat16, device=f"cuda:{self.src}"
        )
        sink = torch.empty_like(source, device=f"cuda:{self.dst}")
        started = time.perf_counter()
        while not self._stop.is_set():
            t0 = time.perf_counter()
            sink.copy_(source)
            torch.cuda.synchronize(self.dst)
            busy = time.perf_counter() - t0
            self.busy_s += busy
            self.bytes_moved += self.nbytes
            if self.util < 1.0:
                time.sleep(busy * (1.0 - self.util) / self.util)
        self.wall_s = time.perf_counter() - started

    def __enter__(self) -> BackgroundLoad:
        if self.util <= 0:
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        time.sleep(0.5)          # let it reach steady state before timing
        return self

    def __exit__(self, *exc) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=30)

    def as_dict(self) -> dict:
        achieved = self.busy_s / self.wall_s if self.wall_s > 0 else None
        return {
            "target_util": self.util,
            "achieved_duty_cycle": achieved,
            "bytes_moved": self.bytes_moved,
            "busy_s": round(self.busy_s, 4),
            "wall_s": round(self.wall_s, 4),
            "pair": f"{self.src}-{self.dst}",
            "note": (
                "duty cycle, not a bandwidth fraction; the analysis uses "
                "achieved_duty_cycle and never target_util"
            ),
        }


# --- the measurements ---------------------------------------------------

def _copy_many(probe, pairs: list[tuple[int, int]], nbytes: int, iters: int):
    """Run one copy per pair CONCURRENTLY, one thread each, and time each.

    Concurrency is the whole point, so the threads are started together and
    each records its own elapsed time. A sequential loop would measure the same
    thing `p2p_probe.py` already measures.
    """
    import torch

    buffers = []
    for src, dst in pairs:
        source = torch.ones(nbytes // 2, dtype=torch.bfloat16, device=f"cuda:{src}")
        buffers.append((source, torch.empty_like(source, device=f"cuda:{dst}")))

    samples: list[list[float]] = [[] for _ in pairs]
    barrier = threading.Barrier(len(pairs))

    def one(index: int) -> None:
        source, sink = buffers[index]
        _, dst = pairs[index]
        for _ in range(probe.WARMUP):
            sink.copy_(source)
        torch.cuda.synchronize(dst)
        for _ in range(iters):
            barrier.wait()               # start every copy together
            t0 = time.perf_counter()
            sink.copy_(source)
            torch.cuda.synchronize(dst)
            samples[index].append(time.perf_counter() - t0)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(len(pairs))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return samples


def measure(probe, args, pairs: list[tuple[int, int]]) -> dict:
    """One condition, the whole size grid. Raw numbers, no verdict."""
    import torch

    results: dict[str, dict] = {}
    for mib in args.sizes:
        nbytes = mib << 20
        background = None
        load = BackgroundLoad(
            probe, *args.background_pair, nbytes, args.background_util
        )
        with load:
            samples = _copy_many(probe, pairs, nbytes, args.iters)
        if args.background_util > 0:
            # **After** the `with`, never inside it. `wall_s` is assigned when
            # the generator thread leaves its loop, which `__exit__` is what
            # causes; a snapshot taken inside reads `wall_s = 0.0`, and
            # `achieved_duty_cycle` is then None for every size in the grid.
            # That is the one field the analysis is told to use -- the note in
            # the record says "uses achieved_duty_cycle and never
            # target_util" -- so the background conditions would have carried
            # a target nobody could check instead of a measurement.
            background = load.as_dict()

        per_pair = {}
        for (src, dst), timings in zip(pairs, samples, strict=True):
            per_pair[f"{src}-{dst}"] = {
                **probe._summarise(sorted(timings), nbytes, legs=1),
                "peer_access": bool(torch.cuda.can_device_access_peer(src, dst)),
                "samples_s": sorted(timings),
            }
        results[f"{mib}MiB"] = {
            "msg_bytes": nbytes,
            "msg_size_class": _class_of(nbytes),
            "pairs": per_pair,
            "background": background,
        }
        print(
            f"  {mib:4d} MiB  "
            + "  ".join(
                f"{k} {v['bandwidth_gbps']:6.2f} GB/s" for k, v in per_pair.items()
            ),
            flush=True,
        )
    return results


def _class_of(nbytes: int) -> str:
    """heteropilot's own bands, so a figure cannot be filed under the wrong one."""
    sys.path.insert(0, str(HETEROPILOT))
    from planner.inventory import msg_size_class_of

    return str(msg_size_class_of(nbytes))


def _pairs(text: str) -> list[tuple[int, int]]:
    out = []
    for chunk in text.split(","):
        src, dst = (int(x) for x in chunk.split("-"))
        out.append((src, dst))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--condition", required=True, choices=sorted(CONDITIONS),
        help="; ".join(f"{k}: {v}" for k, v in sorted(CONDITIONS.items())),
    )
    parser.add_argument(
        "--pairs", default="0-2",
        help="device pairs to drive, e.g. '0-2' or '0-2,1-3'. PLAN.md says "
             "which pairs share a bridge on this node.",
    )
    parser.add_argument("--label", required=True, help="goes in the filename")
    parser.add_argument(
        "--concurrent", type=int, default=None,
        help="how many of --pairs to run at once (default: all of them)",
    )
    parser.add_argument(
        "--share", choices=("same", "independent"), default=None,
        help="what you believe --pairs does; recorded, never inferred",
    )
    parser.add_argument("--background-util", type=float, default=0.0)
    parser.add_argument("--background-pair", type=_pairs, default="4-6")
    parser.add_argument("--iters", type=int, default=10)
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES_MIB)
    parser.add_argument("--out-root", type=Path, default=None)
    parser.add_argument(
        "--binding", choices=("numa_pinned", "unpinned", "unknown"),
        default="unknown",
        help="how this process was bound. `unknown` is compared against "
             "nothing and is NOT the same claim as `unpinned`.",
    )
    args = parser.parse_args()
    args.background_pair = (
        args.background_pair[0] if isinstance(args.background_pair, list)
        else (4, 6)
    )

    try:
        import torch
    except ModuleNotFoundError:
        raise SystemExit(
            "run_pair.py needs torch with CUDA, and this interpreter has none.\n"
            "Neither vendor/heteropilot/.venv (simulator only) nor the system\n"
            "python has it. Build one the way heteropilot does:\n"
            "    cd vendor/heteropilot && bash scripts/install-vllm.sh\n"
            "then run this through that interpreter. See PLAN.md section 5."
        ) from None

    if not torch.cuda.is_available():
        raise SystemExit("torch is installed but reports no CUDA device.")

    pairs = _pairs(args.pairs)
    if args.concurrent is not None:
        pairs = pairs[: args.concurrent]
    ndev = torch.cuda.device_count()
    unreachable = [p for p in pairs for d in p if d >= ndev]
    if unreachable:
        raise SystemExit(
            f"--pairs names device(s) this host does not have: only {ndev} "
            f"visible. CUDA_VISIBLE_DEVICES may be narrowing it."
        )

    if args.condition == "collective":
        # argparse accepted it because it is in CONDITIONS, and nothing below
        # implements it: `measure()` runs peer COPIES whatever the condition
        # says. Left as it was, this would have written p2p timings into a
        # file whose `condition_means` reads "all-reduce, varying world size"
        # -- a mislabelled measurement, which is the one failure this harness
        # exists to prevent. Condition 5 is a different instrument.
        raise SystemExit(
            "--condition collective is not run by this script. It needs "
            "NCCL ranks under torchrun, not peer copies:\n"
            "    bash experiments/microbench/run_collective.sh\n"
            "which drives heteropilot's own "
            "experiments/p2_evidence/link_probe.py (busbw, world 2 and 4)."
        )

    probe = load_probe()
    serials = node_serials()
    affinity = observed_affinity()
    if args.binding == "numa_pinned" and not affinity.get("mem_is_bound"):
        # PLAN.md: "pin both halves or neither". `--cpunodebind` without
        # `--membind` leaves the buffers free to land on the far node, and
        # that is the case that produces a plausible number under a label
        # that does not describe it. The CPU half is visible in
        # `Cpus_allowed_list`; the memory half is only visible here.
        raise SystemExit(
            "--binding numa_pinned, but this process has no NUMA memory "
            f"policy (numa_maps says `{affinity.get('mempolicy')}`, not "
            "`bind:N`).\n"
            f"    Cpus_allowed_list: {affinity.get('Cpus_allowed_list')}\n"
            "Add `--membind=N` -- PLAN.md: pin both halves or neither. "
            "`Mems_allowed_list` cannot show this: it is the cpuset "
            "allowance, and --membind sets a mempolicy.\n"
            "Or pass --binding unpinned."
        )
    if args.binding == "numa_pinned" and affinity.get("looks_unrestricted"):
        raise SystemExit(
            "--binding numa_pinned, but this process may use every CPU:\n"
            f"    Cpus_allowed_list: {affinity.get('Cpus_allowed_list')}\n"
            f"    mempolicy: {affinity.get('mempolicy')}\n"
            "Wrap the command in `numactl --cpunodebind=N --membind=N`, or "
            "pass --binding unpinned. A figure labelled numa_pinned that was "
            "not pinned answers for a condition it was never measured under "
            "(PLAN.md, 'Pinning, and what it lets a measurement claim')."
        )
    before = gpu_occupancy(exclude_pid=os.getpid())
    load_before = os.getloadavg()

    print(f"condition : {args.condition} -- {CONDITIONS[args.condition]}")
    print(f"pairs     : {pairs}   share={args.share or 'unrecorded'}")
    print(f"background: util {args.background_util} on {args.background_pair}")
    print(f"serials   : {serials}")
    print(
        f"binding   : claimed {args.binding}; kernel says cpus "
        f"{affinity.get('Cpus_allowed_list')} mempolicy "
        f"{affinity.get('mempolicy')}"
    )
    print(f"loadavg   : {load_before[0]:.2f} (1 min)")
    print(f"others on the GPUs: {len(before)} process(es)")
    for process in before:
        print(f"   {process['user']:8} {process['pid']:>8}  {process['process']}")
    print()

    started = time.time()
    results = measure(probe, args, pairs)
    after = gpu_occupancy(exclude_pid=os.getpid())
    load_after = os.getloadavg()

    payload = {
        "label": args.label,
        "condition": args.condition,
        "condition_means": CONDITIONS[args.condition],
        "pairs": [f"{s}-{d}" for s, d in pairs],
        "share": args.share,
        "binding": args.binding,
        "iters": args.iters,
        "date": date.today().isoformat(),
        "node_serials": serials,
        "hostname": os.uname().nodename,
        "torch": torch.__version__,
        "nccl": ".".join(str(x) for x in torch.cuda.nccl.version())
        if hasattr(torch.cuda, "nccl") else "unknown",
        "driver_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "all"),
        "method": (
            f"torch {torch.__version__}, run_pair.py --condition "
            f"{args.condition} --share {args.share} "
            f"--background-util {args.background_util}"
        ),
        "binding_observed": affinity,
        # The claim and the kernel's own answer, side by side. A
        # `numa_pinned` label whose process can use every CPU is not a
        # measurement of a pinned run, whatever the flag said.
        "binding_claim_is_consistent": args.binding != "numa_pinned" or (
            not affinity.get("looks_unrestricted")
            and bool(affinity.get("mem_is_bound"))
        ),
        "gpu_occupancy_before": before,
        "gpu_occupancy_after": after,
        # The analysis refuses a run whose occupancy changed mid-flight: a
        # tenant that started or stopped halfway makes the p50 and the p90
        # answers to two different questions.
        # Sets, and self already excluded: nvidia-smi lists one row per
        # (process, device), so a two-pair run shows the same neighbour pid
        # twice and a list comparison would call that a change.
        "occupancy_stable": (
            {p["pid"] for p in before} == {p["pid"] for p in after}
        ),
        # What E-G6's grid had to learn: contamination that is recorded
        # labels itself, and contamination that is only remembered does not.
        # This box idles near 1.0 with no tenant and near 9 with one.
        "loadavg_before": [round(x, 2) for x in load_before],
        "loadavg_after": [round(x, 2) for x in load_after],
        "wall_s": round(time.time() - started, 2),
        "sizes": results,
        "banner": (
            "REAL HARDWARE -- node serials above. Raw timings only; this file "
            "contains no prediction and no verdict."
        ),
    }

    root = args.out_root or (
        Path(__file__).parent / "raw" / f"{payload['date']}-{serials[:16]}"
    )
    root.mkdir(parents=True, exist_ok=True)
    out = root / f"{args.label}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"\nwritten to {out}")
    if not payload["occupancy_stable"]:
        print(
            "WARNING: the set of GPU processes changed during this run. The "
            "analysis will refuse it; re-run when the node is quiet.",
            file=sys.stderr,
        )
        return 1
    print("Record it in experiments/microbench/LOG.md, then commit the raw file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
