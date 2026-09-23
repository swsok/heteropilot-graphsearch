"""Rank representatives by how much room each has against its SLOs.

This is a **heuristic**, and the distinction from `bounds.py` is the whole
point. A bound eliminates on arithmetic that cannot be beaten; a ranker decides
what to spend a simulation on first, and it may be wrong. So it is allowed
things a bound is not:

* **Measured effective bandwidths.** A measured average is not a guaranteed
  ceiling (heteropilot D112), which is why a bound may not divide by one. A
  ranker may: being wrong here costs an ordering, not a verdict.
* **Estimates.** `greedy.estimate`'s roofline TPOT is a proxy, reused rather
  than reinvented so the ranker and the planner's own stage-5 physics do not
  drift apart.

And it is forbidden one thing: **it never produces `PredictedMetrics`.** A
ranker that emitted metrics would be a predictor nobody validated, and its
numbers would flow into a plan as though a simulation had produced them.
`order()` returns a permutation, nothing else.

**`risk_proxy` is a max, not a sum.** A candidate meets its SLOs only if every
one of them is met, so the binding constraint is the worst ratio; averaging
them would let generous TTFT headroom hide a TPOT miss.

**Two estimates, and the bound keeps the other one (E-G2, GS-12).** Under a
spec whose SLO actually binds, the first version of this ranker put four
candidates in its comfortable band that missed their TTFT by 5.8x. Every one
was a `max_num_seqs=32` placement whose sibling at 128 was fine, and the term
that should have said so -- `goodput_ratio` -- read 0.085 against an actual
2.48, because its denominator was the bound's optimistic ceiling, which lets
as many sequences run as the KV cache holds and never reads the knob. That is
the right denominator for a BOUND: a relaxation must be optimistic. It is the
wrong one for a RANKER, whose job is to guess well. `service_margin` therefore
divides by `greedy.estimate`'s knob-aware throughput and adds one prefill
roofline pass to the TTFT; `service_margin_v1` keeps the original terms as the
baseline every comparison is made against. The bound still uses the ceiling,
on purpose, and `test_ranker.py` pins that the ranker is never MORE optimistic
than the ceiling -- the direction that would let it call comfortable what a
bound has proved impossible.

**Diversity is a hedge against the proxy being wrong.** Sorting purely by risk
then cost fills a small budget with near-identical placements, and if the proxy
mis-ranks that structure the whole batch is wasted. `DiversityQuota` reserves
part of the budget for distinct `structure_key`s so a batch covers more than
one bet, and it always returns exactly K.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from graphsearch import paths_root
from graphsearch.bounds import GPU_MEMORY_UTILIZATION
from graphsearch.demand import CommFlow, FlowKind
from graphsearch.embeddings import EmbeddedCandidate
from graphsearch.equivalence import Representative
from graphsearch.paths import effective_bottleneck_bytes_per_s
from graphsearch.schema import ResourceGraph

paths_root.ensure_importable()

from planner.inventory import AcceleratorProfile, ExecutionIsland  # noqa: E402
from planner.optimizer import greedy  # noqa: E402
from planner.optimizer.surrogate import SurrogateRanker  # noqa: E402
from planner.plan import CandidateConfig, Role, ServingArch  # noqa: E402
from planner.predictor.calibration import load_domain_index  # noqa: E402
from planner.spec import ServiceSpec  # noqa: E402
from planner.util import memory as memutil  # noqa: E402

#: The ranker variants a caller may name. `service_margin` is the corrected
#: estimate (G15); `service_margin_v1` is the original, kept so every claim
#: about the correction can be checked against the thing it corrected.
RANKER_V1 = "service_margin_v1"
DEFAULT_RANKER_VARIANT = "service_margin"
RANKER_VARIANTS = (DEFAULT_RANKER_VARIANT, RANKER_V1)


@dataclass(frozen=True)
class RankFeatures:
    """Everything the ordering reads. Diagnostic as well as functional: a
    surprising order should be explainable from these rather than guessed at."""

    candidate_id: str
    ttft_ratio: float
    tpot_ratio: float
    goodput_ratio: float
    cost_per_hour: float | None
    shared_nic_util: float
    cut_margin: float
    memory_margin: float
    #: No calibration domain covers this hardware. Not used in the ordering --
    #: an epistemic gap is `bounds.py`'s business, not a ranking penalty -- but
    #: carried so a caller can report it.
    outside_calibration: bool
    structure_key: tuple
    #: Which terms went into the three ratios, in words. A surprising order is
    #: explained from here; a changed estimate is visible from here.
    basis: str = ""

    @property
    def risk_proxy(self) -> float:
        """The binding constraint. A max, because every SLO must be met."""
        return max(self.ttft_ratio, self.tpot_ratio, self.goodput_ratio)

    @property
    def comfortable(self) -> bool:
        return self.risk_proxy <= 1.0


@dataclass(frozen=True)
class DiversityQuota:
    """Reserve part of a batch for distinct structures.

    `by` names the feature to spread over. `reserved_fraction` is how much of
    the budget is held back from the pure risk/cost ordering.
    """

    by: str = "structure_key"
    reserved_fraction: float = 0.5
    #: When the budget is smaller than the number of groups, take one from each
    #: group in turn rather than filling from the first.
    round_robin_when_short: bool = True


# --- features -------------------------------------------------------------

def _flow_seconds(
    flow: CommFlow, graph: ResourceGraph, *, per_request: bool
) -> float:
    """Wire time for one flow over its best path, reservations subtracted.

    G11 routes this through `ContentionModel`; until then the null model --
    latency plus bytes over the bottleneck -- is what it would compute anyway.
    """
    if not flow.allowed_paths:
        return 0.0
    best = flow.allowed_paths[0].best
    if best is None:
        return float("inf")
    capacity = effective_bottleneck_bytes_per_s(graph, best)
    if capacity <= 0:
        return float("inf")
    payload = flow.bytes_per_request if per_request else flow.bytes_per_event
    return best.latency_ns / 1e9 + payload / capacity


def _memory_report(
    assignment, island: ExecutionIsland, spec: ServiceSpec, utilization: float
):
    return memutil.evaluate(
        spec.model,
        tp_size=assignment.tp_size,
        device_memory_gb=island.total_memory_gb / island.size,
        dtype=spec.service.dtype,
        kv_cache_dtype=spec.service.kv_cache_dtype,
        gpu_memory_utilization=utilization,
    )


def _goodput_ceiling(
    embedding: EmbeddedCandidate,
    spec: ServiceSpec,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    utilization: float,
) -> float:
    """The same optimistic ceiling `bounds.throughput_capacity` computes.

    Shared deliberately: if the ranker used a different ceiling, a candidate
    could rank comfortably and then be eliminated by a bound that disagreed,
    and the two numbers would have to be reconciled by whoever noticed.
    """
    template = embedding.template
    total_tps = 0.0
    for assignment in template.assignments:
        if assignment.role not in (Role.DECODE, Role.AGGREGATED):
            continue
        island = islands[assignment.island_id]
        profile = profiles.get(island.accelerator_model)
        if profile is None:
            return float("inf")
        report = _memory_report(assignment, island, spec, utilization)
        median = max(
            1, spec.traffic.input_tokens.p50 + spec.traffic.output_tokens.p50
        )
        active = max(1.0, report.kv_tokens / median)
        step_s = report.weight_bytes / (profile.memory_bandwidth_gbps * 1e9)
        if step_s <= 0:
            return float("inf")
        total_tps += (active / step_s) * assignment.dp_replicas
    return total_tps / max(1, spec.traffic.output_tokens.p50)


def prefill_roofline_ms(
    template: CandidateConfig,
    spec: ServiceSpec,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    *,
    utilization: float = GPU_MEMORY_UTILIZATION,
) -> float:
    """The least time a prefill (or aggregated) engine needs for one p50 prompt.

    Reading the weights once and writing the prompt's KV, over the profile's
    memory bandwidth -- the same roofline the bounds and heteropilot's own
    stage-5 physics use, and optimistic in the same way: no batching, no
    queueing, no slack. `GreedyEstimate` deliberately has no such field (its
    `roofline_tpot_ms` is decode-only), so it is computed here. E-G2 measured
    it at 2-4 % of the mock's p99 TTFT: a term that is real, small, and better
    than the zero it replaces.
    """
    worst = 0.0
    for assignment in template.assignments:
        if assignment.role not in (Role.PREFILL, Role.AGGREGATED):
            continue
        island = islands[assignment.island_id]
        profile = profiles.get(island.accelerator_model)
        if profile is None or profile.memory_bandwidth_gbps <= 0:
            return float("inf")
        report = _memory_report(assignment, island, spec, utilization)
        prompt_bytes = spec.traffic.input_tokens.p50 * report.kv_bytes_per_token
        seconds = (report.weight_bytes + prompt_bytes) / (
            profile.memory_bandwidth_gbps * 1e9
        )
        worst = max(worst, seconds * 1e3)
    return worst


def _structure_key(embedding: EmbeddedCandidate, graph: ResourceGraph) -> tuple:
    """What makes two candidates the same BET, for diversity purposes."""
    template = embedding.template
    models = sorted(
        {
            str(graph.vertices[d].attrs.get("model"))
            for d in embedding.devices
            if d in graph.vertices
        }
    )
    return (
        max(a.tp_size for a in template.assignments),
        len(embedding.nodes),
        tuple(models),
        template.serving_arch is ServingArch.PD_SPLIT,
    )


def features_for(
    representative: Representative,
    spec: ServiceSpec,
    graph: ResourceGraph,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    *,
    gpu_memory_utilization: float = GPU_MEMORY_UTILIZATION,
    cost_per_hour: float | None = None,
    domain_root=None,
    variant: str = DEFAULT_RANKER_VARIANT,
) -> RankFeatures:
    """Read one representative's exemplar into the numbers the ordering uses.

    `variant` picks the estimate. `service_margin` (default) is the corrected
    one; `service_margin_v1` is the original and exists so the correction can
    be measured rather than asserted. Anything else is refused: a misspelt
    variant that silently fell back would make every comparison a lie.
    """
    if variant not in RANKER_VARIANTS:
        raise ValueError(
            f"unknown ranker variant {variant!r}; one of {RANKER_VARIANTS}"
        )
    corrected = variant == DEFAULT_RANKER_VARIANT
    embedding = representative.exemplar
    template = embedding.template

    ttft_ms = 1e3 * sum(
        _flow_seconds(f, graph, per_request=False)
        for f in embedding.flows
        if f.kind in (FlowKind.PD_KV_TRANSFER, FlowKind.PP_ACTIVATION)
    )
    if corrected:
        ttft_ms += prefill_roofline_ms(
            template, spec, islands, profiles, utilization=gpu_memory_utilization
        )
    ttft_ratio = ttft_ms / spec.slo.ttft.max_ms

    estimate = greedy.estimate(
        template, spec, dict(islands), dict(profiles),
        gpu_memory_utilization=gpu_memory_utilization,
    )
    tp_ms = max(
        (
            _flow_seconds(f, graph, per_request=False) * 1e3
            * f.events_per_request
            / max(1, spec.traffic.output_tokens.p50)
            for f in embedding.flows
            if f.kind is FlowKind.TP_ALLREDUCE
        ),
        default=0.0,
    )
    tpot_ratio = (estimate.roofline_tpot_ms + tp_ms) / spec.slo.tpot.max_ms

    demanded = spec.slo.min_goodput_rps or spec.traffic.arrival_rate_rps
    if corrected:
        # The knob-aware estimate, not the bound's ceiling. The ceiling admits
        # as many sequences as the KV cache holds; a `max_num_seqs=32`
        # placement can serve 32, and the mock -- like a real engine -- stops
        # there. E-G2: ceiling 0.085 vs actual 2.48 on exactly those.
        achievable_rps = estimate.proxy_throughput_tps / max(
            1, spec.traffic.output_tokens.p50
        )
        basis = (
            "service_margin: ttft = PD/PP transfer + one prefill roofline pass; "
            "tpot = decode roofline + TP all-reduce; goodput = demanded / "
            "knob-aware greedy throughput (the bound keeps the optimistic ceiling)"
        )
    else:
        achievable_rps = _goodput_ceiling(
            embedding, spec, islands, profiles, gpu_memory_utilization
        )
        basis = (
            "service_margin_v1: ttft = PD/PP transfer only; tpot = decode "
            "roofline + TP all-reduce; goodput = demanded / optimistic ceiling "
            "(knob-blind, same as the bound)"
        )
    goodput_ratio = demanded / achievable_rps if achievable_rps > 0 else float("inf")

    shared_nic_util = 0.0
    for resource_id, demand in embedding.resource_demand.items():
        resource = graph.shared_resources.get(resource_id)
        if resource is None or resource.available_bytes_per_s <= 0:
            shared_nic_util = float("inf")
            break
        shared_nic_util = max(
            shared_nic_util, demand / resource.available_bytes_per_s
        )

    cut_margin = float("inf")
    rate = spec.traffic.arrival_rate_rps
    for flow in embedding.flows:
        required = flow.bytes_per_request * rate
        if required <= 0 or not flow.allowed_paths:
            continue
        best = flow.allowed_paths[0].best
        if best is None:
            cut_margin = 0.0
            continue
        cut_margin = min(
            cut_margin, effective_bottleneck_bytes_per_s(graph, best) / required
        )

    memory_margin = float("inf")
    for assignment in template.assignments:
        island = islands[assignment.island_id]
        report = _memory_report(assignment, island, spec, gpu_memory_utilization)
        median = max(
            1, spec.traffic.input_tokens.p50 + spec.traffic.output_tokens.p50
        )
        want = median * max(1, template.knobs.max_num_seqs)
        memory_margin = min(memory_margin, report.kv_tokens / want)

    index = load_domain_index(domain_root or paths_root.HETEROPILOT_ROOT)
    hardware = {
        str(graph.vertices[d].attrs.get("sim_hardware"))
        for d in embedding.devices
        if d in graph.vertices
    }
    outside = any(_no_domain(index, name) for name in sorted(hardware))

    return RankFeatures(
        candidate_id=embedding.id,
        ttft_ratio=ttft_ratio,
        tpot_ratio=tpot_ratio,
        goodput_ratio=goodput_ratio,
        cost_per_hour=cost_per_hour,
        shared_nic_util=shared_nic_util,
        cut_margin=cut_margin,
        memory_margin=memory_margin,
        outside_calibration=outside,
        structure_key=_structure_key(embedding, graph),
        basis=basis,
    )


def _no_domain(index, hardware: str) -> bool:
    """True when nothing in the index covers this hardware.

    Failure is reported as "no domain", never as "covered": an index that
    cannot be read is the same epistemic position as one that says nothing.
    """
    if hardware in ("None", ""):
        return True
    try:
        return not any(
            getattr(entry, "hardware", None) == hardware
            for entry in getattr(index, "entries", [])
        )
    except Exception:                                   # pragma: no cover
        return True


# --- ordering -------------------------------------------------------------

_COST_LAST = float("inf")


def _sort_key(features: RankFeatures) -> tuple:
    """Group 1 by cost then risk; group 2 by risk then cost.

    An unpriced candidate sorts after group 1 and before group 2: it is known
    to be comfortable, which is worth more than a cheap candidate that is not,
    and its cost is unknown rather than large.
    """
    cost = _COST_LAST if features.cost_per_hour is None else features.cost_per_hour
    if features.comfortable:
        band = 0 if features.cost_per_hour is not None else 1
        return (band, cost, features.risk_proxy, features.candidate_id)
    return (2, features.risk_proxy, cost, features.candidate_id)


def rank_features(features: Sequence[RankFeatures]) -> list[RankFeatures]:
    return sorted(features, key=_sort_key)


def apply_quota(
    ordered: Sequence[RankFeatures], k_hint: int, quota: DiversityQuota
) -> list[RankFeatures]:
    """Take exactly `k_hint`, holding some of the budget for distinct structures.

    The reserved slots are spread over `structure_key` groups, best-first within
    each. Whatever the reservation does not use goes back to the pure ordering,
    so the quota can never return fewer than a plain top-K would.
    """
    if k_hint <= 0 or not ordered:
        return []
    k = min(k_hint, len(ordered))

    groups: dict[tuple, list[RankFeatures]] = {}
    for item in ordered:
        groups.setdefault(getattr(item, quota.by), []).append(item)
    group_keys = sorted(groups)

    reserved = min(k, math.ceil(k * quota.reserved_fraction))
    picked: list[RankFeatures] = []
    seen: set[str] = set()

    if quota.round_robin_when_short or reserved >= len(group_keys):
        per_group = max(1, reserved // max(1, len(group_keys)))
        for key in group_keys:
            for item in groups[key][:per_group]:
                if len(picked) >= reserved:
                    break
                if item.candidate_id not in seen:
                    picked.append(item)
                    seen.add(item.candidate_id)
            if len(picked) >= reserved:
                break

    for item in ordered:
        if len(picked) >= k:
            break
        if item.candidate_id not in seen:
            picked.append(item)
            seen.add(item.candidate_id)

    # The reservation may have taken items out of order; restore the ranking
    # among what was chosen so a caller taking a prefix still gets the best.
    return rank_features(picked)


class ServiceMarginRanker(SurrogateRanker):
    """Order candidates by how much room each has against its own SLOs.

    Implements heteropilot's `SurrogateRanker`, so a caller can pass this or
    `BinnedRooflineRanker` to the same code. `order()` returns a permutation
    and nothing else -- it never constructs `PredictedMetrics`.
    """

    def __init__(
        self,
        features_of: Mapping[str, RankFeatures] | Callable[[CandidateConfig], RankFeatures],
        *,
        quota: DiversityQuota | None = None,
        k_hint: int | None = None,
    ) -> None:
        self._features_of = features_of
        self.quota = quota
        self.k_hint = k_hint

    def features(self, candidate: CandidateConfig) -> RankFeatures | None:
        if callable(self._features_of):
            return self._features_of(candidate)
        return self._features_of.get(candidate.id)

    def order(
        self,
        candidates: list[CandidateConfig],
        spec: ServiceSpec,
        islands: dict[str, ExecutionIsland],
        profiles: dict[str, AcceleratorProfile],
        *,
        gpu_memory_utilization: float = GPU_MEMORY_UTILIZATION,
    ) -> list[CandidateConfig]:
        by_id = {c.id: c for c in candidates}
        known: list[RankFeatures] = []
        unknown: list[CandidateConfig] = []
        for candidate in candidates:
            features = self.features(candidate)
            if features is None:
                # No features: ordered last, in id order, and never dropped.
                # The ABC contract is same length, same members.
                unknown.append(candidate)
            else:
                known.append(features)

        ordered = rank_features(known)
        if self.quota is not None and self.k_hint is not None:
            head = apply_quota(ordered, self.k_hint, self.quota)
            tail = [f for f in ordered if f not in head]
            ordered = head + tail

        out = [by_id[f.candidate_id] for f in ordered if f.candidate_id in by_id]
        out.extend(sorted(unknown, key=lambda c: c.id))
        return out


def explain(features: RankFeatures) -> str:
    """One line, for a render block or a test failure."""
    cost = "unpriced" if features.cost_per_hour is None else f"{features.cost_per_hour:.4g}/h"
    return (
        f"{features.candidate_id}: risk {features.risk_proxy:.3f} "
        f"(ttft {features.ttft_ratio:.3f}, tpot {features.tpot_ratio:.3f}, "
        f"goodput {features.goodput_ratio:.3f}), {cost}, "
        f"structure {features.structure_key}"
    )


@dataclass
class RankingReport:
    """What a batch was chosen on, for provenance."""

    considered: int = 0
    comfortable: int = 0
    reserved_for_diversity: int = 0
    structures: list[tuple] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "considered": self.considered,
            "comfortable": self.comfortable,
            "reserved_for_diversity": self.reserved_for_diversity,
            "structures": [list(s) for s in self.structures],
        }
