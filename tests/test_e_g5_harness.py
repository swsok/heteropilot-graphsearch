"""E-G5's harness asks about the placement it deploys (GS-30).

Two properties, both of which the harness depended on without a test:

* `plan_args` carries every flag `plan` has, so the harness's search is the CLI's
  search. `run_plan`'s docstring named this file as the check before the file
  existed.
* `evaluate_placement` answers for the placement it is given, not for the
  search's recommendation, and keeps the search's own treatment of that
  placement apart from the verdict of simulating it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from graphsearch import paths_root
from graphsearch.__main__ import build_parser, cmd_plan_objects, evaluate_placement

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"
SERVICE = str(FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml")
CLUSTER = str(FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml")

#: The five states, plus the two outcomes of "evaluated". Anything else means a
#: new word crept into the vocabulary the paper forbids merging.
SEARCH_STATES = (
    "impossible_proven", "excluded_by_scope", "unevaluated",
    "evaluated: feasible", "evaluated: not feasible",
)


def _harness():
    here = ROOT / "experiments" / "e_g5"
    sys.path.insert(0, str(here))
    spec = importlib.util.spec_from_file_location("e_g5_harness", here / "deploy_and_bench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mock_args(**overrides):
    args = build_parser().parse_args(
        ["plan", "--service", SERVICE, "--cluster", CLUSTER, "--predictor", "mock"]
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


def test_the_harness_passes_every_flag_plan_has(tmp_path: Path) -> None:
    harness = _harness()
    cli = vars(build_parser().parse_args(["plan", "--service", SERVICE, "--cluster", CLUSTER]))
    ns = SimpleNamespace(
        predictor="mock", num_requests=10, rep=1, sim_timeout=60,
        max_workers=1, budget_sims=8, topology_key="T1",
    )
    ours = vars(harness.plan_args(Path(SERVICE), tmp_path, ns))
    missing = set(cli) - set(ours) - {"command", "func"}
    assert not missing, f"plan has flags the harness does not pass: {sorted(missing)}"


def test_a_placement_is_answered_for_itself() -> None:
    args = _mock_args()
    objects = cmd_plan_objects(args)
    two = [r for r in objects.representatives if len(r.exemplar.devices) >= 1]
    assert two, "fixture produced no representatives"

    seen = {}
    for rep in two:
        for emb in [rep.exemplar, *rep.embeddings]:
            verdict = evaluate_placement(args, objects, rep.template_id, emb.devices)
            assert verdict.embedding_id == emb.id or verdict.embedding_id in {
                e.id for e in rep.embeddings
            }
            assert any(verdict.search_state.startswith(s) for s in SEARCH_STATES), (
                verdict.search_state
            )
            assert verdict.state in ("evaluated", "unknown_measurement")
            if verdict.state == "evaluated":
                assert verdict.plan is not None
                assert verdict.plan.candidate.id == verdict.embedding_id
            seen[emb.id] = verdict
    assert seen


def test_a_placement_the_template_cannot_occupy_is_out_of_scope() -> None:
    args = _mock_args()
    objects = cmd_plan_objects(args)
    template_id = objects.representatives[0].template_id
    verdict = evaluate_placement(args, objects, template_id, {"no-such-device"})
    assert verdict.state == "excluded_by_scope"
    assert verdict.plan is None



def test_the_burst_pattern_means_the_same_thing_to_both_generators() -> None:
    """GS-35: heteropilot's `burstiness` is the reciprocal of vLLM's.

    The simulator's trace comes from heteropilot's generator fed the spec's
    value; the hardware's from `make_workload.py` fed the pattern's Gamma
    shape. Both must give the burst pattern the same coefficient of variation.
    """
    import numpy as np
    from planner.util.workload import _sample_arrivals

    here = ROOT / "experiments" / "e_g5"
    sys.path.insert(0, str(here))
    import conditions as C

    shape = C.PATTERNS["burst"]
    sim = np.diff(_sample_arrivals(np.random.default_rng(0), 4.0,
                                   C.spec_burstiness("burst"), 200_000))
    import make_workload

    rows = [{"arrival_time_ns": 0, "input_toks": 1} for _ in range(50_000)]
    out = make_workload.rescale(rows, 4.0, shape, seed=0)
    hw = np.diff([r["arrival_time_ns"] / 1e9 for r in out])
    expected = 1.0 / np.sqrt(shape)
    for gaps in (sim, hw):
        cv = gaps.std() / gaps.mean()
        assert abs(cv - expected) / expected < 0.05, cv


def test_closest_miss_is_heteropilots_rule_not_the_lowest_ttft() -> None:
    """Row 8: the closest miss minimises `worst_overshoot`, not predicted TTFT.

    `near_ttft` misses TTFT by 1 % and TPOT by 200 %; `balanced` misses both
    by 20 %. Picking by predicted TTFT would take `near_ttft`; heteropilot's
    `closest_plan` rule takes `balanced`, because a plan that misses one axis
    by a mile is not close to feasible.
    """
    from planner.optimizer.feasibility import FeasibilityReport
    from planner.plan import Violation

    harness = _harness()

    def plan(cid, devices, ttft):
        return SimpleNamespace(
            candidate=SimpleNamespace(id=cid, total_devices=devices),
            predicted=SimpleNamespace(p99_ttft_ms=ttft),
        )

    def report(*violations):
        return FeasibilityReport(passed=False, violations=[
            Violation(metric=m, target=t, predicted=p) for m, t, p in violations])

    near_ttft = (plan("near_ttft", 2, 555.5),
                 report(("p99_ttft_ms", 550, 555.5), ("p99_tpot_ms", 60, 180)))
    balanced = (plan("balanced", 2, 660.0),
                report(("p99_ttft_ms", 550, 660), ("p99_tpot_ms", 60, 72)))
    other_size = (plan("tiny", 1, 551.0), report(("p99_ttft_ms", 550, 551)))
    pairs = [near_ttft, balanced, other_size]

    by_ttft = min((p for p in pairs if p[0].candidate.total_devices == 2),
                  key=lambda pr: pr[0].predicted.p99_ttft_ms)
    assert by_ttft[0].candidate.id == "near_ttft"          # the wrong rule's pick
    chosen = harness.closest_miss(pairs, 2)
    assert chosen[0].candidate.id == "balanced"            # heteropilot's rule
    # the size restriction: a closer 1-device plan is not eligible for 2
    assert harness.closest_miss(pairs, 1)[0].candidate.id == "tiny"
    assert harness.closest_miss(pairs, 4) is None


def test_closest_miss_breaks_ties_by_candidate_id() -> None:
    from planner.optimizer.feasibility import FeasibilityReport
    from planner.plan import Violation

    harness = _harness()

    def pair(cid):
        return (SimpleNamespace(candidate=SimpleNamespace(id=cid, total_devices=2)),
                FeasibilityReport(passed=False, violations=[
                    Violation(metric="p99_ttft_ms", target=550, predicted=660)]))

    assert harness.closest_miss([pair("b"), pair("a"), pair("c")], 2)[0].candidate.id == "a"


def test_feasible_marginal_is_a_different_template() -> None:
    """GS-38: another embedding of the recommended template is not an alternative.

    The condition places every row on its own devices, so `tpl@b` would be
    deployed exactly as `tpl@a` was. The closest-to-1 plan is `tpl@b`; the
    rule must pass over it to `other@c`.
    """
    harness = _harness()

    def plan(cid, ttft):
        return SimpleNamespace(
            candidate=SimpleNamespace(id=cid, total_devices=4),
            predicted=SimpleNamespace(p99_ttft_ms=ttft, p99_tpot_ms=1.0,
                                      slo_goodput_rps=5.0),
        )

    spec = SimpleNamespace(slo=SimpleNamespace(
        ttft=SimpleNamespace(max_ms=100.0), tpot=SimpleNamespace(max_ms=100.0),
        min_goodput_rps=None))
    plans = [plan("tpl@a", 10.0), plan("tpl@b", 99.0), plan("other@c", 50.0)]
    objects = SimpleNamespace(audit=SimpleNamespace(
        feasible_plans=plans, evaluated=3, feasible_ids=["tpl@a", "tpl@b", "other@c"]))

    chosen, _ = harness.feasible_marginal(objects, spec, 4, "tpl@a")
    assert chosen.candidate.id == "other@c"
    only_one_template = SimpleNamespace(audit=SimpleNamespace(
        feasible_plans=plans[:2], evaluated=2, feasible_ids=["tpl@a", "tpl@b"]))
    chosen, why = harness.feasible_marginal(only_one_template, spec, 4, "tpl@a")
    assert chosen is None and "template other than" in why
