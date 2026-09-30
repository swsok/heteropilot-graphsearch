"""Write `fixtures/clusters/real-s8s6.v2.yaml` -- the two-node cluster of E-G5's
inter-node P/D arm -- from the raw files, the way `build_cluster.py` writes the
one-node fixture. Run from the repository root:

    python experiments/e_g5/build_cluster_s8s6.py            # write
    python experiments/e_g5/build_cluster_s8s6.py --check    # fail if stale
    python experiments/e_g5/build_cluster_s8s6.py --shared   # the `shared` variant

Every `source: measured` value is read from a committed raw file, never typed:

- the NIC's capacity, E-G4(b) `ib_send_bw` single-stream median, via
  `experiments/microbench/analyze.py::nic_results`;
- the inter-node all-reduce busbw at world 2 and 4, via `nic_collective`;
- the GPU-to-GPU NIXL figure, from `experiments/pd_probe/raw/nixl/README.md`.

`s6` is the same model of machine, but it is not the machine E-G4 measured. Its
intra-node figures are therefore copied from `s8` and **downgraded to
`source: placeholder`**, and the `s8` measurements are not attached to its
links: a measurement of one machine is not a measurement of another.
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

HERE = Path(__file__).resolve().parent
ROOT = paths_root.GRAPHSEARCH_ROOT
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "experiments" / "microbench"))
import analyze as microbench  # noqa: E402
import build_cluster as single  # noqa: E402

OUT = ROOT / "fixtures" / "clusters" / "real-s8s6.v2.yaml"
OUT_SHARED = ROOT / "fixtures" / "clusters" / "real-s8s6-shared.v2.yaml"
NIXL_README = ROOT / "experiments" / "pd_probe" / "raw" / "nixl" / "README.md"
#: `run_nic.py` puts the `ib_send_bw` server on the near node and the client --
#: the SENDER -- on the peer. E-G4(b) ran it with s8 near, so its single-stream
#: figure is the **s6 -> s8** direction. The s8 -> s6 direction, which this
#: arm's KV crosses, is a separate file, written by `run_nic.py --reverse`.
NIC_RAW = {
    ("s6", "s8"): "experiments/microbench/raw/2026-09-29-nic-s8-s6/b-single.json",
    ("s8", "s6"): "experiments/microbench/raw/2026-09-30-nic-s8-to-s6/b-single.json",
}
COLLECTIVE_RAW = "experiments/microbench/raw/2026-09-30-nic-collective-s8-s6"

#: 100 Gbit/s, the Mellanox MT4123 port rate `ibv_devinfo` reports on both ends,
#: written in GB/s. **Not `bandwidth_unit: Gbit/s`**: graphsearch converts that
#: field, but heteropilot's `planner/topology.py` reads `bandwidth_gbps` as GB/s
#: and never consults the unit, so a Gbit/s link would be 8x apart between the
#: two repositories reading one file (GS-32).
IB_PORT_GBPS = 100 / 8

#: The `shared` condition's reservation: the background's registered duty cycle.
SHARED_FRACTION = 0.6

NODES = ("s8", "s6")


def nic_capacity_gbit(src: str, dst: str) -> float | None:
    """The single-stream median for one direction, or None if never measured."""
    path = ROOT / NIC_RAW[(src, dst)]
    if not path.exists():
        return None
    by_dir = microbench.nic_results(path.parent.parent, only=path.parent.name)
    median = by_dir["single"]["median"]
    return None if median is None else round(median, 2)


def collective_busbw() -> dict[int, float]:
    return {w: b for w, where, b in microbench.nic_collective() if where == "across the NIC"}


def nixl_gpu_to_gpu_gbit() -> float:
    for line in NIXL_README.read_text().splitlines():
        m = re.match(r"^\| 256 Mi \| ([0-9.]+) \|", line)
        if m:
            return float(m.group(1))
    raise SystemExit(f"{NIXL_README}: no 256 Mi row")


def _rename(obj, old: str, new: str):
    if isinstance(obj, dict):
        return {k: _rename(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename(v, old, new) for v in obj]
    if isinstance(obj, str):
        if obj == old:
            return new
        if obj.startswith(old + "/"):
            return new + obj[len(old):]
    return obj


def _node(base: dict, name: str, measured_here: bool) -> tuple[dict, list, list]:
    node = _rename(copy.deepcopy(base["nodes"][0]), "a40x8", name)
    node["nics"] = [{"id": "nic0", "type": "infiniband", "speed_gbps": 100.0}]
    links = _rename(copy.deepcopy(base["links"]), "a40x8", name)
    resources = _rename(copy.deepcopy(base["shared_resources"]), "a40x8", name)
    for link in links:
        link["id"] = f"{name}-{link['id']}"
        if "shared_resource" in link:
            link["shared_resource"] = f"{name}-{link['shared_resource']}"
        if not measured_here:
            link.pop("measurements", None)
    for res in resources:
        res["id"] = f"{name}-{res['id']}"
        if not measured_here:
            res["source"] = "placeholder"
    for d in range(8):
        # The path a GPU's traffic takes to the NIC. It leaves through the GPU's
        # own x16 port (GS-22), so it inherits that port as its resource.
        links.append({
            "id": f"{name}-gpu{d}-nic0",
            "src": f"{name}/gpu{d}", "dst": f"{name}/nic0",
            "type": "PCIE", "bandwidth_gbps": single.PCIE4_X16_GBPS,
            "latency_ns": 0.0, "duplex": "full", "direction": "bidir",
            "p2p": True, "source": "vendor_spec",
            "shared_resource": f"{name}-port-gpu{d}",
        })
    return node, links, resources


def build(shared: bool = False) -> dict:
    base = single.build()
    nodes, links, resources = [], [], []
    for name in NODES:
        n, lk, rs = _node(base, name, measured_here=(name == "s8"))
        nodes.append(n)
        links += lk
        resources += rs

    measured_dir = {d: nic_capacity_gbit(*d) for d in NIC_RAW}
    if measured_dir[("s6", "s8")] is None:
        raise SystemExit("no E-G4(b) single-stream median in the raw files")
    busbw = collective_busbw()
    nixl = nixl_gpu_to_gpu_gbit()
    measurements = [{
        "collective": "p2p", "msg_size_class": "bulk", "binding": "unknown",
        "bus_bw_gbps": round(nixl / 8, 4), "world_size": 2, "source": "measured",
        "method": "nixl 0.9.0 WRITE, VRAM to VRAM, experiments/pd_probe/nixl_bw.py",
        "msg_bytes": [268435456], "date": "2026-09-30",
        "raw": str(NIXL_README.relative_to(ROOT)),
        "note": f"s8 cuda:0 to s6 cuda:0, {nixl} Gbit/s, median of 30 after 5 warmup",
    }]
    for world in sorted(busbw):
        measurements.append({
            "collective": "all_reduce", "msg_size_class": "bulk", "binding": "unknown",
            "bus_bw_gbps": busbw[world], "world_size": world, "source": "measured",
            "method": "torch 2.10.0+cu128 + NCCL 2.27.5, link_probe.py across two nodes",
            "msg_bytes": [], "date": "2026-09-30",
            "raw": f"{COLLECTIVE_RAW}/b-world{world}.json",
            "note": "inter-node busbw plateau",
        })
    # Full duplex, measured (E-G4(b) `bidirectional`): each direction is its own
    # resource. NIXL's connector PULLS -- the decode side reads the prefill
    # side's blocks -- so the KV data of this arm crosses s8 -> s6.
    for src, dst in (("s8", "s6"), ("s6", "s8")):
        rid = f"nic-{src}-to-{dst}"
        links.append({
            "id": f"ib-{src}-{dst}", "src": f"{src}/nic0", "dst": f"{dst}/nic0",
            "type": "INFINIBAND", "bandwidth_gbps": IB_PORT_GBPS,
            "latency_ns": 0.0, "duplex": "full", "direction": "src_to_dst",
            "rdma": True, "source": "vendor_spec", "shared_resource": rid,
            "measurements": copy.deepcopy(measurements) if src == "s8" else [],
        })
        # A direction nobody measured carries the other direction's figure as
        # a PLACEHOLDER: E-G4(b)'s bidirectional run showed the port full
        # duplex, which makes symmetry a reasonable assumption and not a
        # measurement.
        own = measured_dir[(src, dst)]
        capacity = own if own is not None else measured_dir[(dst, src)]
        reserved = (
            round(capacity * SHARED_FRACTION, 2) if (shared and src == "s8") else 0.0
        )
        resources.append({
            "id": rid, "kind": "nic", "capacity": capacity, "unit": "Gbit/s",
            "reserved": reserved, "node": src,
            "source": "measured" if own is not None else "placeholder",
        })
    return {
        "cluster_id": "real-s8s6",
        "schema_version": 2,
        "snapshot_id": "2026-09-30-eg5-pd",
        "nodes": nodes, "links": links, "shared_resources": resources,
    }


def header(shared: bool) -> str:
    fwd = nic_capacity_gbit("s8", "s6")
    back = nic_capacity_gbit("s6", "s8")
    fwd_text = f"{fwd} Gbit/s, measured" if fwd is not None else (
        f"NOT MEASURED -- carries s6->s8's {back} as a placeholder"
    )
    lines = [
        "# real-s8s6 -- the two A40 nodes of E-G5's inter-node P/D arm. NOT fictional.",
        "#",
        "# **Generated. Do not edit.** `python experiments/e_g5/build_cluster_s8s6.py`",
        "# writes it from the raw files, as build_cluster.py writes real-a40x8.",
        "#",
        "# measured      s8's intra-node figures (inherited from real-a40x8); the",
        "#               inter-node all-reduce at world 2 and 4; the NIXL",
        "#               GPU-to-GPU figure (s8 -> s6).",
        f"# NIC s6 -> s8  {back} Gbit/s, measured ({NIC_RAW[('s6', 's8')]})",
        f"# NIC s8 -> s6  {fwd_text}",
        "#               This arm's KV crosses s8 -> s6: the decode instance on s6",
        "#               reads the prefill instance's blocks on s8.",
        "# placeholder   everything on s6: same hardware, not the machine E-G4",
        "#               measured, so s8's numbers are copied and downgraded.",
        "# vendor_spec   every link's bandwidth_gbps, never edited to a measurement.",
        "#               InfiniBand is 12.5 GB/s = 100 Gbit/s, written in GB/s on",
        "#               purpose: heteropilot reads bandwidth_gbps as GB/s and",
        "#               ignores bandwidth_unit (GS-32).",
    ]
    if shared:
        cap = fwd if fwd is not None else back
        lines += [
            "#",
            f"# SHARED VARIANT: nic-s8-to-s6 reserved {round(cap * SHARED_FRACTION, 2)} Gbit/s,",
            f"# {SHARED_FRACTION:.0%} of its capacity -- the registered background duty cycle.",
            "# One field differs from real-s8s6.v2.yaml. A topology ASSUMPTION for the",
            "# prediction, not a measurement.",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import yaml

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    out = OUT_SHARED if args.shared else OUT
    text = header(args.shared) + yaml.safe_dump(
        build(args.shared), sort_keys=False, default_flow_style=False, width=100
    )
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
