"""G12: did the search lose the answer?

Two of the four numbers are not allowed to be non-zero, and neither is a
tuning knob:

* `false_infeasible` -- a bound proved something impossible that the oracle
  found feasible. A bound is wrong.
* `mismerged_pairs` -- two placements in one representative that the oracle
  judged differently. An equivalence is wrong.

The work order says a failure here is fixed by demoting the bound or correcting
the label rule, **never by relaxing the test**. The reason is that this test is
the only thing standing between a compression ratio and a wrong answer wearing
one.

A correctness check that cannot fail is not one, so
`test_the_harness_does_report_a_mismerge_when_there_is_one` exercises the
instrument directly. It has to: the boundary ablation on the shared-NIC fixture
merges two placements the predictor cannot tell apart, because the uplink that
distinguishes them carries only traffic no latency target charges for. That is
GS-8 and heteropilot D124 showing up in a test rather than in a caveat.
"""

from __future__ import annotations

import pytest

from graphsearch import paths_root
from graphsearch.adaptive import AdaptiveConfig
from graphsearch.bounds import BoundPolicy
from graphsearch.equivalence import CompressionPolicy
from graphsearch.oracle import compare, run_oracle, run_proposed, table_row
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import (
    FIXTURES,
    GraphAwareMockPredictor,
    load_toy_cluster,
    toy_profiles_for,
)

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import detect_islands  # noqa: E402
from planner.plan import (  # noqa: E402
    CandidateConfig,
    IslandAssignment,
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
                update={"primary": Objective.MINIMIZE_COST_PER_HOUR, "secondary": None}
            )
        }
    )
    if slo:
        base = base.model_copy(update={"slo": base.slo.model_copy(update=slo)})
    return base


def world(name: str, service_spec, *, limit: int = 2):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)
    generated = CandidateGenerator(
        service_spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=True,
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= limit]
    return cluster, profiles, by_id, graph, templates


def both(name: str, service_spec, **kw):
    cluster, profiles, islands, graph, templates = world(name, service_spec)
    oracle = run_oracle(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    proposed = run_proposed(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates, **kw,
    )
    return oracle, proposed


#: A budget the toy fixtures can meet, so the SLO is not what decides.
ROOMY = {"ttft": None}


def roomy_spec():
    base = spec()
    return base.model_copy(
        update={
            "slo": base.slo.model_copy(
                update={"ttft": base.slo.ttft.model_copy(update={"max_ms": 1e6})}
            )
        }
    )


# --- the two that must be zero -------------------------------------------

@pytest.mark.parametrize("fixture", ["abcde_v2", "shared_nic_v2", "asym_v2"])
def test_no_bound_removes_a_feasible_placement(fixture: str) -> None:
    """`false_infeasible` is a bound being wrong, not a tuning issue."""
    oracle, proposed = both(fixture, roomy_spec())
    comparison = compare(oracle, proposed)
    assert comparison.false_infeasible == [], (
        f"{fixture}: a bound proved these impossible and the oracle found them "
        f"feasible: {comparison.false_infeasible}"
    )


@pytest.mark.parametrize("fixture", ["abcde_v2", "shared_nic_v2", "asym_v2"])
def test_no_representative_merges_two_different_answers(fixture: str) -> None:
    """`mismerged_pairs` is an equivalence being wrong."""
    oracle, proposed = both(fixture, roomy_spec())
    comparison = compare(oracle, proposed)
    assert comparison.mismerged_pairs == [], (
        f"{fixture}: these pairs share a representative and the oracle judged "
        f"them differently: {comparison.mismerged_pairs}"
    )


# --- the check can fail --------------------------------------------------

def _x_and_y_to_z():
    """The research design's §5 counterexample, as two templates.

    Two prefill pairs talking to the SAME third decode partner. With only X and
    Y a P/D candidate crosses BOTH uplinks whichever way it runs, so there is
    nothing to compare -- which is why this needs nodeZ.
    """
    cluster = load_toy_cluster("shared_nic_v2")
    profiles = toy_profiles_for(cluster)
    islands = {i.id: i for i in detect_islands(cluster, profiles)}
    graph = build_resource_graph(cluster, profiles)

    def island_of(node: str) -> str:
        return next(i.id for i in islands.values() if i.node_id == node)

    def pd(prefill: str) -> CandidateConfig:
        return CandidateConfig(
            id=f"pd-{prefill}-Z", model=MODEL, dtype="bfloat16",
            serving_arch=ServingArch.PD_SPLIT,
            assignments=[
                IslandAssignment(
                    island_id=island_of(prefill), role=Role.PREFILL, tp_size=2
                ),
                IslandAssignment(
                    island_id=island_of("nodeZ"), role=Role.DECODE, tp_size=2
                ),
            ],
        )

    return cluster, profiles, islands, graph, [pd("nodeX"), pd("nodeY")]


def test_dropping_the_boundary_produces_a_mismerge() -> None:
    """The existence proof for the research contribution.

    X's uplink already has 6 of its 10 GB/s taken and Y's is free. `P on X ->
    D on Z` and `P on Y -> D on Z` are otherwise identical, so the KV handoff
    crosses a half-taken wire in one and a free one in the other:

    * with the boundary in the signature they stay apart, and the oracle
      agrees -- `mismerged_pairs == []`;
    * with `include_boundary=False` they FOLD, and the oracle judges them
      differently, so the harness must report the pair.

    A correctness check that cannot fail is not one. This one can, and it is
    the first test in this repository that would fail if the compression
    stopped reading the boundary.

    The SLO is read off the oracle rather than written down, because a
    hard-coded threshold that drifts past both TTFTs stops separating them
    and goes green for the wrong reason.
    """
    cluster, profiles, islands, graph, templates = _x_and_y_to_z()

    def oracle_for(service_spec):
        return run_oracle(
            service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
            graph=graph, templates=templates,
        )

    survey = oracle_for(roomy_spec())
    ttfts = sorted(p.predicted.p99_ttft_ms for p in survey.plans.values())
    assert len(ttfts) == 2, f"expected the two placements, got {len(ttfts)}"
    assert ttfts[0] < ttfts[1], (
        f"the contended uplink cost nothing: both TTFTs are {ttfts}. The "
        f"result hook that prices the handoff over its own path is not bound."
    )
    tight = spec(
        ttft=roomy_spec().slo.ttft.model_copy(
            update={"max_ms": (ttfts[0] + ttfts[1]) / 2}
        )
    )

    oracle = oracle_for(tight)
    sighted = run_proposed(
        tight, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    blind = run_proposed(
        tight, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
        compression_policy=CompressionPolicy(include_boundary=False),
    )

    assert len(sighted.representatives) == 2, "exact compression merged them"
    assert len(blind.representatives) == 1, "the ablation did not merge them"

    assert compare(oracle, sighted).mismerged_pairs == []

    blind_pairs = compare(oracle, blind).mismerged_pairs
    assert blind_pairs, (
        "dropping the boundary merged two placements the oracle judged "
        "differently, and the harness did not report it"
    )
    verdicts = {oracle.feasible[e.id] for e in blind.representatives[0].embeddings}
    assert verdicts == {True, False}, (
        f"the pair was reported, but not for the reason this test claims: "
        f"{verdicts}"
    )


def test_the_harness_does_report_a_mismerge_when_there_is_one() -> None:
    """A correctness check that cannot fail is not one.

    The shared-NIC ablation cannot produce a detectable mismerge under the null
    contention model (see above), so the instrument is tested directly: a
    representative holding two placements the oracle judged differently must be
    reported, with both ids named.
    """
    service_spec = roomy_spec()
    cluster, profiles, islands, graph, templates = world("shared_nic_v2", service_spec)
    oracle = run_oracle(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    proposed = run_proposed(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
        compression_policy=CompressionPolicy(include_boundary=False),
    )
    merged = next(
        r for r in proposed.representatives if r.multiplicity >= 2
    )
    first, second = sorted(e.id for e in merged.embeddings)[:2]

    # Flip one member's verdict: the class now covers a feasible and an
    # infeasible placement, which is exactly what must never go unreported.
    oracle.feasible[first] = True
    oracle.feasible[second] = False

    comparison = compare(oracle, proposed)
    assert (first, second) in comparison.mismerged_pairs
    assert not comparison.correct


def test_a_cost_difference_inside_one_representative_is_also_a_mismerge() -> None:
    service_spec = roomy_spec()
    cluster, profiles, islands, graph, templates = world("shared_nic_v2", service_spec)
    oracle = run_oracle(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    proposed = run_proposed(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
        compression_policy=CompressionPolicy(include_boundary=False),
    )
    merged = next(r for r in proposed.representatives if r.multiplicity >= 2)
    first, second = sorted(e.id for e in merged.embeddings)[:2]
    oracle.cost[first] = 1.0
    oracle.cost[second] = 2.0
    assert (first, second) in compare(oracle, proposed).mismerged_pairs


# --- what the approach buys ----------------------------------------------

def test_the_search_simulates_fewer_than_the_oracle() -> None:
    oracle, proposed = both("abcde_v2", roomy_spec())
    assert proposed.simulations < oracle.simulations
    assert proposed.simulations == len(proposed.representatives)


def test_recall_is_total_when_every_representative_is_evaluated() -> None:
    oracle, proposed = both("abcde_v2", roomy_spec())
    comparison = compare(oracle, proposed)
    assert comparison.feasible_recall == pytest.approx(1.0)


def test_there_is_no_cost_regret_when_nothing_was_skipped() -> None:
    oracle, proposed = both("abcde_v2", roomy_spec())
    comparison = compare(oracle, proposed)
    if comparison.cost_regret is None:
        pytest.skip("nothing priced and feasible on both sides")
    assert comparison.cost_regret == pytest.approx(0.0, abs=1e-9)


def test_the_asymmetric_fixture_compresses_nothing_and_is_still_correct() -> None:
    """The failure condition, kept as a fixture on purpose: five nodes, no two
    alike, so exact equivalence folds nothing. Correctness must not depend on
    compression having paid off."""
    oracle, proposed = both("asym_v2", roomy_spec())
    ratio = len(proposed.representatives) / max(1, len(oracle.embeddings))
    comparison = compare(oracle, proposed)
    assert comparison.correct
    assert ratio > 0


# --- a budget shows up as recall, not as a wrong answer ------------------

def test_a_truncated_search_loses_recall_and_says_so() -> None:
    """Stopping early must cost recall, never correctness."""
    service_spec = roomy_spec()
    cluster, profiles, islands, graph, templates = world("abcde_v2", service_spec)
    oracle = run_oracle(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    partial = run_proposed(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
        config=AdaptiveConfig(k_schedule=(2,)),
    )
    comparison = compare(oracle, partial)
    assert comparison.correct
    assert comparison.feasible_recall < 1.0
    assert partial.audit.unevaluated_ids                     # type: ignore[attr-defined]


def test_disabling_the_bounds_changes_nothing_about_the_answer() -> None:
    """The relaxation property again, this time end to end."""
    service_spec = roomy_spec()
    cluster, profiles, islands, graph, templates = world("abcde_v2", service_spec)
    oracle = run_oracle(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    off = run_proposed(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
        bound_policy=BoundPolicy(
            compat=False, memory=False, comm_latency=False,
            throughput_capacity=False,
        ),
    )
    on = run_proposed(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    assert compare(oracle, off).correct
    assert compare(oracle, on).correct
    assert (
        compare(oracle, off).feasible_recall
        == compare(oracle, on).feasible_recall
    )


# --- the row an experiment writes ----------------------------------------

def test_a_table_row_carries_every_number_it_claims() -> None:
    oracle, proposed = both("abcde_v2", roomy_spec())
    comparison = compare(oracle, proposed)
    row = table_row(
        "abcde_v2", comparison,
        {"embeddings": len(oracle.embeddings),
         "representatives": len(proposed.representatives)},
    )
    for key in (
        "fixture", "embeddings", "representatives", "feasible_recall",
        "cost_regret", "false_infeasible", "mismerged_pairs",
        "oracle_simulations", "proposed_simulations", "correct",
    ):
        assert key in row
    assert row["correct"] is True


def test_the_comparison_reports_rather_than_asserts() -> None:
    """`compare` is an instrument: it returns numbers and never raises, so a
    failing fixture produces a row rather than a stack trace."""
    oracle, proposed = both("shared_nic_v2", roomy_spec())
    comparison = compare(oracle, proposed)
    assert isinstance(comparison.as_dict(), dict)
    assert comparison.oracle_simulations >= comparison.proposed_simulations
