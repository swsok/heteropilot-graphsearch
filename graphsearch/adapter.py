"""Compile a placement for the simulator, and report what the simulator cannot see.

The simulator takes a legacy cluster config: a scalar link bandwidth and
latency, or one pair per topology dimension. It has no shared resources and no
paths (heteropilot D3). So the sharpest consequence of that limitation lands
here, and it is sharper for graph search than for the planner:

**Two placements that differ ONLY in whether they cross a contended uplink
compile to the same simulator input.** The equivalence layer was careful to keep
them apart; the adapter cannot tell the simulator why, and the simulator returns
the same prediction for both. A difference the search was built to see is lost
at the last step.

The MVP does not fix that -- a flow-level contention model is out of scope and
`contention.py` ships an interface with a null implementation. What it does is
refuse to lose the fact quietly: `compile_embedded` returns a
`TopologyLossReport` naming every shared resource the config could not express,
and a caveat travels with any plan whose report is non-empty.

**What this costs a reader.** A comparison of two such representatives is a
comparison of their bounds and their cost, not of their simulated performance,
because the simulator gave both the same answer. That is a real limit on what
the first paper can claim from simulation alone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from graphsearch import paths_root
from graphsearch.contention import DEFAULT_CONTENTION_MODEL, ContentionModel
from graphsearch.demand import FlowKind
from graphsearch.embeddings import EmbeddedCandidate
from graphsearch.equivalence import Representative
from graphsearch.paths import effective_bottleneck_bytes_per_s
from graphsearch.schema import ResourceGraph

paths_root.ensure_importable()

from planner.inventory import (  # noqa: E402
    AcceleratorProfile,
    ClusterSpecV2,
    ExecutionIsland,
)
from planner.plan import CandidateConfig, PredictedMetrics  # noqa: E402
from planner.predictor.llmservingsim import (  # noqa: E402
    LLMServingSimPredictor,
    compile_to_sim_config,
)
from planner.spec import ServiceSpec  # noqa: E402
from planner.topology import TopologyGraph, TopologyReduction  # noqa: E402

#: Bytes per second in one GB/s. The simulator's `link_bw` is GB/s (D120).
_GB = 1e9


@dataclass
class TopologyLossReport:
    """What the simulator was NOT told, named rather than implied."""

    model_level: int = 2
    path_aware: bool = False
    contention_modeled: bool = False
    contention_model: str = DEFAULT_CONTENTION_MODEL.name
    #: Shared resources this placement crosses that the config cannot express.
    #: Two representatives differing only in these produce the same simulator
    #: input, and therefore the same prediction.
    dropped_shared_resources: list[str] = field(default_factory=list)
    #: Flows whose time was computed here rather than simulated.
    flows_priced_analytically: list[str] = field(default_factory=list)
    per_dim_bw_bytes_per_s: list[float] = field(default_factory=list)
    per_dim_latency_ns: list[float] = field(default_factory=list)
    basis: str = ""

    @property
    def lossy(self) -> bool:
        return bool(self.dropped_shared_resources)

    def caveat(self) -> str | None:
        if not self.lossy:
            return None
        return (
            f"This placement crosses {len(self.dropped_shared_resources)} shared "
            f"resource(s) the simulator cannot represent "
            f"({', '.join(sorted(self.dropped_shared_resources))}). Another "
            f"placement differing only in those compiles to the SAME simulator "
            f"input and would return the same metrics, so a comparison between "
            f"them is a comparison of bounds and cost, not of simulated "
            f"performance. Contention model: {self.contention_model} (none)."
        )

    def as_provenance(self) -> dict:
        return {
            "model_level": self.model_level,
            "path_aware": self.path_aware,
            "contention_modeled": self.contention_modeled,
            "contention_model": self.contention_model,
            "dropped_shared_resources": sorted(self.dropped_shared_resources),
            "flows_priced_analytically": sorted(self.flows_priced_analytically),
            "per_dim_bw_bytes_per_s": list(self.per_dim_bw_bytes_per_s),
            "per_dim_latency_ns": list(self.per_dim_latency_ns),
            "basis": self.basis,
        }


def _flow_bottleneck(
    embedding: EmbeddedCandidate, graph: ResourceGraph, kinds: Sequence[FlowKind]
) -> tuple[float, float] | None:
    """(bytes/s, latency ns) of the slowest first-choice path among these kinds."""
    best: tuple[float, float] | None = None
    for flow in embedding.flows:
        if flow.kind not in kinds or not flow.allowed_paths:
            continue
        path = flow.allowed_paths[0].best
        if path is None:
            continue
        capacity = effective_bottleneck_bytes_per_s(graph, path)
        if best is None or capacity < best[0]:
            best = (capacity, path.latency_ns)
    return best


def compile_embedded(
    embedding: EmbeddedCandidate,
    cluster: ClusterSpecV2,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    *,
    graph: ResourceGraph,
    topology: TopologyGraph | None = None,
    gpu_memory_utilization: float = 0.90,
    activation_reserve_gb: float = 0.0,
) -> tuple[dict, TopologyReduction, TopologyLossReport]:
    """heteropilot's compile, with the link figures taken from THIS placement.

    The base config comes from `compile_to_sim_config` at topology level 2, so
    every field the simulator needs is produced by the code that owns that
    format. Only `link_bw` and `link_latency` are replaced, with the bottleneck
    of the path this placement's flows actually take -- which is the one thing
    the island-level compiler cannot know.

    Everything the config still cannot say is named in the report rather than
    dropped.
    """
    topology = topology or TopologyGraph(cluster)
    config, reduction = compile_to_sim_config(
        embedding.template,
        cluster,
        dict(islands),
        dict(profiles),
        topology=topology,
        gpu_memory_utilization=gpu_memory_utilization,
        activation_reserve_gb=activation_reserve_gb,
        topology_level=2,
    )

    intra = _flow_bottleneck(embedding, graph, (FlowKind.TP_ALLREDUCE,))
    cross = _flow_bottleneck(
        embedding, graph, (FlowKind.PD_KV_TRANSFER, FlowKind.PP_ACTIVATION)
    )

    bw = config.get("link_bw")
    latency = config.get("link_latency")
    dims = len(bw) if isinstance(bw, list) else 1
    new_bw = list(bw) if isinstance(bw, list) else [bw]
    new_latency = list(latency) if isinstance(latency, list) else [latency]

    # Dimension 0 is the intra-island fabric, 1 the one above it. A flow kind
    # with no representative in this placement leaves its dimension alone --
    # replacing it with a default would be inventing a number.
    if intra is not None:
        new_bw[0] = intra[0] / _GB
        new_latency[0] = intra[1]
    if cross is not None and dims > 1:
        new_bw[1] = cross[0] / _GB
        new_latency[1] = cross[1]

    config["link_bw"] = new_bw if dims > 1 else new_bw[0]
    config["link_latency"] = new_latency if dims > 1 else new_latency[0]

    report = TopologyLossReport(
        dropped_shared_resources=sorted(embedding.boundary.shared_resources),
        flows_priced_analytically=sorted(
            f.flow_id
            for f in embedding.flows
            if f.kind is FlowKind.PD_KV_TRANSFER
        ),
        per_dim_bw_bytes_per_s=[b * _GB for b in new_bw],
        per_dim_latency_ns=list(new_latency),
        basis=(
            "link_bw/link_latency replaced with this placement's first-choice "
            "path bottleneck, reservations subtracted"
        ),
    )
    reduction = TopologyReduction(
        link_bw_gbps=new_bw[0],
        link_latency_ns=new_latency[0],
        basis="graph search: this placement's path",
        assumptions=[*reduction.assumptions, report.basis],
    )
    return config, reduction, report


def apply_pd_transfer_cost_embedded(
    embedding: EmbeddedCandidate,
    metrics: PredictedMetrics,
    spec: ServiceSpec,
    graph: ResourceGraph,
    *,
    contention: ContentionModel = DEFAULT_CONTENTION_MODEL,
) -> tuple[PredictedMetrics, dict]:
    """Price the P/D handoff over the path this placement takes.

    heteropilot charges the interconnect CLASS because a `CandidateConfig` names
    islands; this knows the devices. The driver subtracts heteropilot's figure
    before adding this one -- charging both would double-count, and the
    inflation would read as a topology effect.

    Percentile-aware, like heteropilot's: transfer time scales with prompt
    length and the SLO is gated at a percentile, so p99 uses the p99 prompt.
    Using the median for the tail would understate it and could admit a P/D
    that really violates its SLO.
    """
    flows = [f for f in embedding.flows if f.kind is FlowKind.PD_KV_TRANSFER]
    if not flows:
        return metrics, {}

    times = contention.transfer_times_ns(flows, graph)
    p50_ns = max(times.values(), default=0.0)
    tokens = spec.traffic.input_tokens
    scale = {
        "p50": 1.0,
        "p95": (tokens.p95 or tokens.p50) / max(1, tokens.p50),
        "p99": (tokens.p99 or tokens.p95 or tokens.p50) / max(1, tokens.p50),
    }
    offsets = {name: p50_ns * factor / 1e6 for name, factor in scale.items()}

    adjusted = metrics.model_copy(
        update={
            "p50_ttft_ms": metrics.p50_ttft_ms + offsets["p50"],
            "p95_ttft_ms": metrics.p95_ttft_ms + offsets["p95"],
            "p99_ttft_ms": metrics.p99_ttft_ms + offsets["p99"],
        }
    )
    info = {
        "candidate_id": embedding.id,
        "basis": "graphsearch embedded path",
        "xfer_ms_p50": offsets["p50"],
        "xfer_ms_p95": offsets["p95"],
        "xfer_ms_p99": offsets["p99"],
        "contention_model": contention.name,
        "flows": sorted(f.flow_id for f in flows),
        "assumptions": [
            "priced over this placement's first-choice path, reservations "
            "subtracted",
            "percentile-scaled from the p50 transfer by prompt length",
            f"contention model: {contention.name}",
        ],
    }
    return adjusted, info


def bind(
    predictor: LLMServingSimPredictor,
    embeddings_by_candidate_id: Mapping[str, EmbeddedCandidate],
    graph: ResourceGraph,
    *,
    cluster: ClusterSpecV2,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    spec: ServiceSpec,
    gpu_memory_utilization: float = 0.90,
    activation_reserve_gb: float = 0.0,
) -> Callable[[Mapping[str, EmbeddedCandidate]], None]:
    """Install the compile hook, and return a rebinder for the next batch.

    The hook returns None for any candidate it was not given, so the normal
    compile runs for everything else -- a driver binds only what it drives, and
    heteropilot never learns that `EmbeddedCandidate` exists.
    """
    bound: dict[str, EmbeddedCandidate] = dict(embeddings_by_candidate_id)
    reports: dict[str, TopologyLossReport] = {}
    transfers: dict[str, dict] = {}
    # Cumulative across every batch, and never reset by `rebind`. A run that
    # reports `compile_applied 0` was judging templates, whatever else it
    # printed, and that is the failure this counter exists to make visible --
    # `plan` did exactly that until G16 (GS-13). `_seen` counts every
    # invocation, `_applied` only the ones for a candidate this binder owns.
    calls: dict[str, int] = {
        "batches": 0, "bound": 0,
        "compile_seen": 0, "compile_applied": 0,
        "result_seen": 0, "result_applied": 0,
    }
    topology = TopologyGraph(cluster)

    def hook(
        candidate: CandidateConfig,
        hook_cluster: ClusterSpecV2,
        hook_islands: Mapping[str, ExecutionIsland],
        hook_profiles: Mapping[str, AcceleratorProfile],
    ):
        calls["compile_seen"] += 1
        embedding = bound.get(candidate.id)
        if embedding is None:
            return None
        calls["compile_applied"] += 1
        config, reduction, report = compile_embedded(
            embedding, hook_cluster, hook_islands, hook_profiles,
            graph=graph, topology=topology,
            gpu_memory_utilization=gpu_memory_utilization,
            activation_reserve_gb=activation_reserve_gb,
        )
        reports[candidate.id] = report
        return config, reduction

    def result_hook(candidate: CandidateConfig, result):
        """Price the P/D handoff over the path this placement takes.

        Registered rather than applied afterwards (heteropilot D125): the
        feasibility verdict is taken inside `evaluate_candidates`, and the
        envelope cache stores whatever `predict` returns, so a correction made
        outside would leave the verdict on different numbers and would vanish
        on a cache hit. Callers pair this with
        `evaluate_candidates(pd_transfer=False)` so heteropilot's
        class-default figure is ABSENT rather than subtracted.
        """
        calls["result_seen"] += 1
        embedding = bound.get(candidate.id)
        if embedding is None or result.metrics is None:
            return result
        metrics, info = apply_pd_transfer_cost_embedded(
            embedding, result.metrics, spec, graph
        )
        if not info:
            return result
        calls["result_applied"] += 1
        transfers[candidate.id] = info
        return replace(result, metrics=metrics)

    predictor.set_compile_hook(hook)
    predictor.set_result_hook(result_hook)
    predictor.last_loss_reports = reports          # type: ignore[attr-defined]
    predictor.last_pd_transfers = transfers        # type: ignore[attr-defined]
    predictor.last_hook_calls = calls              # type: ignore[attr-defined]

    def rebind(next_batch: Mapping[str, EmbeddedCandidate]) -> None:
        """Point both hooks at the next batch.

        A predictor that can see placements itself -- the graph-aware mock --
        is told too, so a caller has one binder rather than two that can drift
        out of step.
        """
        bound.clear()
        bound.update(next_batch)
        calls["batches"] += 1
        calls["bound"] += len(next_batch)
        transfers.clear()
        binder = getattr(predictor, "bind_embeddings", None)
        if binder is not None:
            binder(dict(next_batch))
        graph_binder = getattr(predictor, "bind_graph", None)
        if graph_binder is not None:
            graph_binder(graph)

    rebind(dict(embeddings_by_candidate_id))
    return rebind


def graph_signature(representative: Representative, graph: ResourceGraph) -> str:
    """The envelope-cache signature for one representative (H3)."""
    return (
        f"{representative.signature.wl_hash}:{graph.schema_version}:"
        f"{representative.signature.tool_version}"
    )
