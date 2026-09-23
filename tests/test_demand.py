"""G3: what a candidate sends.

The test that earns its place here is `test_matches_heteropilot_stage4`. The
all-reduce formula exists twice on purpose -- once in
`planner/candidate_generator.py`'s stage-4 bound, once in `graphsearch/demand.py`
-- and a shared helper would make the two agree by construction, which proves
nothing. Two implementations checked against each other catch a drift in either.
That check runs against heteropilot's own rejection string, so it also pins the
string's meaning: if someone reworded it, this fails and says so.
"""

from __future__ import annotations

import re

import pytest

from graphsearch import paths_root
from graphsearch.demand import (
    CommFlow,
    FlowKind,
    flows_for,
    pd_kv_bytes,
    placements_from_islands,
    pp_activation_bytes,
    tp_allreduce_bytes,
    tp_allreduces_per_output_token,
)
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import (  # noqa: E402
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)
from planner.plan import (  # noqa: E402
    CandidateConfig,
    IslandAssignment,
    RejectionStage,
    Role,
    ServingArch,
)
from planner.spec import load_service_spec  # noqa: E402
from planner.topology import TopologyGraph  # noqa: E402

HP_ROOT = paths_root.HETEROPILOT_ROOT
MODEL = "meta-llama/Llama-3.1-8B"


def toy(name: str = "abcde_v2"):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    return (
        cluster,
        profiles,
        {i.id: i for i in detect_islands(cluster, profiles)},
        build_resource_graph(cluster, profiles),
    )


FOUR_GPU = """
cluster_id: four
nodes:
  - id: node0
    accelerators:
      - {id: gpu0, type: GPU, vendor: TOY, model: TOYGPU, backend: cuda,
         memory_gb: 80, profile: fixtures/profiles/toy_gpu.yaml}
      - {id: gpu1, type: GPU, vendor: TOY, model: TOYGPU, backend: cuda,
         memory_gb: 80, profile: fixtures/profiles/toy_gpu.yaml}
      - {id: gpu2, type: GPU, vendor: TOY, model: TOYGPU, backend: cuda,
         memory_gb: 80, profile: fixtures/profiles/toy_gpu.yaml}
      - {id: gpu3, type: GPU, vendor: TOY, model: TOYGPU, backend: cuda,
         memory_gb: 80, profile: fixtures/profiles/toy_gpu.yaml}
    nics:
      - {id: nic0, type: ethernet, speed_gbps: 10}
links:
  - {id: l01, src: node0/gpu0, dst: node0/gpu1, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}
  - {id: l12, src: node0/gpu1, dst: node0/gpu2, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}
  - {id: l23, src: node0/gpu2, dst: node0/gpu3, type: NVLINK,
     bandwidth_gbps: 112.5, latency_ns: 500}
  - {id: lnic, src: node0/gpu0, dst: node0/nic0, type: PCIE,
     bandwidth_gbps: 10, latency_ns: 900}
"""


def four_gpu():
    """§9's cluster has two devices per node, so tp=2 dp=2 needs its own."""
    import textwrap

    import yaml
    from planner.inventory import ClusterSpecV2

    cluster = ClusterSpecV2.model_validate(yaml.safe_load(textwrap.dedent(FOUR_GPU)))
    profiles = load_profiles_for(cluster, paths_root.GRAPHSEARCH_ROOT)
    return (
        cluster,
        profiles,
        {i.id: i for i in detect_islands(cluster, profiles)},
        build_resource_graph(cluster, profiles),
    )


def toy_spec():
    from tests.graph_fixtures import FIXTURES

    return load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")


def template(
    islands, *, tp: int = 1, dp: int = 1, island: str | None = None,
    arch: ServingArch = ServingArch.AGGREGATED, assignments=None,
) -> CandidateConfig:
    island = island or sorted(islands)[0]
    return CandidateConfig(
        id="c", model=MODEL, dtype="bfloat16", serving_arch=arch,
        assignments=assignments
        or [IslandAssignment(island_id=island, tp_size=tp, dp_replicas=dp)],
    )


# --- (i) the arithmetic ---------------------------------------------------

def test_the_ring_factor_is_what_makes_tp2_and_tp4_differ() -> None:
    """hidden 4096 x 2 B x 2(tp-1)/tp. tp=2 -> 8192; tp=4 -> 12288."""
    assert tp_allreduce_bytes(MODEL, "bfloat16", 2) == pytest.approx(8192)
    assert tp_allreduce_bytes(MODEL, "bfloat16", 4) == pytest.approx(12288)


def test_tp1_sends_nothing() -> None:
    assert tp_allreduce_bytes(MODEL, "bfloat16", 1) == 0.0


def test_tp0_is_an_error_not_a_zero() -> None:
    with pytest.raises(ValueError, match="tp must be"):
        tp_allreduce_bytes(MODEL, "bfloat16", 0)


def test_two_all_reduces_per_layer() -> None:
    assert tp_allreduces_per_output_token(MODEL) == 64        # 32 layers


def test_dtype_changes_the_payload() -> None:
    assert tp_allreduce_bytes(MODEL, "float32", 2) == pytest.approx(
        2 * tp_allreduce_bytes(MODEL, "bfloat16", 2)
    )


def test_kv_bytes_scale_with_the_prompt() -> None:
    one = pd_kv_bytes(MODEL, "bfloat16", "auto", 1)
    assert pd_kv_bytes(MODEL, "bfloat16", "auto", 731) == pytest.approx(731 * one)


def test_pp_activation_is_one_hidden_tensor() -> None:
    assert pp_activation_bytes(MODEL, "bfloat16") == pytest.approx(4096 * 2)


# --- (ii) the agreement test ----------------------------------------------

_FLOOR = re.compile(
    r"TP=(?P<tp>\d+) all-reduce floor (?P<floor>[\d.]+)ms on (?P<island>\S+)"
)


def test_matches_heteropilot_stage4() -> None:
    """Design §7.9. Two implementations of one formula, checked against each other.

    heteropilot's stage-4 bound prints the floor it computed. This recomputes it
    from `tp_allreduce_bytes` plus the SAME interconnect figure the generator
    asked its topology model for -- so what is compared is the arithmetic, not
    the inputs.

    The printed floor is `%.1f`, so the strongest statement the string supports
    is that both sides round to it. That is asserted as well as the work order's
    0.05 ms tolerance, which is exactly the rounding half-width.
    """
    cluster = load_cluster_spec(HP_ROOT / "examples/clusters/heterogeneous-lab.yaml")
    profiles = load_profiles_for(cluster, HP_ROOT)
    islands = detect_islands(cluster, profiles)
    spec = load_service_spec(HP_ROOT / "examples/service_specs/llama31-8b.yaml")

    # The committed spec's TPOT budget is generous enough that nothing trips
    # the bound, so it is forced -- §7.9 says to.
    tight = spec.model_copy(
        update={
            "slo": spec.slo.model_copy(
                update={"tpot": spec.slo.tpot.model_copy(update={"max_ms": 0.01})}
            )
        }
    )
    generator = CandidateGenerator(
        tight, cluster, islands, profiles, enable_bound_pruning=True
    )
    rejections = [
        r
        for r in generator.generate().rejections
        if r.stage is RejectionStage.TOPOLOGY_INFEASIBLE
    ]
    assert rejections, "no stage-4 rejection to check against"

    topology = TopologyGraph(cluster)
    by_id = {i.id: i for i in islands}
    checked = 0
    for rejection in rejections:
        match = _FLOOR.search(rejection.reason)
        assert match, f"stage-4 reason no longer parses: {rejection.reason!r}"
        tp = int(match["tp"])
        theirs = float(match["floor"])
        island = by_id[match["island"]]

        bw_gbps, lat_ns, _ = topology.island_interconnect(island, world_size=tp)
        payload = tp_allreduce_bytes(tight.model, tight.service.dtype, tp)
        per_allreduce_ns = lat_ns + payload / bw_gbps
        ours = (
            tp_allreduces_per_output_token(tight.model) * per_allreduce_ns
        ) / 1e6

        assert f"{ours:.1f}" == f"{theirs:.1f}", (
            f"stage-4 floor disagrees on {island.id} tp={tp}: "
            f"heteropilot {theirs}, graphsearch {ours:.6f}"
        )
        assert abs(ours - theirs) <= 0.05
        checked += 1
    assert checked == len(rejections)


# --- (iii)-(v) flows ------------------------------------------------------

def test_one_all_reduce_per_replica_with_disjoint_ranks() -> None:
    _, _, islands, graph = four_gpu()
    tmpl = template(islands, tp=2, dp=2)
    flows = flows_for(
        tmpl, placements_from_islands(tmpl, islands), toy_spec(), graph
    )
    tp_flows = [f for f in flows if f.kind is FlowKind.TP_ALLREDUCE]
    assert len(tp_flows) == 2
    a, b = (set(f.participants) for f in tp_flows)
    assert a.isdisjoint(b)


def test_tp1_dp1_has_no_collective_only_edge_traffic() -> None:
    """Enumerated even though no latency target charges for them: they consume
    the same uplink a collective would, and a cut that ignored them would
    over-state what is left."""
    _, _, islands, graph = toy()
    tmpl = template(islands)
    flows = flows_for(tmpl, placements_from_islands(tmpl, islands), toy_spec(), graph)
    kinds = {f.kind for f in flows}
    assert kinds == {FlowKind.INGRESS, FlowKind.EGRESS}
    assert all(f.on_critical_path == "none" for f in flows)


def test_a_pd_candidate_transfers_the_p50_prompt() -> None:
    _, _, islands, graph = toy()
    two = sorted(i.id for i in islands.values() if i.backend == "cuda")[:2]
    tmpl = template(
        islands,
        arch=ServingArch.PD_SPLIT,
        assignments=[
            IslandAssignment(island_id=two[0], role=Role.PREFILL, tp_size=1),
            IslandAssignment(island_id=two[1], role=Role.DECODE, tp_size=1),
        ],
    )
    spec = toy_spec()
    flows = flows_for(tmpl, placements_from_islands(tmpl, islands), spec, graph)
    pd = [f for f in flows if f.kind is FlowKind.PD_KV_TRANSFER]
    assert len(pd) == 1
    assert pd[0].bytes_per_event == pytest.approx(
        pd_kv_bytes(
            spec.model, spec.service.dtype, spec.service.kv_cache_dtype,
            spec.traffic.input_tokens.p50,
        )
    )
    assert pd[0].on_critical_path == "ttft"


def test_the_pd_flow_lists_the_tail_it_was_not_sized_at() -> None:
    """A p99 TTFT check must not silently use the median prompt."""
    _, _, islands, graph = toy()
    two = sorted(i.id for i in islands.values() if i.backend == "cuda")[:2]
    tmpl = template(
        islands, arch=ServingArch.PD_SPLIT,
        assignments=[
            IslandAssignment(island_id=two[0], role=Role.PREFILL, tp_size=1),
            IslandAssignment(island_id=two[1], role=Role.DECODE, tp_size=1),
        ],
    )
    flows = flows_for(tmpl, placements_from_islands(tmpl, islands), toy_spec(), graph)
    pd = next(f for f in flows if f.kind is FlowKind.PD_KV_TRANSFER)
    text = " ".join(pd.assumptions)
    assert "p95 prompt" in text and "p99 prompt" in text


def test_an_aggregated_candidate_has_no_kv_transfer() -> None:
    _, _, islands, graph = toy()
    tmpl = template(islands, tp=2)
    flows = flows_for(tmpl, placements_from_islands(tmpl, islands), toy_spec(), graph)
    assert not [f for f in flows if f.kind is FlowKind.PD_KV_TRANSFER]


def test_a_tp_flow_carries_the_paths_between_its_ranks() -> None:
    _, _, islands, graph = toy()
    tmpl = template(islands, tp=2)
    flows = flows_for(tmpl, placements_from_islands(tmpl, islands), toy_spec(), graph)
    tp_flow = next(f for f in flows if f.kind is FlowKind.TP_ALLREDUCE)
    assert len(tp_flow.allowed_paths) == 1          # one unordered pair
    assert tp_flow.allowed_paths[0].best is not None


def test_events_per_request_scales_with_output_length() -> None:
    _, _, islands, graph = toy()
    spec = toy_spec()
    tmpl = template(islands, tp=2)
    flow = next(
        f
        for f in flows_for(tmpl, placements_from_islands(tmpl, islands), spec, graph)
        if f.kind is FlowKind.TP_ALLREDUCE
    )
    assert flow.events_per_request == pytest.approx(
        tp_allreduces_per_output_token(spec.model) * spec.traffic.output_tokens.p50
    )


def test_every_flow_states_what_it_assumed() -> None:
    _, _, islands, graph = toy()
    tmpl = template(islands, tp=2)
    for flow in flows_for(tmpl, placements_from_islands(tmpl, islands), toy_spec(), graph):
        assert flow.assumptions, f"{flow.flow_id} states nothing"


# --- (vi) determinism -----------------------------------------------------

def test_flow_ids_are_unique_and_the_order_repeats() -> None:
    _, _, islands, graph = four_gpu()
    tmpl = template(islands, tp=2, dp=2)
    placements = placements_from_islands(tmpl, islands)
    first = flows_for(tmpl, placements, toy_spec(), graph)
    second = flows_for(tmpl, placements, toy_spec(), graph)
    ids = [f.flow_id for f in first]
    assert len(set(ids)) == len(ids)
    assert ids == [f.flow_id for f in second]
    # Sorted by (kind, flow_id), so a signature built over the tuple repeats.
    assert [f.kind.value for f in first] == sorted(f.kind.value for f in first)


def test_placements_refuse_an_island_that_is_too_small() -> None:
    _, _, islands, _ = toy()
    small = min(islands.values(), key=lambda i: i.size)
    tmpl = template(islands, tp=1, dp=small.size + 1, island=small.id)
    with pytest.raises(ValueError, match="too few"):
        placements_from_islands(tmpl, islands)


def test_bytes_per_request_is_the_product() -> None:
    flow = CommFlow(
        flow_id="f", kind=FlowKind.TP_ALLREDUCE, participants=("a", "b"),
        bytes_per_event=100.0, events_per_request=3.0, on_critical_path="tpot",
    )
    assert flow.bytes_per_request == pytest.approx(300.0)
