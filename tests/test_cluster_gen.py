"""P4.1: the synthetic clusters E-G6 measures the search against.

The generator exists to sweep one knob -- how alike the nodes are -- because
that is what decides whether the compression has anything to fold. So the tests
are about that knob meaning what the docstring says it means, and about the
files loading through heteropilot's own loader rather than through a shape this
repository invented.

Determinism is not a nicety here either. E-G6's result file records the
arguments, not the nine clusters; if the same arguments did not give the same
cluster, the rows would not be reproducible and the table would be a claim
about files nobody has.
"""

from __future__ import annotations

import pytest
import yaml

from graphsearch import paths_root
from graphsearch.synth.cluster_gen import (
    DEVICE_BANDWIDTHS,
    UPLINK_CAPACITIES,
    archetypes,
    build_parser,
    resolve,
    write,
)

paths_root.ensure_importable()

from planner.inventory import (  # noqa: E402
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)


def args_for(tmp_path, **overrides):
    argv = ["--out", str(tmp_path)]
    for key, value in overrides.items():
        argv += [f"--{key.replace('_', '-')}", str(value)]
    return resolve(build_parser().parse_args(argv))


def generated(tmp_path, **overrides):
    args = args_for(tmp_path, **overrides)
    path = write(args)
    return args, path, yaml.safe_load(path.read_text())


# --- (i) it loads, through heteropilot's loader and not ours --------------

@pytest.mark.parametrize("symmetry", [0.0, 0.5, 1.0])
def test_every_generated_cluster_loads_and_detects_islands(tmp_path, symmetry) -> None:
    _args, path, _ = generated(
        tmp_path, nodes=4, devices_per_node=4, symmetry=symmetry, seed=7
    )
    cluster = load_cluster_spec(path)
    assert cluster.schema_version == 2
    assert len(cluster.nodes) == 4
    profiles = load_profiles_for(cluster, paths_root.GRAPHSEARCH_ROOT)
    assert profiles
    assert detect_islands(cluster, profiles), "no island: nothing can be placed"


def test_every_number_is_labelled_placeholder(tmp_path) -> None:
    """Absolute rule 3. A generated capacity is not a measurement of anything,
    and the file has to say so in the field, not only in the header."""
    _, path, document = generated(tmp_path, nodes=3, devices_per_node=2)
    for link in document["links"]:
        assert link["source"] == "placeholder", link["id"]
    for resource in document["shared_resources"]:
        assert resource["source"] == "placeholder", resource["id"]
    assert "FICTIONAL" in path.read_text().splitlines()[0]


# --- (ii) symmetry means what the docstring says -------------------------

def test_symmetry_one_makes_every_node_identical(tmp_path) -> None:
    _, _, document = generated(
        tmp_path, nodes=6, devices_per_node=4, symmetry=1.0,
        device_kinds=3, uplink_kinds=3, seed=11,
    )
    shapes = {
        (
            node["host_price_per_hour_usd"],
            tuple(sorted(a["model"] for a in node["accelerators"])),
            tuple(sorted(a["price_per_hour_usd"] for a in node["accelerators"])),
        )
        for node in document["nodes"]
    }
    assert len(shapes) == 1, f"symmetry=1 left {len(shapes)} distinct node shapes"

    capacities = {r["capacity"] for r in document["shared_resources"]}
    reserved = {r["reserved"] for r in document["shared_resources"]}
    assert len(capacities) == 1 and len(reserved) == 1


def test_symmetry_zero_makes_no_two_nodes_alike(tmp_path) -> None:
    """The designed failure condition, generated on purpose.

    `graph-toy-asym` is the hand-written version of this and exists so the
    compression ratio 1.0 gets reported rather than avoided; at scale the
    generator has to be able to produce the same situation.
    """
    args = args_for(
        tmp_path, nodes=6, devices_per_node=4, symmetry=0.0,
        device_kinds=3, uplink_kinds=3, seed=11,
    )
    import random

    shapes = archetypes(args, random.Random(args.seed))
    assert len(set(shapes)) == len(shapes), "two archetypes collided at symmetry=0"


def test_symmetry_half_splits_the_nodes(tmp_path) -> None:
    """round(0.5 * 8) = 4 identical, 4 distinct -> 5 archetypes."""
    args = args_for(
        tmp_path, nodes=8, devices_per_node=2, symmetry=0.5,
        device_kinds=3, uplink_kinds=3, seed=3,
    )
    import random

    shapes = archetypes(args, random.Random(args.seed))
    assert len(shapes) == 8
    assert len(set(shapes)) == 5, sorted({s.index for s in shapes})


# --- (iii) determinism ---------------------------------------------------

def test_the_same_arguments_give_the_same_file(tmp_path) -> None:
    """Byte for byte, into the same directory.

    E-G6 records the arguments, not the nine clusters. If this fails the rows
    describe files nobody can reproduce.

    Regenerated in place rather than into two directories on purpose: the
    cluster's `profile:` fields point at `--out`, so two output paths change
    the file for a reason that has nothing to do with the seed. Comparing
    across them would either fail for the wrong reason or need a normalisation
    step that could hide a real difference.
    """
    kwargs = {
        "nodes": 5, "devices_per_node": 4, "symmetry": 0.5,
        "device_kinds": 2, "uplink_kinds": 2, "seed": 99,
    }
    _, path, _ = generated(tmp_path, **kwargs)
    first = path.read_bytes()
    _, again, _ = generated(tmp_path, **kwargs)
    assert again == path
    assert again.read_bytes() == first


def test_a_different_seed_gives_a_different_cluster(tmp_path) -> None:
    kwargs = {
        "nodes": 5, "devices_per_node": 2, "symmetry": 0.0, "uplink_kinds": 3,
    }
    _, path_a, doc_a = generated(tmp_path, seed=1, **kwargs)
    _, path_b, doc_b = generated(tmp_path, seed=2, **kwargs)
    assert path_a != path_b, "the seed must reach the cluster id"
    assert doc_a["nodes"] != doc_b["nodes"]


# --- (iv) the arguments that cannot work are refused ---------------------

@pytest.mark.parametrize(
    "overrides",
    [
        {"symmetry": 1.5},
        {"symmetry": -0.1},
        {"shared_fraction": 2.0},
        {"nodes": 0},
        {"device_kinds": len(DEVICE_BANDWIDTHS) + 1},
        {"uplink_kinds": len(UPLINK_CAPACITIES) + 1},
    ],
)
def test_impossible_arguments_are_refused_with_a_reason(tmp_path, overrides) -> None:
    with pytest.raises(SystemExit) as excinfo:
        args_for(tmp_path, **overrides)
    assert str(excinfo.value).strip(), "refused without saying why"


def test_more_kinds_than_distinct_values_is_refused_rather_than_rounded() -> None:
    """Two 'different' device kinds that resolved to the same bandwidth would
    be the same device, and a cluster built from them would be symmetric while
    claiming not to be -- which is the one thing E-G6's x-axis cannot survive."""
    assert len(set(DEVICE_BANDWIDTHS)) == len(DEVICE_BANDWIDTHS)
    assert len(set(UPLINK_CAPACITIES)) == len(UPLINK_CAPACITIES)


# --- (v) the shape the search needs --------------------------------------

def test_devices_are_nvlink_paired_so_tp2_has_a_fast_path(tmp_path) -> None:
    """Without it the candidate space is flat and the compression has nothing
    structural to fold, so the scalability curve would measure enumeration
    alone."""
    _, _, document = generated(tmp_path, nodes=2, devices_per_node=4)
    nvlinks = [link for link in document["links"] if link["type"] == "NVLINK"]
    assert len(nvlinks) == 2 * 2          # two pairs per node, two nodes


def test_shared_fraction_zero_produces_no_shared_resource(tmp_path) -> None:
    _, _, document = generated(tmp_path, nodes=4, devices_per_node=2, shared_fraction=0.0)
    assert document["shared_resources"] == []
    assert all("shared_resource" not in link for link in document["links"])
