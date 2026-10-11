"""E-G8's analysis: the three-axis verdict, its latency-only auxiliary, and
row 11's load rule."""

from __future__ import annotations

import importlib.util
import sys

import pytest

from graphsearch import paths_root

paths_root.ensure_importable()
ROOT = paths_root.GRAPHSEARCH_ROOT
SLO = {"ttft_max_ms": 550.0, "tpot_max_ms": 60.0}


@pytest.fixture(scope="module")
def an():
    path = ROOT / "experiments" / "e_g8" / "analyze.py"
    spec = importlib.util.spec_from_file_location("e_g8_analyze", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["e_g8_analyze"] = module
    spec.loader.exec_module(module)
    return module


def m(ttft=400.0, tpot=40.0, goodput=0.9, failed=0, mean=100.0, p99=150.0, drain=1.0):
    return {"p99_ttft_ms": ttft, "p99_tpot_ms": tpot, "goodput_rps": goodput,
            "failed": failed, "interval_mean_ms": mean, "interval_p99_ms": p99,
            "goodput_drain_corrected_rps": drain}


def test_goodput_below_the_floor_misses_but_latency_alone_meets(an) -> None:
    v = an.verdict(m(goodput=0.7), SLO, 0.8)
    assert not v["met"] and v["latency_met"]
    assert an.verdict(m(goodput=0.8), SLO, 0.8)["met"]


def test_a_failed_request_misses_on_latency(an) -> None:
    assert not an.verdict(m(failed=1), SLO, 0.8)["latency_met"]


def test_the_predicted_latency_verdict_is_unknown_without_a_prediction(an) -> None:
    assert an.predicted_latency_met({"p99_ttft_ms": None, "p99_tpot_ms": None}, SLO) is None
    assert an.predicted_latency_met({"p99_ttft_ms": 381.0, "p99_tpot_ms": 31.5}, SLO)


@pytest.mark.parametrize("kw,pre,passes", [
    ({}, 0, True),
    ({"p99": 250.0}, 0, False),          # interval p99 above 2x its mean
    ({}, 17, False),                      # a preemption
    ({"drain": 0.85}, 0, False),          # goodput below 0.9 of offered
])
def test_the_load_rule(an, kw, pre, passes) -> None:
    assert an.load_rule(m(**kw), 1.0, pre)["passes"] is passes


def test_the_predicted_goodput_is_read_from_the_committed_detail(an) -> None:
    detail = ("FeasibilityReport(passed=False, violations=[Violation(metric='slo_goodput_rps', "
              "target=0.8, predicted=0.7852656419517176)])")
    assert an.predicted_goodput({"detail": detail}) == pytest.approx(0.7852656419517176)
    assert an.predicted_goodput({"detail": ""}) is None


def test_the_competing_flow_alternative_reproduces_row_7g(an) -> None:
    # Row 7 (g) stated +5.8 ms for s8 -> s6 before E-G5's run.
    import json
    ind = json.loads(an.E_G5_PREDICTION.read_text())["independent"]["xfer_ms_mean"]
    assert round(an.competing_flow_change(ind), 1) == 5.8
