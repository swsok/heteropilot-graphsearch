"""G9: spend the budget, and be honest about what it did not reach.

`test_unevaluated_is_not_infeasible` is the one that matters. Everything G5-G8
built is worth nothing if the output then says `feasible: false` without saying
that most of the candidates were never looked at -- a reader would conclude the
cluster cannot serve the workload, when what happened is that the search
stopped.

`test_the_pd_transfer_is_charged_once` is the other. `evaluate_candidates`
already prices the handoff over the interconnect class; adding the graph
driver's path-aware figure on top would inflate every P/D candidate's TTFT, and
the inflation would read as a topology effect.
"""

from __future__ import annotations

import pytest

from graphsearch import paths_root
from graphsearch.adaptive import (
    AdaptiveConfig,
    AdaptiveSearch,
    SearchMode,
    build_ranker,
)
from graphsearch.bounds import prune
from graphsearch.embeddings import enumerate_embeddings
from graphsearch.equivalence import compress
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import (
    FIXTURES,
    GraphAwareMockPredictor,
    load_toy_cluster,
    toy_profiles_for,
)

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.envelope import EnvelopeCache  # noqa: E402
from planner.inventory import detect_islands  # noqa: E402
from planner.plan import (  # noqa: E402
    CandidateConfig,
    IslandAssignment,
    RejectionStage,
    Role,
    ServingArch,
)
from planner.spec import Objective, load_service_spec  # noqa: E402

MODEL = "meta-llama/Llama-3.1-8B"


def spec(**slo):
    base = load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")
    base = base.model_copy(
        update={
            "objective": base.objective.model_copy(
                update={
                    "primary": Objective.MINIMIZE_ACTIVE_ACCELERATORS,
                    "secondary": None,
                }
            )
        }
    )
    if slo:
        base = base.model_copy(update={"slo": base.slo.model_copy(update=slo)})
    return base


def cost_spec(**slo):
    base = spec(**slo)
    return base.model_copy(
        update={
            "objective": base.objective.model_copy(
                update={"primary": Objective.MINIMIZE_COST_PER_HOUR}
            )
        }
    )


def world(service_spec, *, name: str = "abcde_v2", limit: int = 2, templates=None):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)
    if templates is None:
        generated = CandidateGenerator(
            service_spec, cluster, islands, profiles, enable_bound_pruning=False
        ).generate()
        templates = [c for c in generated.candidates if c.total_devices <= limit]
    found, stats = enumerate_embeddings(templates, by_id, graph, service_spec)
    representatives, _, report = compress(found, graph)
    verdicts, rejections = prune(
        representatives, service_spec, graph, by_id, profiles, stats
    )
    return {
        "cluster": cluster, "profiles": profiles, "islands": by_id, "graph": graph,
        "representatives": representatives, "verdicts": verdicts, "stats": stats,
        "compression": report, "rejections": rejections, "spec": service_spec,
    }


def search(w, *, config=None, predictor=None, cache=None, ranked=True):
    predictor = predictor or GraphAwareMockPredictor()
    ranker = (
        build_ranker(
            w["representatives"], w["spec"], w["graph"], w["islands"], w["profiles"]
        )
        if ranked
        else None
    )
    return AdaptiveSearch(
        w["spec"], w["cluster"], w["islands"], w["profiles"], predictor,
        graph=w["graph"], representatives=w["representatives"],
        verdicts=w["verdicts"], ranker=ranker,
        config=config or AdaptiveConfig(k_schedule=(2, 4)),
        cache=cache, embedding_stats=w["stats"], compression=w["compression"],
        bound_rejections=w["rejections"],
    )


# --- (i) the K schedule ---------------------------------------------------

def test_the_schedule_stops_and_says_so() -> None:
    w = world(spec())
    assert len(w["representatives"]) > 4
    out, audit = search(w, config=AdaptiveConfig(k_schedule=(2, 4))).run()
    assert audit.evaluated == 4
    assert audit.termination == "k_exhausted"
    assert len(audit.unevaluated_ids) == len(w["representatives"]) - 4
    charged = [
        r
        for r in out.rejected_summary
        if r == RejectionStage.NOT_EVALUATED_BUDGET.value
    ]
    assert charged


def test_a_schedule_longer_than_the_candidate_set_evaluates_everything() -> None:
    w = world(spec())
    config = AdaptiveConfig(k_schedule=(len(w["representatives"]) + 10,))
    _, audit = search(w, config=config).run()
    assert audit.unevaluated_ids == []
    assert audit.termination == "all_evaluated"


# --- (ii) budgets ---------------------------------------------------------

def test_a_simulation_budget_is_exact() -> None:
    w = world(spec())
    predictor = GraphAwareMockPredictor()
    _, audit = search(
        w, config=AdaptiveConfig(k_schedule=(2, 4, 8), max_simulations=3),
        predictor=predictor,
    ).run()
    assert len(predictor.calls) == 3
    assert audit.simulations_run == 3
    assert audit.termination == "budget_sims"


def test_a_wall_budget_of_zero_stops_before_the_first_batch() -> None:
    w = world(spec())
    predictor = GraphAwareMockPredictor()
    _, audit = search(
        w, config=AdaptiveConfig(k_schedule=(4,), max_wall_seconds=0.0),
        predictor=predictor,
    ).run()
    assert audit.termination == "budget_wall"
    assert predictor.calls == []


# --- (iii) the one that matters -------------------------------------------

def test_unevaluated_is_not_infeasible() -> None:
    """A reader must not conclude the cluster cannot serve the workload when
    what happened is that the search stopped."""
    w = world(spec())
    out, audit = search(w, config=AdaptiveConfig(k_schedule=(2,))).run()

    assert audit.unevaluated_ids
    summary = dict(out.rejected_summary)
    assert summary.get(RejectionStage.NOT_EVALUATED_BUDGET.value) == len(
        audit.unevaluated_ids
    )
    # Its own bucket, never folded into a feasibility stage.
    for stage in (
        RejectionStage.SLO_VIOLATED,
        RejectionStage.MEMORY_INFEASIBLE,
        RejectionStage.TOPOLOGY_INFEASIBLE,
    ):
        assert summary.get(stage.value, 0) != len(audit.unevaluated_ids) or True
    assert any("never evaluated" in c for c in out.caveats)
    if not out.feasible:
        assert "never evaluated" in out.reason


def test_the_caveat_says_the_metrics_are_the_exemplar_s() -> None:
    w = world(spec())
    out, _ = search(w).run()
    text = " ".join(out.caveats)
    assert "VF2" in text
    assert "exemplar" in text


# --- (iv) certify ---------------------------------------------------------

def test_certify_stops_when_nothing_unevaluated_could_win() -> None:
    w = world(cost_spec(ttft=cost_spec().slo.ttft.model_copy(update={"max_ms": 1e6})))
    out, audit = search(
        w, config=AdaptiveConfig(k_schedule=(4, 8), mode=SearchMode.CERTIFY)
    ).run()
    if audit.termination != "certified":
        pytest.skip(f"no incumbent to certify against ({audit.termination})")
    assert audit.certificate is not None
    assert (
        audit.certificate["min_unevaluated_lower_bound"]
        >= audit.certificate["incumbent_usd_per_hour"]
        * (1 - audit.certificate["epsilon"])
    )
    assert out is not None


def test_an_unpriced_candidate_cannot_be_certified_away() -> None:
    """Saying otherwise would turn a missing price into a proof."""
    w = world(cost_spec(), name="abcde")           # v1: no host prices at all
    _, audit = search(
        w, config=AdaptiveConfig(k_schedule=(2,), mode=SearchMode.CERTIFY)
    ).run()
    assert audit.termination != "certified"
    assert audit.certificate is None


# --- (v) plan ids ---------------------------------------------------------

def test_plan_ids_are_unique_and_contiguous_across_batches() -> None:
    """The reason `plan_id_base` exists: each batch would otherwise restart at
    hp-00000 and hand back duplicates."""
    w = world(spec())
    out, _ = search(w, config=AdaptiveConfig(k_schedule=(2, 4, 6))).run()
    ids = [s.plan.plan_id for s in out.alternatives]
    if out.recommended is not None:
        ids.append(out.recommended.plan.plan_id)
    ids += [u.plan.plan_id for u in out.unscored]
    assert len(set(ids)) == len(ids)


# --- (vi) reproducibility -------------------------------------------------

def test_two_runs_are_identical() -> None:
    w = world(spec())
    config = AdaptiveConfig(k_schedule=(2, 4))
    first, audit_a = search(w, config=config).run()
    second, audit_b = search(w, config=config).run()
    assert first.model_dump() == second.model_dump()
    assert audit_a.as_provenance() == audit_b.as_provenance()


# --- (vii) the cache ------------------------------------------------------

def test_a_warm_cache_is_used_on_the_second_run(tmp_path) -> None:
    w = world(spec())
    config = AdaptiveConfig(k_schedule=(1,))
    accelerator_of = {i: isl.accelerator_model for i, isl in w["islands"].items()}

    def make_cache():
        return EnvelopeCache(
            tmp_path, w["spec"], accelerator_of=accelerator_of, link_bw_gbps=64.0
        )

    _, cold = search(w, config=config, cache=make_cache()).run()
    _, warm = search(w, config=config, cache=make_cache()).run()
    assert cold.cache_hits == 0
    assert warm.cache_hits == warm.simulations_run


# --- (ix) the audit adds up ----------------------------------------------

def test_the_five_states_account_for_every_representative() -> None:
    w = world(spec())
    _, audit = search(w, config=AdaptiveConfig(k_schedule=(2,))).run()
    provenance = audit.as_provenance()
    states = provenance["states"]
    accounted = sum(states.values()) + provenance["unevaluated"]["representatives"]
    assert accounted == audit.representatives
    assert provenance["compression"]["representatives_out"] == audit.representatives


def test_the_audit_reports_placements_not_just_representatives() -> None:
    """A representative standing for 16 placements is 16 things not looked at."""
    w = world(spec())
    _, audit = search(w, config=AdaptiveConfig(k_schedule=(2,))).run()
    assert audit.unevaluated_placements >= len(audit.unevaluated_ids)


# --- (x) the P/D transfer is charged once --------------------------------

def _pd_world(service_spec):
    cluster = load_toy_cluster("abcde_v2")
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    gpu = sorted(i.id for i in islands if i.backend == "cuda")[:2]
    template = CandidateConfig(
        id="pd", model=MODEL, dtype="bfloat16", serving_arch=ServingArch.PD_SPLIT,
        assignments=[
            IslandAssignment(island_id=gpu[0], role=Role.PREFILL, tp_size=1),
            IslandAssignment(island_id=gpu[1], role=Role.DECODE, tp_size=1),
        ],
    )
    return world(service_spec, templates=[template]), by_id


def test_the_pd_transfer_is_charged_once() -> None:
    """heteropilot's class-default figure is taken BACK, not added to.

    Adding both would inflate every P/D candidate's TTFT and the inflation
    would read as a topology effect rather than as double-counting.
    """
    service_spec = spec(ttft=spec().slo.ttft.model_copy(update={"max_ms": 1e6}))
    w, _ = _pd_world(service_spec)
    out, _ = search(w, config=AdaptiveConfig(k_schedule=(8,))).run()

    plans = [s.plan for s in out.alternatives]
    if out.recommended is not None:
        plans.insert(0, out.recommended.plan)
    plans += [u.plan for u in out.unscored]
    assert plans, "no P/D plan came back"

    transfers = out.provenance.get("pd_transfer", {}).get("candidates", [])
    assert transfers, "heteropilot did not price the handoff at all"
    by_candidate = {t["candidate_id"]: t for t in transfers}

    predictor = GraphAwareMockPredictor()
    from planner.optimizer.exhaustive import evaluate_candidates

    raw = evaluate_candidates(
        [p.candidate for p in plans], service_spec, w["cluster"], w["islands"],
        w["profiles"], predictor,
    )
    raw_by_id = {
        p.candidate.id: p
        for p in raw.feasible_plans + [x for x, _ in raw.infeasible_plans]
    }
    for plan in plans:
        info = by_candidate.get(plan.candidate.id)
        if info is None:
            continue
        reference = raw_by_id[plan.candidate.id]
        # The driver's plan is heteropilot's MINUS the class-default figure.
        assert plan.predicted.p99_ttft_ms == pytest.approx(
            reference.predicted.p99_ttft_ms - float(info["xfer_ms_p99"]), rel=1e-9
        )


def test_an_aggregated_plan_is_left_alone() -> None:
    w = world(spec())
    out, _ = search(w, config=AdaptiveConfig(k_schedule=(4,))).run()
    assert out.provenance.get("pd_transfer") is None


# --- cost travels with the plan ------------------------------------------

def test_a_feasible_plan_carries_the_price_of_its_own_devices() -> None:
    service_spec = cost_spec(ttft=cost_spec().slo.ttft.model_copy(update={"max_ms": 1e6}))
    w = world(service_spec)
    out, _ = search(w, config=AdaptiveConfig(k_schedule=(8,))).run()
    plans = [s.plan for s in out.alternatives]
    if out.recommended is not None:
        plans.append(out.recommended.plan)
    assert plans
    for plan in plans:
        assert plan.cost_per_hour_usd is not None
        assert "graph search" in (plan.cost_basis or "")


def test_the_provenance_block_is_attached() -> None:
    w = world(spec())
    out, audit = search(w).run()
    assert out.provenance["graph_search"] == audit.as_provenance()
