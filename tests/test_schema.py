"""G1: `ClusterSpecV2` -> `ResourceGraph`.

The three things this layer is responsible for are the three that would be
silent if they went wrong, so each gets a test that fails loudly:

* a unit conversion (a factor of 8, invisible in every downstream number),
* a shared capacity (the difference between two placements the equivalence
  layer must not merge),
* determinism (a digest that moves with YAML ordering would make the
  compression report describe a partition that does not exist).
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from graphsearch import paths_root
from graphsearch.schema import (
    ResourceGraph,
    UnitError,
    VertexKind,
    build_resource_graph,
    bytes_per_s,
    edges_using,
)
from tests.graph_fixtures import load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.inventory import (  # noqa: E402
    AcceleratorState,
    ClusterSpecV2,
    load_cluster_spec,
    load_profiles_for,
)

HP_ROOT = paths_root.HETEROPILOT_ROOT
EXAMPLE = HP_ROOT / "examples" / "clusters" / "heterogeneous-lab.yaml"


def graph_of(name: str) -> ResourceGraph:
    cluster = load_toy_cluster(name)
    return build_resource_graph(cluster, toy_profiles_for(cluster))


def inline(body: str) -> ClusterSpecV2:
    return ClusterSpecV2.model_validate(yaml.safe_load(textwrap.dedent(body)))


def inline_graph(body: str) -> ResourceGraph:
    return build_resource_graph(inline(body), {})


GPU = "{{id: {aid}, type: GPU, vendor: T, model: M, backend: cuda, memory_gb: 80}}"


def two_gpu_node(node: str = "node0") -> str:
    return f"""
      - id: {node}
        accelerators:
          - {GPU.format(aid="gpu0")}
          - {GPU.format(aid="gpu1")}
        nics:
          - {{id: nic0, type: ethernet, speed_gbps: 10}}
    """


# --- (vi) units, first, because everything else depends on them -----------

def test_the_two_units_and_the_factor_between_them() -> None:
    assert bytes_per_s(1, "GB/s") == pytest.approx(1e9)
    assert bytes_per_s(8, "Gbit/s") == pytest.approx(1e9)
    assert bytes_per_s(100, "Gbit/s") == pytest.approx(12.5e9)


def test_an_unknown_unit_is_refused_not_guessed() -> None:
    """A wrong guess is a factor of 8 that nothing downstream reports."""
    with pytest.raises(UnitError, match="unknown bandwidth unit"):
        bytes_per_s(1, "Gb/s")
    with pytest.raises(ValueError):
        bytes_per_s(1, "")


# --- (i) the committed v1 cluster ----------------------------------------

def test_v1_bandwidth_gbps_is_read_as_gb_per_s() -> None:
    """D120: the field is named for bits and holds bytes. 64 is 6.4e10, not 8e9."""
    cluster = load_cluster_spec(EXAMPLE)
    graph = build_resource_graph(cluster, load_profiles_for(cluster, HP_ROOT))
    link = next(link for link in cluster.links if link.bandwidth_gbps == 64.0)
    assert graph.edges[f"{link.id}:fwd"].capacity_bytes_per_s == pytest.approx(64e9)


def test_a_bidirectional_link_becomes_two_full_capacity_edges() -> None:
    cluster = load_cluster_spec(EXAMPLE)
    graph = build_resource_graph(cluster, load_profiles_for(cluster, HP_ROOT))
    assert len(graph.edges) == 2 * len(cluster.links)
    for link in cluster.links:
        fwd, rev = graph.edges[f"{link.id}:fwd"], graph.edges[f"{link.id}:rev"]
        assert (fwd.src, fwd.dst) == (rev.dst, rev.src)
        assert fwd.capacity_bytes_per_s == rev.capacity_bytes_per_s


def test_accelerator_vertices_carry_what_a_candidate_graph_labels_them_with() -> None:
    cluster = load_cluster_spec(EXAMPLE)
    graph = build_resource_graph(cluster, load_profiles_for(cluster, HP_ROOT))
    accelerators = graph.accelerators()
    assert accelerators
    for vertex in accelerators:
        assert vertex.node_id is not None
        assert vertex.attrs["memory_bytes"] > 0
        # Unstated is None, never a default. A checker has to tell "no profile
        # says" from "the profile says no".
        assert set(vertex.attrs) >= {
            "model", "backend", "memory_bytes", "state", "profile_id",
            "price_per_hour_usd", "active_power_w", "runtime_capabilities",
        }


# --- (i) contention groups share one resource ----------------------------

def test_two_v1_links_in_one_contention_group_share_a_resource() -> None:
    """The committed example has one link per group, so this is built inline."""
    graph = inline_graph(f"""
    cluster_id: t
    nodes:{two_gpu_node()}
    links:
      - {{id: a, src: node0/gpu0, dst: node0/nic0, type: PCIE,
         bandwidth_gbps: 16, latency_ns: 900, contention_group: root}}
      - {{id: b, src: node0/gpu1, dst: node0/nic0, type: PCIE,
         bandwidth_gbps: 8, latency_ns: 900, contention_group: root}}
    """)
    assert set(graph.shared_resources) == {"root"}
    assert [e.id for e in edges_using(graph, "root")] == [
        "a:fwd", "a:rev", "b:fwd", "b:rev"
    ]


def test_a_contention_group_is_given_its_slowest_member_and_says_so() -> None:
    """v1 declares no capacity. The narrowest member is the only defensible
    number, and inventing it silently would make two v1 clusters look measured."""
    graph = inline_graph(f"""
    cluster_id: t
    nodes:{two_gpu_node()}
    links:
      - {{id: a, src: node0/gpu0, dst: node0/nic0, type: PCIE,
         bandwidth_gbps: 16, latency_ns: 900, contention_group: root}}
      - {{id: b, src: node0/gpu1, dst: node0/nic0, type: PCIE,
         bandwidth_gbps: 8, latency_ns: 900, contention_group: root}}
    """)
    resource = graph.shared_resources["root"]
    assert resource.capacity_bytes_per_s == pytest.approx(8e9)
    assert resource.reserved_bytes_per_s == 0.0
    assert resource.source.value == "placeholder"
    assert any("declares no capacity" in n for n in graph.unit_notes)


# --- (ii) v2 units and reservations ---------------------------------------

def test_a_v2_link_in_bits_converts() -> None:
    graph = inline_graph(f"""
    cluster_id: t
    schema_version: 2
    nodes:{two_gpu_node()}
    links:
      - {{id: a, src: node0/gpu0, dst: node0/nic0, type: ETHERNET,
         bandwidth_gbps: 100, bandwidth_unit: "Gbit/s", latency_ns: 5000}}
    """)
    assert graph.edges["a:fwd"].capacity_bytes_per_s == pytest.approx(12.5e9)


def test_a_reservation_is_carried_and_subtracted() -> None:
    graph = graph_of("shared_nic_v2")
    x, y = graph.shared_resources["uplink-nodeX"], graph.shared_resources["uplink-nodeY"]
    assert x.capacity_bytes_per_s == y.capacity_bytes_per_s == pytest.approx(10e9)
    assert x.reserved_bytes_per_s == pytest.approx(6e9)
    assert x.available_bytes_per_s == pytest.approx(4e9)
    assert y.available_bytes_per_s == pytest.approx(10e9)


# --- (iii) the auxiliary vertex, and what the digest can see --------------

def test_every_resource_gets_an_auxiliary_vertex() -> None:
    """So "this path crosses that uplink" is reachability, not a side table."""
    graph = graph_of("abcde_v2")
    for resource_id in graph.shared_resources:
        vertex = graph.vertices[f"res:{resource_id}"]
        assert vertex.kind is VertexKind.SHARED_RESOURCE
        assert vertex.attrs["capacity_bytes_per_s"] > 0


SHARED = """
cluster_id: t
schema_version: 2
nodes:{node}
shared_resources:
  - {{id: root, kind: pcie_uplink, capacity: 16.0, unit: "GB/s"}}
links:
  - {{id: a, src: node0/gpu0, dst: node0/nic0, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900, shared_resource: root}}
  - {{id: b, src: node0/gpu1, dst: node0/nic0, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900, shared_resource: root}}
"""

INDEPENDENT = """
cluster_id: t
schema_version: 2
nodes:{node}
links:
  - {{id: a, src: node0/gpu0, dst: node0/nic0, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900}}
  - {{id: b, src: node0/gpu1, dst: node0/nic0, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900}}
"""


def test_sharing_an_uplink_changes_the_digest() -> None:
    """The property the equivalence layer is built on.

    Two clusters with the same devices and the same link speeds, differing only
    in whether the two links contend, must not hash alike -- otherwise a merge
    that loses a real difference is undetectable downstream.
    """
    shared = inline_graph(SHARED.format(node=two_gpu_node()))
    independent = inline_graph(INDEPENDENT.format(node=two_gpu_node()))
    assert shared.digest() != independent.digest()


def test_a_reservation_changes_the_digest() -> None:
    reserved = SHARED.replace(
        'capacity: 16.0, unit: "GB/s"', 'capacity: 16.0, unit: "GB/s", reserved: 6.0'
    )
    assert (
        inline_graph(SHARED.format(node=two_gpu_node())).digest()
        != inline_graph(reserved.format(node=two_gpu_node())).digest()
    )


# --- (iv) determinism -----------------------------------------------------

def test_link_order_does_not_change_the_digest() -> None:
    """A digest that moved with YAML ordering would make the compression report
    describe a partition that does not exist."""
    raw = yaml.safe_load(textwrap.dedent(INDEPENDENT.format(node=two_gpu_node())))
    forward = build_resource_graph(ClusterSpecV2.model_validate(raw), {})
    raw["links"].reverse()
    raw["nodes"][0]["accelerators"].reverse()
    reversed_ = build_resource_graph(ClusterSpecV2.model_validate(raw), {})
    assert forward.digest() == reversed_.digest()


def test_the_same_cluster_twice_is_identical() -> None:
    assert graph_of("abcde_v2").digest() == graph_of("abcde_v2").digest()


def test_every_toy_cluster_builds() -> None:
    for name in ("abcde", "abcde_v2", "shared_nic", "shared_nic_v2", "asym_v2"):
        graph = graph_of(name)
        assert graph.accelerators()
        assert graph.edges


# --- (v) snapshot_version -------------------------------------------------

def test_the_snapshot_moves_when_a_reservation_does() -> None:
    """A plan is re-checked against this before deployment; if it did not move,
    a plan sized against a free uplink would pass a recheck after something else
    took 6 of its 10 GB/s."""
    base = load_toy_cluster("shared_nic_v2")
    before = build_resource_graph(base, toy_profiles_for(base)).snapshot_version

    changed = base.model_copy(deep=True)
    changed.shared_resources[0].reserved = 9.0
    after = build_resource_graph(changed, toy_profiles_for(base)).snapshot_version
    assert before != after


def test_the_snapshot_moves_when_a_device_is_taken() -> None:
    base = load_toy_cluster("shared_nic_v2")
    before = build_resource_graph(base, toy_profiles_for(base)).snapshot_version

    changed = base.model_copy(deep=True)
    changed.nodes[0].accelerators[0].state = AcceleratorState.ALLOCATED
    after = build_resource_graph(changed, toy_profiles_for(base)).snapshot_version
    assert before != after


def test_the_snapshot_ignores_things_that_are_not_a_reading() -> None:
    """Renaming the cluster is not a change in what the hardware is doing."""
    base = load_toy_cluster("shared_nic_v2")
    renamed = base.model_copy(update={"cluster_id": "something-else"})
    assert (
        build_resource_graph(base, toy_profiles_for(base)).snapshot_version
        == build_resource_graph(renamed, toy_profiles_for(base)).snapshot_version
    )


# --- half duplex ----------------------------------------------------------

def test_half_duplex_binds_the_two_directions_to_one_resource() -> None:
    """Everywhere else two full-capacity edges is optimism a bound may have.
    Here it would be wrong: the wire carries one direction at a time."""
    graph = inline_graph(f"""
    cluster_id: t
    nodes:{two_gpu_node()}
    links:
      - {{id: a, src: node0/gpu0, dst: node0/gpu1, type: PCIE,
         bandwidth_gbps: 16, latency_ns: 900, duplex: half}}
    """)
    resource = graph.shared_resources["halfdup:a"]
    assert resource.capacity_bytes_per_s == pytest.approx(16e9)
    assert [e.id for e in edges_using(graph, "halfdup:a")] == ["a:fwd", "a:rev"]
    assert any("half duplex" in n for n in graph.unit_notes)


HALF_DUPLEX_CONFLICT = """
cluster_id: t
nodes:{node}
links:
  - {{id: a, src: node0/gpu0, dst: node0/nic0, type: PCIE,
     bandwidth_gbps: 16, latency_ns: 900, duplex: half, contention_group: root}}
"""


def test_half_duplex_and_a_named_resource_together_are_refused() -> None:
    """Two resources on one edge: only one could be charged, and picking
    silently would make a bound wrong with nothing to show for it."""
    with pytest.raises(ValueError, match="half"):
        inline_graph(HALF_DUPLEX_CONFLICT.format(node=two_gpu_node()))


# --- subgraph -------------------------------------------------------------

def test_a_subgraph_keeps_only_edges_with_both_ends_inside() -> None:
    graph = graph_of("abcde_v2")
    keep = [v.id for v in graph.accelerators() if v.node_id == "nodeA"]
    sub = graph.subgraph(keep)
    assert set(sub.vertices) == set(keep)
    for edge in sub.edges.values():
        assert edge.src in keep and edge.dst in keep
    assert sub.snapshot_version == graph.snapshot_version


def test_a_subgraph_drops_resources_nothing_in_it_uses() -> None:
    graph = graph_of("abcde_v2")
    sub = graph.subgraph([v.id for v in graph.accelerators() if v.node_id == "nodeA"])
    used = {e.shared_resource_id for e in sub.edges.values()}
    assert set(sub.shared_resources) <= {r for r in used if r}


# --- measurements are carried, never used as a bound ----------------------

def test_measurements_ride_along_untouched() -> None:
    """A measured effective bandwidth is an average, not a guaranteed ceiling,
    so it may not become `capacity`. It is carried so a RANKER can use it."""
    cluster = load_cluster_spec(EXAMPLE)
    graph = build_resource_graph(cluster, load_profiles_for(cluster, HP_ROOT))
    for link in cluster.links:
        edge = graph.edges[f"{link.id}:fwd"]
        assert len(edge.measurements) == len(link.measurements)
        assert edge.capacity_bytes_per_s == pytest.approx(
            bytes_per_s(link.bandwidth_gbps, link.bandwidth_unit)
        )
