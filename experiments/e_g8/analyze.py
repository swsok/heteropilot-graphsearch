"""E-G8's analysis: raw runs -> `experiments/results/e_g8_hetero_pd.md`.

**REAL HARDWARE** when the raw is; the banner says which. Three metrics per
direction. Their criteria are preregistration row 11's, and this file
computes them:

1. **Judgement agreement.** Does the search's predicted verdict (met /
   MISSED on TTFT, TPOT and goodput, at the deployed placement) match the
   measured one? Counted per run; a false *met* counts as a miss (E-G5's
   rule).
2. **The contention effect.** The paired mean change in the per-request KV
   interval, `shared` minus `independent` (E-G5 row 7 c/d), against the
   fluid model's predicted change: same sign, and a ratio from 0.5 to 2.
3. **KV exhaustion on the decode side.** `vllm:num_preemptions_total` from
   each engine's `/metrics`, scraped at the end of a run. Report-only.

Latencies, intervals and the drain-corrected goodput are E-G5's own code
(`experiments/e_g5/analyze.py`), imported rather than copied, so the two arms
cannot drift apart.

    python experiments/e_g8/analyze.py [--raw experiments/e_g8/raw] [--out ...]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

ROOT = paths_root.GRAPHSEARCH_ROOT
sys.path.insert(0, str(ROOT / "experiments" / "e_g5"))
import analyze as g5  # noqa: E402
import conditions as C  # noqa: E402

DEFAULT_RAW = ROOT / "experiments" / "e_g8" / "raw"
DEFAULT_OUT = ROOT / "experiments" / "results" / "e_g8_hetero_pd.md"
CONDITIONS = ("independent", "shared")
DIRECTIONS = {"D1": "prefill `s8` (A40) -> decode `a5k2` (RTX A5000)",
              "D2": "prefill `a5k2` (RTX A5000) -> decode `s8` (A40)"}
PREEMPT = re.compile(r"^vllm:num_preemptions_total(?:\{[^}]*\})?\s+([0-9.eE+-]+)", re.M)


def preemptions(path: Path) -> float | None:
    if not path.exists():
        return None
    found = PREEMPT.findall(path.read_text())
    return sum(float(x) for x in found) if found else None


def fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:g}"


def fmt_feasible(x: bool | None) -> str:
    return "unknown" if x is None else str(x)


def verdict(m: dict, slo: dict, floor: float | None) -> dict:
    """Measured met/MISSED on the three axes (TTFT, TPOT, goodput against the
    rate's registered floor), and on latency alone for the auxiliary column.
    Goodput is E-G5's definition, as row 4's floor rule measured it."""
    ttft = m["p99_ttft_ms"] is not None and m["p99_ttft_ms"] <= slo["ttft_max_ms"]
    tpot = m["p99_tpot_ms"] is not None and m["p99_tpot_ms"] <= slo["tpot_max_ms"]
    good = floor is None or m["goodput_rps"] >= floor
    latency = ttft and tpot and m["failed"] == 0
    return {"ttft": ttft, "tpot": tpot, "goodput": good, "latency_met": latency,
            "met": latency and good}


def predicted_latency_met(p: dict, slo: dict) -> bool | None:
    if p.get("p99_ttft_ms") is None or p.get("p99_tpot_ms") is None:
        return None
    return p["p99_ttft_ms"] <= slo["ttft_max_ms"] and p["p99_tpot_ms"] <= slo["tpot_max_ms"]


def load_rule(m: dict, rate: float, preempt: float | None) -> dict:
    """Row 11's load rule: row 7 (b)'s drain-corrected goodput >= 0.9 of
    offered, plus no decode preemption and a KV interval p99 within 2x its
    mean (the threshold was set after seeing the pilot ratios; row 11)."""
    ratio = m["interval_p99_ms"] / m["interval_mean_ms"] if m["interval_mean_ms"] else None
    checks = {"goodput": m["goodput_drain_corrected_rps"] / rate >= 0.9,
              "no_preemption": preempt == 0,
              "interval_ratio": ratio is not None and ratio <= 2.0}
    return {"ratio": ratio, **checks, "passes": all(checks.values())}


def rule_txt(lr: dict) -> str:
    failed = [k for k in ("goodput", "no_preemption", "interval_ratio") if not lr[k]]
    return "passes" if not failed else "fails: " + ", ".join(failed)


#: Row 11 (e): floor sensitivity, analysis only, as row 9 (c) did for E-G5.
SENSITIVITY_FLOORS = (0.75, 0.7)
PRED_GOODPUT = re.compile(r"metric='slo_goodput_rps', target=[0-9.eE+-]+, "
                          r"predicted=([0-9.eE+-]+)")


def predicted_goodput(p: dict) -> float | None:
    """The simulator's goodput, from the goodput violation in the committed
    prediction's detail; None when no goodput violation was recorded."""
    found = PRED_GOODPUT.search(p.get("detail") or "")
    return float(found.group(1)) if found else None


def met_txt(x: bool | None) -> str:
    return "-" if x is None else ("met" if x else "MISSED")


def runs(root: Path) -> list[dict]:
    out = []
    for prov_path in sorted(root.glob("*/*/*/provenance.json")):
        prov = json.loads(prov_path.read_text())
        d = prov_path.parent
        req = d / "pd" / "requests.jsonl"
        out.append({
            "direction": prov["direction"], "condition": prov["condition"],
            "rep": prov["rep"], "state": prov.get("state"),
            "offered_rps": prov.get("offered_rps"), "dir": d,
            "measured": g5.pd_latencies(req) if req.exists() else None,
            "preempt_decode": preemptions(d / "decode.metrics.txt"),
            "preempt_prefill": preemptions(d / "prefill.metrics.txt"),
            "background": prov.get("background"),
        })
    return out


def pairs(root: Path, direction: str) -> list[dict]:
    """`independent` and `shared` of one repetition, request i against request i."""
    out = []
    for a_dir in sorted((root / direction / "independent").glob("*/")):
        b_dir = root / direction / "shared" / a_dir.name
        ra, rb = a_dir / "pd" / "requests.jsonl", b_dir / "pd" / "requests.jsonl"
        if not (ra.exists() and rb.exists()):
            continue
        a, b = g5.pd_intervals(ra), g5.pd_intervals(rb)
        common = sorted(set(a) & set(b))
        if not common:
            continue
        diffs = [b[i] - a[i] for i in common]
        out.append({"rep": int(a_dir.name), "n": len(common),
                    "duty": (json.loads((b_dir / "provenance.json").read_text())
                             .get("background") or {}).get("achieved_duty_cycle"),
                    "mean_a": statistics.mean(a[i] for i in common),
                    "mean_b": statistics.mean(b[i] for i in common),
                    "diff": statistics.mean(diffs),
                    "diff_sd": statistics.stdev(diffs) if len(diffs) > 1 else 0.0})
    return out


def sensitivity(rows: list[dict], pred: dict | None, slo: dict) -> list[str]:
    """Analysis only, not a criterion: the three-axis verdicts re-judged at
    other floors, predicted from the same committed predictions."""
    if pred is None or not any(r["measured"] for r in rows):
        return []
    head = " | ".join(f"floor {f:g}: predicted / measured / agree" for f in SENSITIVITY_FLOORS)
    out = ["", "Floor sensitivity (analysis only; row 11 (e), as row 9 (c)):", "",
           f"| condition | rep | predicted goodput | {head} |",
           "| --- | --- | --- | " + " | ".join("---" for _ in SENSITIVITY_FLOORS) + " |"]
    for r in rows:
        m = r["measured"]
        if m is None:
            continue
        p = pred[r["condition"]]
        g = predicted_goodput(p)
        lat = predicted_latency_met(p, slo)
        cells = []
        for f in SENSITIVITY_FLOORS:
            pm = None if g is None or lat is None else lat and g >= f
            mm = verdict(m, slo, f)["met"]
            ok = "-" if pm is None else ("yes" if pm == mm else "no")
            cells.append(f"{met_txt(pm)} / {met_txt(mm)} / {ok}")
        out.append(f"| {r['condition']} | {r['rep']} | {fmt(g)} | " + " | ".join(cells) + " |")
    return out


def section(raw: Path, direction: str, slo: dict) -> list[str]:
    out = ["", f"## {direction}: {DIRECTIONS[direction]}", ""]
    sel_path = raw / f"selection-{direction}.json"
    if sel_path.exists():
        sel = json.loads(sel_path.read_text())
        if sel.get("rule_applied", True):
            out += [f"Template, fixed for every run: `{sel['chosen']}`, chosen once at seed "
                    f"{sel['seed']} by row 5's rule (predictor `{sel.get('predictor')}`)."]
        else:
            m = sel["mirror_of"]
            out += [f"Template, fixed for every run: `{sel['chosen']}`, the mirror image of "
                    f"{m['direction']}'s `{m['template_id']}`. Row 5's rule **could not be "
                    f"applied**: at the selection rate no template has a simulator verdict, "
                    f"so the selection is `{sel['state']}` -- {sel['reason']}. At the run "
                    "rate the deployed placement *is* simulated, and metric 1 is judged "
                    "against that prediction (row 11 (e))."]
            out += [f"Simulator error: `{e}`" for e in sel.get("simulator_errors", [])]
        out += ["", "| template | state | predicted p99 TTFT | predicted p99 TPOT | feasible |",
                "| --- | --- | --- | --- | --- |"]
        for t in sel["table"]:
            ttft = f"{t['p99_ttft_ms']:.1f} ms" if t["p99_ttft_ms"] is not None else "-"
            tpot = f"{t['p99_tpot_ms']:.1f} ms" if t["p99_tpot_ms"] is not None else "-"
            out.append(f"| `{t['template_id']}` | {t.get('state', '-')} | {ttft} | {tpot} | "
                       f"{fmt_feasible(t['feasible'])} |")
    else:
        out += ["The template has not been selected."]

    ceil_path = raw / f"sim-ceiling-{direction}.json"
    if ceil_path.exists():
        ceil = json.loads(ceil_path.read_text())
        out += ["", "### Simulator ceiling (report-only, not a criterion)", "",
                "The highest rate on the pilot ladder at which the simulator returns a "
                f"verdict for `{ceil['template_id']}`, descending: "
                f"**{fmt(ceil['highest_judged_rps'])} rps** "
                + ", ".join(f"{st['rps']:g} rps {st['state']}" for st in ceil["steps"])
                + ". Read beside the measured onset of preemption in the knee pilot."]

    # The knee pilot and the pilot pairs: excluded from validation.
    knee = []
    for d in sorted((raw / "pilot").glob(f"knee-rps*/{direction}/independent/*/")):
        req = d / "pd" / "requests.jsonl"
        if req.exists():
            prov = json.loads((d / "provenance.json").read_text())
            knee.append((prov["offered_rps"], g5.pd_latencies(req),
                         preemptions(d / "decode.metrics.txt")))
    if knee:
        out += ["", "### Knee pilot (excluded from validation)", "",
                "| offered rps | drain-corrected goodput / offered | goodput (E-G5) | p99 TTFT "
                "| mean interval | interval p99 / mean | decode preemptions | load rule |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        onset = None
        for rate, m, pre in sorted(knee, key=lambda x: x[0]):
            lr = load_rule(m, rate, pre)
            if onset is None and pre:
                onset = rate
            out.append(f"| {rate:g} | {m['goodput_drain_corrected_rps'] / rate:.3f} | "
                       f"{m['goodput_rps']:.3f} | {m['p99_ttft_ms']:.0f} ms | "
                       f"{m['interval_mean_ms']:.1f} ms | {lr['ratio']:.2f} | {fmt(pre)} | "
                       f"{rule_txt(lr)} |")
        out += ["", "Decode preemption starts at **"
                + (f"{onset:g} rps" if onset else "no rate on the sweep") + "** (metric 3)."]
    pp = pairs(raw / "pilot" / "pairs", direction)
    if pp:
        out += ["", "### Pilot pairs (excluded from validation)", "",
                "| rep | requests paired | interval change (mean) | per-request SD |",
                "| --- | --- | --- | --- |"]
        out += [f"| {r['rep']} | {r['n']} | {r['diff']:+.2f} ms | {r['diff_sd']:.2f} ms |"
                for r in pp]

    rows = [r for r in runs(raw / "runs") if r["direction"] == direction]
    if not rows:
        return [*out, "", "The validation runs have not been made."]
    rate = rows[0]["offered_rps"]
    pred_path = raw / f"prediction-{direction}-rps{rate:g}.json"
    pred = json.loads(pred_path.read_text()) if pred_path.exists() else None

    # 1. judgement agreement
    floor = pred.get("min_goodput_rps") if pred else None
    out += ["", f"### 1. Judgement agreement, {rate:g} rps", "",
            f"Three axes: p99 TTFT <= {slo['ttft_max_ms']:g} ms, p99 TPOT <= "
            f"{slo['tpot_max_ms']:g} ms, goodput >= {fmt(floor)} rps (row 4's rule at this "
            "rate, row 11). The latency-only columns are auxiliary.", "",
            "| condition | rep | predicted | measured p99 TTFT | measured p99 TPOT | "
            "measured goodput | measured | agree | predicted (latency) | "
            "measured (latency) | agree (latency) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    agree = false_met = judged = unknown = 0
    lat_agree = lat_judged = 0
    for r in rows:
        m = r["measured"]
        if m is None or pred is None:
            out.append(f"| {r['condition']} | {r['rep']} | - | - | - | - | {r['state']} | - "
                       "| - | - | - |")
            continue
        p = pred[r["condition"]]
        v = verdict(m, slo, floor)
        p_lat = predicted_latency_met(p, slo)
        lat_ok = None if p_lat is None else p_lat == v["latency_met"]
        if lat_ok is not None:
            lat_judged += 1
            lat_agree += lat_ok
        if p["feasible"] is None:
            # unknown_measurement is not a verdict, so it neither agrees nor misses.
            unknown += 1
            p_txt, ok_txt = p.get("state", "unknown_measurement"), "not judged"
        else:
            p_met = bool(p["feasible"])
            ok = p_met == v["met"]
            judged += 1
            agree += ok
            false_met += p_met and not v["met"]
            p_txt, ok_txt = met_txt(p_met), "yes" if ok else "no"
        out.append(f"| {r['condition']} | {r['rep']} | {p_txt} | "
                   f"{m['p99_ttft_ms']:.1f} ms | {m['p99_tpot_ms']:.1f} ms | "
                   f"{m['goodput_rps']:.3f} rps | {met_txt(v['met'])} | {ok_txt} | "
                   f"{met_txt(p_lat)} | {met_txt(v['latency_met'])} | "
                   f"{'-' if lat_ok is None else ('yes' if lat_ok else 'no')} |")
    out += ["", f"Agreement: **{agree} of {judged}**; false met (counted as a miss): "
            f"**{false_met}**."
            + (f" Not judged, the prediction being `unknown_measurement`: **{unknown}**."
               if unknown else "")
            + f" Auxiliary, latency only: {lat_agree} of {lat_judged}."]
    margins = [(c, (slo["ttft_max_ms"] - pred[c]["p99_ttft_ms"]) / slo["ttft_max_ms"])
               for c in CONDITIONS if pred and pred[c].get("p99_ttft_ms") is not None]
    for c, margin in margins:
        if 0 <= margin < 0.01:
            out += ["", f"`{c}`'s predicted p99 TTFT has a {100 * margin:.1f} % margin, so its "
                    "latency-only verdict is **not counted as evidence of prediction "
                    "accuracy**, whichever way it went (row 11 (e))."]
    out += sensitivity(rows, pred, slo)

    # 2. the contention effect
    main = pairs(raw / "runs", direction)
    out += ["", "### 2. The contention effect on the KV interval", ""]
    if not main:
        out.append("No complete independent/shared pair.")
    else:
        out += ["| pair | requests paired | independent mean | shared mean | change | "
                "background duty (shared) |", "| --- | --- | --- | --- | --- | --- |"]
        out += [f"| {r['rep']} | {r['n']} | {r['mean_a']:.2f} ms | {r['mean_b']:.2f} ms | "
                f"{r['diff']:+.2f} ms | {fmt(r['duty'])} |" for r in main]
        effect = statistics.mean(r["diff"] for r in main)
        pv = pred["predicted_interval_change_ms"] if pred else None
        if not pv:
            out += ["", f"Measured change **{effect:+.2f} ms**; no prediction to compare."]
        else:
            ratio = effect / pv
            same = (effect > 0) == (pv > 0)
            met = same and 0.5 <= ratio <= 2.0
            out += ["", f"Mean of the pair changes **{effect:+.2f} ms** against a predicted "
                    f"**{pv:+.2f} ms**: ratio **{ratio:.2f}**, "
                    + ("same sign" if same else "opposite sign")
                    + f". Same sign and 0.5-2x: **{'met' if met else 'NOT met'}**."]

    # 3. KV exhaustion
    out += ["", "### 3. Preemptions (report-only)", "",
            "| condition | rep | decode engine | prefill engine | failed requests |",
            "| --- | --- | --- | --- | --- |"]
    for r in rows:
        failed = r["measured"]["failed"] if r["measured"] else "-"
        out.append(f"| {r['condition']} | {r['rep']} | {fmt(r['preempt_decode'])} | "
                   f"{fmt(r['preempt_prefill'])} | {failed} |")
    return out


E_G5_RESULTS = ROOT / "experiments" / "results" / "e_g5_real_hardware.md"
E_G5_PREDICTION = ROOT / "experiments" / "e_g5" / "raw" / "pd-prediction-rps1.json"
DUTY = 0.6
LINK = {"D1": "s8 -> a5k2", "D2": "a5k2 -> s8"}


def competing_flow_change(independent_xfer_ms: float, duty: float = DUTY) -> float:
    """**Post hoc, not registered** (row 7 (g) named it beforehand): the
    background as a competing flow under processor sharing instead of a
    standing reservation. A transfer that starts while the background is on
    (a fraction `duty` of the time) gets half the link, and otherwise all of
    it, so it takes (1 + duty) times as long on average. The change is
    `duty` times the independent transfer time. Bursts are 0.6 s long and a
    transfer takes tens of ms, so one rarely straddles a burst edge."""
    return duty * independent_xfer_ms


def e_g5_quantities() -> dict[str, str]:
    """E-G5's registered P/D result (row 7), from its own results file."""
    text = E_G5_RESULTS.read_text()
    i = text.index("| quantity | value |")
    out = {}
    for line in text[i:].splitlines()[2:]:
        if not line.startswith("|"):
            break
        k, v = [c.strip() for c in line.strip("|").split("|")]
        out[k] = v
    return out


def summary(raw: Path, slo: dict) -> list[str]:
    """The paper's view: one row per direction x condition, then the effect
    across the three inter-node directions measured so far."""
    rows = runs(raw / "runs")
    if not rows:
        return []
    out = ["", "## Summary", "",
           "Metric 1 per direction and condition (three repetitions each; the latency-only "
           "verdict is the auxiliary column, row 11 (e)); metric 2 on the `shared` row.", "",
           "| run | predicted | measured | agree | predicted (latency) | measured (latency) "
           "| agree (latency) | p99 TTFT predicted | p99 TTFT measured | KV change | "
           "predicted change | ratio |", "| " + " | ".join(["---"] * 12) + " |"]
    totals = {"agree": 0, "lat_agree": 0, "n": 0}
    ttft_meas, ttft_pred = [], []
    for d in DIRECTIONS:
        pred_path = raw / f"prediction-{d}-rps1.json"
        pred = json.loads(pred_path.read_text())
        floor = pred["min_goodput_rps"]
        main = pairs(raw / "runs", d)
        effect = statistics.mean(r["diff"] for r in main) if main else None
        for c in CONDITIONS:
            rs = [r for r in rows if r["direction"] == d and r["condition"] == c
                  and r["measured"]]
            p = pred[c]
            vs = [verdict(r["measured"], slo, floor) for r in rs]
            p_met, p_lat = bool(p["feasible"]), predicted_latency_met(p, slo)
            agree = sum(p_met == v["met"] for v in vs)
            lat = sum(p_lat == v["latency_met"] for v in vs)
            totals["agree"] += agree
            totals["lat_agree"] += lat
            totals["n"] += len(vs)
            meas = sorted(r["measured"]["p99_ttft_ms"] for r in rs)
            ttft_meas += meas
            ttft_pred.append(p["p99_ttft_ms"])
            met_n = sum(v["met"] for v in vs)
            lat_n = sum(v["latency_met"] for v in vs)
            m2 = (f"{effect:+.2f} ms | {pred['predicted_interval_change_ms']:+.2f} ms | "
                  f"{effect / pred['predicted_interval_change_ms']:.2f}"
                  if c == "shared" and effect is not None else "- | - | -")
            out.append(
                f"| {d} {c} | {met_txt(p_met)} | {met_n} of {len(vs)} met | "
                f"{agree} of {len(vs)} | {met_txt(p_lat)} | {lat_n} of {len(vs)} met | "
                f"{lat} of {len(vs)} | {p['p99_ttft_ms']:.0f} ms | "
                f"{statistics.median(meas):.0f} ms [{meas[0]:.0f}, {meas[-1]:.0f}] | {m2} |")

    g5q = e_g5_quantities()
    g5_ind = json.loads(E_G5_PREDICTION.read_text())["independent"]["xfer_ms_mean"]
    three = [("s8 -> s6 (E-G5)", "A40 -> A40", float(g5q["measured change"]),
              float(g5q["SD across pairs"]), float(g5q["predicted change"]), g5_ind)]
    for d in DIRECTIONS:
        pred = json.loads((raw / f"prediction-{d}-rps1.json").read_text())
        main = pairs(raw / "runs", d)
        diffs = [r["diff"] for r in main]
        three.append((f"{d} {LINK[d]}", "A40 -> A5000" if d == "D1" else "A5000 -> A40",
                      statistics.mean(diffs), statistics.stdev(diffs),
                      pred["predicted_interval_change_ms"],
                      pred["independent"]["xfer_ms_mean"]))
    out += ["", "The contention effect on three inter-node directions, each at 1 rps with "
            "three pairs. The last two columns are **post hoc, not registered**: the "
            "background as a competing flow under processor sharing (row 7 (g)), "
            "`0.6 x` the predicted independent transfer.", "",
            "| direction | accelerators | measured change | SD across pairs | "
            "predicted change | ratio | registered criterion | competing flow, post hoc | "
            "ratio to it |", "| " + " | ".join(["---"] * 9) + " |"]
    for name, acc, m, sd, pv, ind in three:
        ps = competing_flow_change(ind)
        ok = (m > 0) == (pv > 0) and 0.5 <= m / pv <= 2.0
        out.append(f"| {name} | {acc} | {m:+.2f} ms | {sd:.2f} ms | {pv:+.2f} ms | "
                   f"{m / pv:.2f} | {'met' if ok else 'NOT met'} | {ps:+.2f} ms | "
                   f"{m / ps:.2f} |")

    ceil = json.loads((raw / "sim-ceiling-D1.json").read_text())
    raises = min(st["rps"] for st in ceil["steps"] if st["state"] != "evaluated")
    onset = None
    for rate in sorted(float(x.name.removeprefix("knee-rps"))
                       for x in (raw / "pilot").glob("knee-rps*")):
        pre = preemptions(raw / "pilot" / f"knee-rps{rate:g}" / "D1" / "independent" / "1"
                          / "decode.metrics.txt")
        if onset is None and pre:
            onset = rate
    ratios = [m / pv for _, _, m, _, pv, _ in three]
    out += ["", "| quantity | value |", "| --- | --- |",
            f"| three-axis agreement | {totals['agree']} of {totals['n']} |",
            f"| latency-only agreement | {totals['lat_agree']} of {totals['n']} |",
            f"| validation runs | {totals['n']} |",
            f"| p99 TTFT measured low | {min(ttft_meas):.0f} |",
            f"| p99 TTFT measured high | {max(ttft_meas):.0f} |",
            f"| p99 TTFT predicted low | {min(ttft_pred):.0f} |",
            f"| p99 TTFT predicted high | {max(ttft_pred):.0f} |",
            f"| goodput floor | {floor:g} |",
            f"| ratio low | {min(ratios):.2f} |",
            f"| ratio high | {max(ratios):.2f} |",
            f"| hardware preemption onset (D1) | {fmt(onset)} |",
            f"| simulator highest judged rate (D1) | {fmt(ceil['highest_judged_rps'])} |",
            f"| simulator raises from (D1) | {raises:g} |"]
    return out


def render(raw: Path) -> str:
    any_measured = any(r["state"] == "measured" for r in runs(raw / "runs"))
    banner = ("> **REAL HARDWARE** -- two nodes, `s8` (A40) and `a5k2` (`a5000-2` GPU 0); "
              "deployed by this experiment's harness, not by heteropilot's "
              "`planner/deploy/` (GS-28)." if any_measured else
              "> **NOT YET MEASURED** -- no validation run exists; nothing below is a "
              "measurement.")
    slo = g5.slo_of("service")
    out = ["# E-G8 -- prefill/decode across two different accelerators", "", banner, "",
           f"SLO (spec S): p99 TTFT <= {slo['ttft_max_ms']} ms, p99 TPOT <= "
           f"{slo['tpot_max_ms']} ms. {C.REQUESTS_PER_RUN} requests per run."]
    out += summary(raw, slo)
    for d in DIRECTIONS:
        out += section(raw, d, slo)
    out += ["", "## Reproducing", "", "```bash",
            "export PYTHONPATH=$PWD:$PWD/vendor/heteropilot",
            "python experiments/e_g8/analyze.py", "```"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.raw))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
