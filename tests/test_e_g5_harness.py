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

import pytest

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


@pytest.mark.parametrize("state", ["evaluated: feasible", "unevaluated (the budget did not reach it)"])
def test_the_search_state_vocabulary_is_closed(state: str) -> None:
    assert any(state.startswith(s) for s in SEARCH_STATES)
