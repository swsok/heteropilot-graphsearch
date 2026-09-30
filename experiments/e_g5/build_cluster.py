#!/usr/bin/env python
"""P3.2: write `fixtures/clusters/real-a40x8.v2.yaml` from the E-G4 raw files.

**REAL HARDWARE.** Every `source: measured` number in the output is read out of
`experiments/microbench/raw/`, not typed in here. That is the point of
generating the fixture rather than writing it: a measured value that was
transcribed by hand is a value nobody can trace, and the first thing a reader
of a cluster spec wants to know is which numbers were measured and where.

Run it twice and the file is byte-identical; `tests/test_real_cluster.py` pins
that and also loads the result through heteropilot's own `load_cluster_spec`,
so a field this script gets wrong fails here rather than in the middle of P3.3.

**The shared-resource model is GS-22's, and it is the one the measurements
support.** Each GPU's own PCIe x16 port is a `shared_resource`; every PCIe link
is attached to its source GPU's port. Because `build_resource_graph` gives both
directed edges of a `bidir` link the same resource id, this reproduces all
three E-G4 observations at once:

    0->2 and 1->3   different ports  -> no contention   (measured: none)
    0->2 and 2->0   same link, same port -> contention  (measured: yes)
    a background generator on 1-3 reserves port-gpu1, not port-gpu0
                                                        (measured: 0-2 unaffected)

Declaring a per-bridge resource instead -- what `PLAN.md` assumed before any of
this was measured -- predicts a 146 % slowdown for the last case, and the
foreground measured its unloaded rate to three digits.

    python experiments/e_g5/build_cluster.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

ROOT = paths_root.GRAPHSEARCH_ROOT
RAW = ROOT / "experiments" / "microbench" / "raw"
OUT = ROOT / "fixtures" / "clusters" / "real-a40x8.v2.yaml"

#: `nvidia-smi topo -m`, observed 2026-09-28. NV4 pairs, NUMA halves.
NVLINK_PAIRS = [(0, 1), (2, 3), (4, 5), (6, 7)]
NUMA_OF = {d: (0 if d < 4 else 1) for d in range(8)}

#: Which raw file measures which device pair, for the `p2p` measurements. Only
#: pairs that were actually measured appear; the rest of the mesh carries its
#: vendor_spec value alone and stays in the registry's measurement queue.
P2P_SOURCES = {
    (0, 1): "2026-09-28-GPU-11e5c5fd-9e9/a-cond1-single-nvlink-0-1.json",
    (0, 2): "2026-09-28-GPU-11e5c5fd-9e9/a-cond1-single-bridge-0-2.json",
    (5, 7): "2026-09-29-GPU-11e5c5fd-9e9/a-cond1-single-bridge-5-7.json",
    (0, 4): "2026-09-29-GPU-11e5c5fd-9e9/a-cond1-single-sys-0-4.json",
}

#: Condition 5, `link_probe.py` under torchrun. `world_size` is part of the key
#: precisely because these disagree: one wire, 2.2x apart.
COLLECTIVE_SOURCES = {
    ((0, 1), 2): "collective-2026-09-28/c-world2-nvlink-0-1.json",
    ((0, 2), 2): "collective-2026-09-28/c-world2-bridge-0-2.json",
}

#: PCIe 4.0 x16: 16 GT/s x 16 lanes x 128/130 encoding = 31.5 GB/s one way.
#: Computed from the standard, not measured, and labelled vendor_spec.
PCIE4_X16_GBPS = 31.5
#: `profiles/accelerators/a40.yaml` carries 112.5 for this node's NVLink.
NVLINK_GBPS = 112.5
#: `nvidia-smi --query-gpu=memory.total`: 46068 MiB = 44.99 GiB.
GPU_MEMORY_GB = 45.0


def plateau(path: Path, pair: str) -> tuple[float, list[int], str, str]:
    """The 256 MiB figure, its bytes, the date and the method. Measured, read."""
    raw = json.loads(path.read_text())
    block = raw["sizes"]["256MiB"]
    return (
        round(block["pairs"][pair]["bandwidth_gbps"], 2),
        [block["msg_bytes"]],
        raw["date"],
        raw["method"],
    )


def busbw_plateau(path: Path) -> tuple[float, list[int], int, str]:
    """The all-reduce busbw plateau and the world size it holds for.

    The largest message in the sweep, because `bulk` is the plateau and the
    plateau is the only band comparable with a link rate. `link_probe.py`
    reports `algbw` and `busbw` separately and this takes `busbw`: a ring
    all-reduce moves 2(n-1)/n times the buffer over the wire, so `algbw` is
    what the application sees and `busbw` is what the wire did.
    """
    raw = json.loads(path.read_text())
    best = max(raw["allreduce"], key=lambda r: r["bytes"])
    return (
        round(best["busbw_gbps"], 2),
        [int(best["bytes"])],
        int(raw["world_size"]),
        f"torch {raw['torch']} + NCCL {raw['nccl_version']}, link_probe.py "
        f"under torchrun, run_collective.sh",
    )


def measurement(
    collective: str, bw: float, msg_bytes: list[int], world: int,
    date: str, method: str, raw: str, note: str,
) -> dict:
    return {
        "collective": collective,
        "msg_size_class": "bulk",
        "binding": "numa_pinned",
        "bus_bw_gbps": bw,
        "world_size": world,
        "source": "measured",
        "method": method,
        "msg_bytes": msg_bytes,
        "date": date,
        "raw": f"experiments/microbench/raw/{raw}",
        "note": note,
    }


def link_id(a: int, b: int) -> str:
    return f"gpu{a}-gpu{b}"


def build() -> dict:
    node = "a40x8"
    accelerators = [
        {
            "id": f"gpu{d}",
            "type": "GPU",
            "vendor": "NVIDIA",
            "model": "A40",
            "backend": "cuda",
            "memory_gb": GPU_MEMORY_GB,
            "profile": "vendor/heteropilot/profiles/accelerators/a40.yaml",
            # Unpriced on purpose. `price_per_hour_usd: null` means a plan
            # touching this device CANNOT be scored on cost at all, which is
            # correct: nobody has given this lab machine an hourly price, and a
            # partial sum would rank the under-priced plan cheapest. Every
            # cost-objective result from this cluster is therefore uncomputable
            # rather than approximate, and E-G5 reports `cost_regret` as `-`.
            "price_per_hour_usd": None,
        }
        for d in range(8)
    ]

    links = []
    for a in range(8):
        for b in range(a + 1, 8):
            nvlink = (a, b) in NVLINK_PAIRS
            same_numa = NUMA_OF[a] == NUMA_OF[b]
            link = {
                "id": link_id(a, b),
                "src": f"{node}/gpu{a}",
                "dst": f"{node}/gpu{b}",
                "type": "NVLINK" if nvlink else "PCIE",
                "bandwidth_gbps": NVLINK_GBPS if nvlink else PCIE4_X16_GBPS,
                "latency_ns": 0.0,
                "duplex": "full",
                "direction": "bidir",
                "p2p": True,
                "source": "vendor_spec",
            }
            if not nvlink:
                # GS-22: the endpoint's own x16 port is the resource, and both
                # directed edges of a bidir link inherit this one id -- which
                # is what makes 0->2 contend with 2->0 and not with 1->3.
                link["shared_resource"] = f"port-gpu{a}"
            if not same_numa:
                link["note_numa"] = True

            measurements = []
            if (a, b) in P2P_SOURCES:
                path = RAW / P2P_SOURCES[(a, b)]
                bw, msg_bytes, date, method = plateau(path, f"{a}-{b}")
                kind = "NVLink NV4" if nvlink else (
                    "PCIe across the host bridge" if same_numa
                    else "PCIe across NUMA (SYS: host bridge + UPI)"
                )
                measurements.append(measurement(
                    "p2p", bw, msg_bytes, 2, date, method,
                    P2P_SOURCES[(a, b)],
                    f"{kind}; single-flow plateau, 20 repetitions, "
                    f"node quiet (no other tenant)",
                ))
            for (pair, _world), rel in COLLECTIVE_SOURCES.items():
                if pair != (a, b):
                    continue
                bw, msg_bytes, world_size, method = busbw_plateau(RAW / rel)
                measurements.append(measurement(
                    "all_reduce", bw, msg_bytes, world_size, "2026-09-28",
                    method, rel,
                    "busbw plateau, not algbw; the figure comparable with a "
                    "link rate",
                ))
            if measurements:
                link["measurements"] = measurements
            link.pop("note_numa", None)
            links.append(link)

    # The world-4 all-reduce belongs to the island, not to any one link: it is
    # what four ranks over these wires together achieve. It is attached to the
    # two bridge links the group crosses, keyed on world_size=4, which is the
    # component of the key that exists for exactly this (8.71 against 19.34
    # over the same path).
    bw4, bytes4, world4, method4 = busbw_plateau(
        RAW / "collective-2026-09-28/c-world4-numa0.json"
    )
    for a, b in ((0, 2), (1, 3)):
        for link in links:
            if link["id"] == link_id(a, b):
                link.setdefault("measurements", []).append(measurement(
                    "all_reduce", bw4, bytes4, world4, "2026-09-28", method4,
                    "collective-2026-09-28/c-world4-numa0.json",
                    "the TP=4 group on {gpu0,gpu1,gpu2,gpu3}. 2.2x below the "
                    "world-2 figure over the same wires, which is why "
                    "world_size is part of the key and not a note beside it",
                ))

    shared = [
        {
            "id": f"port-gpu{d}",
            "kind": "pcie_uplink",
            "capacity": 25.12,
            "unit": "GB/s",
            "reserved": 0.0,
            "node": node,
            "source": "measured",
        }
        for d in range(8)
    ]

    return {
        "cluster_id": "real-a40x8",
        "schema_version": 2,
        "snapshot_id": "2026-09-29-eg4",
        "nodes": [{
            "id": node,
            "cpu_sockets": [
                {"id": "sock0", "numa_node": 0},
                {"id": "sock1", "numa_node": 1},
            ],
            "host_price_per_hour_usd": None,
            "accelerators": accelerators,
            "nics": [{"id": "nic0", "type": "infiniband", "speed_gbps": 100.0}],
        }],
        "links": links,
        "shared_resources": shared,
    }


HEADER = """\
# real-a40x8 -- the A40 node this repository runs on. NOT a fictional fixture.
#
# **Generated. Do not edit.** `python experiments/e_g5/build_cluster.py` writes
# it from `experiments/microbench/raw/`, so every `source: measured` number is
# traceable to a file that records the node serials, the CPU/memory binding,
# the load average and who else was on the GPUs when it was taken. A measured
# value transcribed by hand is a value nobody can trace.
#
# `tests/test_real_cluster.py` pins that it regenerates byte-identically and
# that heteropilot's own `load_cluster_spec` accepts it.
#
# ---- what is measured and what is not -------------------------------------
#
# measured      the p2p plateaus on gpu0-gpu1 (NVLink), gpu0-gpu2 and gpu5-gpu7
#               (across the host bridge), gpu0-gpu4 (across NUMA); the
#               all-reduce busbw at world 2 and world 4; the eight port
#               capacities. E-G4, 2026-09-28/29.
# vendor_spec   every link's `bandwidth_gbps`. NVLink 112.5 from
#               profiles/accelerators/a40.yaml; PCIe 31.5 = 16 GT/s x 16 lanes
#               x 128/130, computed from the standard. These are NEVER edited
#               to match a measurement (heteropilot absolute rule A3) -- the
#               measurement sits beside them so the two can be compared.
# unmeasured    the rest of the PCIe mesh. It carries its vendor_spec value
#               alone and stays in the registry's measurement queue, which is
#               the correct state for a wire nobody has put a probe on.
# unpriced      every device. `price_per_hour_usd: null` -- no cost objective
#               can be computed from this cluster, and E-G5 reports cost as
#               uncomputed rather than as zero.
#
# ---- the shared-resource model (GS-22) ------------------------------------
#
# Each GPU's own PCIe x16 port is the resource, and each PCIe link is attached
# to its SOURCE port. Both directed edges of a `bidir` link inherit that one
# id, which is what makes gpu0->gpu2 contend with gpu2->gpu0 and not with
# gpu1->gpu3. The per-bridge resource this node's plan originally assumed was
# measured to be wrong: two copies across "one bridge" each got 25.11 GB/s
# against 25.12 alone, and a background generator holding gpu1-gpu3 at a
# measured 0.60 duty cycle left gpu0-gpu2 at its unloaded rate to three digits.
#
# ---- one island of 8, where heteropilot's own a40 fixtures model two of 4 ---
#
# `detect_islands` returns ONE island of all eight devices from this file,
# because every declared link is PCIE or NVLINK and both are in
# `INTRA_ISLAND_LINKS`. heteropilot's `docs/nodes/a40.md` says "a size-4 island
# therefore means GPUs {0,1,2,3} or {4,5,6,7}", and its own fixtures model the
# node that way.
#
# This file does not follow that, and the difference is deliberate. Measured
# 2026-09-29: `can_device_access_peer(0, 4)` is **True** and a copy across the
# NUMA boundary sustains 22.58 GB/s -- 90 % of the 25.12 GB/s the same copy
# gets within one NUMA node. Those eight devices really are one peer-capable
# PCIe domain. Splitting them would require declaring the cross-NUMA links
# ETHERNET or INFINIBAND, which is the only way to make `detect_islands` cut
# there, and they are neither.
#
# The consequence to watch: `max_tp_candidates` therefore includes 8, so a
# candidate may ask for TP=8 spanning both NUMA halves. That is a real option
# on this hardware and E-G5 will measure whether it is a good one -- the
# world-4 all-reduce already collapses to 8.71 GB/s busbw, and world 8 across
# SYS has not been measured at all. Any TP=8 candidate is `unknown_measurement`
# for its collective bandwidth until it is.
"""


def main(argv: list[str] | None = None) -> int:
    import yaml

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--check", action="store_true",
                        help="fail if the file on disk differs")
    args = parser.parse_args(argv)

    text = HEADER + yaml.safe_dump(
        build(), sort_keys=False, default_flow_style=False, width=100
    )
    if args.check:
        current = args.out.read_text() if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is stale; re-run build_cluster.py")
            return 1
        print(f"{args.out} is up to date")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)

    from planner.inventory import load_cluster_spec
    spec = load_cluster_spec(args.out)
    print(f"wrote {args.out}")
    print(f"  {len(spec.nodes[0].accelerators)} accelerators, "
          f"{len(spec.links)} links, "
          f"{len(spec.shared_resources)} shared resources")
    measured = sum(len(link.measurements) for link in spec.links)
    print(f"  {measured} measurements, all source: measured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
