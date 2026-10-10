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


def verdict(m: dict, slo: dict) -> dict:
    """Measured met/MISSED per SLO term, from E-G5's latency summary."""
    ttft = m["p99_ttft_ms"] is not None and m["p99_ttft_ms"] <= slo["ttft_max_ms"]
    tpot = m["p99_tpot_ms"] is not None and m["p99_tpot_ms"] <= slo["tpot_max_ms"]
    return {"ttft": ttft, "tpot": tpot, "met": ttft and tpot and m["failed"] == 0}


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
                    "mean_a": statistics.mean(a[i] for i in common),
                    "mean_b": statistics.mean(b[i] for i in common),
                    "diff": statistics.mean(diffs),
                    "diff_sd": statistics.stdev(diffs) if len(diffs) > 1 else 0.0})
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
                    f"applied**: no template has a simulator verdict here, so the prediction "
                    f"is `{sel['state']}` -- {sel['reason']}."]
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
                "| offered rps | drain-corrected goodput / offered | p99 TTFT | mean interval "
                "| decode preemptions |", "| --- | --- | --- | --- | --- |"]
        for rate, m, pre in sorted(knee, key=lambda x: x[0]):
            out.append(f"| {rate:g} | {m['goodput_drain_corrected_rps'] / rate:.3f} | "
                       f"{m['p99_ttft_ms']:.0f} ms | {m['interval_mean_ms']:.1f} ms | "
                       f"{fmt(pre)} |")
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
    out += ["", f"### 1. Judgement agreement, {rate:g} rps", "",
            "| condition | rep | predicted | measured p99 TTFT | measured p99 TPOT | "
            "measured | agree |", "| --- | --- | --- | --- | --- | --- | --- |"]
    agree = false_met = judged = unknown = 0
    for r in rows:
        m = r["measured"]
        if m is None or pred is None:
            out.append(f"| {r['condition']} | {r['rep']} | - | - | - | {r['state']} | - |")
            continue
        if pred[r["condition"]]["feasible"] is None:
            # unknown_measurement is not a verdict, so it neither agrees nor misses.
            v = verdict(m, slo)
            unknown += 1
            out.append(f"| {r['condition']} | {r['rep']} | "
                       f"{pred[r['condition']].get('state', 'unknown_measurement')} | "
                       f"{m['p99_ttft_ms']:.1f} ms | {m['p99_tpot_ms']:.1f} ms | "
                       f"{'met' if v['met'] else 'MISSED'} | not judged |")
            continue
        p_met = bool(pred[r["condition"]]["feasible"])
        v = verdict(m, slo)
        ok = p_met == v["met"]
        judged += 1
        agree += ok
        false_met += p_met and not v["met"]
        out.append(f"| {r['condition']} | {r['rep']} | {'met' if p_met else 'MISSED'} | "
                   f"{m['p99_ttft_ms']:.1f} ms | {m['p99_tpot_ms']:.1f} ms | "
                   f"{'met' if v['met'] else 'MISSED'} | {'yes' if ok else 'no'} |")
    out += ["", f"Agreement: **{agree} of {judged}**; false met (counted as a miss): "
            f"**{false_met}**."
            + (f" Not judged, the prediction being `unknown_measurement`: **{unknown}**."
               if unknown else "")]

    # 2. the contention effect
    main = pairs(raw / "runs", direction)
    out += ["", "### 2. The contention effect on the KV interval", ""]
    if not main:
        out.append("No complete independent/shared pair.")
    else:
        out += ["| pair | requests paired | independent mean | shared mean | change |",
                "| --- | --- | --- | --- | --- |"]
        out += [f"| {r['rep']} | {r['n']} | {r['mean_a']:.2f} ms | {r['mean_b']:.2f} ms | "
                f"{r['diff']:+.2f} ms |" for r in main]
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
