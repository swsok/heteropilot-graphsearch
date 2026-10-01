"""The P/D arm's metrics: failures counted, and TTFT and TPOT paired per request.

`_bench_latencies` adds no TPOT for a one-token request, so its two lists can
differ in length; zipping them paired one request's TTFT with another's TPOT.
The SLO attainment below is only right if each request is judged on its own.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from graphsearch import paths_root

ROOT = paths_root.GRAPHSEARCH_ROOT


def _analyze():
    here = ROOT / "experiments" / "e_g5"
    sys.path.insert(0, str(here))
    spec = importlib.util.spec_from_file_location("e_g5_analyze", here / "analyze.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _req(i, t0, first, last, out, error=None):
    return {"request_id": f"pd-{i}", "input_toks": 10, "output_toks": out,
            "arrival_time": t0, "queued_ts": t0, "scheduled_ts": None,
            "first_token_ts": first, "last_token_ts": last,
            "prefill_done_ts": None, "streamed_tokens": out, "error": error}


def test_failures_are_counted_and_requests_judged_one_by_one(tmp_path: Path) -> None:
    a = _analyze()
    rows = [
        # a one-token request that meets TTFT: it has no TPOT entry at all
        _req(0, 0.0, 0.1, 0.1, 1),
        # fast TTFT, TPOT 100 ms over 60: misses
        _req(1, 0.0, 0.1, 1.1, 11),
        # fast on both: meets
        _req(2, 0.0, 0.2, 0.7, 11),
        # a failure
        _req(3, 0.0, None, None, 11, error="HTTPStatusError: 500"),
    ]
    # Per request: 0 and 2 meet, 1 misses -> 2/3. Zipping the TTFT list
    # [0, 1, 2] against the TPOT list [1, 2] pairs 0 with 1's TPOT and 1 with
    # 2's, and gets 1/3 -- which is what this test exists to refuse.
    path = tmp_path / "requests.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    m = a.pd_latencies(path)
    assert m["requests"] == 4
    assert m["completed"] == 3
    assert m["failed"] == 1
    assert m["slo_attainment"] == 2 / 3


def _run(path: Path, n: int, rate: float, service_s: float, extra_ms: float = 0.0):
    """An unqueued run: request i arrives at i/rate and takes service_s."""
    rows = []
    for i in range(n):
        t0 = i / rate
        pre = t0 + 0.05
        first = pre + 0.2 + extra_ms / 1000.0
        r = _req(i, t0, first, t0 + service_s, 11)
        r["prefill_done_ts"] = pre
        rows.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_drain_correction_reads_an_unqueued_run_as_unsaturated(tmp_path: Path) -> None:
    a = _analyze()
    path = tmp_path / "requests.jsonl"
    _run(path, 150, 1.0, 25.0)
    m = a.pd_latencies(path)
    # E-G5's definition pays the last request's whole service time ...
    assert m["goodput_rps"] / 1.0 < 0.9
    # ... and the corrected one does not, because nothing queued.
    assert abs(m["goodput_drain_corrected_rps"] / 1.0 - 1.0) < 0.02


def test_pairs_are_matched_by_request_index(tmp_path: Path) -> None:
    a = _analyze()
    root = tmp_path / "pairs"
    _run(root / "pd-independent" / "42" / "pd" / "requests.jsonl", 20, 1.0, 5.0)
    _run(root / "pd-shared" / "42" / "pd" / "requests.jsonl", 20, 1.0, 5.0, extra_ms=7.0)
    for c in ("pd-independent", "pd-shared"):
        (root / c / "42" / "provenance.json").write_text(json.dumps({"offered_rps": 1.0}))
    (row,) = a._pair_rows(root)
    assert row["n"] == 20
    assert abs(row["diff"] - 7.0) < 1e-6
    assert row["diff_sd"] < 1e-6
