"""GS-38: re-predict every deployed E-G5 row with the corrected adapter.

**Post hoc, and no deployment.** Each row's own placement is simulated again,
with its own seed and spec, after `compile_embedded` stopped reading only the
first rank pair of a TP group. The hardware columns are not touched; this adds
a predicted column beside the original one.

A fresh cache is used on purpose: the envelope key carries `link_bw` only as
a band (`network_class`), so a corrected figure that stayed in its band would
be answered with the uncorrected metrics.

    python experiments/e_g5/repredict.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

from graphsearch import paths_root

paths_root.ensure_importable()
HERE = Path(__file__).resolve().parent
ROOT = paths_root.GRAPHSEARCH_ROOT
OUT = HERE / "raw" / "repredict-gs38.json"
CACHE = ROOT / "outputs" / "cache-eg5-gs38"


def _harness():
    sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location("dab", HERE / "deploy_and_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def one_condition(prov_path: str, sim_timeout: float = 7200) -> list[dict]:
    D = _harness()
    import conditions as C

    from graphsearch.__main__ import cmd_plan_objects, evaluate_placement

    prov = json.loads(Path(prov_path).read_text())
    cond, rep = prov["condition"], prov["rep"]
    topo_key = cond.split("__")[2]
    work = D.WORK / cond / str(rep)
    out = []
    for dep in prov["deployments"]:
        pv = dep.get("placement_verdict")
        if not pv or not pv.get("embedding_id") or dep.get("state") != "measured":
            continue
        stress = dep["label"].endswith("impossible_proven")
        spec_path = work / ("bound-stress.yaml" if stress else "service.yaml")
        args = SimpleNamespace(predictor="sim", num_requests=C.REQUESTS_PER_RUN, rep=rep,
                               sim_timeout=sim_timeout, max_workers=4, budget_sims=0,
                               topology_key=topo_key)
        sub = work / ("gs38-stress" if stress else "gs38")
        pa = D.plan_args(spec_path, sub, args, budget=0, cache=CACHE)
        objects = cmd_plan_objects(pa)
        template_id = pv["embedding_id"].split("@", 1)[0]
        v = evaluate_placement(pa, objects, template_id, set(pv["devices"]))
        out.append({
            "condition": cond, "rep": rep, "label": dep["label"],
            "devices": pv["devices"], "template_id": template_id,
            "embedding_id": v.embedding_id,
            "original_predicted": dep.get("predicted"),
            "state": v.state, "feasible": v.feasible,
            "predicted": D._metrics(v.plan) if v.plan else None,
            "violations": v.violations,
            "detail": v.detail,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs", type=int, default=6)
    # The harness's 1800 s was too short beside 14 concurrent conditions: twelve
    # T3 simulations finished after the predictor had given up on them.
    ap.add_argument("--sim-timeout", type=float, default=7200)
    args = ap.parse_args(argv)
    provs = sorted(str(p) for p in (HERE / "raw").glob("llama31-8b__*/*/provenance.json"))
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(one_condition, p, args.sim_timeout): p for p in provs}
        for f in as_completed(futures):
            rows.extend(f.result())
            print(f"{len(rows)} rows ({Path(futures[f]).parent.parent.name})", flush=True)
    rows.sort(key=lambda r: (r["condition"], r["rep"], r["label"]))
    OUT.write_text(json.dumps({"basis": "GS-38: post-hoc re-prediction with the "
                               "corrected adapter, no deployment", "rows": rows},
                              indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
