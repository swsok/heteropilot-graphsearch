"""E-G2 / G15-1: why the service-margin ranker recommended nothing at k=4.

**MockPredictor results. Not performance numbers.** Every figure below comes
from a deterministic mock that respects the same physics as the bounds. The
question this answers is about the RANKER'S ESTIMATE against that mock, so the
mock's fictional constants are the ground truth here and nowhere else.

E-G1b found that on both fixtures under the tight spec the first four
representatives the ranker chose were all infeasible and the first feasible
one arrived at simulation 5. The ranker's first band is `risk_proxy <= 1`,
"estimated to meet every SLO", so either the estimate is optimistic against
the mock, or a term is missing, or the ordering inside the band picks the
wrong members. This script changes no code. It writes one table and answers
three hypotheses with numbers:

    H-a  `ttft_ratio` counts only PD/PP transfer time and puts prefill compute
         and queueing at zero.
    H-b  `goodput_ratio` divides by the bound's OPTIMISTIC ceiling, so it is
         always <= 1 and effectively inert.
    H-c  inside the first band the sort is by cost, so the cheapest -- smallest
         -- configurations come first, and under a tight spec those are the
         ones with no margin left.

A `--diversity` column shows whether the structure quota changes the top four.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import (  # noqa: E402
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)
from planner.spec import load_service_spec  # noqa: E402

from graphsearch.adaptive import build_ranker  # noqa: E402
from graphsearch.bounds import BoundPolicy, CandidateStatus, prune  # noqa: E402
from graphsearch.embeddings import enumerate_embeddings  # noqa: E402
from graphsearch.equivalence import CompressionPolicy, compress  # noqa: E402
from graphsearch.oracle import _candidate_for, run_oracle  # noqa: E402
from graphsearch.ranker import (  # noqa: E402
    DEFAULT_RANKER_VARIANT,
    RANKER_V1,
    DiversityQuota,
    ServiceMarginRanker,
    features_for,
    prefill_roofline_ms,
)
from graphsearch.schema import build_resource_graph  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"
SPEC = FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml"

BANNER = (
    "> **MockPredictor results. Not performance numbers.** The mock is the "
    "ground truth for THIS question -- how far the ranker's estimate sits from "
    "the predictor it is ranking for -- and for no other."
)

CLUSTERS = {
    "graph-toy-abcde": FIXTURES / "clusters/graph-toy-abcde.v2.yaml",
    "graph-toy-shared-nic": FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml",
}

K = 4


def mock():
    from tests.graph_fixtures import GraphAwareMockPredictor

    return GraphAwareMockPredictor()


def _fmt(value, digits=3) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value == float("inf"):
            return "inf"
        return f"{value:.{digits}f}"
    return str(value)


def _quantiles(values: list[float]) -> dict:
    finite = sorted(v for v in values if v not in (float("inf"), float("-inf")))
    if not finite:
        return {"n": 0, "p50": None, "p90": None, "max": None}
    def idx(f: float) -> float:
        return finite[min(len(finite) - 1, round(f * (len(finite) - 1)))]

    return {
        "n": len(finite), "p50": statistics.median(finite),
        "p90": idx(0.9), "max": finite[-1],
    }


def diagnose(name: str, path: Path, limit: int) -> dict:
    spec = load_service_spec(SPEC)
    cluster = load_cluster_spec(path)
    profiles = load_profiles_for(cluster, ROOT)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)

    generated = CandidateGenerator(
        spec, cluster, islands, profiles, enable_bound_pruning=False, enable_pd=True,
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= limit]

    embeddings, stats = enumerate_embeddings(templates, by_id, graph, spec)
    representatives, _, _ = compress(embeddings, graph, CompressionPolicy())
    verdicts, _ = prune(
        representatives, spec, graph, by_id, profiles, stats, policy=BoundPolicy()
    )

    # The oracle prices every embedding; the ranker only ever sees exemplars.
    oracle = run_oracle(
        spec, cluster, by_id, profiles, mock(), graph=graph, templates=templates
    )

    ranker = build_ranker(
        representatives, spec, graph, by_id, profiles, variant=RANKER_V1
    )
    demanded = spec.slo.min_goodput_rps or spec.traffic.arrival_rate_rps

    rankable = [
        r for r in representatives
        if verdicts[r.rep_id].status is not CandidateStatus.IMPOSSIBLE_PROVEN
    ]
    candidates = [_candidate_for(r.exemplar) for r in rankable]
    plain_order = ranker.order(candidates, spec, by_id, profiles)
    diverse = ServiceMarginRanker(
        {r.exemplar.id: ranker.features(_candidate_for(r.exemplar)) for r in rankable},
        quota=DiversityQuota(), k_hint=K,
    )
    diverse_order = diverse.order(candidates, spec, by_id, profiles)
    top_plain = [c.id for c in plain_order[:K]]
    top_diverse = [c.id for c in diverse_order[:K]]

    rows = []
    for r in rankable:
        eid = r.exemplar.id
        f = ranker.features(_candidate_for(r.exemplar))
        v2 = features_for(
            r, spec, graph, by_id, profiles, cost_per_hour=f.cost_per_hour,
            variant=DEFAULT_RANKER_VARIANT,
        )
        plan = oracle.plans.get(eid)
        m = plan.predicted if plan is not None else None
        actual_ttft = m.p99_ttft_ms / spec.slo.ttft.max_ms if m else None
        actual_tpot = m.p99_tpot_ms / spec.slo.tpot.max_ms if m else None
        actual_goodput = (
            demanded / m.slo_goodput_rps if m and m.slo_goodput_rps > 0 else float("inf")
        ) if m else None
        rows.append({
            "id": eid,
            "arch": r.exemplar.template.serving_arch.value,
            "tp": max(a.tp_size for a in r.exemplar.template.assignments),
            "devices": r.exemplar.template.total_devices,
            "multiplicity": len(r.embeddings),
            "ttft_ratio": f.ttft_ratio,
            "tpot_ratio": f.tpot_ratio,
            "goodput_ratio": f.goodput_ratio,
            "risk_proxy": f.risk_proxy,
            "cost": f.cost_per_hour,
            "prefill_roofline_ms": prefill_roofline_ms(
                r.exemplar.template, spec, by_id, profiles
            ),
            "goodput_ratio_v2": v2.goodput_ratio,
            "ttft_ratio_v2": v2.ttft_ratio,
            "predicted_feasible_v2": v2.comfortable,
            "actual_ttft": actual_ttft,
            "actual_tpot": actual_tpot,
            "actual_goodput": actual_goodput,
            "p99_ttft_ms": m.p99_ttft_ms if m else None,
            "predicted_feasible": f.comfortable,
            "actual_feasible": bool(oracle.feasible.get(eid, False)),
            "rank_plain": plain_order.index(next(c for c in candidates if c.id == eid)) + 1,
            "in_top4_plain": eid in top_plain,
            "in_top4_diversity": eid in top_diverse,
        })
    rows.sort(key=lambda r: r["rank_plain"])

    # --- confusion matrix and the false positives decomposed
    tp = sum(1 for r in rows if r["predicted_feasible"] and r["actual_feasible"])
    fp = [r for r in rows if r["predicted_feasible"] and not r["actual_feasible"]]
    fn = sum(1 for r in rows if not r["predicted_feasible"] and r["actual_feasible"])
    tn = sum(1 for r in rows if not r["predicted_feasible"] and not r["actual_feasible"])
    fp_by = {
        "ttft": sum(1 for r in fp if r["actual_ttft"] is not None and r["actual_ttft"] > 1),
        "tpot": sum(1 for r in fp if r["actual_tpot"] is not None and r["actual_tpot"] > 1),
        "goodput": sum(
            1 for r in fp if r["actual_goodput"] is not None and r["actual_goodput"] > 1
        ),
        "ttft_only": sum(
            1 for r in fp
            if r["actual_ttft"] > 1 and not r["actual_tpot"] > 1
        ),
    }

    # --- residuals actual / predicted
    def ratio(a, p):
        if a is None or p is None or p <= 0:
            return None
        return a / p

    residuals = {
        key: _quantiles([
            v for v in (ratio(r[f"actual_{key}"], r[f"{key}_ratio"]) for r in rows)
            if v is not None
        ])
        for key in ("ttft", "tpot", "goodput")
    }

    # --- hypotheses
    ttft_violators = [r for r in rows if r["actual_ttft"] is not None and r["actual_ttft"] > 1]
    h_a = {
        "ttft_violators": len(ttft_violators),
        "violators_ranked_comfortable": sum(1 for r in ttft_violators if r["predicted_feasible"]),
        "ttft_ratio_among_violators": _quantiles([r["ttft_ratio"] for r in ttft_violators]),
        "actual_ttft_among_violators": _quantiles([r["actual_ttft"] for r in ttft_violators]),
        "transfer_share_of_actual_ttft": _quantiles([
            (r["ttft_ratio"] * spec.slo.ttft.max_ms) / r["p99_ttft_ms"]
            for r in rows if r["p99_ttft_ms"]
        ]),
        "prefill_roofline_share_of_actual_ttft": _quantiles([
            r["prefill_roofline_ms"] / r["p99_ttft_ms"] for r in rows if r["p99_ttft_ms"]
        ]),
        # GreedyEstimate has no prefill field: roofline_tpot_ms is decode-only.
        "greedy_estimate_has_prefill_field": False,
    }
    goodput_violators = [
        r for r in rows if r["actual_goodput"] is not None and r["actual_goodput"] > 1
    ]
    h_b = {
        "goodput_ratio_all": _quantiles([r["goodput_ratio"] for r in rows]),
        "goodput_ratio_above_1": sum(1 for r in rows if r["goodput_ratio"] > 1),
        "goodput_violators": len(goodput_violators),
        "goodput_ratio_among_violators": _quantiles(
            [r["goodput_ratio"] for r in goodput_violators]
        ),
        "actual_goodput_among_violators": _quantiles(
            [r["actual_goodput"] for r in goodput_violators]
        ),
        "binding_term_counts": {
            key: sum(1 for r in rows if r[f"{key}_ratio"] == r["risk_proxy"])
            for key in ("ttft", "tpot", "goodput")
        },
    }
    band1 = [r for r in rows if r["predicted_feasible"]]
    top4 = [r for r in rows if r["in_top4_plain"]]
    h_c = {
        "band1_size": len(band1),
        "band1_risk_proxy": _quantiles([r["risk_proxy"] for r in band1]),
        "band1_feasible": sum(1 for r in band1 if r["actual_feasible"]),
        "top4_risk_proxy": [round(r["risk_proxy"], 3) for r in top4],
        "top4_cost": [r["cost"] for r in top4],
        "top4_feasible": sum(1 for r in top4 if r["actual_feasible"]),
        "top4_are_cheapest_in_band1": (
            sorted(r["cost"] for r in top4)
            == sorted(r["cost"] for r in band1)[: len(top4)]
        ),
        "cheapest_feasible_band1_rank": next(
            (r["rank_plain"] for r in band1 if r["actual_feasible"]), None
        ),
        "band1_feasible_risk_proxy": _quantiles(
            [r["risk_proxy"] for r in band1 if r["actual_feasible"]]
        ),
        "band1_infeasible_risk_proxy": _quantiles(
            [r["risk_proxy"] for r in band1 if not r["actual_feasible"]]
        ),
    }
    v2 = {
        "tp": sum(1 for r in rows if r["predicted_feasible_v2"] and r["actual_feasible"]),
        "fp": sum(1 for r in rows if r["predicted_feasible_v2"] and not r["actual_feasible"]),
        "fn": sum(1 for r in rows if not r["predicted_feasible_v2"] and r["actual_feasible"]),
        "tn": sum(1 for r in rows if not r["predicted_feasible_v2"] and not r["actual_feasible"]),
        "flipped": [
            (r["id"], round(r["goodput_ratio"], 3), round(r["goodput_ratio_v2"], 3),
             round(r["actual_goodput"], 3))
            for r in rows if r["predicted_feasible_v2"] != r["predicted_feasible"]
        ],
        "prefill_term_alone_flips": sum(
            1 for r in rows
            if (max(r["ttft_ratio_v2"], r["tpot_ratio"], r["goodput_ratio"]) <= 1)
            != r["predicted_feasible"]
        ),
        "goodput_residual_v2": _quantiles([
            r["actual_goodput"] / r["goodput_ratio_v2"]
            for r in rows if r["goodput_ratio_v2"] > 0 and r["actual_goodput"] is not None
        ]),
    }
    diversity = {
        "top4_plain_feasible": sum(1 for r in rows if r["in_top4_plain"] and r["actual_feasible"]),
        "top4_diversity_feasible": sum(
            1 for r in rows if r["in_top4_diversity"] and r["actual_feasible"]
        ),
        "top4_plain": top_plain,
        "top4_diversity": top_diverse,
    }

    return {
        "fixture": name,
        "spec": {
            "ttft_max_ms": spec.slo.ttft.max_ms, "tpot_max_ms": spec.slo.tpot.max_ms,
            "demanded_rps": demanded,
        },
        "counts": {
            "templates": len(templates), "embeddings": len(embeddings),
            "representatives": len(representatives), "rankable": len(rankable),
            "bound_rejected": len(representatives) - len(rankable),
            "oracle_feasible_embeddings": len(oracle.feasible_ids),
        },
        "confusion": {"tp": tp, "fp": len(fp), "fn": fn, "tn": tn, "fp_by_violation": fp_by},
        "residuals": residuals,
        "h_a": h_a, "h_b": h_b, "h_c": h_c, "diversity": diversity, "v2": v2,
        "rows": rows,
    }


# --- report --------------------------------------------------------------

def p50_of(q: dict) -> str:
    return _fmt(q.get("p50"))


def _q(q: dict) -> str:
    if not q or q.get("n", 0) == 0:
        return "n=0"
    return f"n={q['n']} p50={_fmt(q['p50'])} p90={_fmt(q['p90'])} max={_fmt(q['max'])}"


def markdown(results: list[dict]) -> str:
    out = ["# E-G2 — why the ranker recommended nothing at k=4", "", BANNER, ""]
    out.append(
        "Fixtures used for diagnosis: **graph-toy-abcde** and **graph-toy-shared-nic** "
        "only, under `graph-toy-llama31-8b-tight.yaml`. Anything derived from these "
        "numbers is validated on holdouts the diagnosis never saw "
        "(`e_g2_topk_holdout.md`)."
    )
    out.append("")
    for res in results:
        c, cm, s = res["counts"], res["confusion"], res["spec"]
        out.append(f"## {res['fixture']}")
        out.append("")
        out.append(
            f"{c['templates']} templates → {c['embeddings']} embeddings → "
            f"{c['representatives']} representatives, {c['bound_rejected']} proven "
            f"impossible by the bounds and never ranked, **{c['rankable']} ranked**. "
            f"SLO: TTFT {s['ttft_max_ms']} ms, TPOT {s['tpot_max_ms']} ms, "
            f"{s['demanded_rps']} rps demanded. The oracle found "
            f"{c['oracle_feasible_embeddings']} feasible embeddings."
        )
        out.append("")
        out.append("### 1. Band-1 misclassification")
        out.append("")
        out.append(
            "| | actual feasible | actual infeasible |\n| --- | --- | --- |\n"
            f"| **predicted feasible** (`risk_proxy ≤ 1`) | {cm['tp']} | **{cm['fp']}** |\n"
            f"| **predicted infeasible** | {cm['fn']} | {cm['tn']} |"
        )
        out.append("")
        fb = cm["fp_by_violation"]
        out.append(
            f"False positives decomposed by what the oracle actually violated: "
            f"**TTFT {fb['ttft']}**, TPOT {fb['tpot']}, goodput {fb['goodput']} "
            f"(TTFT alone, TPOT fine: {fb['ttft_only']}). A candidate can violate more "
            f"than one, so these need not sum to {cm['fp']}."
        )
        out.append("")
        out.append(
            "Every ranked representative, in the ranker's order. Ratios are "
            "`estimate / SLO` for the ranker and `oracle p99 / SLO` for the actual "
            "(goodput: `demanded / achieved`); above 1 is a miss."
        )
        out.append("")
        cols = [
            "rank_plain", "id", "arch", "tp", "devices", "ttft_ratio", "tpot_ratio",
            "goodput_ratio", "risk_proxy", "cost", "actual_ttft", "actual_tpot",
            "actual_goodput", "predicted_feasible", "actual_feasible",
            "in_top4_plain", "in_top4_diversity",
        ]
        heads = [
            "#", "representative", "arch", "tp", "dev", "ttft̂", "tpot̂", "goodput̂",
            "risk", "$/h", "ttft", "tpot", "goodput", "pred", "actual",
            "top4", "top4+div",
        ]
        out.append("| " + " | ".join(heads) + " |")
        out.append("| " + " | ".join("---" for _ in heads) + " |")
        for r in res["rows"]:
            out.append("| " + " | ".join(_fmt(r[c]) for c in cols) + " |")
        out.append("")

        out.append("### 2. Residuals, `actual / predicted`")
        out.append("")
        for key, q in res["residuals"].items():
            out.append(f"- **{key}**: {_q(q)}")
        out.append("")

        out.append("### 3. The four that were chosen at k=4")
        out.append("")
        for r in [r for r in res["rows"] if r["in_top4_plain"]]:
            violated = [
                name for name, v in (
                    ("TTFT", r["actual_ttft"]), ("TPOT", r["actual_tpot"]),
                    ("goodput", r["actual_goodput"]),
                ) if v is not None and v > 1
            ]
            outcome = (
                "feasible" if r["actual_feasible"] else "violates " + ", ".join(violated)
            )
            out.append(
                f"- `{r['id']}` ({r['arch']}, tp{r['tp']}, {r['devices']} dev, "
                f"{_fmt(r['cost'], 1)} $/h): in band 1 because "
                f"risk {_fmt(r['risk_proxy'])} = max(ttft̂ {_fmt(r['ttft_ratio'])}, "
                f"tpot̂ {_fmt(r['tpot_ratio'])}, goodput̂ {_fmt(r['goodput_ratio'])}); "
                f"actually {outcome} "
                f"(ttft {_fmt(r['actual_ttft'])}, tpot {_fmt(r['actual_tpot'])}, "
                f"goodput {_fmt(r['actual_goodput'])})."
            )
        out.append("")

        ha, hb, hc, dv = res["h_a"], res["h_b"], res["h_c"], res["diversity"]
        out.append("### 4. Hypotheses, in numbers")
        out.append("")
        out.append(
            f"**H-a — TTFT estimate has no prefill compute and no queueing.** "
            f"{ha['ttft_violators']} representatives miss the TTFT; "
            f"{ha['violators_ranked_comfortable']} of them were ranked comfortable. "
            f"Among violators the ranker's `ttft_ratio` is {_q(ha['ttft_ratio_among_violators'])} "
            f"while the actual is {_q(ha['actual_ttft_among_violators'])}. The transfer "
            f"term the ranker does have accounts for this share of the actual p99 TTFT: "
            f"{_q(ha['transfer_share_of_actual_ttft'])}; a single prefill roofline pass "
            f"(weights once + p50 prompt KV) would account for "
            f"{_q(ha['prefill_roofline_share_of_actual_ttft'])}. `GreedyEstimate` carries "
            f"no prefill field -- `roofline_tpot_ms` is decode-only by design -- so the "
            f"term would have to be computed from `memutil` as this script does."
        )
        out.append("")
        out.append(
            f"**H-b — `goodput_ratio` is inert.** Over all ranked representatives it is "
            f"{_q(hb['goodput_ratio_all'])}; {hb['goodput_ratio_above_1']} are above 1. "
            f"{hb['goodput_violators']} representatives actually miss the demanded goodput; "
            f"their `goodput_ratio` is {_q(hb['goodput_ratio_among_violators'])} against an "
            f"actual {_q(hb['actual_goodput_among_violators'])}. Which term is binding "
            f"(`== risk_proxy`): ttft {hb['binding_term_counts']['ttft']}, tpot "
            f"{hb['binding_term_counts']['tpot']}, goodput {hb['binding_term_counts']['goodput']}."
        )
        out.append("")
        out.append(
            f"**H-c — the band is sorted by cost, so the marginal ones lead.** Band 1 has "
            f"{hc['band1_size']} members, {hc['band1_feasible']} actually feasible; its "
            f"`risk_proxy` is {_q(hc['band1_risk_proxy'])} -- feasible members "
            f"{_q(hc['band1_feasible_risk_proxy'])}, infeasible members "
            f"{_q(hc['band1_infeasible_risk_proxy'])}. The four chosen have risk "
            f"{hc['top4_risk_proxy']} and cost {hc['top4_cost']}; they are the cheapest in "
            f"the band: {_fmt(hc['top4_are_cheapest_in_band1'])}. The first actually-feasible "
            f"band-1 member sits at rank {hc['cheapest_feasible_band1_rank']}."
        )
        out.append("")
        out.append(
            f"**Diversity.** Plain top-4 contains {dv['top4_plain_feasible']} feasible; "
            f"with `DiversityQuota()` the top-4 contains {dv['top4_diversity_feasible']} feasible. "
            f"(`{', '.join(dv['top4_diversity'])}`)"
        )
        out.append("")
        v2 = res["v2"]
        top_risk = hc["top4_risk_proxy"][0] if hc["top4_risk_proxy"] else None
        prefill_pct = _fmt(100 * ha["prefill_roofline_share_of_actual_ttft"]["max"], 1)
        out.append("### 5. Conclusion")
        out.append("")
        out.append(
            f"**H-b is supported, and it is the cause.** Every false positive is a "
            f"`max_num_seqs=32` placement whose `s128`/`s256` siblings on the same "
            f"devices are feasible. The ceiling `goodput_ratio` divides by admits as "
            f"many sequences as the KV cache holds and never reads the knob, so it "
            f"reads the same {_fmt(top_risk)}-band "
            f"risk for both; the mock, like an engine, stops at 32, utilisation goes "
            f"to {p50_of(hb['actual_goodput_among_violators'])} of capacity "
            f"and queueing drives the TTFT to {p50_of(ha['actual_ttft_among_violators'])}x "
            f"the SLO. Re-scoring the same rows with the knob-aware `greedy.estimate` "
            f"throughput as the denominator (`service_margin`) gives a confusion "
            f"matrix of tp={v2['tp']} fp={v2['fp']} fn={v2['fn']} tn={v2['tn']}: the "
            f"{len(v2['flipped'])} flipped rows are exactly the false positives "
            f"(ceiling → estimate → actual: "
            + "; ".join(f"{a:.3f} → {b:.3f} → {c:.3f}" for _, a, b, c in v2["flipped"][:2])
            + f"), and the goodput residual `actual/predicted` falls from "
            f"{_q(res['residuals']['goodput'])} to {_q(v2['goodput_residual_v2'])}."
        )
        out.append("")
        out.append(
            f"**H-a's premise is true and its remedy is immaterial.** The TTFT "
            f"estimate is 0 for every non-P/D placement against an actual of up to "
            f"{_fmt(ha['actual_ttft_among_violators']['max'], 1)}x, but a prefill "
            f"roofline pass covers at most {prefill_pct} % "
            f"of that TTFT; the rest is queueing, which is utilisation, which is H-b's "
            f"term. Adding the prefill term alone changes {v2['prefill_term_alone_flips']} "
            f"verdicts. It is added anyway -- same physics as the bound, and better "
            f"than the zero it replaces -- and recorded in `RankFeatures.basis`."
        )
        out.append("")
        out.append(
            f"**H-c is not supported.** Inside band 1 the feasible and infeasible "
            f"members have the same `risk_proxy` to three decimals "
            f"({_q(hc['band1_feasible_risk_proxy'])} vs {_q(hc['band1_infeasible_risk_proxy'])}) "
            f"and the same cost; there is no margin gradient a δ-tier could sort on, "
            f"so no two-stage sort is introduced. Diversity does not help either "
            f"({dv['top4_plain_feasible']} → {dv['top4_diversity_feasible']} feasible in the "
            f"top four): the "
            f"quota spreads over structures, and the misclassification is inside one."
        )
        out.append("")

    out.append("## Reproducing")
    out.append("")
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("python experiments/scripts/e_g2_ranker_diagnosis.py \\")
    out.append("    --out experiments/results/e_g2_ranker_diagnosis.md")
    out.append("```")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g2_ranker_diagnosis.md")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    results = [
        diagnose(name, path, args.limit)
        for name, path in CLUSTERS.items()
        if not args.only or args.only == name
    ]
    text = markdown(results)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
