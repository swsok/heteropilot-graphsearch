"""Preregistration row 8: the `high` goodput floor, by row 4's rule.

Row 4: 95 % of the lowest measured achieved goodput across T1, T2, T3. At
`high` the search offers no recommendation to measure, so the knee's
recommendation template is deployed at 6 rps on each placement instead. The
runs are a pilot, written to `raw/pilot-levels/high-floor/` and excluded from
validation.

    python experiments/e_g5/high_floor_pilot.py
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

from graphsearch import paths_root

paths_root.ensure_importable()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import conditions as C  # noqa: E402

spec = importlib.util.spec_from_file_location("dab", HERE / "deploy_and_bench.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)
spec = importlib.util.spec_from_file_location("an", HERE / "analyze.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

OUT = HERE / "raw" / "pilot-levels" / "high-floor"
RATE = C.KNEE_RPS * C.LEVELS["high"]


def main() -> int:
    model = "llama31-8b"
    S = C.SPECS["service"]
    results = {}
    for topo_key in ("T1", "T2", "T3"):
        topo = C.TOPOLOGIES[topo_key]
        cond = f"{model}__normal__{topo_key}__knee"
        work = D.WORK / cond / "42"
        knee = json.loads((D.RAW / cond / "42" / "provenance.json").read_text())
        cid = next(x for x in knee["deployments"] if x["label"] == "recommendation")["candidate_id"]
        args = SimpleNamespace(
            predictor="sim", num_requests=C.REQUESTS_PER_RUN, rep=42, sim_timeout=1800,
            max_workers=16, budget_sims=16, topology_key=topo_key, dry_run=False,
            allow_knob_loss=False, bench_timeout=1800, allow_tenants=False,
        )
        spec_path = D.service_spec(model, "normal", "knee", C.KNEE_RPS, work / "service.yaml",
                                   ttft_max_ms=S["ttft_max_ms"], tpot_max_ms=S["tpot_max_ms"],
                                   min_goodput_rps=C.goodput_floor("knee"))
        objects = D.run_plan(spec_path, work, args)            # the knee run's cache
        plan = next(p for p in objects.audit.feasible_plans if p.candidate.id == cid)
        trace = D.workload_at(RATE, model, work, C.PATTERNS["normal"])
        D.say(f"{topo_key}: {cid} at {RATE:g} rps on {topo.devices}")
        row = D.measure(objects, plan, "knee-template-at-high", topo, model, trace,
                        OUT / topo_key, args, offered=RATE)
        req = OUT / topo_key / "bench" / "requests.jsonl"
        m = A.latencies(req) if req.exists() else None
        results[topo_key] = {"candidate_id": cid, "state": row.get("state"),
                             "goodput_rps": m and m["goodput_rps"],
                             "p99_ttft_ms": m and m["p99_ttft_ms"]}
        (OUT / topo_key / "provenance.json").write_text(
            json.dumps({**row, "pilot": "high-floor", "validation_set": False,
                        "gpu_tenants_before": D.gpu_tenants(),
                        "loadavg": [round(x, 2) for x in __import__("os").getloadavg()]},
                       indent=2, sort_keys=True, default=str) + "\n")
    good = [r["goodput_rps"] for r in results.values() if r["goodput_rps"]]
    floor = math.floor(min(good) * 0.95 * 10) / 10 if len(good) == 3 else None
    summary = {"rate_rps": RATE, "placements": results, "rule": "row 4: 0.95 x lowest, "
               "rounded down to 0.1", "floor": floor}
    (OUT / "floor.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
