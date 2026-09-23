"""G6: fold placements that are provably the same, and nothing else.

The load-bearing tests here are the ones that check compression does NOT
happen:

* `test_a_hash_collision_alone_never_merges` forces two structurally different
  placements into one bucket and requires VF2 to keep them apart. A merge on
  the hash would be undetectable downstream -- the two would arrive as one
  candidate with one prediction -- so it is checked directly rather than
  trusted.
* `test_a_crossed_uplink_is_not_the_same_placement` is the difference the whole
  approach exists to see, and `include_boundary=False` shows what dropping it
  costs.
* `test_the_budget_leaves_a_bucket_split_rather_than_merging_it` pins which way
  the budget fails. An unproved equivalence costs a simulation; a wrong one
  costs the result.
"""

from __future__ import annotations

from collections import defaultdict

import networkx as nx
import pytest

from graphsearch import equivalence, paths_root
from graphsearch.embeddings import enumerate_embeddings
from graphsearch.equivalence import (
    CompressionPolicy,
    EquivalenceLevel,
    compress,
    conflict_matrix,
    multiplicities,
    prediction_key,
    signature,
)
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import FIXTURES, load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import detect_islands  # noqa: E402
from planner.plan import (  # noqa: E402
    CandidateConfig,
    IslandAssignment,
    Role,
    ServingArch,
)
from planner.spec import load_service_spec  # noqa: E402

MODEL = "meta-llama/Llama-3.1-8B"


def spec():
    return load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")


def setup(name: str = "abcde_v2"):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    return (
        cluster,
        profiles,
        islands,
        {i.id: i for i in islands},
        build_resource_graph(cluster, profiles),
    )


def island_named(islands, node: str) -> str:
    return next(i.id for i in islands.values() if i.node_id == node)


def template(assignments, tid: str = "t", **kw) -> CandidateConfig:
    return CandidateConfig(
        id=tid, model=MODEL, dtype="bfloat16", assignments=assignments, **kw
    )


def two_device_embeddings():
    """Every placement of every candidate that uses exactly two accelerators."""
    cluster, profiles, islands, by_id, graph = setup()
    toy_spec = spec()
    generated = CandidateGenerator(
        toy_spec, cluster, islands, profiles, enable_bound_pruning=False
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices == 2]
    found, _ = enumerate_embeddings(templates, by_id, graph, toy_spec)
    return found, graph


# --- the research design's §9 table ---------------------------------------

def test_section_9_five_classes_and_their_multiplicities() -> None:
    """§9's table, reproduced by the pipeline rather than asserted from it.

        | A or B internal pair     |  2 |
        | C or D internal pair     |  2 |
        | A and B spanning         |  4 |
        | C and D spanning         |  4 |
        | A/B and C/D spanning     | 16 |

    Two details are worth stating, because both are places where this could
    have looked right and been wrong.

    §9 calls each row "a single TP group over two accelerators". heteropilot
    forbids a TP group that crosses a node, so the spanning rows arrive as two
    single-device replicas instead. The compression is the same operation on
    the same device pairs; only the parallelism label differs, and it differs
    the way the planner's rules require.

    And the planner's candidate space is RICHER than §9's illustrative scope:
    an intra-node pair also exists as `tp=1, dp=2`, two replicas rather than
    one group. Those are real candidates and they get their own
    representatives, which is why the full count is seven and §9's is five.
    """
    embeddings, graph = two_device_embeddings()
    representatives, _, _ = compress(embeddings, graph)

    by_key = defaultdict(list)
    for representative in representatives:
        by_key[prediction_key(representative.exemplar.template)].append(representative)

    # One class per distinct knob set; they are identical in structure.
    assert len({tuple(multiplicities(v)) for v in by_key.values()}) == 1
    one = by_key[sorted(by_key)[0]]
    assert multiplicities(one) == [2, 2, 2, 2, 4, 4, 16]

    def is_section_9_scope(representative) -> bool:
        assignments = representative.exemplar.template.assignments
        if len(assignments) == 1:
            return assignments[0].tp_size == 2          # one TP group
        return True                                     # a spanning pair

    assert multiplicities([r for r in one if is_section_9_scope(r)]) == [2, 2, 4, 4, 16]


def test_the_sixteen_is_the_a_b_by_c_d_class() -> None:
    """Which row is which, so a future change cannot keep the numbers and lose
    the meaning."""
    embeddings, graph = two_device_embeddings()
    representatives, _, _ = compress(embeddings, graph)
    biggest = max(representatives, key=lambda r: r.multiplicity)
    assert biggest.multiplicity == 16
    nodes = {d.split("/")[0] for d in biggest.exemplar.devices}
    # One fast node and one slow node: the 4x4 cross product.
    assert len(nodes & {"nodeA", "nodeB"}) == 1
    assert len(nodes & {"nodeC", "nodeD"}) == 1


def test_compression_is_reported_not_just_performed() -> None:
    embeddings, graph = two_device_embeddings()
    _, _, report = compress(embeddings, graph)
    assert report.embeddings_in == 192
    assert report.representatives_out == 42
    assert report.exact_merges == report.embeddings_in - report.representatives_out
    assert report.ratio == pytest.approx(42 / 192)
    assert report.vf2_calls > 0


# --- (i) identical nodes fold ---------------------------------------------

def test_two_alike_nodes_give_one_representative() -> None:
    """The saving. A and B differ only in their ids, which no label carries."""
    _, _, _, islands, graph = setup()
    toy_spec = spec()
    templates = [
        template([IslandAssignment(island_id=island_named(islands, node), tp_size=2)], node)
        for node in ("nodeA", "nodeB")
    ]
    found, _ = enumerate_embeddings(templates, islands, graph, toy_spec)
    assert len(found) == 2
    assert signature(found[0], graph) == signature(found[1], graph)
    representatives, _, _ = compress(found, graph)
    assert len(representatives) == 1
    assert representatives[0].multiplicity == 2


def test_two_unalike_nodes_do_not() -> None:
    """A's uplink is 10 GB/s and C's is 5. Same devices, different candidate."""
    _, _, _, islands, graph = setup()
    templates = [
        template([IslandAssignment(island_id=island_named(islands, node), tp_size=2)], node)
        for node in ("nodeA", "nodeC")
    ]
    found, _ = enumerate_embeddings(templates, islands, graph, spec())
    assert signature(found[0], graph) != signature(found[1], graph)
    assert len(compress(found, graph)[0]) == 2


# --- (iii) the boundary is what tells two placements apart ----------------

def test_a_crossed_uplink_is_not_the_same_placement() -> None:
    """X holds 6 of its 10 GB/s for something else; Y's is free.

    Everything local is identical -- same GPUs, same NVLINK, same prices. Fold
    these and you have merged a candidate that will miss its SLO with one that
    will not, and nothing downstream can tell, because the two arrive as one.
    """
    cluster = load_toy_cluster("shared_nic_v2")
    profiles = toy_profiles_for(cluster)
    islands = {i.id: i for i in detect_islands(cluster, profiles)}
    graph = build_resource_graph(cluster, profiles)
    templates = [
        template([IslandAssignment(island_id=island_named(islands, node), tp_size=2)], node)
        for node in ("nodeX", "nodeY")
    ]
    found, _ = enumerate_embeddings(templates, islands, graph, spec())
    assert len(compress(found, graph)[0]) == 2


def test_dropping_the_boundary_merges_them() -> None:
    """The ablation, asserted so the claim above is not circular.

    `include_boundary=False` is not a mode to plan in; it exists so the oracle
    harness can report the mis-merge as a measured number rather than a worry.
    """
    cluster = load_toy_cluster("shared_nic_v2")
    profiles = toy_profiles_for(cluster)
    islands = {i.id: i for i in detect_islands(cluster, profiles)}
    graph = build_resource_graph(cluster, profiles)
    templates = [
        template([IslandAssignment(island_id=island_named(islands, node), tp_size=2)], node)
        for node in ("nodeX", "nodeY")
    ]
    found, _ = enumerate_embeddings(templates, islands, graph, spec())
    blind = CompressionPolicy(include_boundary=False)
    assert len(compress(found, graph, blind)[0]) == 1


# --- (iv) a role swap is a different candidate ----------------------------

def test_swapping_prefill_and_decode_changes_the_signature() -> None:
    _, _, _, islands, graph = setup()
    a, b = island_named(islands, "nodeA"), island_named(islands, "nodeC")
    forward = template(
        [
            IslandAssignment(island_id=a, role=Role.PREFILL, tp_size=1),
            IslandAssignment(island_id=b, role=Role.DECODE, tp_size=1),
        ],
        "fwd",
        serving_arch=ServingArch.PD_SPLIT,
    )
    backward = template(
        [
            IslandAssignment(island_id=a, role=Role.DECODE, tp_size=1),
            IslandAssignment(island_id=b, role=Role.PREFILL, tp_size=1),
        ],
        "bwd",
        serving_arch=ServingArch.PD_SPLIT,
    )
    found, _ = enumerate_embeddings([forward, backward], islands, graph, spec())
    forwards = [e for e in found if e.template.id == "fwd"]
    backwards = [e for e in found if e.template.id == "bwd"]
    assert signature(forwards[0], graph) != signature(backwards[0], graph)


# --- (v) the defence that matters -----------------------------------------

def test_a_hash_collision_alone_never_merges(monkeypatch) -> None:
    """Forced into one bucket, kept apart by VF2.

    A WL hash is one-sided: equal structures hash equal, equal hashes do not
    imply equal structures. This is what stops the cheap test from deciding.
    """
    _, _, _, islands, graph = setup()
    templates = [
        template([IslandAssignment(island_id=island_named(islands, node), tp_size=2)], node)
        for node in ("nodeA", "nodeC")            # genuinely different uplinks
    ]
    found, _ = enumerate_embeddings(templates, islands, graph, spec())

    monkeypatch.setattr(nx, "weisfeiler_lehman_graph_hash", lambda *a, **k: "collide")
    monkeypatch.setattr(equivalence, "_histogram", lambda g: "collide")

    signatures = {signature(e, graph) for e in found}
    assert len(signatures) == 1, "the collision was not forced"

    representatives, _, report = compress(found, graph)
    assert len(representatives) == 2
    assert report.vf2_calls >= 1
    assert report.exact_merges == 0


# --- (vi) which way the budget fails --------------------------------------

def test_the_budget_leaves_a_bucket_split_rather_than_merging_it() -> None:
    """An unproved equivalence costs a simulation; a wrong one costs the result."""
    _, _, _, islands, graph = setup()
    templates = [
        template([IslandAssignment(island_id=island_named(islands, node), tp_size=2)], node)
        for node in ("nodeA", "nodeB")            # these WOULD merge
    ]
    found, _ = enumerate_embeddings(templates, islands, graph, spec())
    assert len(compress(found, graph)[0]) == 1

    starved = CompressionPolicy(max_vf2_seconds=0.0)
    representatives, _, report = compress(found, graph, starved)
    assert len(representatives) == 2
    assert report.exact_merges == 0
    assert report.hash_only_groups >= 1
    assert any(r.level is EquivalenceLevel.HASH_ONLY for r in representatives)


def test_compression_can_be_turned_off_entirely() -> None:
    embeddings, graph = two_device_embeddings()
    representatives, _, report = compress(
        embeddings, graph, CompressionPolicy(enabled=False)
    )
    assert len(representatives) == len(embeddings)
    assert report.exact_merges == 0
    assert all(r.multiplicity == 1 for r in representatives)


# --- (vii) the conflict matrix --------------------------------------------

def test_two_placements_sharing_a_device_conflict() -> None:
    _, _, _, islands, graph = setup()
    island = island_named(islands, "nodeA")
    single = template([IslandAssignment(island_id=island, tp_size=1)], "one")
    pair = template([IslandAssignment(island_id=island, tp_size=2)], "two")
    found, _ = enumerate_embeddings([single, pair], islands, graph, spec())

    singles = [e for e in found if e.template.id == "one"]
    both = next(e for e in found if e.template.id == "two")
    # Each single-device placement uses one of the two devices the pair needs.
    for one in singles:
        assert one.devices < both.devices
        assert frozenset({one.id, both.id}) in conflict_matrix(
            [one, both], graph
        ).conflicts

    # Two disjoint single-device placements do not clash on devices.
    assert conflict_matrix(singles, graph).conflicts == frozenset()


def test_one_embedding_does_not_conflict_with_itself() -> None:
    """A list that repeats an embedding describes one placement, not two."""
    _, _, _, islands, graph = setup()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=1)])
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    assert conflict_matrix([found[0], found[0]], graph).conflicts == frozenset()


def test_two_placements_over_subscribing_one_uplink_conflict() -> None:
    """The second reason, and the one a device check would miss entirely."""
    from dataclasses import replace

    _, _, _, islands, graph = setup()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=1)])
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    capacity = graph.shared_resources["uplink-nodeA"].available_bytes_per_s

    fits = [replace(e, resource_demand={"uplink-nodeA": capacity * 0.4}) for e in found]
    assert conflict_matrix(fits, graph).conflicts == frozenset()

    does_not = [replace(e, resource_demand={"uplink-nodeA": capacity * 0.6}) for e in found]
    assert len(conflict_matrix(does_not, graph).conflicts) == 1


def test_multiplicity_is_not_max_concurrent() -> None:
    """A representative covering 16 placements does not mean 16 deployments fit.

    `restore.py` enforces this; here it is pinned so the two numbers cannot
    quietly become one.
    """
    embeddings, graph = two_device_embeddings()
    representatives, conflicts, _ = compress(embeddings, graph)
    biggest = max(representatives, key=lambda r: r.multiplicity)
    assert biggest.multiplicity == 16
    assert conflicts.max_concurrent(biggest) < biggest.multiplicity


# --- (viii) determinism, and what a representative carries ----------------

def test_the_partition_repeats() -> None:
    embeddings, graph = two_device_embeddings()
    first, _, _ = compress(embeddings, graph)
    second, _, _ = compress(embeddings, graph)
    assert [r.rep_id for r in first] == [r.rep_id for r in second]
    assert [sorted(e.id for e in r.embeddings) for r in first] == [
        sorted(e.id for e in r.embeddings) for r in second
    ]


def test_every_embedding_lands_in_exactly_one_representative() -> None:
    embeddings, graph = two_device_embeddings()
    representatives, _, _ = compress(embeddings, graph)
    seen = [e.id for r in representatives for e in r.embeddings]
    assert len(seen) == len(embeddings)
    assert len(set(seen)) == len(seen)


def test_a_representative_carries_a_mapping_back_to_every_member() -> None:
    """What `restore.py` turns a plan into physical devices with."""
    embeddings, graph = two_device_embeddings()
    representatives, _, _ = compress(embeddings, graph)
    for representative in representatives:
        assert set(representative.role_mappings) == {
            e.id for e in representative.embeddings
        }


def test_the_signature_records_the_tool_it_was_computed_with() -> None:
    """GS-2: a WL hash is only comparable against itself."""
    _, _, _, islands, graph = setup()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=2)])
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    version = signature(found[0], graph).tool_version
    assert version.startswith(f"networkx=={nx.__version__}")
    assert "labels=" in version


def test_knobs_are_in_the_bucket_key_though_not_in_the_graph() -> None:
    """Two templates differing only in `max_num_seqs` have identical graphs and
    simulate differently. Merging them would be a real mis-merge, which is why
    the bucket key is not simply the signature."""
    from planner.plan import VllmKnobs

    _, _, _, islands, graph = setup()
    island = island_named(islands, "nodeA")
    a = template([IslandAssignment(island_id=island, tp_size=2)], "a",
                 knobs=VllmKnobs(max_num_seqs=32))
    b = template([IslandAssignment(island_id=island, tp_size=2)], "b",
                 knobs=VllmKnobs(max_num_seqs=128))
    found, _ = enumerate_embeddings([a, b], islands, graph, spec())
    assert signature(found[0], graph) == signature(found[1], graph)
    assert prediction_key(a) != prediction_key(b)
    assert len(compress(found, graph)[0]) == 2
