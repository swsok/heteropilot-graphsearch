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

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from graphsearch import paths_root
from graphsearch.adaptive import AdaptiveConfig, AdaptiveSearch, build_ranker
from graphsearch.bounds import BoundPolicy, CandidateStatus, prune
from graphsearch.contention import DEFAULT_CONTENTION_MODEL, ContentionModel
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
from graphsearch.equivalence import signature as embedding_signature
from graphsearch.ranker import DEFAULT_RANKER_VARIANT
from graphsearch.schema import ResourceGraph

paths_root.ensure_importable()

from planner.envelope import EnvelopeCache  # noqa: E402
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
    #: Seconds per stage, the same shape `SearchAudit.timings` carries. The
    #: oracle has only two -- `enumerate` and `sim` -- and `sim` is the term
    #: E-G3's `saving` subtracts from. Never serialised anywhere: a wall-clock
    #: cannot be byte-identical between two runs (GS-15).
    timings: dict[str, float] = field(default_factory=dict)
    #: embedding id -> feasible? **Only placements the simulator actually
    #: judged appear here.** A simulation that errored is absent, not False.
    feasible: dict[str, bool] = field(default_factory=dict)
    #: embedding id -> objective-relevant cost, None when unpriced.
    cost: dict[str, float | None] = field(default_factory=dict)
    #: embedding id -> the plan, for a caller that wants the metrics.
    plans: dict[str, DeploymentPlan] = field(default_factory=dict)
    #: embedding id -> why the simulator produced no verdict for it. This is
    #: `unknown_measurement`, the fourth of the five states, and it is kept
    #: apart from `feasible=False` because a budget, a crash or a timeout is a
    #: property of the RUN and never of the placement (work order rule 4).
    #:
    #: It is not a hypothetical. The first real-simulator E-G3 run on
    #: graph-toy-shared-nic had 18 of 288 placements come back SIM_ERROR;
    #: recording them as infeasible made 96 pairs "disagree" with their own
    #: equivalence class, and `mismerged_pairs` read 96 when the equivalence
    #: relation had done nothing wrong.
    unjudged: dict[str, str] = field(default_factory=dict)
    simulations: int = 0

    @property
    def feasible_ids(self) -> set[str]:
        return {k for k, v in self.feasible.items() if v}

    @property
    def judged_ids(self) -> set[str]:
        """Placements the simulator reached a verdict on, either way."""
        return set(self.feasible)

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
    #: Placements the oracle could not judge -- a simulator error, a timeout.
    #: `unknown_measurement`, never `infeasible`. It does not make a run
    #: incorrect; it makes it INCOMPLETE, and the difference is the whole of
    #: work order rule 4.
    unjudged: list[str] = field(default_factory=list)
    #: Pairs inside one equivalence class that could not be compared because at
    #: least one member was unjudged. Excluded from `mismerged_pairs` and
    #: reported on its own, because "feasible vs no answer" measures the
    #: simulator, not the equivalence.
    unjudged_pairs: list[tuple[str, str]] = field(default_factory=list)

    @property
    def correct(self) -> bool:
        """The two numbers that are not allowed to be non-zero.

        `unjudged` is deliberately not one of them. A run with unjudged
        placements has proved less than a complete one and says so through
        `complete`; it has not proved anything WRONG.
        """
        return not self.false_infeasible and not self.mismerged_pairs

    @property
    def complete(self) -> bool:
        """Whether every placement got a verdict. Reported beside `correct`."""
        return not self.unjudged

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
            "unjudged": len(self.unjudged),
            "unjudged_pairs": len(self.unjudged_pairs),
            "correct": self.correct,
            "complete": self.complete,
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
    contention: ContentionModel = DEFAULT_CONTENTION_MODEL,
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
            contention=contention,
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


def _oracle_cache_signature(embedding_id: str, signature, graph: ResourceGraph) -> str:
    """The envelope-cache signature for one placement, **in the oracle arm**.

    It leads with the EMBEDDING ID, and that is the whole point. Keying the
    oracle by the graph signature alone -- the way the proposed arm keys it --
    makes every embedding of one equivalence class share a cache entry, so the
    second and later members are served the first's metrics and
    `mismerged_pairs` is 0 by construction. The oracle would then be auditing
    the compression with the compression's own answer, which is GS-9's mistake
    one level up.

    Measured, not reasoned: the first real-simulator run of E-G3 on
    graph-toy-shared-nic reported 288 oracle simulations and wrote 48 cache
    files. It had simulated 48 placements and copied the rest.

    The graph signature stays in the key beside the id, so an entry cannot
    answer across a networkx release that hashes the same graph differently
    (`tool_version`) or across a schema change.
    """
    return (
        f"{embedding_id}:{signature.wl_hash}:{graph.schema_version}:"
        f"{signature.tool_version}"
    )


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
    cache: EnvelopeCache | None = None,
    max_workers: int | None = None,
) -> OracleResult:
    """Every embedding, simulated. No compression, no bounds, no top-K.

    Slow by design -- the same bargain `planner/optimizer/exhaustive.py`
    strikes. It is the only way to tell a pruning bug from an empty feasible
    set.

    **The cache is keyed per EMBEDDING ID.** Two things would each make this
    function detect zero mis-merges every time and look like a pass:

    * no signature at all -- `EnvelopeKey` describes parallelism and hardware
      and cannot describe which shared resources a placement crosses, so every
      embedding of a template collides on one key and the second is served the
      first's metrics;
    * the *graph* signature, which is what the proposed arm uses -- then every
      embedding of one equivalence class shares an entry, and the oracle
      audits the compression using the compression's own answer.

    So the oracle's key leads with the embedding id: one placement, one entry,
    every time. It costs the oracle the simulations the compression would have
    saved, which is precisely what makes it a baseline.
    """
    started = time.perf_counter()
    embeddings, _ = enumerate_embeddings(templates, islands, graph, spec, policy)
    result = OracleResult(embeddings=list(embeddings))
    result.timings["enumerate"] = time.perf_counter() - started
    if not embeddings:
        return result
    embedded_pd = bind_predictor(
        predictor, embeddings, graph,
        spec=spec, cluster=cluster, islands=islands, profiles=profiles,
    )

    if cache is not None:
        signatures = {
            e.id: _oracle_cache_signature(e.id, embedding_signature(e, graph), graph)
            for e in embeddings
        }
        cache = cache.with_signature_of(lambda c: signatures.get(c.id))

    started = time.perf_counter()
    evaluation = evaluate_candidates(
        [_candidate_for(e) for e in embeddings],
        spec, cluster, dict(islands), dict(profiles), predictor,
        cache=cache, max_workers=max_workers,
        pd_transfer=not embedded_pd,
    )
    # The term E-G3 compares against. Measured around the evaluation and not
    # around the whole function, because `saving` subtracts the compression's
    # cost separately and an `enumerate` counted on both sides would cancel
    # out of one and not the other.
    result.timings["sim"] = time.perf_counter() - started
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
    # Whatever is left got no verdict: the simulator errored, timed out, or
    # the evaluator refused it before simulating. `setdefault(..., False)`
    # used to live here, and it was rule 4 being broken in one line -- an
    # unevaluated placement recorded as an infeasible one.
    judged = set(result.feasible)
    for rejection in evaluation.rejections:
        candidate_id = getattr(rejection, "candidate_id", None)
        if candidate_id is not None and candidate_id not in judged:
            result.unjudged[candidate_id] = str(
                getattr(rejection, "stage", "unknown")
            )
    for embedding in embeddings:
        if embedding.id not in judged:
            result.unjudged.setdefault(embedding.id, "no verdict returned")
    return result


def binder_for(
    predictor, graph, spec, cluster, islands, profiles,
    contention: ContentionModel = DEFAULT_CONTENTION_MODEL,
):
    """`AdaptiveSearch` wants a binder that returns nothing; `bind_predictor`
    returns whether it installed the result hook. `prices_pd_on_the_path`
    answers the same question up front, so the return value is dropped here
    rather than widening the callback's type."""

    def bind(batch: Mapping[str, object]) -> None:
        bind_predictor(
            predictor,
            [e for e in batch.values() if isinstance(e, EmbeddedCandidate)],
            graph, spec=spec, cluster=cluster, islands=islands, profiles=profiles,
            contention=contention,
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
    cache: EnvelopeCache | None = None,
    max_workers: int | None = None,
    contention: ContentionModel = DEFAULT_CONTENTION_MODEL,
) -> ProposedResult:
    """The real pipeline: enumerate, compress, bound, rank, evaluate.

    Each stage is timed and the seconds are handed to `AdaptiveSearch`, which
    adds its own `rank` and `sim`. `saving` is then
    `t_sim_oracle - (t_sim_proposed + t_hash + t_vf2 + t_bounds)` and every
    term in it was measured rather than assumed (P1.3). `hash` and `vf2` come
    from the compression report rather than a wall-clock around `compress`,
    because that call also builds the conflict matrix, which is not a cost of
    the compression.
    """
    timings: dict[str, float] = {}

    started = time.perf_counter()
    embeddings, stats = enumerate_embeddings(
        templates, islands, graph, spec, embedding_policy
    )
    timings["enumerate"] = time.perf_counter() - started

    # `conflicts=False`: this pipeline discards the matrix, and at scale
    # building it is most of the compression's wall time (GS-21). Opting out
    # returns a matrix that REFUSES to be read, never an empty one.
    representatives, _, report = compress(
        embeddings, graph,
        compression_policy or CompressionPolicy(conflicts=False),
    )
    timings.update(report.as_timings())

    started = time.perf_counter()
    verdicts, rejections = prune(
        representatives, spec, graph, islands, profiles, stats,
        policy=bound_policy or BoundPolicy(),
    )
    timings["bounds"] = time.perf_counter() - started
    search = AdaptiveSearch(
        spec, cluster, islands, profiles, predictor,
        graph=graph, representatives=representatives, verdicts=verdicts,
        ranker=build_ranker(
            representatives, spec, graph, islands, profiles,
            variant=ranker_variant, contention=contention,
        ),
        config=config or AdaptiveConfig(k_schedule=(len(representatives) or 1,)),
        embedding_stats=stats, compression=report, bound_rejections=rejections,
        bind_embeddings=binder_for(
            predictor, graph, spec, cluster, islands, profiles, contention
        ),
        embedded_pd_cost=prices_pd_on_the_path(predictor),
        cache=cache, max_workers=max_workers, timings=timings,
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
    #
    # **Only members the oracle actually judged.** A placement whose simulation
    # errored has no verdict, and comparing "feasible" against "no answer"
    # measures the simulator's reliability, not the equivalence relation. The
    # pairs it would produce are counted separately as `unjudged_pairs` and
    # reported; they are a reason to distrust the RUN, not the compression.
    judged = oracle.judged_ids
    mismerged: list[tuple[str, str]] = []
    unjudged_pairs: list[tuple[str, str]] = []
    for representative in proposed.representatives:
        members = sorted(e.id for e in representative.embeddings)
        costs = {member: oracle.cost.get(member) for member in members}
        for index, first in enumerate(members):
            for second in members[index + 1 :]:
                if first not in judged or second not in judged:
                    unjudged_pairs.append((first, second))
                    continue
                if oracle.feasible[first] != oracle.feasible[second] or not _close(
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
        unjudged=sorted(oracle.unjudged),
        unjudged_pairs=unjudged_pairs,
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
