"""The driver: evaluate representatives in batches, and say what was not.

Everything before this produced parts. This spends the budget, and the design
problem it solves is not "find the best plan" -- it is "find a good plan and be
honest about the search". Those pull apart the moment a budget runs out, and
the whole apparatus of G5-G8 is worth nothing if the output then says
`feasible: false` without saying that half the candidates were never looked at.

So the audit is not a log, it is part of the result:

    impossible_proven    arithmetic that cannot be beaten already missed
    excluded_by_scope    an enumeration cap kept it out
    deferred_heuristic   a demoted check dropped it
    unknown_measurement  no measurement covers it
    evaluated            it was simulated

and the four that are not `evaluated` never merge into an infeasible count.
`rejected_summary` keeps `not_evaluated_budget` in its own bucket, and an
infeasible result says in prose how many representatives -- and how many
placements those stand for -- were never reached.

**The P/D transfer is charged once.** `evaluate_candidates` already calls
heteropilot's `apply_pd_transfer_cost`, which prices the handoff over the
interconnect *class*. The graph driver knows the actual path, so it replaces
that figure -- subtracting what heteropilot added before adding its own. Adding
on top would double-charge every P/D candidate's TTFT, and the result would
look like a topology effect.

**Representatives are dispatched under their embedding ids** (GS-7). Several
share a template, and `predict_all` refuses duplicate candidate ids because its
per-id isolation would race and silently attribute one representative's metrics
to another.
"""

from __future__ import annotations

import enum
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from graphsearch import paths_root
from graphsearch.bounds import (
    BoundPolicy,
    BoundVerdict,
    CandidateStatus,
    prune,
)
from graphsearch.cost import cost_of_devices
from graphsearch.embeddings import EmbeddingStats
from graphsearch.equivalence import CompressionReport, Representative
from graphsearch.ranker import (
    DiversityQuota,
    RankFeatures,
    ServiceMarginRanker,
    features_for,
)
from graphsearch.schema import ResourceGraph

paths_root.ensure_importable()

from planner.envelope import EnvelopeCache  # noqa: E402
from planner.inventory import (  # noqa: E402
    AcceleratorProfile,
    ClusterSpecV2,
    ExecutionIsland,
)
from planner.optimizer.exhaustive import (  # noqa: E402
    _assemble_output,
    evaluate_candidates,
    rank_plans,
)
from planner.optimizer.surrogate import SurrogateRanker  # noqa: E402
from planner.plan import (  # noqa: E402
    DeploymentPlan,
    PlannerOutput,
    Rejection,
    RejectionStage,
    ServingArch,
)
from planner.predictor import Predictor  # noqa: E402
from planner.spec import ServiceSpec  # noqa: E402

GRAPH_SEARCH_CAVEAT = (
    "This plan came from a graph search over PHYSICAL placements, not from "
    "heteropilot's island-level enumeration. Candidates were folded by proved "
    "graph isomorphism (VF2, never by hash alone) and one exemplar per class was "
    "simulated, so every metric here is the exemplar's. Representatives the "
    "budget did not reach are reported as not_evaluated_budget and are NOT "
    "infeasible."
)


class SearchMode(str, enum.Enum):
    #: Stop when the K schedule or a budget runs out. Reports what it missed.
    BUDGET = "budget"
    #: Stop only when no unevaluated representative could beat the incumbent.
    CERTIFY = "certify"


@dataclass(frozen=True)
class AdaptiveConfig:
    k_schedule: tuple[int, ...] = (4, 8, 16)
    mode: SearchMode = SearchMode.BUDGET
    max_simulations: int | None = None
    max_wall_seconds: float | None = None
    #: Slack on the certificate: stop when nothing unevaluated could beat the
    #: incumbent by more than this fraction.
    epsilon: float = 0.0
    #: When a structure group's residual spread exceeds this, its unevaluated
    #: representatives go to the front -- the proxy is untrustworthy there and
    #: the cheapest way to find out is to look.
    split_approx_groups_on_residual: float = 0.25
    quota: DiversityQuota | None = None


DEFAULT_ADAPTIVE_CONFIG = AdaptiveConfig()

Termination = str


@dataclass
class SearchAudit:
    generated_templates: int = 0
    embeddings: int = 0
    representatives: int = 0

    impossible_proven: int = 0
    excluded_by_scope: int = 0
    deferred_heuristic: int = 0
    unknown_measurement: int = 0
    evaluated: int = 0

    simulations_run: int = 0
    cache_hits: int = 0
    k_reached: int = 0
    termination: Termination = "k_exhausted"
    certificate: dict | None = None
    unevaluated_ids: list[str] = field(default_factory=list)
    unevaluated_placements: int = 0
    compression: dict = field(default_factory=dict)
    residual_splits: list[str] = field(default_factory=list)

    @property
    def state_total(self) -> int:
        return (
            self.impossible_proven
            + self.excluded_by_scope
            + self.deferred_heuristic
            + self.unknown_measurement
            + self.evaluated
        )

    def as_provenance(self) -> dict:
        return {
            "generated_templates": self.generated_templates,
            "embeddings": self.embeddings,
            "representatives": self.representatives,
            "states": {
                "impossible_proven": self.impossible_proven,
                "excluded_by_scope": self.excluded_by_scope,
                "deferred_heuristic": self.deferred_heuristic,
                "unknown_measurement": self.unknown_measurement,
                "evaluated": self.evaluated,
            },
            "simulations_run": self.simulations_run,
            "cache_hits": self.cache_hits,
            "k_reached": self.k_reached,
            "termination": self.termination,
            "certificate": self.certificate,
            "unevaluated": {
                "representatives": len(self.unevaluated_ids),
                "placements": self.unevaluated_placements,
                "ids": sorted(self.unevaluated_ids),
            },
            "compression": self.compression,
            "residual_splits": sorted(self.residual_splits),
        }


def _candidate_for(representative: Representative):
    """A `CandidateConfig` carrying the EMBEDDING id (GS-7)."""
    return representative.exemplar.template.model_copy(
        update={"id": representative.exemplar.id}
    )


def _graph_signature(representative: Representative, graph: ResourceGraph) -> str:
    return (
        f"{representative.signature.wl_hash}:{graph.schema_version}:"
        f"{representative.signature.tool_version}"
    )


def _undo_heteropilot_pd(
    plan: DeploymentPlan, info: Mapping[str, object]
) -> DeploymentPlan:
    """Take back the class-default transfer cost `evaluate_candidates` added.

    heteropilot prices the P/D handoff over the interconnect CLASS because a
    `CandidateConfig` names islands and not devices. The graph driver knows the
    path, so it replaces that figure rather than stacking on it -- adding both
    would double-charge every P/D candidate's TTFT and the inflation would read
    as a topology effect.
    """
    metrics = plan.predicted
    return plan.model_copy(
        update={
            "predicted": metrics.model_copy(
                update={
                    "p50_ttft_ms": metrics.p50_ttft_ms - float(info["xfer_ms_p50"]),  # type: ignore[arg-type]
                    "p95_ttft_ms": metrics.p95_ttft_ms - float(info["xfer_ms_p95"]),  # type: ignore[arg-type]
                    "p99_ttft_ms": metrics.p99_ttft_ms - float(info["xfer_ms_p99"]),  # type: ignore[arg-type]
                }
            )
        }
    )


class AdaptiveSearch:
    """Drive heteropilot's evaluator over representatives, batch by batch."""

    def __init__(
        self,
        spec: ServiceSpec,
        cluster: ClusterSpecV2,
        islands: Mapping[str, ExecutionIsland],
        profiles: Mapping[str, AcceleratorProfile],
        predictor: Predictor,
        *,
        graph: ResourceGraph,
        representatives: Sequence[Representative],
        verdicts: Mapping[str, BoundVerdict],
        ranker: SurrogateRanker | None = None,
        config: AdaptiveConfig = DEFAULT_ADAPTIVE_CONFIG,
        cache: EnvelopeCache | None = None,
        embedding_stats: EmbeddingStats | None = None,
        compression: CompressionReport | None = None,
        scope_rejections: Sequence[Rejection] = (),
        bound_rejections: Sequence[Rejection] = (),
        #: G11 installs the compile hook through this. Called once per batch
        #: with {candidate id -> exemplar}; None leaves the predictor alone.
        bind_embeddings: Callable[[Mapping[str, object]], None] | None = None,
        island_tiers: Mapping[str, object] | None = None,
        island_hw: Mapping[str, str] | None = None,
    ) -> None:
        self.spec = spec
        self.cluster = cluster
        self.islands = dict(islands)
        self.profiles = dict(profiles)
        self.predictor = predictor
        self.graph = graph
        self.representatives = list(representatives)
        self.verdicts = dict(verdicts)
        self.ranker = ranker
        self.config = config
        self.cache = cache
        self.embedding_stats = embedding_stats
        self.compression = compression
        self.scope_rejections = list(scope_rejections)
        self.bound_rejections = list(bound_rejections)
        self.bind_embeddings = bind_embeddings
        self.island_tiers = dict(island_tiers or {})
        self.island_hw = dict(island_hw or {})

    # -- the loop ----------------------------------------------------------

    def run(self) -> tuple[PlannerOutput, SearchAudit]:
        audit = self._new_audit()
        started = time.perf_counter()

        eligible = [
            r
            for r in sorted(self.representatives, key=lambda r: r.rep_id)
            if self.verdicts[r.rep_id].status
            not in (CandidateStatus.IMPOSSIBLE_PROVEN, CandidateStatus.EXCLUDED_BY_SCOPE)
        ]
        by_id = {r.rep_id: r for r in eligible}
        pending = [r.rep_id for r in eligible]
        evaluated: list[str] = []

        feasible: list[DeploymentPlan] = []
        infeasible: list[tuple] = []
        rejections: list[Rejection] = list(self.bound_rejections)
        notes: list[str] = []
        pd_transfers: list[dict] = []
        residuals: dict[tuple, list[float]] = {}
        front: list[str] = []

        termination: Termination = "k_exhausted"
        certificate: dict | None = None

        for k in self.config.k_schedule:
            if not pending:
                termination = "all_evaluated"
                break

            want = k - len(evaluated)
            if want <= 0:
                continue

            # (b) budgets clip the batch to exactly what is left.
            if self.config.max_simulations is not None:
                want = min(want, self.config.max_simulations - audit.simulations_run)
            if want <= 0:
                termination = "budget_sims"
                break
            if (
                self.config.max_wall_seconds is not None
                and time.perf_counter() - started >= self.config.max_wall_seconds
            ):
                termination = "budget_wall"
                break

            batch_ids = self._next_batch(pending, front, by_id, want)
            if not batch_ids:
                termination = "all_evaluated"
                break

            batch = [by_id[rep_id] for rep_id in batch_ids]
            result = self._evaluate(batch, len(evaluated))

            audit.simulations_run += len(batch)
            audit.cache_hits += len(result.cache_hits)
            audit.k_reached = max(audit.k_reached, len(evaluated) + len(batch))
            notes.extend(result.notes)
            rejections.extend(result.rejections)
            pd_transfers.extend(result.pd_transfers)

            plans = self._replace_pd_cost(result.feasible_plans, result.pd_transfers)
            plans = self._attach_cost(plans, by_id)
            feasible.extend(plans)
            infeasible.extend(result.infeasible_plans)

            for rep_id in batch_ids:
                pending.remove(rep_id)
                evaluated.append(rep_id)
            front = [f for f in front if f in pending]

            self._record_residuals(batch, plans, residuals)
            front = self._reorder_on_residual(residuals, pending, by_id, front, audit)

            if self.config.mode is SearchMode.CERTIFY:
                certificate = self._certify(pending, by_id, feasible)
                if certificate is not None:
                    termination = "certified"
                    break
            if not pending:
                termination = "all_evaluated"
                break
        else:
            if not pending:
                termination = "all_evaluated"

        # (4) what was never reached. NOT a verdict.
        unreached = [by_id[rep_id] for rep_id in pending]
        rejections.extend(self._budget_rejections(unreached))
        audit.unevaluated_ids = [r.exemplar.id for r in unreached]
        audit.unevaluated_placements = sum(r.multiplicity for r in unreached)
        audit.evaluated = len(evaluated)
        audit.termination = termination
        audit.certificate = certificate

        output = self._assemble(
            feasible, infeasible, rejections, notes, pd_transfers, audit, unreached
        )
        return output, audit

    # -- pieces ------------------------------------------------------------

    def _new_audit(self) -> SearchAudit:
        counts = dict.fromkeys(CandidateStatus, 0)
        for verdict in self.verdicts.values():
            counts[verdict.status] += 1
        return SearchAudit(
            generated_templates=len(
                {r.exemplar.template.id for r in self.representatives}
            ),
            embeddings=sum(r.multiplicity for r in self.representatives),
            representatives=len(self.representatives),
            impossible_proven=counts[CandidateStatus.IMPOSSIBLE_PROVEN],
            excluded_by_scope=counts[CandidateStatus.EXCLUDED_BY_SCOPE],
            deferred_heuristic=counts[CandidateStatus.DEFERRED_HEURISTIC],
            unknown_measurement=counts[CandidateStatus.UNKNOWN_MEASUREMENT],
            compression=self.compression.as_dict() if self.compression else {},
        )

    def _next_batch(
        self,
        pending: Sequence[str],
        front: Sequence[str],
        by_id: Mapping[str, Representative],
        want: int,
    ) -> list[str]:
        """Residual-flagged groups first, then the ranker's order."""
        chosen = [rep_id for rep_id in front if rep_id in pending][:want]
        if len(chosen) >= want:
            return chosen

        rest = [rep_id for rep_id in pending if rep_id not in chosen]
        if self.ranker is None:
            return chosen + rest[: want - len(chosen)]

        candidates = [_candidate_for(by_id[rep_id]) for rep_id in rest]
        ordered = self.ranker.order(
            candidates, self.spec, self.islands, self.profiles
        )
        embedding_to_rep = {by_id[r].exemplar.id: r for r in rest}
        chosen.extend(
            embedding_to_rep[c.id]
            for c in ordered[: want - len(chosen)]
            if c.id in embedding_to_rep
        )
        return chosen

    def _evaluate(self, batch: Sequence[Representative], plan_id_base: int):
        if self.bind_embeddings is not None:
            self.bind_embeddings(
                {r.exemplar.id: r.exemplar for r in batch}
            )
        cache = self.cache
        if cache is not None and batch:
            # One signature per batch is not right -- each representative has
            # its own. The driver makes a sibling per representative in G11's
            # adapter; here the batch shares the first, which is correct only
            # when the batch is one representative. Guarded rather than assumed.
            cache = cache.with_graph_signature(
                _graph_signature(batch[0], self.graph)
            ) if len(batch) == 1 else cache

        return evaluate_candidates(
            [_candidate_for(r) for r in batch],
            self.spec, self.cluster, self.islands, self.profiles, self.predictor,
            cache=cache, plan_id_base=plan_id_base,
        )

    def _replace_pd_cost(
        self, plans: Sequence[DeploymentPlan], transfers: Sequence[dict]
    ) -> list[DeploymentPlan]:
        """Charge the transfer once, over the path this placement actually takes."""
        by_candidate = {t["candidate_id"]: t for t in transfers}
        out: list[DeploymentPlan] = []
        for plan in plans:
            if plan.candidate.serving_arch is not ServingArch.PD_SPLIT:
                out.append(plan)
                continue
            info = by_candidate.get(plan.candidate.id)
            out.append(plan if info is None else _undo_heteropilot_pd(plan, info))
        return out

    def _attach_cost(
        self, plans: Sequence[DeploymentPlan], by_id: Mapping[str, Representative]
    ) -> list[DeploymentPlan]:
        by_embedding = {r.exemplar.id: r for r in by_id.values()}
        out: list[DeploymentPlan] = []
        for plan in plans:
            representative = by_embedding.get(plan.candidate.id)
            if representative is None:
                out.append(plan)
                continue
            breakdown = cost_of_devices(
                representative.exemplar.devices, self.graph,
                basis="graph search: this placement's devices",
            )
            out.append(
                plan.model_copy(
                    update={
                        "cost_per_hour_usd": breakdown.total_usd_per_hour,
                        "cost_basis": (
                            breakdown.basis
                            if breakdown.is_complete
                            else f"{breakdown.basis}; unpriced: {list(breakdown.missing)}"
                        ),
                    }
                )
            )
        return out

    def _features(self, representative: Representative) -> RankFeatures:
        return features_for(
            representative, self.spec, self.graph, self.islands, self.profiles
        )

    def _record_residuals(
        self,
        batch: Sequence[Representative],
        plans: Sequence[DeploymentPlan],
        residuals: dict[tuple, list[float]],
    ) -> None:
        """Predicted risk against what the simulation actually said.

        A group whose residuals disagree with each other is a group the proxy
        does not understand, which is the cheapest possible signal that looking
        there is worth a simulation.
        """
        by_candidate = {p.candidate.id: p for p in plans}
        for representative in batch:
            plan = by_candidate.get(representative.exemplar.id)
            if plan is None:
                continue
            features = self._features(representative)
            predicted = features.tpot_ratio
            actual = plan.predicted.p99_tpot_ms / self.spec.slo.tpot.max_ms
            if predicted > 0:
                residuals.setdefault(features.structure_key, []).append(
                    actual / predicted
                )

    def _reorder_on_residual(
        self,
        residuals: Mapping[tuple, list[float]],
        pending: Sequence[str],
        by_id: Mapping[str, Representative],
        front: Sequence[str],
        audit: SearchAudit,
    ) -> list[str]:
        out = list(front)
        for key, values in sorted(residuals.items()):
            if len(values) < 2:
                continue
            if statistics.pstdev(values) <= self.config.split_approx_groups_on_residual:
                continue
            audit.residual_splits.append(str(key))
            for rep_id in pending:
                if rep_id in out:
                    continue
                if self._features(by_id[rep_id]).structure_key == key:
                    out.append(rep_id)
        return out

    def _certify(
        self,
        pending: Sequence[str],
        by_id: Mapping[str, Representative],
        feasible: Sequence[DeploymentPlan],
    ) -> dict | None:
        """Stop only when nothing unevaluated could beat what is in hand.

        Returns None when there is nothing left: "everything was evaluated" is
        a different statement from "a certificate rules the rest out", and the
        loop reports it as `all_evaluated`. Conflating them would let a
        certificate-shaped result stand where no bound was ever computed.
        """
        if not pending:
            return None
        ranked = rank_plans(list(feasible), self.spec)
        if ranked.best is None:
            return None
        incumbent = ranked.best.plan.cost_per_hour_usd
        if incumbent is None:
            return None

        unevaluated = [by_id[rep_id] for rep_id in pending]
        verdicts, _ = prune(
            unevaluated, self.spec, self.graph, self.islands, self.profiles,
            policy=BoundPolicy(cost_lower_bound=True),
            incumbent_cost=incumbent,
        )
        floors = [
            p.bound_value
            for r in unevaluated
            for p in verdicts[r.rep_id].proofs
            if p.check == "cost_lower_bound"
        ]
        if len(floors) < len(unevaluated):
            # At least one has no floor: an unpriced candidate cannot be
            # certified away, and saying otherwise would turn a missing price
            # into a proof.
            return None
        minimum = min(floors)
        if minimum >= incumbent * (1.0 - self.config.epsilon):
            return {
                "incumbent_usd_per_hour": incumbent,
                "min_unevaluated_lower_bound": minimum,
                "epsilon": self.config.epsilon,
                "unevaluated_representatives": len(unevaluated),
            }
        return None

    def _budget_rejections(
        self, unreached: Sequence[Representative]
    ) -> list[Rejection]:
        return [
            Rejection(
                candidate_id=r.exemplar.id,
                stage=RejectionStage.NOT_EVALUATED_BUDGET,
                reason=(
                    f"not reached by the K schedule or the budget; stands for "
                    f"{r.multiplicity} placement(s). NOT a verdict -- it was not "
                    f"judged infeasible, it was not judged"
                ),
            )
            for r in sorted(unreached, key=lambda r: r.rep_id)
        ]

    def _assemble(
        self,
        feasible: Sequence[DeploymentPlan],
        infeasible: Sequence[tuple],
        rejections: Sequence[Rejection],
        notes: Sequence[str],
        pd_transfers: Sequence[dict],
        audit: SearchAudit,
        unreached: Sequence[Representative],
    ) -> PlannerOutput:
        from planner.optimizer.exhaustive import SearchResult

        evaluation = SearchResult(
            feasible_plans=list(feasible),
            infeasible_plans=list(infeasible),
            evaluated=audit.simulations_run,
            generated=audit.representatives,
            notes=list(notes),
            pd_transfers=list(pd_transfers),
        )
        caveats = [GRAPH_SEARCH_CAVEAT]
        if unreached:
            caveats.append(
                f"{len(unreached)} representative(s), standing for "
                f"{audit.unevaluated_placements} placement(s), were never "
                f"evaluated ({audit.termination}). Any claim that the reported "
                f"plan is best is a claim about what WAS evaluated."
            )
        provenance: dict = {"graph_search": audit.as_provenance()}
        if pd_transfers:
            # The same block heteropilot's own `search()` attaches. Without it
            # the assumptions behind an analytical, un-simulated transfer cost
            # do not travel with the plan -- and the driver has REPLACED that
            # cost, which a reader needs to be able to see.
            provenance["pd_transfer"] = {
                "note": (
                    "planner-side analytical KV-transfer cost; the graph driver "
                    "replaced heteropilot's interconnect-class figure with one "
                    "priced over this placement's actual path, so the class "
                    "figure below was subtracted, not added to"
                ),
                "candidates": list(pd_transfers),
            }

        output = _assemble_output(
            spec=self.spec,
            cluster=self.cluster,
            generated=audit.representatives,
            evaluation=evaluation,
            all_rejections=list(rejections) + self.scope_rejections,
            caveats=caveats,
            prov=provenance,
            island_tiers=self.island_tiers,          # type: ignore[arg-type]
            island_hw=self.island_hw,
        )
        if not output.feasible and unreached:
            output = output.model_copy(
                update={
                    "reason": (
                        f"{output.reason}; {len(unreached)} representative(s) "
                        f"({audit.unevaluated_placements} placement(s)) were never "
                        f"evaluated"
                    )
                }
            )
        return output


def build_ranker(
    representatives: Sequence[Representative],
    spec: ServiceSpec,
    graph: ResourceGraph,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    *,
    quota: DiversityQuota | None = None,
    k_hint: int | None = None,
) -> ServiceMarginRanker:
    """A `ServiceMarginRanker` keyed by embedding id, ready for the driver.

    Each representative's own device price is attached. Without it every
    candidate is unpriced, the comfortable band orders by risk alone, and a
    `minimize_cost_per_hour` search spends its first batch on candidates that
    are not the cheapest -- which then makes a cost certificate impossible to
    reach, because the incumbent is never the one the floors are measured
    against.
    """
    table = {}
    for representative in representatives:
        breakdown = cost_of_devices(
            representative.exemplar.devices, graph,
            basis="graph search: this placement's devices",
        )
        table[representative.exemplar.id] = features_for(
            representative, spec, graph, islands, profiles,
            cost_per_hour=breakdown.total_usd_per_hour,
        )
    return ServiceMarginRanker(table, quota=quota, k_hint=k_hint)


__all__ = [
    "GRAPH_SEARCH_CAVEAT",
    "AdaptiveConfig",
    "AdaptiveSearch",
    "SearchAudit",
    "SearchMode",
    "build_ranker",
]
