"""P4.1: synthetic clusters for the scalability study, every number placeholder.

E-G6 asks how the search's cost grows with two things: **how many devices**
there are, and **how alike the nodes are**. The second is the one that matters,
because the compression folds isomorphic placements and a cluster with no two
nodes alike has nothing to fold. So the generator takes a `--symmetry` knob and
the grid sweeps it.

**What `--symmetry` means, exactly.** The fraction of nodes that are identical
to one another:

    identical = round(symmetry * nodes)     nodes sharing archetype 0
    the rest  = nodes - identical           one distinct archetype each

so `--symmetry 1` gives one archetype and every node alike, `--symmetry 0`
gives `nodes` archetypes and no two alike, and `--symmetry 0.5` over 8 nodes
gives four identical plus four distinct — five archetypes. Written down here
because the E-G6 curve is plotted against this number, and "symmetry" could
reasonably have meant three other things.

**Nothing generated here is a measurement.** Every capacity, price, latency and
bandwidth is `source: placeholder`, and the file says so in its own header. The
profiles carry `sim_hardware: A5000` so the mock predictor has a perf bundle to
read; the devices described are not A5000s and nothing measured about an A5000
may be claimed from a run on them.

    python -m graphsearch.synth.cluster_gen \\
        --nodes 16 --devices-per-node 8 --symmetry 0.5 --seed 42 \\
        --out outputs/synth/n16d8s05
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path

import yaml

#: Capacities a generated uplink may take, GB/s. A closed list rather than a
#: continuous draw: `--uplink-kinds 3` has to mean three DISTINCT capacities, or
#: two nodes drawn from it could differ by 0.01 GB/s and count as asymmetric
#: while being, for every purpose the search has, the same node.
UPLINK_CAPACITIES = (10.0, 25.0, 50.0, 100.0, 200.0, 400.0)

#: Memory bandwidths a generated device kind may take, GB/s. Same reasoning.
DEVICE_BANDWIDTHS = (768.0, 1024.0, 1555.0, 2039.0, 3352.0, 4800.0)

PROFILE_HEADER = """\
# GENERATED, FICTIONAL, and not a description of any device.
#
# Written by graphsearch/synth/cluster_gen.py for the E-G6 scalability study.
# Every number is `source: placeholder`. `sim_hardware: A5000` reuses
# heteropilot's measured perf bundle so the mock predictor has something to
# read -- the device described here is NOT an A5000 and nothing measured about
# an A5000 may be claimed from a run on this file.
"""


@dataclass(frozen=True)
class Archetype:
    """One node shape. Nodes sharing an archetype are identical, field for field."""

    index: int
    device_kind: int
    uplink_capacity: float
    reserved: float
    host_price: float
    device_price: float
    shared: bool


def archetypes(args, rng: random.Random) -> list[Archetype]:
    """One archetype per node, `round(symmetry * nodes)` of them the same.

    Drawn in a fixed order from a seeded generator, so the same arguments give
    the same cluster byte for byte. The common archetype is index 0 and is
    always drawn first, which is why raising `--symmetry` does not reshuffle
    the nodes that were already alike -- it only adds more of them.
    """
    identical = round(args.symmetry * args.nodes)
    identical = max(0, min(args.nodes, identical))

    def draw(index: int) -> Archetype:
        return Archetype(
            index=index,
            device_kind=rng.randrange(args.device_kinds),
            uplink_capacity=UPLINK_CAPACITIES[rng.randrange(args.uplink_kinds)],
            # Distinct reservations are what make two otherwise-identical nodes
            # non-isomorphic, so this is the knob asymmetry actually turns.
            reserved=round(rng.uniform(0.0, 0.5), 3),
            host_price=round(rng.uniform(0.5, 2.0), 3),
            device_price=round(rng.uniform(1.0, 4.0), 3),
            shared=rng.random() < args.shared_fraction,
        )

    common = draw(0)
    out = [common] * identical
    out.extend(draw(i + 1) for i in range(args.nodes - identical))
    return out


def profiles_for(args, kinds: set[int]) -> dict[str, dict]:
    """One profile document per device kind actually used."""
    out = {}
    for kind in sorted(kinds):
        out[f"kind{kind}"] = {
            "profile_id": f"synth-kind{kind}",
            "vendor": "SYNTH",
            "model": f"SYNTHDEV{kind}",
            "backend": "cuda",
            "memory_gb": 80,
            "memory_bandwidth_gbps": DEVICE_BANDWIDTHS[kind % len(DEVICE_BANDWIDTHS)],
            "sim_hardware": "A5000",
            "source": "placeholder",
            "perf_data": "profiler/perf/A5000/",
            "price_per_hour_usd": 2.0,
            "price_source": "placeholder",
            "supported_models": [
                {"pattern": "meta-llama/Llama-3.1-8B", "dtypes": ["bfloat16"]}
            ],
            "max_tp_size": args.max_tp_size,
            "runtime_capabilities": {
                "collectives": ["all_reduce", "p2p"],
                "max_world_size": 8,
                "kv_transfer": True,
                "source": "placeholder",
            },
        }
    return out


def build(args) -> tuple[dict, dict[str, dict]]:
    """The cluster document and the profile documents it references."""
    rng = random.Random(args.seed)
    shapes = archetypes(args, rng)

    nodes: list[dict] = []
    links: list[dict] = []
    shared: list[dict] = []

    for index, shape in enumerate(shapes):
        node_id = f"node{index:03d}"
        profile = f"{args.profile_dir}/kind{shape.device_kind}.yaml"
        accelerators = [
            {
                "id": f"gpu{d}",
                "type": "GPU",
                "vendor": "SYNTH",
                "model": f"SYNTHDEV{shape.device_kind}",
                "backend": "cuda",
                "memory_gb": 80,
                "profile": profile,
                "price_per_hour_usd": shape.device_price,
            }
            for d in range(args.devices_per_node)
        ]
        nodes.append(
            {
                "id": node_id,
                "cpu_sockets": [{"id": "sock0", "numa_node": 0}],
                "host_price_per_hour_usd": shape.host_price,
                "accelerators": accelerators,
                "nics": [{"id": "nic0", "type": "ethernet", "speed_gbps": 100}],
            }
        )

        uplink_id = f"uplink-{node_id}"
        if shape.shared:
            shared.append(
                {
                    "id": uplink_id,
                    "kind": "pcie_uplink",
                    "capacity": shape.uplink_capacity,
                    "unit": "GB/s",
                    "reserved": round(shape.reserved * shape.uplink_capacity, 3),
                    "node": node_id,
                    "source": "placeholder",
                }
            )

        # Devices are paired by an NVLINK, the way a real board does it, so a
        # tp=2 group has a fast path and a tp=4 one does not. Without that the
        # candidate space is flat and the compression has nothing structural
        # to fold.
        for d in range(0, args.devices_per_node - 1, 2):
            links.append(
                {
                    "id": f"l-{node_id}-nv{d}",
                    "src": f"{node_id}/gpu{d}",
                    "dst": f"{node_id}/gpu{d + 1}",
                    "type": "NVLINK",
                    "bandwidth_gbps": 112.5,
                    "latency_ns": 500,
                    "source": "placeholder",
                }
            )
        for d in range(args.devices_per_node):
            link = {
                "id": f"l-{node_id}-up{d}",
                "src": f"{node_id}/gpu{d}",
                "dst": f"{node_id}/nic0",
                "type": "PCIE",
                "bandwidth_gbps": shape.uplink_capacity,
                "latency_ns": 900,
                "source": "placeholder",
            }
            if shape.shared:
                link["shared_resource"] = uplink_id
            links.append(link)
        links.append(
            {
                "id": f"l-{node_id}-sw",
                "src": f"{node_id}/nic0",
                "dst": "sw0",
                "type": "ETHERNET",
                "bandwidth_gbps": 100.0,
                "latency_ns": 5000,
                "source": "placeholder",
            }
        )

    cluster = {
        "cluster_id": args.cluster_id,
        "schema_version": 2,
        "nodes": nodes,
        "net_switches": [{"id": "sw0", "ports": max(8, len(nodes))}],
        "shared_resources": shared,
        "links": links,
    }
    return cluster, profiles_for(args, {s.device_kind for s in shapes})


def header(args, shapes: list[Archetype]) -> str:
    distinct = len(set(shapes))
    return (
        f"# GENERATED, FICTIONAL. Not a description of any cluster.\n"
        f"#\n"
        f"# graphsearch/synth/cluster_gen.py, for the E-G6 scalability study.\n"
        f"# Every number below is `source: placeholder`; a result computed from\n"
        f"# this file is a result about the SEARCH and not about hardware.\n"
        f"#\n"
        f"# nodes={args.nodes} devices_per_node={args.devices_per_node} "
        f"(={args.nodes * args.devices_per_node} devices)\n"
        f"# symmetry={args.symmetry} -> {distinct} distinct archetype(s) over "
        f"{args.nodes} nodes\n"
        f"# device_kinds={args.device_kinds} uplink_kinds={args.uplink_kinds} "
        f"shared_fraction={args.shared_fraction} seed={args.seed}\n"
        f"#\n"
        f"# Regenerate with exactly these arguments and you get this file back,\n"
        f"# byte for byte. That is what makes the E-G6 rows reproducible\n"
        f"# without committing nine clusters.\n"
    )


def write(args) -> Path:
    cluster, profiles = build(args)
    rng_shapes = archetypes(args, random.Random(args.seed))

    out = Path(args.out)
    (out / "profiles").mkdir(parents=True, exist_ok=True)
    for name, document in sorted(profiles.items()):
        (out / "profiles" / f"{name}.yaml").write_text(
            PROFILE_HEADER
            + yaml.safe_dump(document, sort_keys=True, default_flow_style=False)
        )

    path = out / f"{args.cluster_id}.v2.yaml"
    path.write_text(
        header(args, rng_shapes)
        + yaml.safe_dump(cluster, sort_keys=False, default_flow_style=False)
    )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m graphsearch.synth.cluster_gen",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--devices-per-node", type=int, default=4)
    parser.add_argument("--device-kinds", type=int, default=1)
    parser.add_argument("--uplink-kinds", type=int, default=1)
    parser.add_argument("--shared-fraction", type=float, default=1.0)
    parser.add_argument("--symmetry", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tp-size", type=int, default=2)
    parser.add_argument("--cluster-id", default=None)
    parser.add_argument(
        "--profile-dir", default=None,
        help="what the cluster's `profile:` fields point at, relative to the "
             "root the loader is given. Defaults to `<out>/profiles`.",
    )
    parser.add_argument("--out", default="outputs/synth")
    return parser


def resolve(args) -> argparse.Namespace:
    """Fill the derived defaults and refuse the arguments that cannot work."""
    if not 0.0 <= args.symmetry <= 1.0:
        raise SystemExit(f"--symmetry must be in [0, 1], got {args.symmetry}")
    if not 0.0 <= args.shared_fraction <= 1.0:
        raise SystemExit(
            f"--shared-fraction must be in [0, 1], got {args.shared_fraction}"
        )
    if args.nodes < 1 or args.devices_per_node < 1:
        raise SystemExit("--nodes and --devices-per-node must be >= 1")
    if not 1 <= args.device_kinds <= len(DEVICE_BANDWIDTHS):
        raise SystemExit(
            f"--device-kinds must be 1..{len(DEVICE_BANDWIDTHS)}; each kind "
            f"needs a distinct memory bandwidth or two 'different' devices "
            f"would be the same device"
        )
    if not 1 <= args.uplink_kinds <= len(UPLINK_CAPACITIES):
        raise SystemExit(
            f"--uplink-kinds must be 1..{len(UPLINK_CAPACITIES)}; each kind "
            f"needs a distinct capacity"
        )
    if args.cluster_id is None:
        args.cluster_id = (
            f"synth-n{args.nodes}-d{args.devices_per_node}"
            f"-s{str(args.symmetry).replace('.', '')}-seed{args.seed}"
        )
    if args.profile_dir is None:
        args.profile_dir = f"{args.out.rstrip('/')}/profiles"
    return args


def main(argv: list[str] | None = None) -> int:
    args = resolve(build_parser().parse_args(argv))
    path = write(args)
    print(f"{path}  ({args.nodes * args.devices_per_node} devices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
