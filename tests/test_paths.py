"""G2: paths, cut capacity, and the boundary a candidate does not own.

The cut is the number a communication-latency bound divides into, so the tests
that matter are the ones pinning its DIRECTION of error. A cut that is too
large only makes a bound weaker; a cut that is too small rejects a candidate
that would have met its SLO, which is the failure the "a pruning stage is a
relaxation of feasibility" rule exists to prevent.

So: parallel links must add up, an external reservation must come off, and an
unstated capability must not be read as a satisfied one.
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from graphsearch import paths_root
from graphsearch.paths import (
    PathPolicy,
    all_pairs,
    boundary_context,
    cut_capacity,
    effective_bottleneck_bytes_per_s,
    path_set,
    to_networkx,
)
from graphsearch.schema import ResourceGraph, build_resource_graph
from tests.graph_fixtures import load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.inventory import ClusterSpecV2, LinkType  # noqa: E402


def graph_of(name: str) -> ResourceGraph:
    cluster = load_toy_cluster(name)
    return build_resource_graph(cluster, toy_profiles_for(cluster))


def inline_graph(body: str) -> ResourceGraph:
    raw = yaml.safe_load(textwrap.dedent(body))
    return build_resource_graph(ClusterSpecV2.model_validate(raw), {})


GPU = "{{id: {aid}, type: GPU, vendor: T, model: M, backend: cuda, memory_gb: 80}}"

#: Symmetric on both ends on purpose. An asymmetric version -- two NICs out,
#: one in -- is limited by the single link at the destination, which is correct
#: but hides the property this fixture exists to show.
TWO_NIC = f"""
cluster_id: t
nodes:
  - id: node0
    accelerators:
      - {GPU.format(aid="gpu0")}
    nics:
      - {{id: nic0, type: ethernet, speed_gbps: 10}}
      - {{id: nic1, type: ethernet, speed_gbps: 10}}
  - id: node1
    accelerators:
      - {GPU.format(aid="gpu0")}
    nics:
      - {{id: nic0, type: ethernet, speed_gbps: 10}}
      - {{id: nic1, type: ethernet, speed_gbps: 10}}
links:
  - {{id: a0, src: node0/gpu0, dst: node0/nic0, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900}}
  - {{id: a1, src: node0/gpu0, dst: node0/nic1, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900}}
  - {{id: f0, src: node0/nic0, dst: node1/nic0, type: ETHERNET,
     bandwidth_gbps: 10, latency_ns: 5000}}
  - {{id: f1, src: node0/nic1, dst: node1/nic1, type: ETHERNET,
     bandwidth_gbps: 10, latency_ns: 5000}}
  - {{id: b0, src: node1/nic0, dst: node1/gpu0, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900}}
  - {{id: b1, src: node1/nic1, dst: node1/gpu0, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900}}
"""


# --- (i) path bottlenecks reproduce the research design's example ---------

@pytest.mark.parametrize(
    "src, dst, expected",
    [
        ("nodeA/gpu0", "nodeB/gpu0", 10e9),
        ("nodeC/gpu0", "nodeD/gpu0", 5e9),
        ("nodeA/gpu0", "nodeC/gpu0", 5e9),
    ],
)
def test_cross_node_bottlenecks(src: str, dst: str, expected: float) -> None:
    """§9's cluster: A/B behind 10 GB/s, C/D behind 5, and a mixed pair takes
    the slower of the two."""
    best = path_set(graph_of("abcde_v2"), src, dst).best
    assert best is not None
    assert best.bottleneck_bytes_per_s == pytest.approx(expected)


def test_a_path_records_which_resources_it_crosses() -> None:
    best = path_set(graph_of("abcde_v2"), "nodeA/gpu0", "nodeB/gpu0").best
    assert best is not None
    assert best.shared_resources == {"uplink-nodeA", "uplink-nodeB"}


def test_an_intra_node_pair_crosses_nothing_shared() -> None:
    best = path_set(graph_of("abcde_v2"), "nodeA/gpu0", "nodeA/gpu1").best
    assert best is not None
    assert best.shared_resources == frozenset()
    assert best.hops == 1


def test_paths_are_sorted_shortest_first_then_fastest() -> None:
    result = path_set(inline_graph(TWO_NIC), "node0/gpu0", "node1/gpu0")
    assert len(result.paths) == 2
    keys = [(p.hops, -p.bottleneck_bytes_per_s, p.edges) for p in result.paths]
    assert keys == sorted(keys)
    assert result.best is result.paths[0]


def test_no_path_is_reported_not_raised() -> None:
    result = path_set(graph_of("shared_nic_v2"), "nodeX/gpu0", "nodeX/gpu0")
    assert result.paths == ()
    assert any("same vertex" in n for n in result.notes)


def test_max_hops_truncates() -> None:
    graph = graph_of("abcde_v2")
    assert path_set(graph, "nodeA/gpu0", "nodeB/gpu0", PathPolicy(max_hops=2)).paths == ()
    assert path_set(graph, "nodeA/gpu0", "nodeB/gpu0", PathPolicy(max_hops=8)).paths


# --- (ii) cuts add up -----------------------------------------------------

def test_the_cut_between_two_nodes_is_their_uplink() -> None:
    cut = cut_capacity(
        graph_of("abcde_v2"), ["nodeA/gpu0", "nodeA/gpu1"], ["nodeB/gpu0", "nodeB/gpu1"]
    )
    assert cut.bytes_per_s == pytest.approx(10e9)


def test_parallel_paths_add_rather_than_taking_the_slowest() -> None:
    """The reason a cut exists at all.

    Two 10 GB/s routes between one pair are a 20 GB/s cut. A bound that priced
    them at 10 would reject a candidate that would have worked -- and a stage
    may only reject when the most optimistic arithmetic already misses.
    """
    graph = inline_graph(TWO_NIC)
    assert path_set(graph, "node0/gpu0", "node1/gpu0").best.bottleneck_bytes_per_s == (
        pytest.approx(10e9)
    )
    cut = cut_capacity(graph, ["node0/gpu0"], ["node1/gpu0"])
    assert cut.bytes_per_s == pytest.approx(20e9)


def test_a_vertex_on_both_sides_is_an_error() -> None:
    with pytest.raises(ValueError, match="both sides"):
        cut_capacity(graph_of("abcde_v2"), ["nodeA/gpu0"], ["nodeA/gpu0"])


def test_an_empty_side_has_no_capacity_and_says_so() -> None:
    cut = cut_capacity(graph_of("abcde_v2"), [], ["nodeB/gpu0"])
    assert cut.bytes_per_s == 0.0
    assert any("no capacity" in a for a in cut.assumptions)


# --- (iii) a reservation comes off before anything else -------------------

def test_an_external_reservation_shrinks_the_cut() -> None:
    """X holds 6 of its 10 GB/s for something outside this deployment.

    Computing the cut over the full 10 is not optimism, it is wrong: no later
    measurement rescues a plan sized against bandwidth that was never there.
    """
    cut = cut_capacity(
        graph_of("shared_nic_v2"), ["nodeX/gpu0", "nodeX/gpu1"], ["nodeY/gpu0", "nodeY/gpu1"]
    )
    assert cut.bytes_per_s == pytest.approx(4e9)
    assert "uplink-nodeX" in cut.saturating_resources


def test_the_unreserved_direction_is_not_penalised() -> None:
    """Y's uplink is free; the pair is limited by X's reservation, not by Y."""
    graph = graph_of("shared_nic_v2")
    assert graph.shared_resources["uplink-nodeY"].available_bytes_per_s == (
        pytest.approx(10e9)
    )
    cut = cut_capacity(graph, ["nodeX/gpu0"], ["nodeY/gpu0"])
    assert cut.bytes_per_s == pytest.approx(4e9)
    assert "uplink-nodeY" not in cut.saturating_resources


def test_effective_bottleneck_subtracts_what_the_wire_does_not_know() -> None:
    graph = graph_of("shared_nic_v2")
    best = path_set(graph, "nodeX/gpu0", "nodeY/gpu0").best
    assert best is not None
    assert best.bottleneck_bytes_per_s == pytest.approx(10e9)
    assert effective_bottleneck_bytes_per_s(graph, best) == pytest.approx(4e9)


# --- (iv) an unstated capability is not a satisfied one -------------------

def test_require_rdma_finds_nothing_where_nothing_states_it() -> None:
    """D2's rule again. A v1 cluster states no RDMA anywhere, so requiring it
    correctly finds no path -- and the reason distinguishes unstated from
    stated-false, because the two ask for different things to happen next."""
    graph = graph_of("abcde")
    policy = PathPolicy(require_rdma=True)
    result = path_set(graph, "nodeA/gpu0", "nodeB/gpu0", policy)
    assert result.paths == ()
    assert any("rdma not stated" in n for n in result.notes)

    cut = cut_capacity(graph, ["nodeA/gpu0"], ["nodeB/gpu0"], policy)
    assert cut.bytes_per_s == 0.0
    assert any("rdma not stated" in a for a in cut.assumptions)


def test_require_rdma_keeps_a_link_that_states_it() -> None:
    body = TWO_NIC.replace(
        "bandwidth_gbps: 10, latency_ns: 5000}",
        "bandwidth_gbps: 10, latency_ns: 5000, rdma: true}",
    ).replace(
        "bandwidth_gbps: 16, latency_ns: 900}",
        "bandwidth_gbps: 16, latency_ns: 900, rdma: true}",
    ).replace("cluster_id: t", "cluster_id: t\nschema_version: 2")
    graph = inline_graph(body)
    assert path_set(graph, "node0/gpu0", "node1/gpu0", PathPolicy(require_rdma=True)).paths


def test_allowed_types_filters() -> None:
    graph = graph_of("abcde_v2")
    only_pcie = PathPolicy(allowed_types=frozenset({LinkType.PCIE}))
    assert path_set(graph, "nodeA/gpu0", "nodeA/gpu1", only_pcie).paths
    # Leaving the node needs the ETHERNET hop, which this policy forbids.
    assert path_set(graph, "nodeA/gpu0", "nodeB/gpu0", only_pcie).paths == ()


# --- (v) the boundary -----------------------------------------------------

def test_an_intra_node_pair_touches_its_own_uplink_and_no_other() -> None:
    """The boundary is over ALL allowed paths, not just the best one.

    §9's nodes give both GPUs equal access to the uplink, so a pair inside one
    node can also reach the other through its NIC -- a slower route the ranker
    would not choose, but one the candidate can take. Counting it keeps two
    placements distinct when they differ only in a fallback route, which is the
    conservative direction for an equivalence signature: a merge that loses a
    real difference is the failure G6 exists to prevent, and an extra
    representative is only a missed saving.

    What matters for the compression is the second assertion: node A's pair does
    not claim node C's uplink, so A-internal and C-internal stay different
    representatives -- which is what makes §9's five rather than three.
    """
    graph = graph_of("abcde_v2")
    devices = ["nodeA/gpu0", "nodeA/gpu1"]
    context = boundary_context(graph, devices, all_pairs(graph, devices))
    assert context.shared_resources == {"uplink-nodeA"}
    assert "nodeA/nic0" in context.transit_vertices
    assert not any(r.endswith(("nodeB", "nodeC", "nodeD")) for r in context.shared_resources)


def test_a_cross_node_pair_carries_both_uplinks() -> None:
    """What makes two otherwise-identical placements different candidates."""
    graph = graph_of("abcde_v2")
    devices = ["nodeA/gpu0", "nodeB/gpu0"]
    context = boundary_context(graph, devices, all_pairs(graph, devices))
    assert context.shared_resources == {"uplink-nodeA", "uplink-nodeB"}
    assert "nodeA/nic0" in context.transit_vertices
    assert "sw0" in context.transit_vertices
    assert set(context.reserved_bytes_per_s) == context.shared_resources


def test_the_boundary_reports_the_reservation_that_tells_two_nodes_apart() -> None:
    graph = graph_of("shared_nic_v2")
    devices = ["nodeX/gpu0", "nodeY/gpu0"]
    context = boundary_context(graph, devices, all_pairs(graph, devices))
    assert context.reserved_bytes_per_s["uplink-nodeX"] == pytest.approx(6e9)
    assert context.reserved_bytes_per_s["uplink-nodeY"] == pytest.approx(0.0)


def test_a_candidate_never_lists_its_own_devices_as_transit() -> None:
    graph = graph_of("abcde_v2")
    devices = ["nodeA/gpu0", "nodeB/gpu0"]
    context = boundary_context(graph, devices, all_pairs(graph, devices))
    assert not (context.transit_vertices & set(devices))


# --- (vi) determinism -----------------------------------------------------

def test_paths_cuts_and_boundaries_repeat() -> None:
    graph = graph_of("abcde_v2")
    devices = ["nodeA/gpu0", "nodeB/gpu0"]
    for _ in range(3):
        assert [p.edges for p in path_set(graph, *devices).paths] == [
            p.edges for p in path_set(graph, *devices).paths
        ]
        assert cut_capacity(graph, [devices[0]], [devices[1]]).bytes_per_s == (
            cut_capacity(graph, [devices[0]], [devices[1]]).bytes_per_s
        )
    first = boundary_context(graph, devices, all_pairs(graph, devices))
    second = boundary_context(graph, devices, all_pairs(graph, devices))
    assert first == second


def test_to_networkx_gates_every_shared_resource_once() -> None:
    graph = graph_of("abcde_v2")
    flow = to_networkx(graph)
    gates = [
        (a, b) for a, b, d in flow.edges(data=True) if d.get("gate")
    ]
    assert len(gates) == len(graph.shared_resources)
    for a, b in gates:
        assert a.endswith("_in") and b.endswith("_out")


def test_the_gate_carries_available_not_nominal_capacity() -> None:
    flow = to_networkx(graph_of("shared_nic_v2"))
    capacity = flow["res:uplink-nodeX_in"]["res:uplink-nodeX_out"]["capacity"]
    assert capacity == pytest.approx(4e9)


def test_the_assumptions_are_stated_on_every_cut() -> None:
    """A reader must not have to rediscover that this is nominal, uncontended
    capacity with the resource modelled as a single gate."""
    cut = cut_capacity(graph_of("abcde_v2"), ["nodeA/gpu0"], ["nodeB/gpu0"])
    text = " ".join(cut.assumptions)
    assert "NOMINAL" in text
    assert "no per-flow contention" in text
    assert "over-connects" in text
