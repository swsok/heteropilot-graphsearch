"""Preregistration row 8: the `high` level's verdict, decided once, exhaustively.

For each pattern and topology at `high`, seed 42:

1. evaluate EVERY representative in GS-27's scope (<= N devices), so that
   "no feasible plan of this size" is a statement about the scope and not
   about a budget;
2. branch: a feasible plan of size N -> the recommendation and feasible
   marginal are fixed; none -> the closest miss is fixed (heteropilot's
   `closest_plan` rule, restricted to N);
3. run the registered adaptive search (K = 16) on the same spec and record
   how many of the scope's feasible plans it found -- the recall of the
   budgeted search on a real-hardware spec.

Writes `raw/high-scope/<model>__<pattern>__<topology>.json`; the hardware
repetitions read it and deploy what it names. Simulations are cached in
`outputs/cache-eg5-high/`. CPU only; run it when no hardware is measuring.

    python experiments/e_g5/high_scope.py --max-workers 60
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from graphsearch import paths_root

paths_root.ensure_importable()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import conditions as C  # noqa: E402

_spec = importlib.util.spec_from_file_location("dab", HERE / "deploy_and_bench.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


def one(model: str, pattern: str, topo_key: str, args) -> dict:
    from planner.optimizer.exhaustive import rank_plans

    n = len(C.TOPOLOGIES[topo_key].devices)
    S = C.SPECS["service"]
    rate = C.KNEE_RPS * C.LEVELS["high"]
    cond = f"{model}__{pattern}__{topo_key}__high"
    work = D.WORK / "high-scope" / cond
    work.mkdir(parents=True, exist_ok=True)
    spec_path = D.service_spec(model, pattern, "high", rate, work / "service.yaml",
                               ttft_max_ms=S["ttft_max_ms"], tpot_max_ms=S["tpot_max_ms"],
                               min_goodput_rps=C.goodput_floor("high"))
    a = SimpleNamespace(predictor="sim", num_requests=C.REQUESTS_PER_RUN, rep=42,
                        sim_timeout=args.sim_timeout, max_workers=args.max_workers,
                        budget_sims=16, topology_key=topo_key)
    full = D.run_plan(spec_path, work, a, exhaustive=True, cache=D.HIGH_CACHE)
    k16 = D.run_plan(spec_path, work, a, exhaustive=False, cache=D.HIGH_CACHE)

    scope = D.scope_record(full, n, True)
    in_scope = {p.candidate.id for p in full.audit.feasible_plans
                if p.candidate.total_devices == n}
    found = {p.candidate.id for p in k16.audit.feasible_plans
             if p.candidate.total_devices == n}
    scope["budget_k16"] = {"evaluated": k16.audit.evaluated,
                           "feasible_of_size_found": len(found & in_scope),
                           "feasible_of_size_in_scope": len(in_scope)}
    record = {"condition": cond, "seed": 42, "rate_rps": rate,
              "goodput_floor": C.goodput_floor("high"), "scope": scope}

    sized = [p for p in full.audit.feasible_plans if p.candidate.total_devices == n]
    if sized:
        # The same selection the other levels use, on the exhaustive objects:
        # the recommendation of this size, and alternative A by its rule.
        picked = D.candidates_of_size(full, n)
        if picked:
            rec = getattr(picked[0], "plan", picked[0])
        else:
            ranked = rank_plans(sized, full.spec)
            rec = ranked.best.plan if ranked.best else min(sized, key=lambda p: p.candidate.id)
        fm, why = D.feasible_marginal(full, full.spec, n, rec.candidate.id)
        record.update(branch="recommendation",
                      recommendation=rec.candidate.id.split("@", 1)[0],
                      recommendation_id=rec.candidate.id,
                      feasible_marginal=fm.candidate.id.split("@", 1)[0] if fm else None,
                      feasible_marginal_why=why)
    else:
        miss = D.closest_miss(full.audit.infeasible_plans, n)
        hp = full.output.closest_plan
        record.update(branch="closest_miss", closest_miss={
            "template_id": miss[0].candidate.id.split("@", 1)[0],
            "chosen_id": miss[0].candidate.id,
            "rule": ("min worst_overshoot over the exhaustive scope's infeasible "
                     f"plans of {n} devices, ties by candidate id (row 8)"),
            "worst_overshoot": miss[1].worst_overshoot,
            "violations_at_its_own_placement": D._violations(miss[1]),
            "heteropilot_closest_plan_id": hp.candidate.id if hp else None,
            "same_as_heteropilot": bool(hp) and hp.candidate.id == miss[0].candidate.id,
        })
    record["written_at"] = datetime.now(timezone.utc).isoformat()
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-workers", type=int, default=60)
    ap.add_argument("--sim-timeout", type=float, default=1800)
    ap.add_argument("--patterns", nargs="+", default=["normal", "burst"])
    ap.add_argument("--topologies", nargs="+", default=["T1", "T2", "T3"])
    args = ap.parse_args(argv)
    D.HIGH_SCOPE.mkdir(parents=True, exist_ok=True)
    for pattern in args.patterns:
        for topo in args.topologies:
            D.say(f"high scope: {pattern} {topo}")
            rec = one("llama31-8b", pattern, topo, args)
            out = D.HIGH_SCOPE / f"{rec['condition'].rsplit('__', 1)[0]}.json"
            out.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
            s = rec["scope"]
            D.say(f"  {s['representatives']} reps, {s['evaluated']} evaluated, "
                  f"{s['feasible_of_size']} feasible of size; branch {rec['branch']}; "
                  f"K=16 found {s['budget_k16']['feasible_of_size_found']}/"
                  f"{s['budget_k16']['feasible_of_size_in_scope']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
