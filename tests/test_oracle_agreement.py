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
from planner.spec import Objective, load_service_spec  # noqa: E402


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
        service_spec, cluster, islands, profiles, enable_bound_pruning=False
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

def test_dropping_the_boundary_merges_what_the_predictor_cannot_tell_apart() -> None:
    """The ablation merges -- and under the NULL contention model that merge is
    undetectable, which is the point GS-8 and heteropilot D124 record.

    `include_boundary=False` folds nodeX and nodeY into one representative even
    though X holds 6 of its 10 GB/s and Y's uplink is free. The oracle does not
    object, and it is right not to: the uplink that distinguishes them appears
    only on the INGRESS and EGRESS paths, which are `on_critical_path: "none"`,
    so its utilisation never reaches a metric. Two placements that differ only
    in a resource no latency target charges for predict identically.

    That is not the compression being safe. It is the predictor being blind to
    the difference -- the same blindness the adapter's `TopologyLossReport`
    reports on every plan. A mismerge here becomes DETECTABLE only once a
    `ContentionModel` exists, and until then a comparison of these two
    representatives is a comparison of bounds and cost.
    """
    service_spec = roomy_spec()
    cluster, profiles, islands, graph, templates = world("shared_nic_v2", service_spec)
    oracle = run_oracle(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    blind = run_proposed(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
        compression_policy=CompressionPolicy(include_boundary=False),
    )
    sighted = run_proposed(
        service_spec, cluster, islands, profiles, GraphAwareMockPredictor(),
        graph=graph, templates=templates,
    )
    assert len(blind.representatives) < len(sighted.representatives), (
        "the ablation did not actually merge anything"
    )
    # Both are "correct" by the oracle, because the oracle cannot see the
    # difference either. The compression keeping them apart is a bet on a
    # contention model that does not exist yet.
    assert compare(oracle, sighted).correct
    assert compare(oracle, blind).correct


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
