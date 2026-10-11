"""Write `fixtures/clusters/real-s8a5k.v2.yaml`, the two-node cluster of E-G8
(revision R5.1): `s8` (A40 x 8) and `a5k2` (`a5000-2` GPU 0). Values come from
the R5.0 raw files, the way `experiments/e_g5/build_cluster_s8s6.py` writes the
A40 pair. Run from the repository root:

    python experiments/e_g8/build_cluster_s8a5k.py                  # write
    python experiments/e_g8/build_cluster_s8a5k.py --check          # fail if stale
    python experiments/e_g8/build_cluster_s8a5k.py --shared D1      # s8 -> a5k2 reserved
    python experiments/e_g8/build_cluster_s8a5k.py --shared D2      # a5k2 -> s8 reserved

Every `source: measured` value is read from a committed raw file, never typed:

- each direction's NIC capacity: the `ib_send_bw` single-stream median
  (`experiments/pd_probe/raw/a5000-links/`, via
  `experiments/microbench/analyze.py::nic_results`). Both directions were
  measured, so neither is a placeholder;
- the GPU-to-GPU NIXL figure for each direction, at 256 MiB with `a5000-2`
  GPU 0's BAR1 resized to 32 GB (`experiments/pd_probe/a5000/README.md`);
- the two-node all-reduce busbw at world 2: the median over ten runs of each
  run's largest-message figure. NCCL chose `GDR 0` in every run, so it is a
  host-staged figure and its note says so.

**`a5k2` carries GPU 0 only.** E-G8 deploys there and nowhere else on the
node, and every R5.0 figure was taken from it. GPU 1 is out of scope, not
infeasible. Since `a5000-2`'s BIOS update of 2026-10-10 both GPUs boot with a
32 GB BAR1, so GPU 1's earlier 256 MiB BAR1 is no longer the reason.

`s8`'s intra-node figures are E-G4's, inherited through `real-a40x8`, exactly
as in `real-s8s6`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import statistics
import sys
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

HERE = Path(__file__).resolve().parent
ROOT = paths_root.GRAPHSEARCH_ROOT
sys.path.insert(0, str(ROOT / "experiments" / "e_g5"))
sys.path.insert(0, str(ROOT / "experiments" / "microbench"))


def _load(name: str, path: Path):
    """By path and under its own name: e_g5 and microbench both have an
    `analyze` module, and whichever is imported first would win."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


microbench = _load("microbench_analyze", ROOT / "experiments" / "microbench" / "analyze.py")
import build_cluster as single  # noqa: E402
import build_cluster_s8s6 as pair  # noqa: E402

FIXTURES = ROOT / "fixtures" / "clusters"
OUT = FIXTURES / "real-s8a5k.v2.yaml"
OUT_SHARED = {"D1": FIXTURES / "real-s8a5k-shared-d1.v2.yaml",
              "D2": FIXTURES / "real-s8a5k-shared-d2.v2.yaml"}

LINKS_RAW = ROOT / "experiments" / "pd_probe" / "raw" / "a5000-links"
#: `run_nic.py` puts the server (the receiver) on the near node, `s8`; without
#: `--reverse` the peer sends. So `nic-s8-a5000-2` is a5k2 -> s8.
NIC_RAW = {
    ("a5k2", "s8"): "2026-10-09-nic-s8-a5000-2",
    ("s8", "a5k2"): "2026-10-09-nic-s8-to-a5000-2",
}
COLLECTIVE_RAW = LINKS_RAW / "2026-10-09-nic-collective-s8-a5000-2"
PROBE_README = ROOT / "experiments" / "pd_probe" / "a5000" / "README.md"

#: Which README column holds the BAR1-32 GB figure for each direction.
NIXL_COLUMN = {("s8", "a5k2"): "`s8`->`a5000-2` (BAR1 32 GB)",
               ("a5k2", "s8"): "`a5000-2`->`s8` (BAR1 32 GB)"}

#: The KV crosses the prefill node's NIC towards the decode node (the decode
#: side pulls the prefill side's blocks). D1: prefill s8, decode a5k2.
KV_DIRECTION = {"D1": ("s8", "a5k2"), "D2": ("a5k2", "s8")}

#: `nvidia-smi`: 24564 MiB = 23.99 GiB.
A5000_MEMORY_GB = 24.0
#: The A5000 node's NIC sits in a PCIe Gen3 x8 slot: 8 GT/s x 8 lanes x
#: 128/130 = 7.88 GB/s one way. From the standard, labelled vendor_spec.
PCIE3_X8_GBPS = 7.88


def nic_capacity_gbit(src: str, dst: str) -> float:
    name = NIC_RAW[(src, dst)]
    median = microbench.nic_results(LINKS_RAW, only=name)["single"]["median"]
    if median is None:
        raise SystemExit(f"{name}: no single-stream median")
    return round(median, 2)


def collective() -> tuple[float, int, list[str]]:
    """Median over runs of the largest-message busbw, the run count, the files."""
    files = sorted(COLLECTIVE_RAW.glob("xnode-*.json"))
    if not files:
        raise SystemExit(f"{COLLECTIVE_RAW}: no runs")
    per_run = []
    for path in files:
        raw = json.loads(path.read_text())
        per_run.append(max(raw["allreduce"], key=lambda r: r["bytes"])["busbw_gbps"])
    return round(statistics.median(per_run), 3), len(per_run), [p.name for p in files]


def nixl_gbit(src: str, dst: str) -> float:
    lines = PROBE_README.read_text().splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("| bytes |"):
            continue
        head = [c.strip() for c in line.strip("|").split("|")]
        col = head.index(NIXL_COLUMN[(src, dst)])
        for row in lines[i + 2:]:
            cells = [c.strip() for c in row.strip("|").split("|")]
            if cells[0] == "256 Mi":
                value = cells[col]
                if not re.fullmatch(r"[0-9.]+", value):
                    raise SystemExit(f"{PROBE_README}: 256 Mi {src}->{dst} is {value!r}")
                return float(value)
    raise SystemExit(f"{PROBE_README}: no NIXL table with a 256 Mi row")


def a5k2_node() -> tuple[dict, list]:
    node = {
        "id": "a5k2",
        "cpu_sockets": [{"id": "sock0", "numa_node": 0}],
        "host_price_per_hour_usd": None,
        "accelerators": [{
            "id": "gpu0", "type": "GPU", "vendor": "NVIDIA", "model": "RTX-A5000",
            "backend": "cuda", "memory_gb": A5000_MEMORY_GB,
            "profile": "vendor/heteropilot/profiles/accelerators/a5000.yaml",
            # Unpriced, as every device in these fixtures: a partial price
            # would rank the under-priced plan cheapest.
            "price_per_hour_usd": None,
        }],
        "nics": [{"id": "nic0", "type": "infiniband", "speed_gbps": 100.0}],
    }
    links = [{
        "id": "a5k2-gpu0-nic0", "src": "a5k2/gpu0", "dst": "a5k2/nic0",
        "type": "PCIE", "bandwidth_gbps": PCIE3_X8_GBPS, "latency_ns": 0.0,
        "duplex": "full", "direction": "bidir", "p2p": True, "source": "vendor_spec",
    }]
    return node, links


def build(shared: str | None = None) -> dict:
    base = single.build()
    s8, s8_links, s8_resources = pair._node(base, "s8", measured_here=True)
    a5k2, a5k2_links = a5k2_node()
    links = s8_links + a5k2_links
    resources = list(s8_resources)

    busbw, runs, _files = collective()
    for src, dst in (("s8", "a5k2"), ("a5k2", "s8")):
        nixl = nixl_gbit(src, dst)
        measurements = [{
            "collective": "p2p", "msg_size_class": "bulk", "binding": "unknown",
            "bus_bw_gbps": round(nixl / 8, 4), "world_size": 2, "source": "measured",
            "method": "nixl 0.9.0 WRITE, VRAM to VRAM, experiments/pd_probe/nixl_bw.py",
            "msg_bytes": [268435456], "date": "2026-10-09",
            "raw": "experiments/pd_probe/raw/nixl-a5000/rebar32g",
            "note": (f"{src} cuda:0 to {dst} cuda:0, {nixl} Gbit/s, median of 30 after "
                     f"5 warmup; a5000-2 GPU 0 BAR1 32 GB (resized at run time); UCX rc_mlx5 "
                     f"zero-copy cuda to cuda (GPUDirect RDMA)"),
        }, {
            "collective": "all_reduce", "msg_size_class": "bulk", "binding": "unknown",
            "bus_bw_gbps": busbw, "world_size": 2, "source": "measured",
            "method": "torch 2.10.0+cu128 + NCCL, link_probe.py across two nodes",
            "msg_bytes": [67108864], "date": "2026-10-09",
            "raw": str(COLLECTIVE_RAW.relative_to(ROOT)),
            "note": (f"inter-node busbw plateau, median of {runs} runs; NCCL chose "
                     f"GDR 0 (host-staged) on this topology by default"),
        }]
        rid = f"nic-{src}-to-{dst}"
        links.append({
            "id": f"ib-{src}-{dst}", "src": f"{src}/nic0", "dst": f"{dst}/nic0",
            "type": "INFINIBAND", "bandwidth_gbps": pair.IB_PORT_GBPS,
            "latency_ns": 0.0, "duplex": "full", "direction": "src_to_dst",
            "rdma": True, "source": "vendor_spec", "shared_resource": rid,
            "measurements": measurements,
        })
        capacity = nic_capacity_gbit(src, dst)
        reserved = (round(capacity * pair.SHARED_FRACTION, 2)
                    if shared and KV_DIRECTION[shared] == (src, dst) else 0.0)
        resources.append({
            "id": rid, "kind": "nic", "capacity": capacity, "unit": "Gbit/s",
            "reserved": reserved, "node": src, "source": "measured",
        })
    return {
        "cluster_id": "real-s8a5k",
        "schema_version": 2,
        "snapshot_id": "2026-10-09-eg8",
        "nodes": [s8, a5k2], "links": links, "shared_resources": resources,
    }


def header(shared: str | None) -> str:
    fwd, back = nic_capacity_gbit("s8", "a5k2"), nic_capacity_gbit("a5k2", "s8")
    busbw, runs, _ = collective()
    lines = [
        "# real-s8a5k -- E-G8's two nodes: s8 (A40 x 8) and a5k2 (a5000-2 GPU 0). NOT fictional.",
        "#",
        "# **Generated. Do not edit.** `python experiments/e_g8/build_cluster_s8a5k.py`",
        "# writes it from the R5.0 raw files, as build_cluster_s8s6.py writes real-s8s6.",
        "#",
        "# measured      s8's intra-node figures (inherited from real-a40x8); each",
        "#               NIC direction; the NIXL GPU-to-GPU figure each way; the",
        f"#               two-node all-reduce at world 2 ({busbw} GB/s, median of {runs},",
        "#               NCCL GDR 0: host-staged).",
        f"# NIC s8 -> a5k2   {fwd} Gbit/s ({NIC_RAW[('s8', 'a5k2')]})",
        f"# NIC a5k2 -> s8   {back} Gbit/s ({NIC_RAW[('a5k2', 's8')]})",
        "# a5k2          GPU 0 only: the GPU E-G8 deploys on and every R5.0 figure",
        "#               came from. GPU 1 is out of scope, not infeasible. Both boot",
        "#               with a 32 GB BAR1 since the BIOS update of 2026-10-10;",
        "#               experiments/pd_probe/a5000/gpu0_rebar.sh checks it before a run.",
        "# A5000 profile vendor/heteropilot/profiles/accelerators/a5000.yaml. Its tp=1",
        "#               perf bundle is a5000-2's own: a re-profile there agrees at",
        "#               medians of 0.1-0.4 % (experiments/e_g8/profile/README.md).",
        "# vendor_spec   every link's bandwidth_gbps. The A5000 NIC is in a PCIe",
        "#               Gen3 x8 slot (7.88 GB/s); InfiniBand is 12.5 GB/s, in GB/s",
        "#               on purpose (GS-32).",
    ]
    if shared:
        src, dst = KV_DIRECTION[shared]
        cap = nic_capacity_gbit(src, dst)
        lines += [
            "#",
            f"# SHARED VARIANT ({shared}): nic-{src}-to-{dst} reserved "
            f"{round(cap * pair.SHARED_FRACTION, 2)} Gbit/s,",
            f"# {pair.SHARED_FRACTION:.0%} of its capacity, the direction {shared}'s KV crosses.",
            "# One field differs from real-s8a5k.v2.yaml. A topology ASSUMPTION for the",
            "# prediction, not a measurement.",
        ]
    return "\n".join(lines) + "\n"


def render(shared: str | None) -> str:
    import yaml

    return header(shared) + yaml.safe_dump(
        build(shared), sort_keys=False, default_flow_style=False, width=100
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shared", choices=sorted(KV_DIRECTION), default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    out = OUT_SHARED[args.shared] if args.shared else OUT
    text = render(args.shared)
    if args.check:
        current = out.read_text() if out.exists() else ""
        print(f"{out} is {'up to date' if current == text else 'stale'}")
        return 0 if current == text else 1
    out.write_text(text)
    from planner.inventory import load_cluster_spec

    spec = load_cluster_spec(out)
    print(f"wrote {out}: {len(spec.nodes)} nodes, {len(spec.links)} links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
