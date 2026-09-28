"""P2.3: what happens to two transfers that want the same wire.

`NullContentionModel` prices every flow as if it had the path to itself. That is
the optimistic direction, which is what a bound needs and what every result up
to E-G3 was computed under. `FluidContentionModel` is the first model in this
repository that lets one flow slow another down.

The test that matters most is the last one: **fluid is never faster than null**.
A pruning stage may reject only when the most optimistic arithmetic already
misses the constraint, so the bounds must keep using `null`; if fluid could ever
come out faster, using it anywhere near a bound would silently break the
relaxation property that the whole `false_infeasible = 0` claim rests on.
"""

from __future__ import annotations

import pytest

from graphsearch.contention import (
    CONTENTION_MODELS,
    FluidContentionModel,
    NullContentionModel,
    contention_model,
)
from graphsearch.demand import CommFlow, FlowKind
from graphsearch.paths import Path, PathSet
from graphsearch.schema import ResourceGraph, SharedResource

GB = 1e9


def graph_with(**resources: tuple[float, float]) -> ResourceGraph:
    """A graph carrying only shared resources: id -> (capacity, reserved).

    Nothing else is read by a contention model -- it works from the flows'
    already-resolved paths -- so building a whole cluster here would be
    scenery, and scenery is where a test stops saying what it checks.
    """
    return ResourceGraph(
        schema_version=2,
        cluster_id="contention-test",
        vertices={},
        edges={},
        shared_resources={
            name: SharedResource(
                id=name,
                capacity_bytes_per_s=capacity,
                reserved_bytes_per_s=reserved,
                kind="pcie_uplink",
                node_id=None,
            )
            for name, (capacity, reserved) in resources.items()
        },
        snapshot_version="test",
    )


def flow(
    flow_id: str,
    nbytes: float,
    *,
    link_cap: float = 100 * GB,
    latency_ns: float = 0.0,
    resources: tuple[str, ...] = (),
) -> CommFlow:
    path = Path(
        edges=(f"e-{flow_id}",),
        bottleneck_bytes_per_s=link_cap,
        latency_ns=latency_ns,
        shared_resources=frozenset(resources),
    )
    return CommFlow(
        flow_id=flow_id,
        kind=FlowKind.PD_KV_TRANSFER,
        participants=("a", "b"),
        bytes_per_event=nbytes,
        events_per_request=1.0,
        on_critical_path="ttft",
        allowed_paths=(PathSet(src="a", dst="b", paths=(path,)),),
    )


FLUID = FluidContentionModel()
NULL = NullContentionModel()


# --- (i) one flow is the same under both ---------------------------------

def test_a_single_flow_is_latency_plus_bytes_over_capacity() -> None:
    graph = graph_with(uplink=(10 * GB, 0.0))
    one = flow("f", 10 * GB, link_cap=10 * GB, latency_ns=500.0, resources=("uplink",))
    expected = 500.0 + 1e9          # 10 GB over 10 GB/s = 1 s = 1e9 ns
    assert FLUID.transfer_times_ns([one], graph)["f"] == pytest.approx(expected)
    assert NULL.transfer_times_ns([one], graph)["f"] == pytest.approx(expected)


# --- (ii) two flows on one resource each get half ------------------------

def test_two_flows_on_one_resource_each_get_half_the_capacity() -> None:
    graph = graph_with(uplink=(10 * GB, 0.0))
    flows = [
        flow("a", 10 * GB, link_cap=10 * GB, resources=("uplink",)),
        flow("b", 10 * GB, link_cap=10 * GB, resources=("uplink",)),
    ]
    times = FLUID.transfer_times_ns(flows, graph)
    # Equal bytes, equal share: both finish at 20 GB / 10 GB/s = 2 s.
    assert times["a"] == pytest.approx(2e9)
    assert times["b"] == pytest.approx(2e9)
    # And null still says one second each, which is the whole difference.
    assert NULL.transfer_times_ns(flows, graph)["a"] == pytest.approx(1e9)


def test_the_shorter_of_two_flows_finishes_first_and_frees_its_share() -> None:
    """The event in "event-driven". While both run they share; after the small
    one finishes the large one has the resource to itself."""
    graph = graph_with(uplink=(10 * GB, 0.0))
    flows = [
        flow("small", 2 * GB, link_cap=10 * GB, resources=("uplink",)),
        flow("large", 10 * GB, link_cap=10 * GB, resources=("uplink",)),
    ]
    times = FLUID.transfer_times_ns(flows, graph)
    # Both at 5 GB/s until `small` is done at 0.4 s, by which point `large`
    # has moved 2 GB. Its remaining 8 GB then run at the full 10 GB/s: 0.8 s.
    assert times["small"] == pytest.approx(0.4e9)
    assert times["large"] == pytest.approx(1.2e9)


# --- (iii) independent resources do not interact -------------------------

def test_two_flows_on_independent_resources_are_unchanged() -> None:
    """The check on the implementation, not evidence for the model.

    If these differ, fluid is wrong in a way that has nothing to do with
    contention -- there is none here to model.
    """
    graph = graph_with(left=(10 * GB, 0.0), right=(10 * GB, 0.0))
    flows = [
        flow("a", 10 * GB, link_cap=10 * GB, resources=("left",)),
        flow("b", 10 * GB, link_cap=10 * GB, resources=("right",)),
    ]
    fluid = FLUID.transfer_times_ns(flows, graph)
    null = NULL.transfer_times_ns(flows, graph)
    assert fluid == pytest.approx(null)
    assert fluid["a"] == pytest.approx(1e9)


# --- (iv) an external reservation comes off first ------------------------

def test_a_reservation_is_subtracted_before_anything_is_shared() -> None:
    """6 of 10 GB/s held outside this deployment leaves 4, not 10.

    The reservation is a permanently active flow: it never finishes and never
    takes a turn in the split. A model that shared 10 GB/s three ways would
    hand this deployment bandwidth that was never there.
    """
    graph = graph_with(uplink=(10 * GB, 6 * GB))
    one = flow("f", 4 * GB, link_cap=10 * GB, resources=("uplink",))
    assert FLUID.transfer_times_ns([one], graph)["f"] == pytest.approx(1e9)

    flows = [
        flow("a", 4 * GB, link_cap=10 * GB, resources=("uplink",)),
        flow("b", 4 * GB, link_cap=10 * GB, resources=("uplink",)),
    ]
    times = FLUID.transfer_times_ns(flows, graph)
    # 2 GB/s each: 4 GB takes 2 s.
    assert times["a"] == pytest.approx(2e9)
    assert times["b"] == pytest.approx(2e9)


def test_a_fully_reserved_resource_is_infinite_rather_than_a_crash() -> None:
    graph = graph_with(uplink=(10 * GB, 10 * GB))
    one = flow("f", 1 * GB, link_cap=10 * GB, resources=("uplink",))
    assert FLUID.transfer_times_ns([one], graph)["f"] == float("inf")


# --- (v) flows that start at different times -----------------------------

def test_flows_that_do_not_overlap_do_not_contend() -> None:
    """Contention is about WHEN, not only about WHERE.

    `a` is finished before `b` begins, so neither is slowed at all and fluid
    agrees with null on both -- shifted by the start offset.
    """
    graph = graph_with(uplink=(10 * GB, 0.0))
    flows = [
        flow("a", 10 * GB, link_cap=10 * GB, resources=("uplink",)),
        flow("b", 10 * GB, link_cap=10 * GB, resources=("uplink",)),
    ]
    times = FLUID.transfer_times_ns(flows, graph, starts={"b": 2e9})
    assert times["a"] == pytest.approx(1e9)
    assert times["b"] == pytest.approx(3e9)


def test_a_late_flow_only_shares_the_interval_it_overlaps() -> None:
    """The piecewise split, with the arithmetic done by hand.

    `a` (10 GB) starts at 0 and has the 10 GB/s uplink alone for 0.5 s, moving
    5 GB. `b` (5 GB) starts at 0.5 s; both then run at 5 GB/s. `b` finishes its
    5 GB at 1.5 s, by which time `a` has moved 5 + 5 = 10 GB and is done too.
    """
    graph = graph_with(uplink=(10 * GB, 0.0))
    flows = [
        flow("a", 10 * GB, link_cap=10 * GB, resources=("uplink",)),
        flow("b", 5 * GB, link_cap=10 * GB, resources=("uplink",)),
    ]
    times = FLUID.transfer_times_ns(flows, graph, starts={"b": 0.5e9})
    assert times["b"] == pytest.approx(1.5e9)
    assert times["a"] == pytest.approx(1.5e9)


# --- (vi) the path's own bottleneck still caps the flow ------------------

def test_a_flow_cannot_exceed_its_own_link_however_free_the_resource_is() -> None:
    graph = graph_with(uplink=(100 * GB, 0.0))
    one = flow("f", 1 * GB, link_cap=1 * GB, resources=("uplink",))
    assert FLUID.transfer_times_ns([one], graph)["f"] == pytest.approx(1e9)


def test_a_flow_crossing_no_shared_resource_is_priced_by_its_link() -> None:
    graph = graph_with()
    one = flow("f", 2 * GB, link_cap=1 * GB)
    assert FLUID.transfer_times_ns([one], graph)["f"] == pytest.approx(2e9)


# --- (vii) determinism ---------------------------------------------------

def test_two_runs_over_the_same_input_agree_exactly() -> None:
    graph = graph_with(uplink=(10 * GB, 1 * GB), other=(4 * GB, 0.0))
    flows = [
        flow("a", 3 * GB, link_cap=10 * GB, resources=("uplink",)),
        flow("b", 7 * GB, link_cap=10 * GB, resources=("uplink", "other")),
        flow("c", 1 * GB, link_cap=2 * GB, resources=("other",)),
    ]
    first = FLUID.transfer_times_ns(flows, graph)
    second = FLUID.transfer_times_ns(list(reversed(flows)), graph)
    assert first == second


# --- (viii) the invariant the bounds depend on ---------------------------

@pytest.mark.parametrize(
    "resources_a,resources_b",
    [(("uplink",), ("uplink",)), (("uplink",), ("other",)), ((), ())],
)
def test_fluid_is_never_faster_than_null(resources_a, resources_b) -> None:
    """Sharing a resource can only slow a flow down, never speed one up.

    This is what makes `null` the model a BOUND may use: a pruning stage
    rejects only when the most optimistic arithmetic already misses the
    constraint, and null is that arithmetic. If fluid could come out faster,
    a bound computed with it would reject candidates that would have worked --
    `false_infeasible`, from a modelling choice rather than a defect.
    """
    graph = graph_with(uplink=(10 * GB, 2 * GB), other=(5 * GB, 0.0))
    flows = [
        flow("a", 6 * GB, link_cap=8 * GB, latency_ns=300.0, resources=resources_a),
        flow("b", 3 * GB, link_cap=8 * GB, latency_ns=300.0, resources=resources_b),
    ]
    fluid = FLUID.transfer_times_ns(flows, graph)
    null = NULL.transfer_times_ns(flows, graph)
    for flow_id in ("a", "b"):
        assert fluid[flow_id] >= null[flow_id] - 1e-6, (
            f"{flow_id}: fluid {fluid[flow_id]} is FASTER than null "
            f"{null[flow_id]}; null would no longer be a safe bound"
        )


# --- (ix) the model is selectable by name and says which it is -----------

def test_every_model_carries_its_name() -> None:
    assert NULL.name == "null"
    assert FLUID.name == "fluid"
    assert set(CONTENTION_MODELS) == {"null", "fluid"}
    for name, model in CONTENTION_MODELS.items():
        assert model.name == name, "a report would label this one wrongly"


def test_an_unknown_model_is_refused_by_name() -> None:
    assert contention_model("fluid") is CONTENTION_MODELS["fluid"]
    with pytest.raises(SystemExit) as excinfo:
        contention_model("packet")
    assert "null" in str(excinfo.value) and "fluid" in str(excinfo.value)


# --- (x) the model where it is actually used -----------------------------
#
# P2.5 asks for a test that the X->Z and Y->Z representatives of
# graph-toy-shared-nic differ in TTFT under `fluid` and agree under `null`.
# **They differ under both**, and the reason is not the contention model: an
# external reservation is subtracted by `effective_bottleneck_bytes_per_s`,
# which both models use and which predates all of this (D124). X's uplink has
# 6 of its 10 GB/s held, so the two were never going to agree.
#
# What `fluid` actually changes is the case the work order names in the same
# paragraph and the test sentence does not: a candidate whose OWN flows overlap
# on one resource. That needs `dp > 1`, which needs more than two devices.
# Recorded as GS-20.

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import detect_islands  # noqa: E402
from planner.spec import load_service_spec  # noqa: E402

from graphsearch import paths_root  # noqa: E402
from graphsearch.embeddings import enumerate_embeddings  # noqa: E402
from graphsearch.equivalence import compress  # noqa: E402
from graphsearch.ranker import features_for  # noqa: E402
from graphsearch.schema import build_resource_graph  # noqa: E402
from tests.graph_fixtures import (  # noqa: E402
    FIXTURES,
    load_toy_cluster,
    toy_profiles_for,
)

paths_root.ensure_importable()


def _shared_nic(limit: int):
    spec = load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")
    cluster = load_toy_cluster("shared_nic_v2")
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)
    generated = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=True,
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= limit]
    embeddings, _ = enumerate_embeddings(templates, by_id, graph, spec)
    representatives, _, _ = compress(embeddings, graph)
    return spec, by_id, profiles, graph, representatives


def _pd_flow_count(representative) -> int:
    return sum(
        1
        for f in representative.exemplar.flows
        if f.kind is FlowKind.PD_KV_TRANSFER
    )


def test_two_concurrent_transfers_contend_under_fluid_and_not_under_null() -> None:
    """The property the model exists for, on the real pipeline.

    A `dp = 2` P/D candidate sends two KV transfers at once over uplinks it
    shares with itself. Under `null` each is priced as if alone; under `fluid`
    they halve each other's share. That gap is the contribution.
    """
    spec, islands, profiles, graph, representatives = _shared_nic(limit=4)
    concurrent = [r for r in representatives if _pd_flow_count(r) > 1]
    assert concurrent, "no candidate with concurrent P/D flows; nothing to test"

    for representative in concurrent:
        null = features_for(
            representative, spec, graph, islands, profiles, contention=NULL
        )
        fluid = features_for(
            representative, spec, graph, islands, profiles, contention=FLUID
        )
        assert fluid.ttft_ratio > null.ttft_ratio, (
            f"{representative.exemplar.id}: fluid {fluid.ttft_ratio} did not "
            f"exceed null {null.ttft_ratio} despite "
            f"{_pd_flow_count(representative)} concurrent transfers"
        )


def test_one_transfer_alone_is_priced_the_same_by_both() -> None:
    """A candidate with a single flow has nothing to contend with.

    This is why `--contention fluid` leaves most of the corpus untouched, and
    why a run that changed everywhere would be a bug rather than a finding.
    """
    spec, islands, profiles, graph, representatives = _shared_nic(limit=2)
    alone = [r for r in representatives if _pd_flow_count(r) == 1]
    assert alone
    for representative in alone:
        null = features_for(
            representative, spec, graph, islands, profiles, contention=NULL
        )
        fluid = features_for(
            representative, spec, graph, islands, profiles, contention=FLUID
        )
        assert fluid.ttft_ratio == pytest.approx(null.ttft_ratio)


def test_the_reservation_separates_the_counterexample_under_both_models() -> None:
    """Where the X/Y difference actually comes from, pinned so it is not
    re-attributed to the contention model by a later reader.

    X's uplink has 6 of 10 GB/s held by something outside the deployment.
    `effective_bottleneck_bytes_per_s` subtracts it, and BOTH models use that,
    so a representative crossing X is slower than one crossing only Y whichever
    model is selected. The contention model is not what keeps them apart --
    the equivalence relation and the reservation are.
    """
    spec, islands, profiles, graph, representatives = _shared_nic(limit=2)
    crossing_x = [
        r
        for r in representatives
        if _pd_flow_count(r) and "uplink-nodeX" in r.exemplar.boundary.shared_resources
    ]
    clear_of_x = [
        r
        for r in representatives
        if _pd_flow_count(r)
        and "uplink-nodeX" not in r.exemplar.boundary.shared_resources
    ]
    assert crossing_x and clear_of_x, "the fixture lost its counterexample"

    for model in (NULL, FLUID):
        loaded = features_for(
            crossing_x[0], spec, graph, islands, profiles, contention=model
        )
        free = features_for(
            clear_of_x[0], spec, graph, islands, profiles, contention=model
        )
        assert loaded.ttft_ratio > free.ttft_ratio, (
            f"under {model.name} the loaded uplink was not slower; the "
            f"reservation is no longer being subtracted"
        )
