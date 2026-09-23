"""G5: templates become placements on named devices.

The counts here are the ones the compression in G6 will be measured against, so
they are asserted as arithmetic rather than as whatever the code happens to
produce: for an island of n free devices, R replicas of D devices each,

    C(n, R*D) x (R*D)! / (D!^R x R!)

distinct placements. `test_the_counts_are_the_combinatorics` states it directly
so a change in enumeration cannot quietly move the denominator of every
compression ratio in the paper.
"""

from __future__ import annotations

from math import comb, factorial

import pytest
import yaml

from graphsearch import paths_root
from graphsearch.demand import FlowKind
from graphsearch.embeddings import (
    EmbeddingPolicy,
    embeddings_by_template,
    enumerate_embeddings,
)
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import FIXTURES, load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import (  # noqa: E402
    ClusterSpecV2,
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)
from planner.plan import CandidateConfig, IslandAssignment  # noqa: E402
from planner.spec import load_service_spec  # noqa: E402

HP_ROOT = paths_root.HETEROPILOT_ROOT
GS_ROOT = paths_root.GRAPHSEARCH_ROOT
MODEL = "meta-llama/Llama-3.1-8B"


def spec():
    return load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")


def toy(name: str = "abcde_v2"):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    return (
        {i.id: i for i in detect_islands(cluster, profiles)},
        build_resource_graph(cluster, profiles),
    )


def island_named(islands, node: str) -> str:
    return next(i.id for i in islands.values() if i.node_id == node)


def template(assignments, tid: str = "t") -> CandidateConfig:
    return CandidateConfig(
        id=tid, model=MODEL, dtype="bfloat16", assignments=assignments
    )


_GPU = (
    "      - {{id: gpu{i}, type: GPU, vendor: TOY, model: TOYGPU, backend: cuda,\n"
    "         memory_gb: 80, profile: fixtures/profiles/toy_gpu.yaml}}"
)


def n_gpu(count: int):
    """A single fully-connected island of `count` devices, built at column 0."""
    body = (
        "cluster_id: n\nnodes:\n  - id: n0\n    accelerators:\n"
        + "\n".join(_GPU.format(i=i) for i in range(count))
        + "\n    nics:\n      - {id: nic0, type: ethernet, speed_gbps: 10}\nlinks:\n"
        + "\n".join(
            f"  - {{id: l{a}{b}, src: n0/gpu{a}, dst: n0/gpu{b}, type: NVLINK,\n"
            f"     bandwidth_gbps: 112.5, latency_ns: 500}}"
            for a in range(count)
            for b in range(a + 1, count)
        )
        + "\n"
    )
    cluster = ClusterSpecV2.model_validate(yaml.safe_load(body))
    profiles = load_profiles_for(cluster, GS_ROOT)
    return (
        {i.id: i for i in detect_islands(cluster, profiles)},
        build_resource_graph(cluster, profiles),
    )


def expected(n: int, replicas: int, per_replica: int) -> int:
    need = replicas * per_replica
    return (
        comb(n, need)
        * factorial(need)
        // (factorial(per_replica) ** replicas * factorial(replicas))
    )


# --- (i)-(ii) the counts --------------------------------------------------

def test_a_full_island_has_exactly_one_placement() -> None:
    """§9's node A holds two devices, so tp=2 uses both and there is no choice."""
    islands, graph = toy()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=2)])
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    assert len(found) == 1
    assert found[0].devices == {"nodeA/gpu0", "nodeA/gpu1"}


def test_one_device_of_two_is_two_placements() -> None:
    islands, graph = toy()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=1)])
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    assert {tuple(sorted(e.devices)) for e in found} == {
        ("nodeA/gpu0",), ("nodeA/gpu1",)
    }


def test_two_islands_multiply() -> None:
    islands, graph = toy()
    tmpl = template(
        [
            IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=1),
            IslandAssignment(island_id=island_named(islands, "nodeB"), tp_size=1),
        ]
    )
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    assert len(found) == 4


@pytest.mark.parametrize(
    "devices, tp, dp",
    [(4, 1, 1), (4, 2, 1), (4, 1, 2), (4, 2, 2), (4, 4, 1), (3, 1, 2)],
)
def test_the_counts_are_the_combinatorics(devices: int, tp: int, dp: int) -> None:
    """C(n, RD) x (RD)!/(D!^R R!). Every compression ratio divides by this."""
    islands, graph = n_gpu(devices)
    tmpl = template(
        [IslandAssignment(island_id=next(iter(islands)), tp_size=tp, dp_replicas=dp)]
    )
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    assert len(found) == expected(devices, dp, tp)


def test_an_island_too_small_yields_nothing_rather_than_raising() -> None:
    """Not an error: the generator produces templates per island, and one that
    does not fit is simply a template with no embedding."""
    islands, graph = n_gpu(2)
    tmpl = template(
        [IslandAssignment(island_id=next(iter(islands)), tp_size=2, dp_replicas=2)]
    )
    found, stats = enumerate_embeddings([tmpl], islands, graph, spec())
    assert found == []
    assert stats.embeddings == 0


# --- symmetry -------------------------------------------------------------

def test_replica_order_is_folded_and_the_fold_is_counted() -> None:
    """Four devices into two unordered pairs is 3, not 6.

    `skipped_symmetric` is the evidence. The work order's example reads
    "dp=2 tp=1 -> 3"; 3 is the count for tp=2 dp=2 (partitioning 4 labelled
    devices into 2 unordered pairs), while tp=1 dp=2 is 6. Both are asserted.
    """
    islands, graph = n_gpu(4)
    tmpl = template(
        [IslandAssignment(island_id=next(iter(islands)), tp_size=2, dp_replicas=2)]
    )
    folded, stats = enumerate_embeddings([tmpl], islands, graph, spec())
    assert len(folded) == 3
    assert stats.skipped_symmetric == 3

    ordered, _ = enumerate_embeddings(
        [tmpl], islands, graph, spec(), EmbeddingPolicy(canonical_only=False)
    )
    assert len(ordered) == 6


def test_the_other_reading_of_that_example() -> None:
    islands, graph = n_gpu(4)
    tmpl = template(
        [IslandAssignment(island_id=next(iter(islands)), tp_size=1, dp_replicas=2)]
    )
    folded, stats = enumerate_embeddings([tmpl], islands, graph, spec())
    assert len(folded) == 6
    assert stats.skipped_symmetric == 6


def test_one_replica_has_no_symmetry_to_remove() -> None:
    islands, graph = n_gpu(4)
    tmpl = template([IslandAssignment(island_id=next(iter(islands)), tp_size=2)])
    _, stats = enumerate_embeddings([tmpl], islands, graph, spec())
    assert stats.skipped_symmetric == 0


# --- (iii) a cap is a scope statement -------------------------------------

def test_a_cap_truncates_and_says_by_how_much() -> None:
    """Dropped-for-budget is not infeasible. G7 turns this into
    `EXCLUDED_BY_SCOPE`, which needs both the count and the template id."""
    islands, graph = toy()
    tmpl = template(
        [
            IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=1),
            IslandAssignment(island_id=island_named(islands, "nodeB"), tp_size=1),
        ]
    )
    found, stats = enumerate_embeddings(
        [tmpl], islands, graph, spec(), EmbeddingPolicy(max_embeddings_per_template=1)
    )
    assert len(found) == 1
    assert stats.truncated_by_policy == 3
    assert stats.truncated_template_ids == ["t"]


def test_no_cap_records_no_truncation() -> None:
    islands, graph = toy()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=1)])
    _, stats = enumerate_embeddings([tmpl], islands, graph, spec())
    assert stats.truncated_by_policy == 0
    assert stats.truncated_template_ids == []


# --- (v) the regression: one placement per template -----------------------

def test_a_cluster_of_exactly_sized_islands_reduces_to_the_templates() -> None:
    """Design §7.5. Where every island is exactly the size a candidate needs,
    the embedding set is the template set -- so the graph mode has not invented
    a search space where heteropilot had none."""
    cluster = load_cluster_spec(HP_ROOT / "examples/clusters/heterogeneous-lab.yaml")
    profiles = load_profiles_for(cluster, HP_ROOT)
    islands = detect_islands(cluster, profiles)
    hp_spec = load_service_spec(HP_ROOT / "examples/service_specs/llama31-8b.yaml")
    graph = build_resource_graph(cluster, profiles)

    generated = CandidateGenerator(
        hp_spec, cluster, islands, profiles, enable_bound_pruning=False
    ).generate()
    by_id = {i.id: i for i in islands}
    exact = [
        c
        for c in generated.candidates
        if all(
            a.total_devices == by_id[a.island_id].size for a in c.assignments
        )
    ]
    assert exact, "no exactly-sized candidate to check"

    found, _ = enumerate_embeddings(exact, by_id, graph, hp_spec)
    grouped = embeddings_by_template(found)
    for candidate in exact:
        assert len(grouped[candidate.id]) == 1
        assert grouped[candidate.id][0].template is candidate


# --- (vii) what the boundary carries --------------------------------------

def test_a_cross_node_placement_carries_both_uplinks() -> None:
    islands, graph = toy()
    tmpl = template(
        [
            IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=1),
            IslandAssignment(island_id=island_named(islands, "nodeB"), tp_size=1),
        ]
    )
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    for embedding in found:
        assert {"uplink-nodeA", "uplink-nodeB"} <= embedding.boundary.shared_resources


def test_an_intra_node_placement_does_not_claim_the_far_uplink() -> None:
    """The difference the equivalence layer exists to see."""
    islands, graph = toy()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=2)])
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    assert "uplink-nodeB" not in found[0].boundary.shared_resources


def test_resource_demand_is_bytes_per_second_not_per_request() -> None:
    islands, graph = toy()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=2)])
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    demand = found[0].resource_demand
    assert demand
    assert all(v > 0 for v in demand.values())


def test_the_flows_come_from_the_placement_not_the_template() -> None:
    islands, graph = toy()
    tmpl = template([IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=2)])
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    tp_flows = [f for f in found[0].flows if f.kind is FlowKind.TP_ALLREDUCE]
    assert len(tp_flows) == 1
    assert set(tp_flows[0].participants) == found[0].devices


# --- (vi) identity and determinism ----------------------------------------

def test_ids_are_unique_and_the_order_repeats() -> None:
    islands, graph = n_gpu(4)
    tmpl = template(
        [IslandAssignment(island_id=next(iter(islands)), tp_size=2, dp_replicas=2)]
    )
    first, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    second, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    ids = [e.id for e in first]
    assert len(set(ids)) == len(ids)
    assert ids == [e.id for e in second]


def test_the_key_ignores_the_order_a_placement_was_built_in() -> None:
    islands, graph = n_gpu(4)
    tmpl = template(
        [IslandAssignment(island_id=next(iter(islands)), tp_size=2, dp_replicas=2)]
    )
    found, _ = enumerate_embeddings([tmpl], islands, graph, spec())
    by_devices = {frozenset(e.devices): e.embedding_key for e in found}
    # All three use all four devices; the key must still tell them apart,
    # because WHICH pairs are replicas is a different placement.
    assert len(by_devices) == 1
    assert len({e.embedding_key for e in found}) == 3


def test_an_unknown_island_is_an_error() -> None:
    islands, graph = toy()
    tmpl = template([IslandAssignment(island_id="no-such-island", tp_size=1)])
    with pytest.raises(KeyError, match="not in this inventory"):
        enumerate_embeddings([tmpl], islands, graph, spec())


# --- the mock reads the placement ----------------------------------------

def test_the_mock_charges_a_crossed_uplink() -> None:
    """A placement that leaves the node must not predict the same as one that
    stays on it -- otherwise the search cannot tell them apart and G6's care
    about boundaries buys nothing."""
    from tests.graph_fixtures import GraphAwareMockPredictor

    cluster = load_toy_cluster("abcde_v2")
    profiles = toy_profiles_for(cluster)
    islands = {i.id: i for i in detect_islands(cluster, profiles)}
    graph = build_resource_graph(cluster, profiles)
    toy_spec = spec()

    inside = template(
        [IslandAssignment(island_id=island_named(islands, "nodeA"), tp_size=2)], "inside"
    )
    found, _ = enumerate_embeddings([inside], islands, graph, toy_spec)

    predictor = GraphAwareMockPredictor()
    predictor.bind_graph(graph)
    bare = predictor.predict(inside, toy_spec, cluster, islands, profiles)

    predictor.bind_embeddings({"inside": found[0]})
    priced = predictor.predict(inside, toy_spec, cluster, islands, profiles)

    assert priced.metrics is not None and bare.metrics is not None
    # Never faster than the base figure: the mock only ADDS communication time,
    # so it cannot beat the roofline bound that admitted the candidate.
    assert priced.metrics.p99_tpot_ms >= bare.metrics.p99_tpot_ms
    assert priced.metrics.p99_ttft_ms >= bare.metrics.p99_ttft_ms


# --- the research design's §9 count, end to end ---------------------------

def test_section_9_counts_45_physical_pairs_down_to_28() -> None:
    """The headline number of the whole approach, produced rather than asserted.

    §9's cluster holds 10 accelerators, so 45 unordered pairs exist. Of those,
    17 involve an NPU: 8 A/B-GPU-with-NPU, 8 C/D-GPU-with-NPU, and the NPU pair
    itself. The example's runtime contract does not support them, and this
    repository expresses that with no special case at all -- `toy_npu.yaml`
    declares no `sim_hardware`, so the generator's first stage drops every
    candidate that would use one.

    28 GPU pairs are left, and G6 folds them to 5 representatives.
    """
    from itertools import combinations

    cluster = load_toy_cluster("abcde_v2")
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    graph = build_resource_graph(cluster, profiles)
    toy_spec = spec()

    accelerators = [
        f"{node.id}/{accel.id}" for node in cluster.nodes for accel in node.accelerators
    ]
    assert len(list(combinations(accelerators, 2))) == 45

    generated = CandidateGenerator(
        toy_spec, cluster, islands, profiles, enable_bound_pruning=False
    ).generate()
    two_device = [c for c in generated.candidates if c.total_devices == 2]
    found, _ = enumerate_embeddings(
        two_device, {i.id: i for i in islands}, graph, toy_spec
    )

    pairs = {frozenset(e.devices) for e in found}
    assert len(pairs) == 28
    assert not any(
        "npu" in device for pair in pairs for device in pair
    ), "an NPU pair reached enumeration; the runtime contract stopped working"
