"""Evaluate every placement, and measure what the search cost.

heteropilot keeps `planner/optimizer/exhaustive.py` and forbids deleting it,
because it is the only way to tell a pruning bug from a genuinely empty feasible
set. This is the same instrument one level up: the compression, the bounds and
the adaptive top-K each remove work, and each could remove the answer. Running
every embedding through the *same predictor* is what separates "the search was
fast" from "the search was fast and right".

Four numbers come out, and two of them must be zero:

    false_infeasible   proved impossible, but the oracle found it feasible
                       -> a BOUND IS WRONG. Not a tuning issue.
    mismerged_pairs    two placements in one representative that the oracle
                       judged differently -> AN EQUIVALENCE IS WRONG.

    feasible_recall    of the placements the oracle found feasible, how many
                       the search still reaches
    cost_regret        how much worse the search's best is than the oracle's

The first two are correctness; the last two are what the approach buys. A
failure in the first two is never fixed by relaxing the test -- the work order
says so, and the reason is that the test is the only thing standing between a
compression ratio and a wrong answer wearing one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from graphsearch import paths_root
from graphsearch.adaptive import AdaptiveConfig, AdaptiveSearch, build_ranker
from graphsearch.bounds import BoundPolicy, CandidateStatus, prune
from graphsearch.cost import cost_of_devices
from graphsearch.embeddings import (
    DEFAULT_EMBEDDING_POLICY,
    EmbeddedCandidate,
    EmbeddingPolicy,
    enumerate_embeddings,
)
from graphsearch.equivalence import (
    CompressionPolicy,
    Representative,
    compress,
)
from graphsearch.ranker import DEFAULT_RANKER_VARIANT
from graphsearch.schema import ResourceGraph

paths_root.ensure_importable()

from planner.inventory import (  # noqa: E402
    AcceleratorProfile,
    ClusterSpecV2,
    ExecutionIsland,
)
from planner.optimizer.exhaustive import evaluate_candidates  # noqa: E402
from planner.plan import CandidateConfig, DeploymentPlan, PlannerOutput  # noqa: E402
from planner.predictor import Predictor  # noqa: E402
from planner.spec import ServiceSpec  # noqa: E402


@dataclass
class OracleResult:
    """Every embedding, judged, with nothing folded or skipped."""

    embeddings: list[EmbeddedCandidate] = field(default_factory=list)
    #: embedding id -> feasible?
    feasible: dict[str, bool] = field(default_factory=dict)
    #: embedding id -> objective-relevant cost, None when unpriced.
    cost: dict[str, float | None] = field(default_factory=dict)
    #: embedding id -> the plan, for a caller that wants the metrics.
    plans: dict[str, DeploymentPlan] = field(default_factory=dict)
    simulations: int = 0

    @property
    def feasible_ids(self) -> set[str]:
        return {k for k, v in self.feasible.items() if v}

    def best_cost(self) -> float | None:
        priced = [
            self.cost[i]
            for i in self.feasible_ids
            if self.cost.get(i) is not None
        ]
        return min(priced) if priced else None      # type: ignore[type-var]


@dataclass
class ProposedResult:
    """What the real search produced, plus the bookkeeping to compare it."""

    output: PlannerOutput
    audit: object
    representatives: list[Representative] = field(default_factory=list)
    #: rep_id -> verdict, so `false_infeasible` can name what was proved.
    verdicts: Mapping[str, object] = field(default_factory=dict)
    #: embedding ids the search reached a FEASIBLE verdict for, expanded from
    #: the representatives it evaluated.
    feasible_ids: set[str] = field(default_factory=set)
    #: embedding ids eliminated by a bound, expanded the same way.
    eliminated_ids: set[str] = field(default_factory=set)
    best_cost: float | None = None
    simulations: int = 0


@dataclass
class OracleComparison:
    feasible_recall: float
    cost_regret: float | None
    false_infeasible: list[str] = field(default_factory=list)
    mismerged_pairs: list[tuple[str, str]] = field(default_factory=list)
    oracle_simulations: int = 0
    proposed_simulations: int = 0
    oracle_feasible: int = 0
    proposed_feasible: int = 0

    @property
    def correct(self) -> bool:
        """The two numbers that are not allowed to be non-zero."""
        return not self.false_infeasible and not self.mismerged_pairs

    def as_dict(self) -> dict:
        return {
            "feasible_recall": round(self.feasible_recall, 6),
            "cost_regret": (
                None if self.cost_regret is None else round(self.cost_regret, 6)
            ),
            "false_infeasible": sorted(self.false_infeasible),
            "mismerged_pairs": [list(p) for p in sorted(self.mismerged_pairs)],
            "oracle_simulations": self.oracle_simulations,
            "proposed_simulations": self.proposed_simulations,
            "oracle_feasible": self.oracle_feasible,
            "proposed_feasible": self.proposed_feasible,
            "correct": self.correct,
        }


def _candidate_for(embedding: EmbeddedCandidate) -> CandidateConfig:
    return embedding.template.model_copy(update={"id": embedding.id})


def bind_predictor(
    predictor: Predictor,
    embeddings: Sequence[EmbeddedCandidate],
    graph: ResourceGraph,
    *,
    spec: ServiceSpec | None = None,
    cluster: ClusterSpecV2 | None = None,
    islands: Mapping[str, ExecutionIsland] | None = None,
    profiles: Mapping[str, AcceleratorProfile] | None = None,
) -> bool:
    """Let the predictor see WHICH devices each candidate runs on.

    Without this the oracle judges templates, not placements: every embedding
    of one template gets the same metrics, so `mismerged_pairs` can never be
    non-zero and the correctness check is vacuous.

    Two things have to be bound, and binding only the first was a real defect.
    The compile hook tells the predictor the devices; the RESULT hook prices
    the P/D handoff over the path those devices force. Without the second,
    heteropilot's class-default transfer figure stands -- and that figure is
    the same for every placement of a template, so two placements differing
    only in which contended uplink they cross come back identical and the
    counterexample cannot appear. Returns True when the result hook is
    installed, which is the caller's signal to ask `evaluate_candidates` for
    `pd_transfer=False` so the class-default figure is ABSENT rather than
    subtracted (heteropilot D125).

    A predictor with neither hook is used as-is, and the caller is then
    measuring something weaker -- which is why this is a named function
    rather than a silent `getattr`.
    """
    have_context = None not in (spec, cluster, islands, profiles)
    if have_context and hasattr(predictor, "set_result_hook"):
        from graphsearch.adapter import bind as bind_adapter

        bind_adapter(
            predictor,                               # type: ignore[arg-type]
            {e.id: e for e in embeddings},
            graph,
            cluster=cluster,                         # type: ignore[arg-type]
            islands=islands,                         # type: ignore[arg-type]
            profiles=profiles,                       # type: ignore[arg-type]
            spec=spec,                               # type: ignore[arg-type]
        )
        return True

    binder = getattr(predictor, "bind_embeddings", None)
    if binder is None:
        return False
    graph_binder = getattr(predictor, "bind_graph", None)
    if graph_binder is not None:
        graph_binder(graph)
    binder({e.id: e for e in embeddings})
    return False


def run_oracle(
    spec: ServiceSpec,
    cluster: ClusterSpecV2,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    predictor: Predictor,
    *,
    graph: ResourceGraph,
    templates: Sequence[CandidateConfig],
    policy: EmbeddingPolicy = DEFAULT_EMBEDDING_POLICY,
) -> OracleResult:
    """Every embedding, simulated. No compression, no bounds, no top-K.

    Slow by design -- the same bargain `planner/optimizer/exhaustive.py`
    strikes. It is the only way to tell a pruning bug from an empty feasible
    set.
    """
    embeddings, _ = enumerate_embeddings(templates, islands, graph, spec, policy)
    result = OracleResult(embeddings=list(embeddings))
    if not embeddings:
        return result
    embedded_pd = bind_predictor(
        predictor, embeddings, graph,
        spec=spec, cluster=cluster, islands=islands, profiles=profiles,
    )

    evaluation = evaluate_candidates(
        [_candidate_for(e) for e in embeddings],
        spec, cluster, dict(islands), dict(profiles), predictor,
        pd_transfer=not embedded_pd,
    )
    result.simulations = len(embeddings)

    by_devices = {e.id: e.devices for e in embeddings}
    for plan in evaluation.feasible_plans:
        result.feasible[plan.candidate.id] = True
        result.plans[plan.candidate.id] = plan
        result.cost[plan.candidate.id] = cost_of_devices(
            by_devices[plan.candidate.id], graph
        ).total_usd_per_hour
    for plan, _ in evaluation.infeasible_plans:
        result.feasible[plan.candidate.id] = False
        result.plans[plan.candidate.id] = plan
        result.cost[plan.candidate.id] = cost_of_devices(
            by_devices[plan.candidate.id], graph
        ).total_usd_per_hour
    for embedding in embeddings:
        result.feasible.setdefault(embedding.id, False)
    return result


def binder_for(predictor, graph, spec, cluster, islands, profiles):
    """`AdaptiveSearch` wants a binder that returns nothing; `bind_predictor`
    returns whether it installed the result hook. `prices_pd_on_the_path`
    answers the same question up front, so the return value is dropped here
    rather than widening the callback's type."""

    def bind(batch: Mapping[str, object]) -> None:
        bind_predictor(
            predictor,
            [e for e in batch.values() if isinstance(e, EmbeddedCandidate)],
            graph, spec=spec, cluster=cluster, islands=islands, profiles=profiles,
        )

    return bind


def prices_pd_on_the_path(predictor: Predictor) -> bool:
    """Whether `bind_predictor` will install the graph-aware transfer cost.

    Public because the CLI needs the same answer the oracle does. They used to
    differ, and the difference was not visible: `plan` built an `AdaptiveSearch`
    with no binder at all, so its predictor never learned which devices a
    candidate ran on and it judged TEMPLATES while `compare` judged placements
    (GS-13).
    """
    return hasattr(predictor, "set_result_hook")


def run_proposed(
    spec: ServiceSpec,
    cluster: ClusterSpecV2,
    islands: Mapping[str, ExecutionIsland],
    profiles: Mapping[str, AcceleratorProfile],
    predictor: Predictor,
    *,
    graph: ResourceGraph,
    templates: Sequence[CandidateConfig],
    embedding_policy: EmbeddingPolicy = DEFAULT_EMBEDDING_POLICY,
    compression_policy: CompressionPolicy | None = None,
    bound_policy: BoundPolicy | None = None,
    config: AdaptiveConfig | None = None,
    ranker_variant: str = DEFAULT_RANKER_VARIANT,
) -> ProposedResult:
    """The real pipeline: enumerate, compress, bound, rank, evaluate."""
    embeddings, stats = enumerate_embeddings(
        templates, islands, graph, spec, embedding_policy
    )
    representatives, _, report = compress(
        embeddings, graph, compression_policy or CompressionPolicy()
    )
    verdicts, rejections = prune(
        representatives, spec, graph, islands, profiles, stats,
        policy=bound_policy or BoundPolicy(),
    )
    search = AdaptiveSearch(
        spec, cluster, islands, profiles, predictor,
        graph=graph, representatives=representatives, verdicts=verdicts,
        ranker=build_ranker(
            representatives, spec, graph, islands, profiles, variant=ranker_variant
        ),
        config=config or AdaptiveConfig(k_schedule=(len(representatives) or 1,)),
        embedding_stats=stats, compression=report, bound_rejections=rejections,
        bind_embeddings=binder_for(predictor, graph, spec, cluster, islands, profiles),
        embedded_pd_cost=prices_pd_on_the_path(predictor),
    )
    output, audit = search.run()

    feasible_ids: set[str] = set()
    eliminated_ids: set[str] = set()

    # From the AUDIT, not from `output.alternatives`: the latter is the Pareto
    # frontier with equivalents collapsed, so counting recall off it would
    # report every dominated-but-feasible placement as lost.
    feasible_exemplars = set(audit.feasible_ids)       # type: ignore[attr-defined]

    for representative in representatives:
        members = {e.id for e in representative.embeddings}
        if verdicts[representative.rep_id].status is CandidateStatus.IMPOSSIBLE_PROVEN:
            eliminated_ids |= members
        elif representative.exemplar.id in feasible_exemplars:
            # The class was judged through its exemplar, so the verdict covers
            # every member -- that is what G6 proved when it merged them.
            feasible_ids |= members

    best_cost = None
    if output.recommended is not None:
        best_cost = output.recommended.plan.cost_per_hour_usd

    return ProposedResult(
        output=output, audit=audit, representatives=representatives,
        verdicts=verdicts, feasible_ids=feasible_ids,
        eliminated_ids=eliminated_ids, best_cost=best_cost,
        simulations=audit.simulations_run,           # type: ignore[attr-defined]
    )


def compare(oracle: OracleResult, proposed: ProposedResult) -> OracleComparison:
    """The four numbers, two of which must be zero."""
    oracle_feasible = oracle.feasible_ids

    # A bound said impossible; the oracle disagreed. A bound is wrong.
    false_infeasible = sorted(proposed.eliminated_ids & oracle_feasible)

    # Two members of one representative the oracle judged differently. An
    # equivalence is wrong.
    mismerged: list[tuple[str, str]] = []
    for representative in proposed.representatives:
        members = sorted(e.id for e in representative.embeddings)
        verdicts = {
            member: oracle.feasible.get(member) for member in members
        }
        costs = {member: oracle.cost.get(member) for member in members}
        for index, first in enumerate(members):
            for second in members[index + 1 :]:
                if verdicts[first] != verdicts[second] or not _close(
                    costs[first], costs[second]
                ):
                    mismerged.append((first, second))

    recall = (
        1.0
        if not oracle_feasible
        else len(proposed.feasible_ids & oracle_feasible) / len(oracle_feasible)
    )

    oracle_best = oracle.best_cost()
    regret: float | None = None
    if oracle_best is not None and proposed.best_cost is not None and oracle_best > 0:
        regret = (proposed.best_cost - oracle_best) / abs(oracle_best)

    return OracleComparison(
        feasible_recall=recall,
        cost_regret=regret,
        false_infeasible=false_infeasible,
        mismerged_pairs=mismerged,
        oracle_simulations=oracle.simulations,
        proposed_simulations=proposed.simulations,
        oracle_feasible=len(oracle_feasible),
        proposed_feasible=len(proposed.feasible_ids),
    )


def _close(a: float | None, b: float | None, rel: float = 1e-9) -> bool:
    if a is None or b is None:
        return a is b or a == b
    if a == b:
        return True
    return abs(a - b) <= rel * max(abs(a), abs(b))


def table_row(name: str, comparison: OracleComparison, extra: Mapping[str, object]) -> dict:
    """One row of the compression/correctness table the experiments emit."""
    return {"fixture": name, **dict(extra), **comparison.as_dict()}
