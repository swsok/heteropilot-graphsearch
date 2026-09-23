"""G4: cost, and the one rule that shapes it.

**An incomplete sum is not a cost.** Every test here is a variation on that:
summing what is priced makes an under-priced plan look cheapest, and
substituting the device count turns "we do not know" into a number. Both
failures rank by something other than money while looking like money.

heteropilot's H1 takes the other side of the contract -- `pareto.can_score`
refuses a cost objective on an unpriced plan and names what is missing -- so
`missing` here is what makes that message possible.
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from graphsearch import paths_root
from graphsearch.cost import (
    CostBreakdown,
    cheapest,
    cost_lower_bound,
    cost_of_devices,
    price_coverage,
)
from graphsearch.schema import ResourceGraph, build_resource_graph
from tests.graph_fixtures import load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.inventory import (  # noqa: E402
    ClusterSpecV2,
    detect_islands,
    load_profiles_for,
)
from planner.plan import CandidateConfig, IslandAssignment  # noqa: E402

GS_ROOT = paths_root.GRAPHSEARCH_ROOT


def unprice(graph: ResourceGraph, device_id: str) -> ResourceGraph:
    """The same graph with one accelerator's price removed.

    Both toy profiles carry a price, and `_accelerator_attrs` falls back to the
    profile when the device states none -- correctly. So an unpriced device
    cannot be expressed in a fixture that uses them, and the cases about a
    missing price are built by blanking the attribute here. That keeps these
    tests about the cost module rather than about the fallback, which
    `test_the_v1_toy_cluster_returns_none_without_raising` covers instead.
    """
    from dataclasses import replace

    vertex = graph.vertices[device_id]
    attrs = dict(vertex.attrs)
    attrs["price_per_hour_usd"] = None
    return replace(
        graph,
        vertices={**graph.vertices, device_id: replace(vertex, attrs=attrs)},
    )


def graph_of(name: str) -> ResourceGraph:
    cluster = load_toy_cluster(name)
    return build_resource_graph(cluster, toy_profiles_for(cluster))


def _node(node: str, *, gpus: int, gpu_price: float | None, host: float | None) -> str:
    lines = [f"  - id: {node}\n"]
    if host is not None:
        lines.append(f"    host_price_per_hour_usd: {host}\n")
    lines.append("    accelerators:\n")
    for index in range(gpus):
        price = f", price_per_hour_usd: {gpu_price}" if gpu_price is not None else ""
        lines.append(
            f"      - {{id: gpu{index}, type: GPU, vendor: TOY, model: TOYGPU, "
            f"backend: cuda, memory_gb: 80,\n"
            f"         profile: fixtures/profiles/toy_gpu.yaml{price}}}\n"
        )
    return "".join(lines)


def cluster_yaml(*nodes: str, cluster_id: str = "t", links: str = "") -> str:
    """Assembled at column 0. An f-string indented inside a function mixes its
    own indentation with `_node`'s, and `textwrap.dedent` strips neither."""
    return (
        f"cluster_id: {cluster_id}\nschema_version: 2\nnodes:\n"
        + "".join(nodes)
        + (f"links:\n{links}" if links else "")
    )


def build(body: str):
    raw = yaml.safe_load(textwrap.dedent(body))
    cluster = ClusterSpecV2.model_validate(raw)
    profiles = load_profiles_for(cluster, GS_ROOT)
    return (
        cluster,
        {i.id: i for i in detect_islands(cluster, profiles)},
        build_resource_graph(cluster, profiles),
    )


#: Two nodes, deliberately unequal in BOTH halves, so a lower bound that took
#: the wrong devices or the wrong host would be visible.
TWO_PRICES = f"""
cluster_id: priced
schema_version: 2
nodes:
{_node("cheap", gpus=4, gpu_price=1.0, host=0.5)}{_node("dear", gpus=4, gpu_price=9.0, host=4.0)}
links:
  - {{id: c01, src: cheap/gpu0, dst: cheap/gpu1, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}}
  - {{id: c12, src: cheap/gpu1, dst: cheap/gpu2, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}}
  - {{id: c23, src: cheap/gpu2, dst: cheap/gpu3, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}}
  - {{id: d01, src: dear/gpu0, dst: dear/gpu1, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}}
  - {{id: d12, src: dear/gpu1, dst: dear/gpu2, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}}
  - {{id: d23, src: dear/gpu2, dst: dear/gpu3, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}}
"""


# --- (i) the sum ----------------------------------------------------------

def test_two_devices_on_one_host() -> None:
    """2.0 a device, 1.0 the host, one node touched -> 5.0."""
    breakdown = cost_of_devices(["nodeA/gpu0", "nodeA/gpu1"], graph_of("abcde_v2"))
    assert breakdown.accelerator_usd_per_hour == pytest.approx(4.0)
    assert breakdown.host_usd_per_hour == pytest.approx(1.0)
    assert breakdown.total_usd_per_hour == pytest.approx(5.0)
    assert breakdown.missing == ()


def test_a_host_is_charged_once_per_node_not_once_per_device() -> None:
    graph = graph_of("abcde_v2")
    one = cost_of_devices(["nodeA/gpu0"], graph)
    two = cost_of_devices(["nodeA/gpu0", "nodeA/gpu1"], graph)
    assert two.host_usd_per_hour == one.host_usd_per_hour


def test_crossing_a_node_boundary_charges_the_second_host() -> None:
    graph = graph_of("abcde_v2")
    assert cost_of_devices(["nodeA/gpu0", "nodeB/gpu0"], graph).total_usd_per_hour == (
        pytest.approx(6.0)                       # 2 + 2 devices, 1 + 1 hosts
    )


def test_a_repeated_device_is_counted_once() -> None:
    graph = graph_of("abcde_v2")
    assert cost_of_devices(["nodeA/gpu0", "nodeA/gpu0"], graph).total_usd_per_hour == (
        cost_of_devices(["nodeA/gpu0"], graph).total_usd_per_hour
    )


def test_something_that_is_not_an_accelerator_is_an_error() -> None:
    """A NIC has no price and never will; silently returning 0 for it would be
    the same failure as summing a partial set."""
    with pytest.raises(KeyError, match="not an accelerator"):
        cost_of_devices(["nodeA/nic0"], graph_of("abcde_v2"))


# --- (ii) one missing price makes the whole total None --------------------

def test_one_unpriced_device_voids_the_total() -> None:
    _, _, graph = build(
        cluster_yaml(_node("n0", gpus=1, gpu_price=None, host=1.0))
    )
    # The profile still prices it, so the price is blanked at the vertex: this
    # is a test of the cost module, not of the profile fallback.
    breakdown = cost_of_devices(["n0/gpu0"], unprice(graph, "n0/gpu0"))
    assert breakdown.total_usd_per_hour is None
    assert breakdown.missing == ("n0/gpu0",)


def test_the_parts_are_still_reported_when_the_total_is_not() -> None:
    """"The GPUs come to 9.0 and one host price is missing" is more use to a
    reader than a bare None."""
    _, _, graph = build(
        cluster_yaml(_node("n0", gpus=1, gpu_price=9.0, host=None))
    )
    breakdown = cost_of_devices(["n0/gpu0"], graph)
    assert breakdown.total_usd_per_hour is None
    assert breakdown.accelerator_usd_per_hour == pytest.approx(9.0)
    assert breakdown.missing == ("n0",)


def test_the_total_is_never_a_device_count() -> None:
    """The forbidden substitution, asserted directly.

    Four unpriced accelerators must not come back as 4 -- or as any number.
    """
    _, _, graph = build(
        cluster_yaml(_node("n0", gpus=4, gpu_price=None, host=None))
    )
    for index in range(4):
        graph = unprice(graph, f"n0/gpu{index}")
    breakdown = cost_of_devices([f"n0/gpu{i}" for i in range(4)], graph)
    assert breakdown.total_usd_per_hour is None
    assert breakdown.accelerator_usd_per_hour == 0.0


# --- (iii) the lower bound really is one ----------------------------------

def template(island: str, *, tp: int = 1, dp: int = 1) -> CandidateConfig:
    return CandidateConfig(
        id="c", model="meta-llama/Llama-3.1-8B", dtype="bfloat16",
        assignments=[IslandAssignment(island_id=island, tp_size=tp, dp_replicas=dp)],
    )


@pytest.mark.parametrize("tp, dp", [(1, 1), (2, 1), (2, 2)])
def test_the_bound_is_never_above_an_actual_placement(tp: int, dp: int) -> None:
    """Sound elimination needs this: a template whose FLOOR beats an incumbent
    may be dropped, so the floor must not exceed anything achievable."""
    _, islands, graph = build(TWO_PRICES)
    for island in islands.values():
        bound = cost_lower_bound(template(island.id, tp=tp, dp=dp), islands, graph)
        need = tp * dp
        actual = cost_of_devices(
            [f"{island.node_id}/{d}" for d in island.accelerator_ids[:need]], graph
        )
        assert bound.total_usd_per_hour is not None
        assert actual.total_usd_per_hour is not None
        assert bound.total_usd_per_hour <= actual.total_usd_per_hour + 1e-9


def test_the_bound_takes_the_cheapest_devices_not_the_first() -> None:
    mixed = """
    cluster_id: mixed
    schema_version: 2
    nodes:
      - id: n0
        host_price_per_hour_usd: 1.0
        accelerators:
          - {id: gpu0, type: GPU, vendor: TOY, model: TOYGPU, backend: cuda,
             memory_gb: 80, profile: fixtures/profiles/toy_gpu.yaml,
             price_per_hour_usd: 9.0}
          - {id: gpu1, type: GPU, vendor: TOY, model: TOYGPU, backend: cuda,
             memory_gb: 80, profile: fixtures/profiles/toy_gpu.yaml,
             price_per_hour_usd: 1.0}
    links:
      - {id: l01, src: n0/gpu0, dst: n0/gpu1, type: NVLINK,
         bandwidth_gbps: 112.5, latency_ns: 500}
    """
    _, islands, graph = build(mixed)
    island = next(iter(islands.values()))
    bound = cost_lower_bound(template(island.id), islands, graph)
    assert bound.total_usd_per_hour == pytest.approx(2.0)      # 1.0 device + 1.0 host


def test_the_bound_charges_the_host_exactly_once() -> None:
    """An island is node-local, so every embedding pays the same host. That
    half is exact; only the device half is relaxed."""
    _, islands, graph = build(TWO_PRICES)
    island = next(i for i in islands.values() if i.node_id == "cheap")
    bound = cost_lower_bound(template(island.id, tp=2, dp=2), islands, graph)
    assert bound.host_usd_per_hour == pytest.approx(0.5)
    assert bound.accelerator_usd_per_hour == pytest.approx(4.0)


def test_a_bound_over_too_few_priced_devices_is_missing_not_low() -> None:
    """A floor built on the priced subset would sit below anything achievable
    and eliminate candidates that are in fact cheaper than it claims."""
    _, islands, graph = build(
        cluster_yaml(
            _node("n0", gpus=2, gpu_price=1.0, host=1.0),
            cluster_id="partial",
            links=(
                "  - {id: l01, src: n0/gpu0, dst: n0/gpu1, type: NVLINK,\n"
                "     bandwidth_gbps: 112.5, latency_ns: 500}\n"
            ),
        )
    )
    island = next(iter(islands.values()))
    bound = cost_lower_bound(template(island.id, tp=2), islands, unprice(graph, "n0/gpu1"))
    assert bound.total_usd_per_hour is None
    assert any("priced 1 of 2" in m for m in bound.missing)


def test_an_unknown_island_is_an_error() -> None:
    _, islands, graph = build(TWO_PRICES)
    with pytest.raises(KeyError, match="not in this inventory"):
        cost_lower_bound(template("no-such-island"), islands, graph)


# --- (iv) a cluster with no prices at all ---------------------------------

def test_the_v1_toy_cluster_returns_none_without_raising() -> None:
    """v1 has no host price field at all, so nothing there can be fully priced.
    That is a None, not an exception and not a zero."""
    breakdown = cost_of_devices(["nodeA/gpu0", "nodeA/gpu1"], graph_of("abcde"))
    assert breakdown.total_usd_per_hour is None
    assert "nodeA" in breakdown.missing


def test_price_coverage_says_what_is_missing_before_a_search_runs() -> None:
    complete = price_coverage(graph_of("abcde_v2"))
    assert complete.is_complete
    assert complete.unpriced == ()

    partial = price_coverage(graph_of("abcde"))
    assert not partial.is_complete
    assert partial.unpriced_hosts == 5


# --- cheapest -------------------------------------------------------------

def test_an_absence_does_not_win_by_default() -> None:
    priced = CostBreakdown(1.0, 1.0, 2.0)
    unpriced = CostBreakdown(0.0, 0.0, None, missing=("n0/gpu0",))
    assert cheapest([priced, unpriced]) is priced
    assert cheapest([unpriced]) is None
    assert cheapest([]) is None
