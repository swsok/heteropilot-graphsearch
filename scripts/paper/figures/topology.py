"""The eight-GPU node and the three placements E-G5 deploys on it (revision R3.1).

Everything drawn is read from the cluster description and the experiment's own
condition table, never typed in:

- devices, the NVLink pairs and every GPU's PCIe port come from
  `fixtures/clusters/real-a40x8.v2.yaml`;
- the three link figures are that file's MEASURED entries -- the NVLink pair's
  p2p plateau, the PCIe pair's p2p plateau across the host bridge, and the
  four-rank all-reduce bus bandwidth -- so the paper's literal-number rule holds
  for the figure as it does for the text;
- T1, T2 and T3 are `experiments/e_g5/conditions.py`'s `TOPOLOGIES`.

The description does not say which CPU socket or PCIe switch a GPU hangs off,
so neither is drawn: a figure that placed them would be inventing a topology
the measurements never saw.

    python scripts/paper/figures/topology.py --out-dir paper/figures
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures" / "clusters" / "real-a40x8.v2.yaml"
CONDITIONS = ROOT / "experiments" / "e_g5" / "conditions.py"

#: Colour per placement, and the order they are drawn in (largest first, so
#: T3's outline does not hide the pairs inside it).
PLACEMENT_STYLE = {"T3": "#7b3294", "T2": "#e66101", "T1": "#1a9641"}


def _measured(links: list[dict], link_id: str, collective: str, world: int) -> float:
    for link in links:
        if link["id"] != link_id:
            continue
        for m in link.get("measurements") or []:
            if (m["collective"], m["world_size"]) == (collective, world) \
                    and m.get("source") == "measured":
                return float(m["bus_bw_gbps"])
    raise SystemExit(f"topology.py: no measured {collective} w{world} on {link_id}")


def _topologies() -> dict[str, tuple[int, ...]]:
    sys.path.insert(0, str(CONDITIONS.parent))
    import conditions

    return {key: tuple(t.devices) for key, t in conditions.TOPOLOGIES.items()
            if key in PLACEMENT_STYLE}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, default=ROOT / "paper" / "figures")
    args = parser.parse_args(argv)

    try:
        import matplotlib
    except ModuleNotFoundError:
        print("topology.py: matplotlib is not installed; no figure written", file=sys.stderr)
        return 1
    import yaml

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    spec = yaml.safe_load(FIXTURE.read_text())
    node = spec["nodes"][0]
    gpus = [a["id"] for a in node["accelerators"]]
    links = spec["links"]
    nvlink = sorted(tuple(link["id"].split("-")) for link in links if link["type"] == "NVLINK")
    ports = {r["id"].removeprefix("port-"): r for r in spec["shared_resources"]
             if r["kind"] == "pcie_uplink"}
    nvl_bw = _measured(links, "gpu0-gpu1", "p2p", 2)
    pcie_bw = _measured(links, "gpu0-gpu2", "p2p", 2)
    ring_bw = _measured(links, "gpu0-gpu2", "all_reduce", 4)
    placements = _topologies()

    # GPUs left to right in index order, NVLink partners adjacent; the fabric
    # below them, and one row per placement under that, a marker under each
    # device the placement uses -- T2 is {0, 2}, not the span from 0 to 2.
    x = {g: 1.0 + i for i, g in enumerate(gpus)}
    y_gpu, y_fabric = 3.0, 1.95
    rows = {"T1": 1.25, "T2": 0.85, "T3": 0.45}
    fig, ax = plt.subplots(figsize=(3.45, 2.05))
    right = x[gpus[-1]] + 0.5

    ax.add_patch(FancyBboxPatch((0.5, y_fabric - 0.17), right - 0.5, 0.34,
                                boxstyle="round,pad=0.02", fc="#f2f2f2", ec="#888888", lw=0.6))
    ax.text(0.6, y_fabric, f"host PCIe ({node['id']})", fontsize=5.5, va="center")
    nic = node["nics"][0]
    ax.text(right - 0.1, y_fabric, f"{nic['id']}: {nic['type']}", fontsize=5.5,
            va="center", ha="right")
    for g in gpus:
        ax.plot([x[g], x[g]], [y_gpu - 0.2, y_fabric + 0.17], color="#888888", lw=0.6)
    port_cap = {round(float(ports[g]["capacity"]), 2) for g in gpus if g in ports}
    if len(port_cap) == 1:
        ax.text(x[gpus[0]] + 0.06, (y_gpu + y_fabric) / 2 - 0.05,
                f"port {port_cap.pop():g} GB/s", fontsize=4.8, color="#555555")

    for a, b in nvlink:
        ax.plot([x[a] + 0.2, x[b] - 0.2], [y_gpu, y_gpu], color="#2c7bb6", lw=2.0)
    a, b = nvlink[0]
    ax.text((x[a] + x[b]) / 2, y_gpu + 0.3, f"NVLink {nvl_bw:g} GB/s", fontsize=4.8,
            ha="center", color="#2c7bb6")
    for g in gpus:
        ax.add_patch(FancyBboxPatch((x[g] - 0.2, y_gpu - 0.2), 0.4, 0.4,
                                    boxstyle="round,pad=0.02", fc="white", ec="black", lw=0.6))
        ax.text(x[g], y_gpu, g.removeprefix("gpu"), fontsize=6, ha="center", va="center")

    what = {"T1": "NVLink pair",
            "T2": f"across the host bridge, PCIe {pcie_bw:g} GB/s",
            "T3": f"two NVLink pairs bridged, all-reduce w4 {ring_bw:g} GB/s"}
    for key, y in rows.items():
        devices = [gpus[i] for i in placements[key]]
        colour = PLACEMENT_STYLE[key]
        ax.plot([x[d] for d in devices], [y] * len(devices), "o", ms=3.2, color=colour)
        if len(devices) > 1:
            ax.plot([min(x[d] for d in devices), max(x[d] for d in devices)], [y, y],
                    color=colour, lw=0.5, ls=":")
        ax.text(0.55, y, key, fontsize=5.8, va="center", color=colour, fontweight="bold")
        ax.text(x[gpus[4]] - 0.3, y, what[key], fontsize=4.8, va="center", color=colour)
    ax.set_xlim(0.4, right + 0.05)
    ax.set_ylim(0.2, y_gpu + 0.5)
    ax.set_aspect("equal")
    ax.axis("off")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / "topology.pdf"
    fig.savefig(out, bbox_inches="tight", metadata={"CreationDate": None})
    plt.close(fig)
    print(f"{FIXTURE.relative_to(ROOT)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
