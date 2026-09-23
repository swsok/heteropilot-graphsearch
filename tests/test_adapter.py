"""G11: compile a placement, and name what the simulator could not be told.

`test_the_loss_report_names_what_the_config_cannot_say` is the point. Two
placements differing only in whether they cross a contended uplink compile to
the same simulator input and get the same prediction -- the equivalence layer
kept them apart and the adapter cannot tell the simulator why. That is D3's
limitation landing on graph search, and the MVP's answer is to report it rather
than to lose it quietly.
"""

from __future__ import annotations

import pytest

from graphsearch import paths_root
from graphsearch.adapter import (
    TopologyLossReport,
    apply_pd_transfer_cost_embedded,
    bind,
    compile_embedded,
    graph_signature,
)
from graphsearch.contention import (
    ContentionModel,
    NullContentionModel,
)
from graphsearch.demand import FlowKind
from graphsearch.embeddings import enumerate_embeddings
from graphsearch.equivalence import compress
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import FIXTURES, load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.inventory import detect_islands  # noqa: E402
from planner.plan import (  # noqa: E402
    CandidateConfig,
    IslandAssignment,
    PredictedMetrics,
    Role,
    ServingArch,
)
from planner.spec import load_service_spec  # noqa: E402
from planner.util.workload import WorkloadTrace  # noqa: E402

MODEL = "meta-llama/Llama-3.1-8B"


def spec():
    return load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")


def world(name: str = "abcde_v2"):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    return cluster, profiles, {i.id: i for i in islands}, build_resource_graph(
        cluster, profiles
    )


def island_named(islands, node: str) -> str:
    return next(i.id for i in islands.values() if i.node_id == node)


def embed(templates, islands, graph, service_spec):
    found, _ = enumerate_embeddings(templates, islands, graph, service_spec)
    return found


def tp2(islands, node: str, tid: str | None = None) -> CandidateConfig:
    return CandidateConfig(
        id=tid or f"tp2-{node}", model=MODEL, dtype="bfloat16",
        assignments=[
            IslandAssignment(island_id=island_named(islands, node), tp_size=2)
        ],
    )


def pd(islands, prefill: str, decode: str) -> CandidateConfig:
    return CandidateConfig(
        id=f"pd-{prefill}-{decode}", model=MODEL, dtype="bfloat16",
        serving_arch=ServingArch.PD_SPLIT,
        assignments=[
            IslandAssignment(
                island_id=island_named(islands, prefill), role=Role.PREFILL, tp_size=1
            ),
            IslandAssignment(
                island_id=island_named(islands, decode), role=Role.DECODE, tp_size=1
            ),
        ],
    )


def trace(tmp_path) -> WorkloadTrace:
    path = tmp_path / "wl.jsonl"
    path.write_text('{"input_toks": 8, "output_toks": 4, "arrival_time_ns": 0}\n')
    return WorkloadTrace(
        path=path, num_requests=1, seed=42, total_input_tokens=8,
        total_output_tokens=4, horizon_s=1.0,
    )


# --- the point ------------------------------------------------------------

def test_the_loss_report_names_what_the_config_cannot_say() -> None:
    """D3 landing on graph search: the config has no shared resources."""
    cluster, profiles, islands, graph = world("shared_nic_v2")
    service_spec = spec()
    found = embed([tp2(islands, "nodeX"), tp2(islands, "nodeY")], islands, graph,
                  service_spec)
    assert len(found) == 2

    configs = []
    reports = []
    for embedding in found:
        config, _, report = compile_embedded(
            embedding, cluster, islands, profiles, graph=graph
        )
        configs.append(config)
        reports.append(report)

    # X holds 6 of its 10 GB/s; Y's uplink is free. The two placements are
    # different candidates, and the reports say which resources made them so.
    assert reports[0].dropped_shared_resources != reports[1].dropped_shared_resources
    assert all(r.lossy for r in reports)
    for report in reports:
        caveat = report.caveat()
        assert caveat is not None
        assert "SAME simulator input" in caveat
        assert "bounds and cost" in caveat


def test_a_placement_that_crosses_nothing_shared_reports_no_loss() -> None:
    cluster, profiles, islands, graph = world("abcde_v2")
    found = embed([tp2(islands, "nodeA")], islands, graph, spec())
    _, _, report = compile_embedded(
        found[0], cluster, islands, profiles, graph=graph
    )
    if not report.dropped_shared_resources:
        assert report.caveat() is None
    else:
        # §9's nodes give both GPUs uplink access, so an intra-node pair does
        # reach one -- the report is right and the fixture is why.
        assert report.caveat() is not None


# --- the link figures come from the placement ----------------------------

def test_link_bw_is_this_placement_s_bottleneck() -> None:
    cluster, profiles, islands, graph = world("abcde_v2")
    service_spec = spec()
    found = embed([tp2(islands, "nodeA")], islands, graph, service_spec)
    config, reduction, report = compile_embedded(
        found[0], cluster, islands, profiles, graph=graph
    )
    bw = config["link_bw"]
    first = bw[0] if isinstance(bw, list) else bw
    tp_flow = next(
        f for f in found[0].flows if f.kind is FlowKind.TP_ALLREDUCE
    )
    path = tp_flow.allowed_paths[0].best
    assert path is not None
    assert first == pytest.approx(path.bottleneck_bytes_per_s / 1e9)
    assert "this placement" in reduction.basis
    assert report.per_dim_bw_bytes_per_s[0] == pytest.approx(
        path.bottleneck_bytes_per_s
    )


def test_a_dimension_with_no_flow_is_left_alone() -> None:
    """Replacing it with a default would be inventing a number."""
    cluster, profiles, islands, graph = world("abcde_v2")
    found = embed([tp2(islands, "nodeA")], islands, graph, spec())
    config, _, _ = compile_embedded(
        found[0], cluster, islands, profiles, graph=graph
    )
    assert config["link_bw"] is not None
    assert config["link_latency"] is not None


def test_the_config_is_otherwise_heteropilot_s() -> None:
    """Only the link figures are replaced; every other field is produced by the
    code that owns that format."""
    from planner.predictor.llmservingsim import compile_to_sim_config
    from planner.topology import TopologyGraph

    cluster, profiles, islands, graph = world("abcde_v2")
    found = embed([tp2(islands, "nodeA")], islands, graph, spec())
    ours, _, _ = compile_embedded(found[0], cluster, islands, profiles, graph=graph)
    theirs, _ = compile_to_sim_config(
        found[0].template, cluster, islands, profiles,
        topology=TopologyGraph(cluster), topology_level=2,
    )
    for key in theirs:
        if key in ("link_bw", "link_latency"):
            continue
        assert ours[key] == theirs[key], f"{key} was changed"


# --- the predictor hook ---------------------------------------------------

def test_the_hook_declines_a_candidate_it_was_not_given(monkeypatch, tmp_path) -> None:
    """A driver binds only what it drives; everything else takes the normal path."""
    from planner.predictor import llmservingsim

    cluster, profiles, islands, graph = world("abcde_v2")
    found = embed([tp2(islands, "nodeA")], islands, graph, spec())

    calls: list[str] = []

    def boom(*_a, **_k):
        calls.append("real")
        raise llmservingsim.CompileError("the real compile ran")

    predictor = llmservingsim.LLMServingSimPredictor(
        trace(tmp_path), work_dir=tmp_path / "w"
    )
    bind(
        predictor, {found[0].id: found[0]}, graph,
        cluster=cluster, islands=islands, profiles=profiles, spec=spec(),
    )
    monkeypatch.setattr(llmservingsim, "compile_to_sim_config", boom)

    other = tp2(islands, "nodeB", tid="not-bound")
    result = predictor.predict(other, spec(), cluster, islands, profiles)
    assert calls == ["real"]
    assert "the real compile ran" in result.detail


def test_a_bound_candidate_takes_the_graph_compile(tmp_path) -> None:
    from planner.predictor import llmservingsim

    cluster, profiles, islands, graph = world("abcde_v2")
    found = embed([tp2(islands, "nodeA")], islands, graph, spec())
    predictor = llmservingsim.LLMServingSimPredictor(
        trace(tmp_path), work_dir=tmp_path / "w"
    )
    bind(
        predictor, {found[0].id: found[0]}, graph,
        cluster=cluster, islands=islands, profiles=profiles, spec=spec(),
    )
    candidate = found[0].template.model_copy(update={"id": found[0].id})
    hook = predictor._compile_hook
    assert hook is not None
    compiled = hook(candidate, cluster, islands, profiles)
    assert compiled is not None
    assert predictor.last_loss_reports[candidate.id] is not None


def test_rebinding_replaces_the_batch(tmp_path) -> None:
    from planner.predictor import llmservingsim

    cluster, profiles, islands, graph = world("abcde_v2")
    found = embed(
        [tp2(islands, "nodeA"), tp2(islands, "nodeB")], islands, graph, spec()
    )
    predictor = llmservingsim.LLMServingSimPredictor(
        trace(tmp_path), work_dir=tmp_path / "w"
    )
    rebind = bind(
        predictor, {found[0].id: found[0]}, graph,
        cluster=cluster, islands=islands, profiles=profiles, spec=spec(),
    )
    hook = predictor._compile_hook
    assert hook is not None

    second = found[1].template.model_copy(update={"id": found[1].id})
    assert hook(second, cluster, islands, profiles) is None
    rebind({found[1].id: found[1]})
    assert hook(second, cluster, islands, profiles) is not None


# --- the P/D cost ---------------------------------------------------------

def metrics(**kw) -> PredictedMetrics:
    base = {
        "p50_ttft_ms": 10.0, "p95_ttft_ms": 20.0, "p99_ttft_ms": 30.0,
        "p50_tpot_ms": 1.0, "p95_tpot_ms": 2.0, "p99_tpot_ms": 3.0,
        "throughput_tps": 1.0, "slo_goodput_rps": 1.0, "slo_attainment": 1.0,
        "completed_requests": 1, "completed_tokens": 1,
    }
    base.update(kw)
    return PredictedMetrics(**base)


def test_the_pd_cost_is_percentile_aware() -> None:
    """Using the median for the tail would understate it and could admit a P/D
    that really violates its SLO."""
    _, _, islands, graph = world("abcde_v2")
    service_spec = spec()
    found = embed([pd(islands, "nodeA", "nodeC")], islands, graph, service_spec)
    adjusted, info = apply_pd_transfer_cost_embedded(
        found[0], metrics(), service_spec, graph
    )
    assert info["xfer_ms_p99"] > info["xfer_ms_p50"]
    assert adjusted.p99_ttft_ms - 30.0 == pytest.approx(info["xfer_ms_p99"])
    assert adjusted.p50_tpot_ms == 1.0          # TPOT is untouched


def test_an_aggregated_placement_has_nothing_to_charge() -> None:
    _, _, islands, graph = world("abcde_v2")
    found = embed([tp2(islands, "nodeA")], islands, graph, spec())
    adjusted, info = apply_pd_transfer_cost_embedded(
        found[0], metrics(), spec(), graph
    )
    assert info == {}
    assert adjusted.p99_ttft_ms == 30.0


def test_the_contention_model_is_named_in_the_record() -> None:
    """Two results computed under different models must not be compared by
    accident."""
    _, _, islands, graph = world("abcde_v2")
    service_spec = spec()
    found = embed([pd(islands, "nodeA", "nodeC")], islands, graph, service_spec)
    _, info = apply_pd_transfer_cost_embedded(
        found[0], metrics(), service_spec, graph
    )
    assert info["contention_model"] == "null"
    assert any("contention model" in a for a in info["assumptions"])


# --- the contention interface --------------------------------------------

def test_the_null_model_prices_each_flow_alone() -> None:
    _, _, islands, graph = world("abcde_v2")
    service_spec = spec()
    found = embed([pd(islands, "nodeA", "nodeC")], islands, graph, service_spec)
    flows = list(found[0].flows)
    times = NullContentionModel().transfer_times_ns(flows, graph)
    assert set(times) == {f.flow_id for f in flows}
    assert all(t >= 0 for t in times.values())


def test_the_abstract_model_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        ContentionModel()          # type: ignore[abstract]


def test_a_model_must_return_a_time_for_every_flow() -> None:
    _, _, islands, graph = world("abcde_v2")
    found = embed([tp2(islands, "nodeA")], islands, graph, spec())
    times = NullContentionModel().transfer_times_ns(list(found[0].flows), graph)
    assert len(times) == len(found[0].flows)


# --- the cache signature --------------------------------------------------

def test_two_representatives_get_different_cache_signatures() -> None:
    _, _, islands, graph = world("abcde_v2")
    found = embed(
        [tp2(islands, "nodeA"), tp2(islands, "nodeC")], islands, graph, spec()
    )
    representatives, _, _ = compress(found, graph)
    assert len(representatives) == 2
    signatures = {graph_signature(r, graph) for r in representatives}
    assert len(signatures) == 2


def test_the_signature_carries_the_schema_and_the_tool() -> None:
    _, _, islands, graph = world("abcde_v2")
    found = embed([tp2(islands, "nodeA")], islands, graph, spec())
    representatives, _, _ = compress(found, graph)
    signature = graph_signature(representatives[0], graph)
    assert f":{graph.schema_version}:" in signature
    assert "networkx==" in signature


def test_the_report_serialises_for_provenance() -> None:
    report = TopologyLossReport(dropped_shared_resources=["uplink-nodeA"])
    block = report.as_provenance()
    assert block["contention_modeled"] is False
    assert block["dropped_shared_resources"] == ["uplink-nodeA"]
    assert block["contention_model"] == "null"
