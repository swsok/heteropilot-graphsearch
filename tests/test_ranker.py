"""G8: order representatives by the room each has, and never predict anything.

Two properties carry this file.

`test_the_ranker_never_produces_metrics` is the prohibition. A ranker that
emitted `PredictedMetrics` would be a predictor nobody validated, and its
numbers would reach a plan as though a simulation had produced them.

`test_the_tpot_ratio_is_not_below_the_comm_latency_floor` is the consistency
one. The ranker may use measured effective bandwidths where a bound may not, so
the two can legitimately disagree -- but not in the direction where the ranker
calls a candidate comfortable that `bounds.py` has already proved impossible.
"""

from __future__ import annotations

import pytest

from graphsearch import paths_root
from graphsearch.bounds import BoundPolicy, prune
from graphsearch.embeddings import enumerate_embeddings
from graphsearch.equivalence import compress
from graphsearch.ranker import (
    DiversityQuota,
    RankFeatures,
    ServiceMarginRanker,
    apply_quota,
    explain,
    features_for,
    rank_features,
)
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import FIXTURES, load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import detect_islands  # noqa: E402
from planner.optimizer.surrogate import BinnedRooflineRanker  # noqa: E402
from planner.plan import CandidateConfig, PredictedMetrics  # noqa: E402
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


def pipeline(service_spec, *, limit: int = 2, name: str = "abcde_v2"):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)
    generated = CandidateGenerator(
        service_spec, cluster, islands, profiles, enable_bound_pruning=False
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= limit]
    found, stats = enumerate_embeddings(templates, by_id, graph, service_spec)
    representatives, _, _ = compress(found, graph)
    return cluster, profiles, by_id, graph, representatives, stats


def features(**kw) -> RankFeatures:
    base = {
        "candidate_id": "c",
        "ttft_ratio": 0.5,
        "tpot_ratio": 0.5,
        "goodput_ratio": 0.5,
        "cost_per_hour": 1.0,
        "shared_nic_util": 0.1,
        "cut_margin": 10.0,
        "memory_margin": 10.0,
        "outside_calibration": False,
        "structure_key": (1, 1, ("TOYGPU",), False),
    }
    base.update(kw)
    return RankFeatures(**base)


# --- the prohibition ------------------------------------------------------

def test_the_ranker_never_produces_metrics() -> None:
    """A ranker that emitted metrics would be an unvalidated predictor whose
    numbers reach a plan as though a simulation had produced them.

    Asserted structurally rather than by grepping the source: the module does
    not import `PredictedMetrics` at all, and `order()` returns nothing but the
    `CandidateConfig` objects it was given. A text scan would trip over the
    docstrings that explain this very rule.
    """
    import graphsearch.ranker as module

    assert not hasattr(module, "PredictedMetrics")
    assert PredictedMetrics not in vars(module).values()

    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    candidates = [
        r.exemplar.template.model_copy(update={"id": r.exemplar.id})
        for r in representatives
    ]
    table = {
        c.id: features_for(r, service_spec, graph, by_id, profiles)
        for c, r in zip(candidates, representatives, strict=True)
    }
    ordered = ServiceMarginRanker(table).order(
        list(candidates), service_spec, by_id, profiles
    )
    given = {c.id: c for c in candidates}
    assert all(isinstance(c, CandidateConfig) for c in ordered)
    assert all(c is given[c.id] for c in ordered), (
        "order() returned objects it was not given"
    )


# --- (i) the ABC contract -------------------------------------------------

def test_order_is_a_permutation() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    candidates = [
        r.exemplar.template.model_copy(update={"id": r.exemplar.id})
        for r in representatives
    ]
    table = {
        c.id: features_for(r, service_spec, graph, by_id, profiles)
        for c, r in zip(candidates, representatives, strict=True)
    }
    ranker = ServiceMarginRanker(table)
    ordered = ranker.order(candidates, service_spec, by_id, profiles)
    assert len(ordered) == len(candidates)
    assert {c.id for c in ordered} == {c.id for c in candidates}
    assert [c.id for c in ranker.order(candidates, service_spec, by_id, profiles)] == [
        c.id for c in ordered
    ]


def test_a_candidate_with_no_features_is_ordered_last_not_dropped() -> None:
    """Same length, same members -- the ABC says so, and a dropped candidate
    would silently leave the search."""
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    candidates = [
        r.exemplar.template.model_copy(update={"id": r.exemplar.id})
        for r in representatives
    ][:4]
    table = {
        candidates[0].id: features_for(
            representatives[0], service_spec, graph, by_id, profiles
        )
    }
    ordered = ServiceMarginRanker(table).order(
        candidates, service_spec, by_id, profiles
    )
    assert {c.id for c in ordered} == {c.id for c in candidates}
    assert ordered[0].id == candidates[0].id


# --- (ii) the ordering ----------------------------------------------------

def test_comfortable_candidates_come_first_cheapest_among_them() -> None:
    ordered = rank_features(
        [
            features(candidate_id="risky-cheap", tpot_ratio=2.0, cost_per_hour=0.1),
            features(candidate_id="calm-dear", cost_per_hour=9.0),
            features(candidate_id="calm-cheap", cost_per_hour=1.0),
        ]
    )
    assert [f.candidate_id for f in ordered] == [
        "calm-cheap", "calm-dear", "risky-cheap"
    ]


def test_an_unpriced_comfortable_candidate_sits_between_the_bands() -> None:
    """Known to be comfortable beats cheap-but-not; unknown cost is not a large
    cost."""
    ordered = rank_features(
        [
            features(candidate_id="risky", tpot_ratio=2.0, cost_per_hour=0.1),
            features(candidate_id="unpriced", cost_per_hour=None),
            features(candidate_id="priced", cost_per_hour=5.0),
        ]
    )
    assert [f.candidate_id for f in ordered] == ["priced", "unpriced", "risky"]


def test_risk_is_the_worst_ratio_not_the_average() -> None:
    """A candidate meets its SLOs only if every one is met, so generous TTFT
    headroom must not hide a TPOT miss."""
    tight = features(ttft_ratio=0.01, tpot_ratio=1.5, goodput_ratio=0.01)
    assert tight.risk_proxy == pytest.approx(1.5)
    assert not tight.comfortable


def test_exactly_at_the_limit_is_comfortable() -> None:
    assert features(tpot_ratio=1.0).comfortable
    assert not features(tpot_ratio=1.0001).comfortable


# --- (iii)-(iv) diversity -------------------------------------------------

def test_the_quota_reserves_room_for_a_second_structure() -> None:
    """Ten cheap lookalikes would otherwise fill a budget of four, and if the
    proxy mis-ranks that structure the whole batch is wasted."""
    cheap = [
        features(
            candidate_id=f"tp1-{i}", cost_per_hour=1.0,
            structure_key=(1, 1, ("TOYGPU",), False),
        )
        for i in range(10)
    ]
    dear = [
        features(
            candidate_id=f"tp2-{i}", cost_per_hour=5.0,
            structure_key=(2, 1, ("TOYGPU",), False),
        )
        for i in range(2)
    ]
    picked = apply_quota(
        rank_features(cheap + dear), 4, DiversityQuota(reserved_fraction=0.5)
    )
    assert len(picked) == 4
    assert any(f.candidate_id.startswith("tp2") for f in picked)


def test_the_quota_returns_exactly_k_even_with_more_groups_than_budget() -> None:
    items = [
        features(candidate_id=f"g{i}", structure_key=(i, 1, ("TOYGPU",), False))
        for i in range(5)
    ]
    picked = apply_quota(rank_features(items), 3, DiversityQuota())
    assert len(picked) == 3
    assert len({f.structure_key for f in picked}) == 3


def test_the_quota_never_returns_fewer_than_a_plain_top_k() -> None:
    items = [features(candidate_id=f"c{i}", cost_per_hour=float(i)) for i in range(6)]
    ordered = rank_features(items)
    for k in range(1, 7):
        assert len(apply_quota(ordered, k, DiversityQuota())) == k


def test_a_budget_of_zero_takes_nothing() -> None:
    assert apply_quota(rank_features([features()]), 0, DiversityQuota()) == []


def test_the_chosen_batch_is_still_in_ranking_order() -> None:
    """A caller taking a prefix of the batch must still get the best of it."""
    items = [
        features(candidate_id=f"c{i}", cost_per_hour=float(i),
                 structure_key=(i % 2, 1, ("TOYGPU",), False))
        for i in range(6)
    ]
    picked = apply_quota(rank_features(items), 4, DiversityQuota())
    assert picked == rank_features(picked)


# --- (v) consistency with the bound ---------------------------------------

def test_the_tpot_ratio_is_not_below_the_comm_latency_floor() -> None:
    """The ranker may use figures a bound may not, so the two can disagree --
    but never in the direction where the ranker calls a candidate comfortable
    that `bounds.py` has already proved impossible."""
    service_spec = spec(tpot=spec().slo.tpot.model_copy(update={"max_ms": 0.01}))
    _, profiles, by_id, graph, representatives, stats = pipeline(service_spec)
    verdicts, _ = prune(
        representatives, service_spec, graph, by_id, profiles, stats,
        policy=BoundPolicy(compat=False, memory=False, throughput_capacity=False),
    )
    eliminated = [r for r in representatives if verdicts[r.rep_id].eliminated]
    assert eliminated, "nothing was eliminated; the check is vacuous"
    for representative in eliminated:
        got = features_for(representative, service_spec, graph, by_id, profiles)
        assert not got.comfortable, (
            f"{got.candidate_id} was proved impossible but ranks comfortable: "
            f"{explain(got)}"
        )


def test_the_goodput_ceiling_is_the_one_the_bound_uses() -> None:
    """If the two differed, a candidate could rank comfortably and then be
    eliminated by a bound that disagreed with the ranking."""
    service_spec = spec(min_goodput_rps=1e9)
    _, profiles, by_id, graph, representatives, stats = pipeline(service_spec)
    verdicts, _ = prune(representatives, service_spec, graph, by_id, profiles, stats)
    for representative in representatives:
        proofs = [
            p
            for p in verdicts[representative.rep_id].proofs
            if p.check == "throughput_capacity"
        ]
        if not proofs:
            continue
        got = features_for(representative, service_spec, graph, by_id, profiles)
        assert got.goodput_ratio > 1.0
        break
    else:
        pytest.fail("no throughput proof to compare against")


# --- (vi) the baseline ranker still works on the same input ---------------

def test_the_binned_roofline_ranker_accepts_the_same_candidates() -> None:
    """Both implement heteropilot's ABC, so the driver can swap them."""
    service_spec = spec()
    _, profiles, by_id, _, representatives, _ = pipeline(service_spec)
    candidates = [
        r.exemplar.template.model_copy(update={"id": r.exemplar.id})
        for r in representatives
    ]
    baseline = BinnedRooflineRanker().order(
        list(candidates), service_spec, by_id, profiles
    )
    assert len(baseline) == len(candidates)
    assert {c.id for c in baseline} == {c.id for c in candidates}


# --- features -------------------------------------------------------------

def test_features_report_what_the_order_was_built_on() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    got = features_for(representatives[0], service_spec, graph, by_id, profiles)
    assert got.ttft_ratio >= 0
    assert got.tpot_ratio > 0
    assert got.goodput_ratio > 0
    assert got.memory_margin > 0
    assert isinstance(got.outside_calibration, bool)
    assert got.candidate_id in explain(got)


def test_a_toy_profile_has_no_calibration_domain() -> None:
    """Reported, not penalised: an epistemic gap is `bounds.py`'s business.

    Failure to read the index is treated as "no domain" as well -- an index
    that cannot be read is the same epistemic position as one that says nothing.
    """
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    got = features_for(representatives[0], service_spec, graph, by_id, profiles)
    assert got.outside_calibration is True


def test_a_crossed_uplink_shows_up_as_utilisation() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    utilisations = [
        features_for(r, service_spec, graph, by_id, profiles).shared_nic_util
        for r in representatives
    ]
    assert any(u > 0 for u in utilisations)


def test_the_structure_key_separates_the_bets() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    keys = {
        features_for(r, service_spec, graph, by_id, profiles).structure_key
        for r in representatives
    }
    assert len(keys) > 1, "every candidate looks like the same bet"
    for key in keys:
        assert len(key) == 4
        assert isinstance(key[3], bool)


def test_order_accepts_a_callable_as_well_as_a_table() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    by_candidate = {
        r.exemplar.id: features_for(r, service_spec, graph, by_id, profiles)
        for r in representatives
    }
    candidates = [
        r.exemplar.template.model_copy(update={"id": r.exemplar.id})
        for r in representatives
    ]
    table_order = ServiceMarginRanker(by_candidate).order(
        list(candidates), service_spec, by_id, profiles
    )
    callable_order = ServiceMarginRanker(
        lambda c: by_candidate.get(c.id)
    ).order(list(candidates), service_spec, by_id, profiles)
    assert [c.id for c in table_order] == [c.id for c in callable_order]


def test_a_ranker_with_a_quota_still_returns_every_candidate() -> None:
    """The quota picks a HEAD; nothing leaves the list."""
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    candidates = [
        r.exemplar.template.model_copy(update={"id": r.exemplar.id})
        for r in representatives
    ]
    table = {
        c.id: features_for(r, service_spec, graph, by_id, profiles)
        for c, r in zip(candidates, representatives, strict=True)
    }
    ranker = ServiceMarginRanker(table, quota=DiversityQuota(), k_hint=4)
    ordered = ranker.order(list(candidates), service_spec, by_id, profiles)
    assert {c.id for c in ordered} == {c.id for c in candidates}
    assert len(ordered) == len(candidates)


def test_a_candidate_config_is_never_mutated() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, _ = pipeline(service_spec)
    candidates = [
        r.exemplar.template.model_copy(update={"id": r.exemplar.id})
        for r in representatives
    ]
    before = [c.model_dump() for c in candidates]
    table = {
        c.id: features_for(r, service_spec, graph, by_id, profiles)
        for c, r in zip(candidates, representatives, strict=True)
    }
    ServiceMarginRanker(table).order(list(candidates), service_spec, by_id, profiles)
    assert [c.model_dump() for c in candidates] == before


def test_the_abc_is_actually_implemented() -> None:
    from planner.optimizer.surrogate import SurrogateRanker

    assert issubclass(ServiceMarginRanker, SurrogateRanker)
    assert isinstance(ServiceMarginRanker({}), SurrogateRanker)


def test_an_empty_candidate_list_is_not_an_error() -> None:
    service_spec = spec()
    _, profiles, by_id, _, _, _ = pipeline(service_spec)
    assert ServiceMarginRanker({}).order([], service_spec, by_id, profiles) == []


