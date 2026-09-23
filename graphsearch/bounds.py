"""Provable elimination, and five states that are not all refusals.

The rule this module lives under is heteropilot's, and it is absolute: **a
pruning stage must be a relaxation of the feasibility test, never an extra
condition.** A check may reject only when the most optimistic arithmetic
available already misses a constraint the feasibility test actually declares.
The planner has been here before -- an early throughput bound rejected
under-provisioned candidates although §5.6 declared no throughput constraint,
and the oracle-agreement test caught it as a pruned-versus-oracle disagreement.
It was removed, and the comment left in `planner/candidate_generator.py` says
restoring it needs feasibility to declare one first. H1 did that, which is why
`throughput_capacity` can exist here and why it does not run at all until a spec
sets `slo.min_goodput_rps`.

`test_each_bound_is_a_relaxation` is the guard: with every check on and with
each one off, the best feasible candidate must be the same one with the same
objective value.

**Five states, and only one of them is a verdict about the hardware.**

    impossible_proven    arithmetic that cannot be beaten already misses
    excluded_by_scope    an enumeration cap kept it out; never judged
    deferred_heuristic   a demoted check dropped it; not sound, may be wrong
    unknown_measurement  no measurement covers it; we do not know
    evaluated            it was simulated

Folding any of the middle three into "infeasible" reports a budget, or an
absence of measurement, as a property of the cluster. That is the failure
`OUTSIDE_CALIBRATION_DOMAIN` already exists to avoid in heteropilot, and the
same discipline applies to a cap and to a demoted check.

Every rejection carries a `BoundProof` with the inputs it used, so the number
can be recomputed by a reader rather than believed.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from graphsearch import paths_root
from graphsearch.contention import allreduces_per_token
from graphsearch.cost import cost_lower_bound as cost_floor
from graphsearch.demand import FlowKind
from graphsearch.embeddings import EmbeddedCandidate, EmbeddingStats
from graphsearch.equivalence import Representative
from graphsearch.paths import DEFAULT_POLICY, PathPolicy, cut_capacity
from graphsearch.schema import ResourceGraph

paths_root.ensure_importable()

from planner.inventory import (  # noqa: E402
    AcceleratorProfile,
    ExecutionIsland,
    compatibility,
)
from planner.plan import Rejection, RejectionStage, Role, ServingArch  # noqa: E402
from planner.spec import Objective, ServiceSpec  # noqa: E402
from planner.util import memory as memutil  # noqa: E402

CheckName = Literal[
    "compat", "memory", "comm_latency", "throughput_capacity", "cost_lower_bound"
]

ALL_CHECKS: tuple[CheckName, ...] = (
    "compat",
    "memory",
    "comm_latency",
    "throughput_capacity",
    "cost_lower_bound",
)


class CandidateStatus(str, enum.Enum):
    IMPOSSIBLE_PROVEN = "impossible_proven"
    EXCLUDED_BY_SCOPE = "excluded_by_scope"
    DEFERRED_HEURISTIC = "deferred_heuristic"
    UNKNOWN_MEASUREMENT = "unknown_measurement"
    EVALUATED = "evaluated"


@dataclass(frozen=True)
class BoundProof:
    """Enough to recompute the number, not just to believe it."""

    check: CheckName
    bound_value: float
    threshold: float
    unit: str
    #: What was assumed away to make the bound optimistic. A reader deciding
    #: whether to trust a rejection needs to know what it did NOT charge for.
    relaxations: tuple[str, ...]
    inputs: Mapping[str, float]
    #: False when the check was demoted: it ran, it may be right, and it is not
    #: a proof. Nothing may be eliminated on an unsafe proof.
    safe: bool = True
    detail: str = ""

    @property
    def violated(self) -> bool:
        return self.bound_value > self.threshold


@dataclass
class BoundVerdict:
    status: CandidateStatus
    stage: RejectionStage | None = None
    proofs: list[BoundProof] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def eliminated(self) -> bool:
        return self.status is CandidateStatus.IMPOSSIBLE_PROVEN


@dataclass(frozen=True)
class BoundPolicy:
    compat: bool = True
    memory: bool = True
    comm_latency: bool = True
    throughput_capacity: bool = True
    #: Off by default: it needs an incumbent and a cost objective, and running
    #: it without one would be a no-op that still had to be explained.
    cost_lower_bound: bool = False
    #: Checks that RUN but may not eliminate. Their proofs carry `safe=False`
    #: and their candidates become `deferred_heuristic`, which the output keeps
    #: apart from a refusal.
    demoted: frozenset[str] = frozenset()

    def enabled(self, check: CheckName) -> bool:
        return bool(getattr(self, check))

    def is_demoted(self, check: CheckName) -> bool:
        return check in self.demoted


DEFAULT_BOUND_POLICY = BoundPolicy()

#: heteropilot's own memory derate (D10): the simulator's model applies no
#: utilization or activation reserve, so a fit computed against raw capacity
#: over-states usable KV by 71% on a 24 GB card.
GPU_MEMORY_UTILIZATION = 0.90


def _relax(*items: str) -> tuple[str, ...]:
    return tuple(items)


# --- 1. compat ------------------------------------------------------------

def _check_compat(
    representative: Representative,
    spec: ServiceSpec,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
) -> tuple[BoundProof | None, list[str]]:
    """Model/dtype support, and what the runtime says it can do.

    An UNSTATED capability is skipped and the skip is recorded. "No profile
    says" is not "the profile says no", and rejecting a candidate for something
    nobody wrote down would make an unfilled field into a hardware verdict.
    """
    notes: list[str] = []
    template = representative.exemplar.template
    for assignment in template.assignments:
        island = islands[assignment.island_id]
        profile = profiles.get(island.accelerator_model)
        if profile is None:
            notes.append(
                f"island {island.id}: no profile for {island.accelerator_model!r}; "
                f"compatibility not checked"
            )
            continue

        if not compatibility(spec.model, spec.service.dtype, profile):
            return (
                BoundProof(
                    check="compat", bound_value=1.0, threshold=0.0, unit="boolean",
                    relaxations=_relax("profile's supported_models is taken as complete"),
                    inputs={},
                    detail=(
                        f"profile {profile.profile_id} declares no support for "
                        f"{spec.model} at {spec.service.dtype}"
                    ),
                ),
                notes,
            )

        caps = profile.runtime_capabilities
        if caps is None:
            notes.append(
                f"profile {profile.profile_id}: runtime_capabilities unstated: "
                f"not checked"
            )
            continue

        if assignment.tp_size > 1 and "all_reduce" not in caps.collectives:
            return (
                BoundProof(
                    check="compat", bound_value=1.0, threshold=0.0, unit="boolean",
                    relaxations=(), inputs={"tp": float(assignment.tp_size)},
                    detail=(
                        f"profile {profile.profile_id} states collectives "
                        f"{sorted(caps.collectives)}, which has no all_reduce, and "
                        f"the assignment is tp={assignment.tp_size}"
                    ),
                ),
                notes,
            )
        if caps.max_world_size is not None and assignment.tp_size > caps.max_world_size:
            return (
                BoundProof(
                    check="compat", bound_value=float(assignment.tp_size),
                    threshold=float(caps.max_world_size), unit="ranks",
                    relaxations=(), inputs={"tp": float(assignment.tp_size)},
                    detail=f"profile {profile.profile_id} states max_world_size",
                ),
                notes,
            )
        if template.serving_arch is ServingArch.PD_SPLIT and caps.kv_transfer is not True:
            return (
                BoundProof(
                    check="compat", bound_value=1.0, threshold=0.0, unit="boolean",
                    relaxations=(), inputs={},
                    detail=(
                        f"profile {profile.profile_id} states kv_transfer="
                        f"{caps.kv_transfer!r}, and this is a pd_split candidate"
                    ),
                ),
                notes,
            )
    return None, notes


# --- 2. memory ------------------------------------------------------------

def _median_len(spec: ServiceSpec, role: Role) -> int:
    if role is Role.PREFILL:
        return spec.traffic.input_tokens.p50
    return spec.traffic.input_tokens.p50 + spec.traffic.output_tokens.p50


def _check_memory(
    representative: Representative,
    spec: ServiceSpec,
    islands: Mapping[str, ExecutionIsland],
) -> BoundProof | None:
    """Weights plus one median request's KV, against derated device memory."""
    template = representative.exemplar.template
    for assignment in template.assignments:
        island = islands[assignment.island_id]
        need = _median_len(spec, assignment.role)
        fits, report = memutil.feasible(
            spec.model,
            tp_size=assignment.tp_size,
            device_memory_gb=island.total_memory_gb / island.size,
            min_kv_tokens=need,
            dtype=spec.service.dtype,
            kv_cache_dtype=spec.service.kv_cache_dtype,
            gpu_memory_utilization=GPU_MEMORY_UTILIZATION,
        )
        if not fits:
            return BoundProof(
                check="memory",
                bound_value=float(need),
                threshold=float(report.kv_tokens),
                unit="tokens",
                relaxations=_relax(
                    "no offload",
                    "no quantization beyond the spec dtype",
                    "no activation recompute",
                    "one median-length request only",
                ),
                inputs={
                    "tp": float(assignment.tp_size),
                    "device_memory_gb": island.total_memory_gb / island.size,
                    "weight_bytes": float(report.weight_bytes),
                    "kv_bytes_per_token": float(report.kv_bytes_per_token),
                    "usable_kv_bytes": float(report.usable_kv_bytes),
                    "gpu_memory_utilization": GPU_MEMORY_UTILIZATION,
                },
                detail=(
                    f"island {island.id} at tp={assignment.tp_size} holds "
                    f"{report.kv_tokens} KV tokens, below the {need} one median "
                    f"request needs"
                ),
            )
    return None


# --- 3. comm_latency ------------------------------------------------------

_COMM_RELAXATIONS = _relax(
    "compute is free",
    "cut capacity = max-flow over nominal capacities minus external reservation",
    "no per-flow contention",
    "ring all-reduce, factor 2(tp-1)/tp",
    "measured effective bandwidths are NOT used: an average is not a ceiling",
    "the external reservation snapshot is taken as an upper bound on outside "
    "load: if something else is using less than it reserved, the real cut is "
    "wider and the bound only looser",
)


def _worst_cut(
    embedding: EmbeddedCandidate,
    graph: ResourceGraph,
    participants: Sequence[str],
    policy: PathPolicy,
) -> float:
    """Smallest capacity any one rank has to the rest of its group.

    A collective is limited by its narrowest member, so the bound takes the
    worst such cut. Splitting rank-versus-rest rather than every bipartition
    keeps this linear; a finer split could only make the cut smaller, which
    would make the bound tighter and therefore unsound in the direction that
    matters.
    """
    members = sorted(set(participants))
    if len(members) < 2:
        return float("inf")
    worst = float("inf")
    for member in members:
        rest = [m for m in members if m != member]
        cut = cut_capacity(graph, [member], rest, policy)
        worst = min(worst, cut.bytes_per_s)
    return worst


def _check_comm_latency(
    representative: Representative,
    spec: ServiceSpec,
    graph: ResourceGraph,
    policy: PathPolicy,
) -> BoundProof | None:
    embedding = representative.exemplar

    # --- TPOT: the all-reduce floor, assuming compute is free.
    #
    # The per-token multiplier comes from `contention.allreduces_per_token`, the
    # same function the graph-aware mock calls. They used to compute it apart
    # and disagreed -- the mock charged one all-reduce per token against this
    # `2 x layers` -- so the mock could return a TPOT below the floor that
    # admitted the candidate, and a mock faster than a bound makes an oracle
    # disagreement meaningless. The CAPACITY still differs by design: a bound
    # must divide by an optimistic cut, a predictor by its path.
    layers_term = allreduces_per_token(spec.model)
    worst_tpot_ms = 0.0
    worst_inputs: dict[str, float] = {}
    for flow in embedding.flows:
        if flow.kind is not FlowKind.TP_ALLREDUCE:
            continue
        cut = _worst_cut(embedding, graph, flow.participants, policy)
        latency_ns = min(
            (p.best.latency_ns for p in flow.allowed_paths if p.best is not None),
            default=0.0,
        )
        if cut <= 0:
            per_allreduce_ns = float("inf")
        else:
            per_allreduce_ns = latency_ns + flow.bytes_per_event / cut * 1e9
        floor_ms = layers_term * per_allreduce_ns / 1e6
        if floor_ms > worst_tpot_ms:
            worst_tpot_ms = floor_ms
            worst_inputs = {
                "bytes_per_allreduce": flow.bytes_per_event,
                "cut_bytes_per_s": cut,
                "path_latency_ns": latency_ns,
                "allreduces_per_token": float(layers_term),
            }

    if worst_tpot_ms > spec.slo.tpot.max_ms:
        return BoundProof(
            check="comm_latency", bound_value=worst_tpot_ms,
            threshold=spec.slo.tpot.max_ms, unit="ms",
            relaxations=_COMM_RELAXATIONS, inputs=worst_inputs,
            detail="TP all-reduce floor exceeds the TPOT budget with zero compute",
        )

    # --- TTFT: transfers that must finish before the first token.
    #
    # ONE request's path, not the sum over replicas. With dp=2 there are two
    # `prefill i -> decode i` flows, and they carry DIFFERENT requests in
    # parallel. Adding both to one request's TTFT makes the floor larger than
    # anything achievable, which stops it being a relaxation -- it would reject
    # a candidate the feasibility test would accept, the exact failure
    # heteropilot's removed throughput bound was.
    #
    # So the KV transfer is charged at its FASTEST replica pair (the most
    # optimistic route a request could take) and pipeline stages are summed,
    # because those are sequential within one request.
    ttft_ms = 0.0
    ttft_inputs: dict[str, float] = {}

    kv_times: list[float] = []
    for flow in embedding.flows:
        if flow.kind is not FlowKind.PD_KV_TRANSFER:
            continue
        cut = _worst_cut(embedding, graph, flow.participants, policy)
        latency_ns = min(
            (p.best.latency_ns for p in flow.allowed_paths if p.best is not None),
            default=0.0,
        )
        if cut <= 0:
            kv_times.append(float("inf"))
            continue
        kv_times.append((latency_ns + flow.bytes_per_event / cut * 1e9) / 1e6)
        ttft_inputs[f"{flow.flow_id}_bytes"] = flow.bytes_per_event
        ttft_inputs[f"{flow.flow_id}_cut_bytes_per_s"] = cut
    if kv_times:
        ttft_ms += min(kv_times)
        ttft_inputs["kv_transfer_ms_fastest_pair"] = min(kv_times)

    for flow in embedding.flows:
        if flow.kind is not FlowKind.PP_ACTIVATION:
            continue
        cut = _worst_cut(embedding, graph, flow.participants, policy)
        latency_ns = min(
            (p.best.latency_ns for p in flow.allowed_paths if p.best is not None),
            default=0.0,
        )
        if cut <= 0:
            ttft_ms = float("inf")
            ttft_inputs["pp_cut_bytes_per_s"] = 0.0
            break
        # Sequential: each stage boundary is crossed on the way to the first
        # token, and nothing here models overlapping them with compute.
        contribution = (latency_ns + flow.bytes_per_event / cut * 1e9) / 1e6
        ttft_ms += contribution
        ttft_inputs[f"{flow.flow_id}_bytes"] = flow.bytes_per_event
        ttft_inputs[f"{flow.flow_id}_cut_bytes_per_s"] = cut

    if ttft_ms > spec.slo.ttft.max_ms:
        return BoundProof(
            check="comm_latency", bound_value=ttft_ms,
            threshold=spec.slo.ttft.max_ms, unit="ms",
            relaxations=_COMM_RELAXATIONS + _relax(
                "the KV transfer is charged at its fastest replica pair: "
                "replicas carry different requests in parallel, so summing "
                "them would floor one request's TTFT above anything achievable",
                "pipeline stages are sequential and do not overlap compute",
                "sized at the p50 prompt",
            ),
            inputs=ttft_inputs,
            detail="pre-first-token transfers exceed the TTFT budget with zero compute",
        )
    return None


# --- 4. throughput_capacity ----------------------------------------------

def _check_throughput(
    representative: Representative,
    spec: ServiceSpec,
    graph: ResourceGraph,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    policy: PathPolicy,
) -> BoundProof | None:
    """An optimistic ceiling on tokens per second, against the declared floor.

    Runs ONLY when `slo.min_goodput_rps` is set. Until H1 added that field §5.6
    declared no throughput constraint, and a bound with no constraint to relax
    is an extra condition -- the exact mistake `candidate_generator` had to undo.
    """
    floor = spec.slo.min_goodput_rps
    if floor is None:
        return None

    template = representative.exemplar.template
    decode = [
        a
        for a in template.assignments
        if a.role in (Role.DECODE, Role.AGGREGATED)
    ]
    ub_tps = 0.0
    for assignment in decode:
        island = islands[assignment.island_id]
        profile = profiles.get(island.accelerator_model)
        if profile is None:
            return None                     # nothing to bound with; not a refusal
        report = memutil.evaluate(
            spec.model,
            tp_size=assignment.tp_size,
            device_memory_gb=island.total_memory_gb / island.size,
            dtype=spec.service.dtype,
            kv_cache_dtype=spec.service.kv_cache_dtype,
            gpu_memory_utilization=GPU_MEMORY_UTILIZATION,
        )
        median = max(1, _median_len(spec, assignment.role))
        # Optimistic on both factors: every KV slot is a live request, and a
        # decode step costs only the weight sweep.
        active = max(1.0, report.kv_tokens / median)
        step_s = report.weight_bytes / (profile.memory_bandwidth_gbps * 1e9)
        if step_s <= 0:
            return None
        ub_tps += (active / step_s) * assignment.dp_replicas

    ub_rps = ub_tps / max(1, spec.traffic.output_tokens.p50)

    # The wire can also cap it, and a cut the collective cannot beat is a
    # ceiling on requests just as a roofline is.
    ub_rps_cut = float("inf")
    for flow in representative.exemplar.flows:
        if flow.kind is not FlowKind.TP_ALLREDUCE:
            continue
        cut = _worst_cut(representative.exemplar, graph, flow.participants, policy)
        per_request = flow.bytes_per_request
        if per_request > 0 and cut > 0:
            ub_rps_cut = min(ub_rps_cut, cut / per_request)

    ceiling = min(ub_rps, ub_rps_cut)
    if ceiling < floor:
        return BoundProof(
            check="throughput_capacity", bound_value=floor, threshold=ceiling,
            unit="requests/s",
            relaxations=_relax(
                "every KV slot holds a live request",
                "a decode step costs only the weight sweep; knobs ignored",
                "KV streaming ignored",
                "cut capacity is nominal and uncontended",
            ),
            inputs={
                "ub_rps_memory": ub_rps,
                "ub_rps_cut": ub_rps_cut,
                "min_goodput_rps": floor,
            },
            detail=(
                f"an optimistic ceiling of {ceiling:.4g} req/s is below the declared "
                f"floor of {floor:g}"
            ),
        )
    return None


# --- 5. cost_lower_bound --------------------------------------------------

def _check_cost(
    representative: Representative,
    spec: ServiceSpec,
    islands: Mapping[str, ExecutionIsland],
    graph: ResourceGraph,
    incumbent_cost: float | None,
) -> BoundProof | None:
    if incumbent_cost is None:
        return None
    if spec.objective.primary is not Objective.MINIMIZE_COST_PER_HOUR:
        return None
    breakdown = cost_floor(representative.exemplar.template, islands, graph)
    if breakdown.total_usd_per_hour is None:
        return None                         # unpriced is not expensive
    if breakdown.total_usd_per_hour >= incumbent_cost:
        return BoundProof(
            check="cost_lower_bound",
            bound_value=breakdown.total_usd_per_hour,
            threshold=incumbent_cost,
            unit="usd/hour",
            relaxations=_relax(
                "the cheapest devices in each assigned island",
                "each touched host charged once, in full",
            ),
            inputs={
                "floor_usd_per_hour": breakdown.total_usd_per_hour,
                "incumbent_usd_per_hour": incumbent_cost,
            },
            detail=(
                f"the cheapest embedding of this template costs "
                f"{breakdown.total_usd_per_hour:.4g}/h, which cannot beat an "
                f"incumbent at {incumbent_cost:.4g}/h"
            ),
        )
    return None


# --- the stage each status charges to ------------------------------------

_CHECK_STAGE: dict[CheckName, RejectionStage] = {
    "compat": RejectionStage.BACKEND_INCOMPATIBLE,
    "memory": RejectionStage.MEMORY_INFEASIBLE,
    "comm_latency": RejectionStage.TOPOLOGY_INFEASIBLE,
    "throughput_capacity": RejectionStage.THROUGHPUT_UPPER_BOUND,
    "cost_lower_bound": RejectionStage.ANALYTICAL_LOWER_BOUND,
}


def prune(
    representatives: Sequence[Representative],
    spec: ServiceSpec,
    graph: ResourceGraph,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    stats: EmbeddingStats | None = None,
    *,
    policy: BoundPolicy = DEFAULT_BOUND_POLICY,
    incumbent_cost: float | None = None,
    path_policy: PathPolicy = DEFAULT_POLICY,
) -> tuple[dict[str, BoundVerdict], list[Rejection]]:
    """Judge each representative, and say what was never judged at all.

    Checking the exemplar judges every embedding it stands for: G6 merged them
    only after VF2 confirmed the candidate graphs isomorphic, so the arithmetic
    here reads the same numbers for all of them.
    """
    verdicts: dict[str, BoundVerdict] = {}
    rejections: list[Rejection] = []

    for representative in sorted(representatives, key=lambda r: r.rep_id):
        verdict = BoundVerdict(status=CandidateStatus.EVALUATED)
        for check in ALL_CHECKS:
            if not policy.enabled(check) and not policy.is_demoted(check):
                continue

            proof = _run(
                check, representative, spec, graph, islands, profiles,
                incumbent_cost, path_policy,
            )
            if proof is None:
                continue

            demoted = policy.is_demoted(check)
            proof = (
                proof
                if not demoted
                else BoundProof(
                    check=proof.check, bound_value=proof.bound_value,
                    threshold=proof.threshold, unit=proof.unit,
                    relaxations=proof.relaxations + _relax(
                        "check demoted by policy: this is not a proof"
                    ),
                    inputs=proof.inputs, safe=False, detail=proof.detail,
                )
            )
            verdict.proofs.append(proof)
            verdict.status = (
                CandidateStatus.DEFERRED_HEURISTIC
                if demoted
                else CandidateStatus.IMPOSSIBLE_PROVEN
            )
            verdict.stage = (
                RejectionStage.SURROGATE_PRUNED if demoted else _CHECK_STAGE[check]
            )
            rejections.append(
                Rejection(
                    candidate_id=representative.exemplar.id,
                    stage=verdict.stage,
                    reason=_reason(proof, representative),
                )
            )
            break

        notes = _compat_notes(representative, spec, islands, profiles, policy)
        verdict.notes.extend(notes)
        verdicts[representative.rep_id] = verdict

    rejections.extend(_scope_rejections(stats))
    return verdicts, rejections


def _run(
    check: CheckName,
    representative: Representative,
    spec: ServiceSpec,
    graph: ResourceGraph,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    incumbent_cost: float | None,
    path_policy: PathPolicy,
) -> BoundProof | None:
    if check == "compat":
        return _check_compat(representative, spec, islands, profiles)[0]
    if check == "memory":
        return _check_memory(representative, spec, islands)
    if check == "comm_latency":
        return _check_comm_latency(representative, spec, graph, path_policy)
    if check == "throughput_capacity":
        return _check_throughput(
            representative, spec, graph, islands, profiles, path_policy
        )
    if check == "cost_lower_bound":
        return _check_cost(representative, spec, islands, graph, incumbent_cost)
    raise ValueError(f"unknown check {check!r}")            # pragma: no cover


def _compat_notes(
    representative: Representative,
    spec: ServiceSpec,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    policy: BoundPolicy,
) -> list[str]:
    if not policy.enabled("compat") and not policy.is_demoted("compat"):
        return []
    return _check_compat(representative, spec, islands, profiles)[1]


def _reason(proof: BoundProof, representative: Representative) -> str:
    relaxed = "; ".join(proof.relaxations) or "none"
    return (
        f"{proof.check}: {proof.detail} "
        f"(bound {proof.bound_value:.6g} {proof.unit} against "
        f"{proof.threshold:.6g}; covers {representative.multiplicity} placement(s); "
        f"relaxations: {relaxed})"
    )


def _scope_rejections(stats: EmbeddingStats | None) -> list[Rejection]:
    """One per truncated template. NOT a verdict, and the reason says so."""
    if stats is None:
        return []
    return [
        Rejection(
            candidate_id=f"{template_id}/*",
            stage=RejectionStage.EXCLUDED_BY_SCOPE,
            reason=(
                f"{stats.truncated_by_policy} placement(s) of this template were "
                f"never enumerated: max_embeddings_per_template. NOT a verdict -- "
                f"they were not judged infeasible, they were not judged"
            ),
        )
        for template_id in sorted(set(stats.truncated_template_ids))
    ]


def surviving(
    representatives: Sequence[Representative], verdicts: Mapping[str, BoundVerdict]
) -> list[Representative]:
    """Those nothing proved impossible. A demoted check does not remove one."""
    return [
        r
        for r in representatives
        if not verdicts[r.rep_id].eliminated
    ]


def status_counts(verdicts: Mapping[str, BoundVerdict]) -> dict[str, int]:
    counts = {status.value: 0 for status in CandidateStatus}
    for verdict in verdicts.values():
        counts[verdict.status.value] += 1
    return counts
