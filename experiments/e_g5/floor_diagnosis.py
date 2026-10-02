"""GS-38: why burst T1/T2 at low/knee recommended nothing, and how the
goodput floor's value moves every condition's recommendation.

**Cached predictions only, no deployment, no new simulation.** Each condition
is planned again with the arguments its run used, against a COPY of that
run's cache (so a miss could not write corrected-adapter numbers into the
original), and the run is refused unless every evaluation was a cache hit
(`simulations_run` counts hits too, so the test is `cache_hits == simulations_run`). The
evaluated set is therefore exactly the one the registered run reached.

Re-judging at another floor keeps each plan's latency verdict as the run's
own feasibility report gave it -- with the accuracy-domain margins the
planner applied -- and re-tests only `slo_goodput_rps >= floor`, which takes
no margin. What this cannot say: a different floor reorders the ranker's
budget (GS-36), so a run actually made at that floor could have reached other
candidates. The evaluated set here is the registered floor's.

**It must run under the pre-GS-38 adapter.** heteropilot's envelope key
bands `link_bw` (`network_class`), and the corrected adapter moves T1, T2 and
T3 into other bands, so under it every lookup misses. The predictions being
diagnosed were made by the old adapter, so run this through
`run_floor_diagnosis.sh`, which builds that tree:

    bash experiments/e_g5/run_floor_diagnosis.sh
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

from graphsearch import paths_root

paths_root.ensure_importable()
HERE = Path(__file__).resolve().parent
ROOT = paths_root.GRAPHSEARCH_ROOT
OUT = HERE / "raw" / "floor-diagnosis-gs38.json"
SCRATCH = ROOT / "outputs" / "gs38-diag-cache"
FLOORS = (1.4, 1.5, 1.6)
LATENCY = ("p99_ttft_ms", "p99_tpot_ms", "p50_ttft_ms", "p50_tpot_ms",
           "p95_ttft_ms", "p95_tpot_ms")


def _harness():
    sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location("dab", HERE / "deploy_and_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(plan, report, floor_registered) -> dict:
    axes = sorted({v.metric for v in (report.violations if report else [])})
    return {
        "id": plan.candidate.id,
        "devices": plan.candidate.total_devices,
        "p99_ttft_ms": plan.predicted.p99_ttft_ms,
        "p99_tpot_ms": plan.predicted.p99_tpot_ms,
        "slo_goodput_rps": plan.predicted.slo_goodput_rps,
        "violated_axes": axes,
        "latency_ok": not any(a in LATENCY for a in axes),
        "other_ok": all(a in LATENCY or a == "slo_goodput_rps" for a in axes),
    }


def one_condition(prov_path: str) -> dict:
    D = _harness()
    import conditions as C
    from planner.optimizer.exhaustive import rank_plans

    prov = json.loads(Path(prov_path).read_text())
    cond, rep, level = prov["condition"], int(prov["rep"]), prov["level"]
    high = level == "high"
    src_cache = D.HIGH_CACHE if high else D.WORK / "cache"
    cache = SCRATCH / f"{cond}-{rep}"
    if cache.exists():
        shutil.rmtree(cache)
    shutil.copytree(src_cache, cache)
    work = D.WORK / cond / str(rep)
    args = SimpleNamespace(predictor="sim", num_requests=C.REQUESTS_PER_RUN, rep=rep,
                           sim_timeout=1800, max_workers=4, budget_sims=16,
                           topology_key=prov["topology_key"])
    pa = D.plan_args(work / "service.yaml", work / "gs38-diag", args,
                     exhaustive=high, cache=cache)
    from graphsearch.__main__ import cmd_plan_objects

    objects = cmd_plan_objects(pa)
    shutil.rmtree(cache)
    audit = objects.audit
    spec = objects.spec
    floor = spec.slo.min_goodput_rps
    size = len(C.TOPOLOGIES[prov["topology_key"]].devices)
    rows = ([_row(p, None, floor) for p in audit.feasible_plans]
            + [_row(p, r, floor) for p, r in audit.infeasible_plans])
    plans = {p.candidate.id: p for p in audit.feasible_plans}
    plans.update({p.candidate.id: p for p, _ in audit.infeasible_plans})

    deployed = next((d for d in prov["deployments"] if d["label"] in
                     ("recommendation", "closest_miss")
                     and d.get("placement_verdict")), None)
    deployed_template = (deployed["placement_verdict"]["embedding_id"].split("@")[0]
                         if deployed and deployed["placement_verdict"].get("embedding_id")
                         else None)

    def recommend_at(f: float):
        ok = [plans[r["id"]] for r in rows if r["latency_ok"] and r["other_ok"]
              and r["slo_goodput_rps"] is not None and r["slo_goodput_rps"] >= f]
        spec_f = spec.model_copy(update={"slo": spec.slo.model_copy(
            update={"min_goodput_rps": f})})
        ranking = rank_plans(ok, spec_f)
        ordered = ([ranking.best] if ranking.best else []) + list(ranking.alternatives)
        sized = [getattr(e, "plan", e) for e in ordered
                 if getattr(e, "plan", e).candidate.total_devices == size]
        n_sized = sum(1 for p in ok if p.candidate.total_devices == size)
        pick = sized[0].candidate.id if sized else None
        return {"floor": f, "feasible": len(ok), "feasible_of_size": n_sized,
                "recommendation": pick,
                "recommendation_template": pick.split("@")[0] if pick else None,
                "same_template_as_deployed": (pick.split("@")[0] == deployed_template
                                              if pick and deployed_template else None)}

    sized_rows = [r for r in rows if r["devices"] == size]
    return {
        "condition": cond, "rep": rep, "level": level,
        "pattern": prov["pattern"], "topology": prov["topology_key"],
        "registered_floor": floor, "size": size,
        "simulations_run": audit.simulations_run, "cache_hits": audit.cache_hits,
        "cache_misses": audit.simulations_run - audit.cache_hits,
        "evaluated": len(rows), "evaluated_of_size": len(sized_rows),
        "deployed_label": deployed["label"] if deployed else None,
        "deployed_template": deployed_template,
        "axis_counts_of_size": {
            a: sum(1 for r in sized_rows if a in r["violated_axes"])
            for a in sorted({a for r in sized_rows for a in r["violated_axes"]})},
        "goodput_only_of_size": sum(1 for r in sized_rows
                                    if r["violated_axes"] == ["slo_goodput_rps"]),
        "max_goodput_of_size": max((r["slo_goodput_rps"] for r in sized_rows
                                    if r["slo_goodput_rps"] is not None), default=None),
        "max_goodput_latency_ok_of_size": max(
            (r["slo_goodput_rps"] for r in sized_rows
             if r["latency_ok"] and r["slo_goodput_rps"] is not None), default=None),
        "at_registered_floor": recommend_at(floor),
        "sensitivity": [recommend_at(f) for f in FLOORS],
        "candidates_of_size": sorted(sized_rows, key=lambda r: r["id"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs", type=int, default=12)
    args = ap.parse_args(argv)
    provs = []
    for p in sorted((HERE / "raw").glob("llama31-8b__*/*/provenance.json")):
        prov = json.loads(p.read_text())
        if prov["level"] == "high" and int(prov["rep"]) != 42:
            continue  # row 8 (b): the exhaustive evaluation is seed 42 only
        provs.append(str(p))
    out = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(one_condition, p): p for p in provs}
        for f in as_completed(futures):
            r = f.result()
            out.append(r)
            print(f"{len(out)}/{len(provs)} {r['condition']}/{r['rep']} "
                  f"misses={r['cache_misses']}", flush=True)
    out.sort(key=lambda r: (r["condition"], r["rep"]))
    bad = [f"{r['condition']}/{r['rep']}" for r in out if r["cache_misses"]]
    if bad:
        # Refused, not written: a miss was simulated with whatever adapter this
        # tree has, and a table built on it would not be the run's predictions.
        print(f"refused, cache misses: {bad}")
        return 1
    OUT.write_text(json.dumps({
        "basis": "GS-38: cached predictions only, pre-GS-38 adapter; refused on any cache miss",
        "cache_misses": bad, "floors": list(FLOORS), "rows": out},
        indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}; cache misses: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
