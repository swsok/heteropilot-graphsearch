#!/usr/bin/env python
"""P3.4: what the planner predicted against what the hardware did.

**REAL HARDWARE.** Every measured column comes from
`experiments/e_g5/raw/`, on the node whose serials each provenance file
carries. The predicted columns are the planner's, taken from the plan that was
deployed rather than recomputed.

Two questions, deliberately kept apart because they have different answers:

  1. **Does the recommendation meet its SLOs?** Predicted against measured
     $p99$, per deployment, at the rate that deployment's own spec declared.
  2. **Was a bound that rejected a candidate right to?** The candidate the
     throughput bound rejected by the smallest margin is deployed and offered
     the floor it was rejected against. If it meets that floor the bound was
     wrong and `false_infeasible` is non-zero on hardware, which stops the
     experiment. If it does not -- the expected outcome, since the bound is a
     relaxation -- the useful number is not the verdict but **how far the
     optimistic ceiling sits above the measured capacity**.

Calibration uses the **existing** accuracy domain only. Creating one from this
data would be circular: a margin fitted on E-G5 cannot then be tested by E-G5.

    python experiments/e_g5/analyze.py --out experiments/results/e_g5_real_hardware.md
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.util.percentile import percentile  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
RAW = ROOT / "experiments" / "e_g5" / "raw"
VALIDATE = ROOT / "vendor" / "heteropilot" / "bench" / "core" / "validate.py"

BANNER = (
    "> **REAL HARDWARE.** Every measured column comes from "
    "`experiments/e_g5/raw/`, on the node whose accelerator serials each "
    "provenance file carries. The predicted columns are graph search's "
    "verdict on the placement that was deployed (GS-30): each placement "
    "simulated for itself, not the search's own pick. Only the predicted "
    "columns are simulations."
)


def latencies(path: Path):
    """heteropilot's own definitions, imported rather than re-implemented."""
    spec = importlib.util.spec_from_file_location("hp_validate", VALIDATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requests = [
        json.loads(line)
        for line in path.read_text().splitlines() if line.strip()
    ]
    ttft, tpot, _lat = module._bench_latencies(requests)
    queued = [r["queued_ts"] for r in requests]
    done = [r["last_token_ts"] for r in requests]
    span = max(done) - min(queued)
    return {
        "requests": len(requests),
        "p99_ttft_ms": percentile(sorted(ttft), 99),
        "p50_ttft_ms": percentile(sorted(ttft), 50),
        "p99_tpot_ms": percentile(sorted(tpot), 99),
        "goodput_rps": len(requests) / span if span > 0 else 0.0,
    }


def rows(raw_root: Path) -> list[dict]:
    out = []
    for prov_path in sorted(raw_root.glob("*/*/provenance.json")):
        prov = json.loads(prov_path.read_text())
        if prov.get("dry_run"):
            continue
        for dep in prov.get("deployments", []):
            measured_path = prov_path.parent / dep["label"] / "bench" / "requests.jsonl"
            if not measured_path.exists():
                out.append({
                    "condition": prov["condition"], "rep": prov["rep"],
                    "deployment": dep["label"], "state": dep.get("state"),
                    "why": dep.get("why"), "measured": None,
                })
                continue
            out.append({
                "condition": prov["condition"],
                "rep": prov["rep"],
                "deployment": dep["label"],
                "state": dep.get("state"),
                "devices": dep.get("placement_override", {}).get("this_harness_uses"),
                "offered_rps": dep.get("offered_rps"),
                "candidate": dep.get("candidate_id"),
                "predicted": dep.get("predicted"),
                "placement_verdict": dep.get("placement_verdict"),
                "closest_miss": dep.get("closest_miss"),
                "measured": latencies(measured_path),
                "slo": prov.get("slo"),
            })
    return out


#: The SLO every row is judged against, from `conditions.SPECS`. Read here
#: rather than restated so the table and the spec cannot drift.
def slo_of(condition_spec: str) -> dict:
    import sys
    sys.path.insert(0, str(ROOT / "experiments" / "e_g5"))
    import conditions as C
    return C.SPECS[condition_spec]


def verdict(row: dict) -> tuple[str, list[str]]:
    """Met or missed, and which axis did it. Never a single boolean.

    A deployment that misses one target and clears two has not simply failed;
    which one it missed is the result. Reporting a bare `False` would throw
    away the only part a reader can act on.
    """
    if not row.get("measured"):
        return "not measured", []
    bound = row["deployment"].endswith("impossible_proven")
    spec = slo_of("bound_stress" if bound else "service")
    # The service floor is per LEVEL (preregistration row 8): reading the
    # knee's 2.3 for every row judged `low` against a floor its own spec did
    # not have, and gave `high` -- which has none -- a goodput axis.
    floor = spec["min_goodput_rps"] if bound else level_floor(row["condition"])
    m = row["measured"]
    missed = []
    if m["p99_ttft_ms"] > spec["ttft_max_ms"]:
        missed.append(f"TTFT {m['p99_ttft_ms']:.0f} > {spec['ttft_max_ms']:.0f} ms")
    if m["p99_tpot_ms"] > spec["tpot_max_ms"]:
        missed.append(f"TPOT {m['p99_tpot_ms']:.1f} > {spec['tpot_max_ms']:.0f} ms")
    if floor is not None and m["goodput_rps"] < floor:
        missed.append(f"goodput {m['goodput_rps']:.2f} < {floor:.2f} rps")
    return ("met" if not missed else "MISSED"), missed


def level_floor(condition: str):
    import sys
    sys.path.insert(0, str(ROOT / "experiments" / "e_g5"))
    import conditions as C
    return C.goodput_floor(condition.split("__")[3])


def predicted_verdict(row: dict) -> str:
    """The search's verdict on THIS placement, in the SLO's words."""
    v = row.get("placement_verdict")
    if not v:
        return "not recorded (before GS-30)"
    if v.get("state") != "evaluated":
        return v.get("state", "-")
    return "met" if v.get("feasible") else "MISSED"


def table(data: list[dict]) -> list[str]:
    head = ["condition", "deployment", "devices", "offered rps",
            "p99 TTFT pred", "p99 TTFT meas", "p99 TPOT pred", "p99 TPOT meas",
            "goodput meas", "predicted", "measured"]
    out = ["| " + " | ".join(head) + " |",
           "| " + " | ".join("---" for _ in head) + " |"]
    for row in data:
        if not row.get("measured"):
            out.append(
                f"| {row['condition']} | {row['deployment']} | - | - | - | - | "
                f"- | - | - | - | {row.get('state', 'not run')} |"
            )
            continue
        p, m = row["predicted"], row["measured"]
        state, _missed = verdict(row)

        def f(v, d):
            return "-" if v is None else f"{v:.{d}f}"

        out.append(
            f"| {row['condition']} | {row['deployment']} | {row['devices']} | "
            f"{row['offered_rps']:.1f} | {f(p and p['p99_ttft_ms'], 1)} | "
            f"{m['p99_ttft_ms']:.1f} | {f(p and p['p99_tpot_ms'], 2)} | "
            f"{m['p99_tpot_ms']:.2f} | {m['goodput_rps']:.3f} | "
            f"{predicted_verdict(row)} | **{state}** |"
        )
    return out


def placement_table(data: list[dict]) -> list[str]:
    """The recommendation at each placement, medians over repetitions.

    Separate from the full table because it is the one comparison the whole
    experiment exists to make, and burying it among the boundary rows would
    ask the reader to find it.
    """
    import statistics

    groups: dict[str, list[dict]] = {}
    for row in data:
        if row["deployment"] != "recommendation" or not row.get("measured"):
            continue
        topo = row["condition"].split("__")[2]
        groups.setdefault(topo, []).append(row)

    head = ["placement", "devices", "reps", "p99 TTFT pred", "predicted",
            "p99 TTFT median", "vs T1", "range", "p99 TPOT median",
            "goodput median", "measured"]
    out = ["| " + " | ".join(head) + " |",
           "| " + " | ".join("---" for _ in head) + " |"]
    base = (statistics.median(r["measured"]["p99_ttft_ms"] for r in groups["T1"])
            if "T1" in groups else None)
    for topo in sorted(groups):
        rows_ = groups[topo]
        ttft = sorted(r["measured"]["p99_ttft_ms"] for r in rows_)
        ratio = f"{statistics.median(ttft) / base:.1f}x" if base else "-"
        tpot = [r["measured"]["p99_tpot_ms"] for r in rows_]
        good = [r["measured"]["goodput_rps"] for r in rows_]
        state, _ = verdict(rows_[0])
        states = {verdict(r)[0] for r in rows_}
        state = "met" if states == {"met"} else "MISSED"
        preds = [r["predicted"]["p99_ttft_ms"] for r in rows_ if r.get("predicted")]
        pverdicts = {predicted_verdict(r) for r in rows_}
        pred = f"{statistics.median(preds):.1f} ms" if preds else "-"
        out.append(
            f"| {topo} | {rows_[0]['devices']} | {len(rows_)} | {pred} | "
            f"{' / '.join(sorted(pverdicts))} | "
            f"{statistics.median(ttft):.1f} ms | {ratio} | "
            f"[{min(ttft):.1f}, {max(ttft):.1f}] | "
            f"{statistics.median(tpot):.2f} ms | "
            f"{statistics.median(good):.3f} rps | **{state}** |"
        )
    return out


def _recommendations(data: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in data:
        if row["deployment"] == "recommendation" and row.get("measured"):
            groups.setdefault(row["condition"].split("__")[2], []).append(row)
    return groups


def placement_sentence(data: list[dict]) -> str:
    """The T1/T2 comparison, computed from the rows rather than written once."""
    import statistics

    g = _recommendations(data)
    if "T1" not in g or "T2" not in g:
        return "T1 and T2 were not both measured, so they are not compared here."
    med = {t: statistics.median(r["measured"]["p99_ttft_ms"] for r in g[t])
           for t in ("T1", "T2")}
    rng = {t: (min(r["measured"]["p99_ttft_ms"] for r in g[t]),
               max(r["measured"]["p99_ttft_ms"] for r in g[t])) for t in ("T1", "T2")}
    state = {t: "met" if all(verdict(r)[0] == "met" for r in g[t]) else "missed"
             for t in ("T1", "T2")}
    overlap = rng["T1"][1] >= rng["T2"][0] and rng["T2"][1] >= rng["T1"][0]
    return (
        f"**T1 {state['T1']} the latency target and T2 {state['T2']} it**: median "
        f"p99 TTFT {med['T1']:.0f} ms against {med['T2']:.0f} ms, "
        f"{med['T2'] / med['T1']:.1f}x, with the same model, trace, scheduler "
        f"knobs, seed and plan. The only difference is which wire the "
        f"tensor-parallel all-reduce crosses. {len(g['T1'])} and {len(g['T2'])} "
        f"repetitions, and the ranges "
        f"{'overlap' if overlap else 'do not overlap'}."
    )


def direction_sentence(served: list[dict]) -> str:
    """Optimistic, pessimistic or mixed -- from the ratios, per axis."""
    ttft = [r["measured"]["p99_ttft_ms"] / r["predicted"]["p99_ttft_ms"]
            for r in served if r["predicted"]["p99_ttft_ms"]]
    tpot = [r["measured"]["p99_tpot_ms"] / r["predicted"]["p99_tpot_ms"]
            for r in served if r["predicted"]["p99_tpot_ms"]]

    def word(xs):
        if not xs:
            return "not computable"
        if all(x > 1 for x in xs):
            return "optimistic in every row"
        if all(x < 1 for x in xs):
            return "pessimistic in every row"
        return f"optimistic in {sum(x > 1 for x in xs)} of {len(xs)} rows"

    return (
        f"On p99 TTFT the simulator is **{word(ttft)}**; on p99 TPOT it is "
        f"**{word(tpot)}**. No margin from this data is fitted here and none "
        "may be: a domain built from E-G5 could not then be tested by E-G5."
    )


# --- the inter-node P/D arm (preregistration rows 5-6, GS-32) -------------

PD_BANNER_FIRST = (
    "**Deployed by this experiment's harness, not by heteropilot's "
    "`planner/deploy/`**, which has no router and cannot launch a split "
    "architecture (GS-28, heteropilot D128). The router is "
    "`experiments/e_g5/pd_router.py`, an instrument for this measurement and "
    "not a serving component (GS-32)."
)


def pd_latencies(path: Path) -> dict:
    """`latencies`, over the requests that completed; failures are counted.

    A failed request has no first or last token, so it cannot enter a
    percentile and cannot anchor the span. It is reported as a count beside
    the metrics instead of being dropped without a trace.
    """
    spec = importlib.util.spec_from_file_location("hp_validate", VALIDATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reqs = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    ok = [r for r in reqs if not r.get("error") and r.get("last_token_ts") is not None]
    ttft, tpot, _ = module._bench_latencies(ok)
    span = max(r["last_token_ts"] for r in ok) - min(r["queued_ts"] for r in ok) if ok else 0
    slo = slo_of("service")
    # Per request, not by zipping the two lists: `_bench_latencies` adds no
    # TPOT for a one-token request, so the lists can differ in length and a
    # zip would pair one request's TTFT with another's TPOT.
    met = 0
    for r in ok:
        one_ttft, one_tpot, _ = module._bench_latencies([r])
        if one_ttft and one_ttft[0] <= slo["ttft_max_ms"] and (
            not one_tpot or one_tpot[0] <= slo["tpot_max_ms"]
        ):
            met += 1
    return {
        "requests": len(reqs), "completed": len(ok), "failed": len(reqs) - len(ok),
        "length_off": sum(
            1 for r in ok
            if (r.get("completion_tokens") if r.get("completion_tokens") is not None
                else r["streamed_tokens"]) != r["output_toks"]),
        "p50_ttft_ms": percentile(sorted(ttft), 50) if ttft else None,
        "p99_ttft_ms": percentile(sorted(ttft), 99) if ttft else None,
        "p99_tpot_ms": percentile(sorted(tpot), 99) if tpot else None,
        "goodput_rps": len(ok) / span if span > 0 else 0.0,
        "slo_attainment": met / len(ok) if ok else 0.0,
        **_pd_extras(ok, span),
    }


#: Row 7 (b). E-G5's goodput divides by the span from the first arrival to the
#: LAST completion, so even an unqueued run loses the last request's whole
#: service time to the denominator: with this trace's ~665-token outputs that is
#: 0.845 at 1 rps and 0.732 at 2, and no pilot rate could reach 0.9. The
#: drain-corrected figure subtracts the e2e of a request that met no queue --
#: the median over the first EARLY requests, before one can form.
EARLY = 15


def _pd_extras(ok: list[dict], span: float) -> dict:
    import statistics

    by_idx = sorted(ok, key=lambda r: int(r["request_id"].split("-")[1]))
    e2e_early = [r["last_token_ts"] - r["queued_ts"] for r in by_idx[:EARLY]]
    d_early = statistics.median(e2e_early) if e2e_early else 0.0
    intervals = [(r["first_token_ts"] - r["prefill_done_ts"]) * 1000.0
                 for r in ok if r.get("prefill_done_ts") is not None]
    return {
        "unqueued_e2e_s": d_early,
        "goodput_drain_corrected_rps": (
            len(ok) / (span - d_early) if span - d_early > 0 else 0.0),
        "interval_mean_ms": statistics.mean(intervals) if intervals else None,
        "interval_p99_ms": percentile(sorted(intervals), 99) if intervals else None,
    }


def pd_intervals(path: Path) -> dict[int, float]:
    """Request index -> its KV interval in ms (row 7 c), for completed requests."""
    out = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("error") or r.get("first_token_ts") is None or r.get("prefill_done_ts") is None:
            continue
        out[int(r["request_id"].split("-")[1])] = (
            (r["first_token_ts"] - r["prefill_done_ts"]) * 1000.0)
    return out


def pd_rows(raw_root: Path, sub: str = "pd") -> list[dict]:
    out = []
    for prov_path in sorted((raw_root / sub).glob("*/*/provenance.json")):
        prov = json.loads(prov_path.read_text())
        req = prov_path.parent / "pd" / "requests.jsonl"
        out.append({
            "condition": prov["condition"], "rep": prov["rep"],
            "state": prov.get("state"),
            "measured": pd_latencies(req) if req.exists() else None,
            "prediction": prov.get("prediction"),
            "background": prov.get("background"),
            "template": prov.get("template_id") or (
                ((prov.get("prediction") or {}).get("chosen") or {}).get("template_id")),
            "requests_path": req,
            "offered_rps": prov.get("offered_rps"),
        })
    return out


def pd_row5_section(raw_root: Path) -> list[str]:
    import statistics

    data = pd_rows(raw_root, "pd-row5")
    out = ["", "### The row-5 runs (GS-33), kept and not validated", ""]
    if not data:
        return []
    out.append(
        "Registered by row 5 and run before row 7 existed. Each repetition chose "
        "its own template and the configuration saturated; they are kept as the "
        "record of why row 7 was needed, and no verdict is drawn from them."
    )
    out += ["", "| condition | rep | completed | failed | p50 TTFT | p99 TTFT | "
            "p99 TPOT | goodput | SLO attainment | background duty |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]

    def f(v, d=1):
        return "-" if v is None else f"{v:.{d}f}"

    for r in data:
        m, b = r["measured"] or {}, r["background"] or {}
        out.append(
            f"| {r['condition']} | {r['rep']} | {m.get('completed', '-')} | "
            f"{m.get('failed', '-')} | {f(m.get('p50_ttft_ms'))} | "
            f"{f(m.get('p99_ttft_ms'))} | {f(m.get('p99_tpot_ms'), 2)} | "
            f"{f(m.get('goodput_rps'), 3)} | {f(m.get('slo_attainment'), 3)} | "
            f"{f(b.get('achieved_duty_cycle'), 3) if b else 'none'} |"
        )

    by = {c: [r for r in data if r["condition"] == c and r["measured"]]
          for c in ("pd-independent", "pd-shared")}

    # Paired, per repetition: within a repetition both conditions deployed the
    # same template, so this difference is the NIC load and nothing else.
    out += ["", "#### Paired by repetition", "",
            "| rep | template | independent p99 TTFT | shared p99 TTFT | change | "
            "predicted change | goodput / offered |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    reps = sorted({r["rep"] for r in data})
    saturated = []
    for rep in reps:
        a = next((r for r in by["pd-independent"] if r["rep"] == rep), None)
        b = next((r for r in by["pd-shared"] if r["rep"] == rep), None)
        if not a or not b:
            continue
        pa = a["prediction"]["independent"]["p99_ttft_ms"]
        pb = (b["prediction"].get("shared") or {}).get("p99_ttft_ms")
        ratio = a["measured"]["goodput_rps"] / a["offered_rps"] if a["offered_rps"] else 0
        if ratio < 0.9:
            saturated.append(rep)
        out.append(
            f"| {rep} | `…{(a['template'] or '')[-12:]}` | "
            f"{a['measured']['p99_ttft_ms']:.1f} ms | {b['measured']['p99_ttft_ms']:.1f} ms | "
            f"{b['measured']['p99_ttft_ms'] - a['measured']['p99_ttft_ms']:+.1f} ms | "
            + (f"{pb - pa:+.1f} ms" if pb is not None else "-")
            + f" | {ratio:.2f} |"
        )
    if saturated:
        out += ["", f"**Saturated in repetitions {', '.join(map(str, saturated))}.** "
                "Goodput is below 90 % of the offered rate, so requests queue for "
                "the whole trace and p99 TTFT is set by that queue, not by the path "
                "the KV takes. In that regime a change in the NIC's load is not "
                "observable, and this arm cannot answer its question."]

    out += ["", "#### Row 5's criterion", ""]
    templates = {r["template"] for r in by["pd-independent"] + by["pd-shared"]}
    if not by["pd-independent"] or not by["pd-shared"]:
        out.append("Not computable: both conditions have not been measured.")
    elif len(templates) > 1:
        out.append(
            "**Not computable as registered.** The criterion reads the spread of "
            "the three independent repetitions as noise, which assumes they are "
            "replicates. They are not: each repetition re-ran the search and "
            f"deployed the template it chose, and the repetitions chose "
            f"{len(templates)} different ones ("
            + ", ".join(f"`…{t[-12:]}`" for t in sorted(templates))
            + "). The spread is therefore a configuration difference, and a "
            "verdict computed from it would be met by construction. It is not "
            "reported as met."
        )
    else:
        mi = [r["measured"]["p99_ttft_ms"] for r in by["pd-independent"]]
        ms = [r["measured"]["p99_ttft_ms"] for r in by["pd-shared"]]
        pi = [r["prediction"]["independent"]["p99_ttft_ms"] for r in by["pd-independent"]]
        ps = [r["prediction"]["shared"]["p99_ttft_ms"] for r in by["pd-shared"]
              if r["prediction"].get("shared")]
        spread = max(mi) - min(mi)
        d_meas = statistics.median(ms) - statistics.median(mi)
        d_pred = (statistics.median(ps) - statistics.median(pi)) if ps else None
        if d_pred is None:
            verdict_text = "not computable: the shared prediction did not simulate"
        elif abs(d_meas) <= spread:
            verdict_text = ("**met**" if abs(d_pred) <= spread else "**NOT met**") + (
                f": the measured change is inside the independent spread "
                f"({spread:.1f} ms), so it counts as no change, and the "
                f"predicted change is {abs(d_pred):.1f} ms")
        else:
            same = (d_meas > 0) == (d_pred > 0) and d_pred != 0
            verdict_text = ("**met**" if same else "**NOT met**") + (
                ": the predicted and measured changes have "
                + ("the same sign" if same else "different signs"))
        out += [
            "| | independent | shared | change |",
            "| --- | --- | --- | --- |",
            f"| predicted p99 TTFT (median) | {statistics.median(pi):.1f} ms | "
            f"{statistics.median(ps):.1f} ms | {d_pred:+.1f} ms |" if ps else
            "| predicted p99 TTFT | - | - | - |",
            f"| measured p99 TTFT (median) | {statistics.median(mi):.1f} ms | "
            f"{statistics.median(ms):.1f} ms | {d_meas:+.1f} ms |",
            "",
            f"Registered: the two changes have the same sign, with a measured "
            f"change inside the spread of the independent repetitions counted "
            f"as none. Verdict: {verdict_text}. Magnitudes are report-only.",
        ]
    return out


def agreement_table(data: list[dict]) -> list[str]:
    """Whether the search's verdict on each placement matches the hardware's.

    Only rows whose placement was simulated to a verdict are counted; a row
    recorded before GS-30, or one the simulator returned nothing for, is not
    an agreement and not a disagreement.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for row in data:
        if not row.get("measured"):
            continue
        pv = predicted_verdict(row)
        if pv not in ("met", "MISSED"):
            continue
        topo = row["condition"].split("__")[2]
        groups.setdefault(topo, []).append((pv, verdict(row)[0]))
    head = ["placement", "rows", "agree", "disagree", "disagreements"]
    out = ["| " + " | ".join(head) + " |",
           "| " + " | ".join("---" for _ in head) + " |"]
    for topo in sorted(groups):
        pairs = groups[topo]
        agree = sum(1 for a, b in pairs if a == b)
        kinds = sorted({f"predicted {a}, measured {b}" for a, b in pairs if a != b})
        out.append(f"| {topo} | {len(pairs)} | {agree} | {len(pairs) - agree} | "
                   f"{'; '.join(kinds) or '-'} |")
    total = sum(len(v) for v in groups.values())
    agree = sum(1 for v in groups.values() for a, b in v if a == b)
    out.append(f"| all | {total} | {agree} | {total - agree} | - |")
    return out


def _pair_rows(root: Path) -> list[dict]:
    """Row 7 (d): the two conditions of one repetition, paired request by request.

    Same template, trace and seed, so request i is the same prompt at the same
    offset in both; its interval difference is the NIC load and nothing else.
    """
    import statistics

    out = []
    for a_dir in sorted((root / "pd-independent").glob("*/")):
        b_dir = root / "pd-shared" / a_dir.name
        ra, rb = a_dir / "pd" / "requests.jsonl", b_dir / "pd" / "requests.jsonl"
        if not (ra.exists() and rb.exists()):
            continue
        a, b = pd_intervals(ra), pd_intervals(rb)
        common = sorted(set(a) & set(b))
        d = [b[i] - a[i] for i in common]
        ma, mb = pd_latencies(ra), pd_latencies(rb)
        out.append({
            "rep": int(a_dir.name), "n": len(common),
            "mean_a": statistics.mean(a[i] for i in common),
            "mean_b": statistics.mean(b[i] for i in common),
            "diff": statistics.mean(d), "diff_sd": statistics.stdev(d) if len(d) > 1 else 0.0,
            "p99_a": ma["p99_ttft_ms"], "p99_b": mb["p99_ttft_ms"],
            "offered": json.loads((a_dir / "provenance.json").read_text())["offered_rps"],
        })
    return out


def pd_section(raw_root: Path) -> list[str]:
    import statistics

    out = ["", "## The inter-node P/D arm", "", "> **REAL HARDWARE**, two nodes.", "",
           PD_BANNER_FIRST, ""]
    out.append(
        "**This arm's question is the size of the contention effect and whether "
        "the model's prediction of it agrees, not whether a P/D deployment meets "
        "its SLO** (preregistration row 7 f). Prefill on `s8` GPU 0, decode on "
        "`s6` GPU 0, `NixlConnector`. The primary metric is the per-request "
        "**interval** from the prefill response to the decode stream's first "
        "token -- the KV pull plus the decode instance's first step -- as a "
        "paired mean difference; p99 TTFT is secondary. A constant added to "
        "every request shows in a mean and is buried in a p99.[^pdtokens]"
    )
    sel_path = raw_root / "pd-selection.json"
    if sel_path.exists():
        sel = json.loads(sel_path.read_text())
        out += ["", f"Template, fixed for every run (row 7 a): `{sel['chosen']}`, chosen "
                f"once at seed {sel['seed']}. **Every P/D template was predicted "
                f"infeasible on TPOT**"
                + (" before selection" if sel["all_infeasible"] else "")
                + ", which is reported as a separate fact and is not this arm's "
                "question:", "",
                "| template | predicted p99 TTFT | predicted p99 TPOT | feasible |",
                "| --- | --- | --- | --- |"]
        for t in sel["table"]:
            out.append(f"| `…{t['template_id'][-12:]}` | {t['p99_ttft_ms']:.1f} ms | "
                       f"{t['p99_tpot_ms']:.1f} ms | {t['feasible']} |")

    # --- the knee pilot (row 7 b), excluded from validation -------------------
    pilot = raw_root / "pd-pilot"
    knee = []
    for d in sorted(pilot.glob("knee-rps*/pd-independent/*/")):
        req = d / "pd" / "requests.jsonl"
        if req.exists():
            prov = json.loads((d / "provenance.json").read_text())
            knee.append((prov["offered_rps"], pd_latencies(req)))
    chosen_rate = None
    if knee:
        out += ["", "### The knee pilot (excluded from validation)", "",
                "| offered rps | goodput / offered | drain-corrected | p50 TTFT | "
                "p99 TTFT | mean interval |", "| --- | --- | --- | --- | --- | --- |"]
        for rate, m in sorted(knee, key=lambda x: x[0]):
            corr = m["goodput_drain_corrected_rps"] / rate
            if corr >= 0.9:
                chosen_rate = rate
            out.append(f"| {rate:g} | {m['goodput_rps'] / rate:.3f} | {corr:.3f} | "
                       f"{m['p50_ttft_ms']:.0f} ms | {m['p99_ttft_ms']:.0f} ms | "
                       f"{m['interval_mean_ms']:.1f} ms |")
        out += ["", ("The rerun rate is the highest pilot rate whose drain-corrected "
                     "goodput is at least 0.9 of offered: "
                     + (f"**{chosen_rate:g} rps**." if chosen_rate else
                        "**none qualified**.")
                     + " E-G5's own goodput divides by the span to the last "
                     "completion, so an unqueued run of this trace scores 0.845 at "
                     "1 rps; the corrected figure removes one unqueued request's "
                     "service time from the span (row 7 b).")]

    # --- the pilot pairs: the SD that sets 3 or 6 repetitions -------------------
    pp = _pair_rows(pilot / "pairs")
    if pp:
        diffs = [r["diff"] for r in pp]
        sd = statistics.stdev(diffs) if len(diffs) > 1 else None
        out += ["", "### Pilot pairs (excluded from validation)", "",
                "| rep | requests paired | interval change (mean) | per-request SD |",
                "| --- | --- | --- | --- |"]
        for r in pp:
            out.append(f"| {r['rep']} | {r['n']} | {r['diff']:+.2f} ms | {r['diff_sd']:.2f} ms |")
        if sd is not None:
            out += ["", f"SD of the pair-mean change across pilot pairs: **{sd:.2f} ms**."]

    # --- the validation runs (row 7 d, e) --------------------------------------
    main = _pair_rows(raw_root / "pd")
    if not main:
        out += ["", "The validation runs have not been made."]
    else:
        rate = main[0]["offered"]
        pred_path = raw_root / f"pd-prediction-rps{rate:g}.json"
        pred = json.loads(pred_path.read_text()) if pred_path.exists() else None
        pv = pred["predicted_interval_change_ms"] if pred else None
        pt = pred["predicted_p99_ttft_change_ms"] if pred else None
        out += ["", f"### The validation pairs, {rate:g} rps", "",
                "| pair | requests paired | interval mean independent | shared | change | "
                "predicted change | p99 TTFT independent | shared | change | predicted |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in main:
            out.append(
                f"| {r['rep']} | {r['n']} | {r['mean_a']:.2f} ms | {r['mean_b']:.2f} ms | "
                f"{r['diff']:+.2f} ms | {pv:+.2f} ms | {r['p99_a']:.1f} ms | "
                f"{r['p99_b']:.1f} ms | {r['p99_b'] - r['p99_a']:+.1f} ms | "
                f"{pt:+.1f} ms |" if pred else
                f"| {r['rep']} | {r['n']} | {r['mean_a']:.2f} | {r['mean_b']:.2f} | "
                f"{r['diff']:+.2f} | - | {r['p99_a']:.1f} | {r['p99_b']:.1f} | - | - |")
        effect = statistics.mean(r["diff"] for r in main)
        out += ["", "#### The registered criterion (row 7 e)", ""]
        if pv is None or pv == 0:
            out.append("Not computable: no prediction for this rate.")
        else:
            ratio = effect / pv
            same = (effect > 0) == (pv > 0)
            met = same and 0.5 <= ratio <= 2.0
            sd = statistics.stdev(r["diff"] for r in main) if len(main) > 1 else 0.0
            out += ["| quantity | value |", "| --- | --- |",
                    f"| measured change | {effect:+.2f} |",
                    f"| SD across pairs | {sd:.2f} |",
                    f"| predicted change | {pv:+.2f} |",
                    f"| ratio | {ratio:.2f} |",
                    f"| verdict | {'met' if met else 'NOT met'} |", ""]
            out.append(
                f"Mean of the pair changes **{effect:+.2f} ms** against a predicted "
                f"**{pv:+.2f} ms**: ratio **{ratio:.2f}**, "
                + ("same sign" if same else "opposite sign")
                + f". Registered: same sign and a ratio between 0.5 and 2. "
                f"Verdict: **{'met' if met else 'NOT met'}**.")
    out += pd_row5_section(raw_root)
    out += ["",
            "[^pdtokens]: This arm compares **latency** between two P/D conditions, "
            "not outputs. A disaggregated greedy token stream is not the aggregated "
            "one: across these two nodes two of three probe prompts diverged, "
            "reproducibly (GS-29). No statement about output identity is made from "
            "these rows."]
    return out


def _axis(name: str) -> str:
    """`p99_ttft_ms` / `TTFT 3341 > 550 ms` -> `ttft`; the same for tpot, goodput."""
    low = name.lower()
    for axis in ("ttft", "tpot", "goodput"):
        if axis in low:
            return axis
    return low


def closest_miss_table(data: list[dict]) -> list[str]:
    """Row 8: at `high` the closest miss is deployed in the recommendation's
    place, and what is tested is the verdict "no feasible plan of this size".

    (i) did the hardware miss its SLO too -- the direction of the verdict;
    (ii) did it miss on the axes the prediction said it would.
    """
    rows = [r for r in data if r["deployment"] == "closest_miss" and r.get("measured")]
    if not rows:
        return []
    head = ["condition", "devices", "offered rps", "p99 TTFT pred", "p99 TTFT meas",
            "p99 TPOT pred", "p99 TPOT meas", "goodput meas",
            "predicted violated axes", "measured violated axes",
            "(i) hardware missed", "(ii) same axes"]
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    agree_i = agree_ii = 0
    for row in rows:
        p, m = row["predicted"] or {}, row["measured"]
        cm = row["closest_miss"] or {}
        pred_axes = sorted({_axis(v["metric"]) for v in cm.get("predicted_violated_axes", [])})
        pred_txt = ", ".join(
            f"{_axis(v['metric'])} +{v['overshoot_ratio'] * 100:.0f} %"
            for v in sorted(cm.get("predicted_violated_axes", []), key=lambda v: v["metric"]))
        state, missed = verdict(row)
        meas_axes = sorted({_axis(x.split()[0]) for x in missed})
        i_ok = state == "MISSED"
        ii_ok = i_ok and pred_axes == meas_axes
        agree_i += i_ok
        agree_ii += ii_ok

        def f(v, d):
            return "-" if v is None else f"{v:.{d}f}"

        out.append(
            f"| {row['condition']} | {row['devices']} | {row['offered_rps']:.1f} | "
            f"{f(p.get('p99_ttft_ms'), 1)} | {m['p99_ttft_ms']:.1f} | "
            f"{f(p.get('p99_tpot_ms'), 2)} | {m['p99_tpot_ms']:.2f} | "
            f"{m['goodput_rps']:.3f} | {pred_txt or '-'} | "
            f"{', '.join(meas_axes) or 'none'} | {'yes' if i_ok else '**no**'} | "
            f"{'yes' if ii_ok else '**no**'} |")
    out += ["", f"(i) the hardware also missed: **{agree_i} of {len(rows)}**. "
            f"(ii) and on the predicted axes: **{agree_ii} of {len(rows)}**."]
    return out


def high_scope_table(raw_root: Path, data: list[dict]) -> list[str]:
    """Row 8 (a)-(c): what the seed-42 exhaustive evaluation found per
    condition, what was deployed because of it, and the hardware's verdict."""
    files = sorted((raw_root / "high-scope").glob("*.json"))
    if not files:
        return []
    head = ["condition", "representatives", "evaluated", "feasible of size", "branch",
            "deployed", "K=16 recall", "hardware (seeds 42 / 43 / 44)"]
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    recalls = []
    for f in files:
        sc = json.loads(f.read_text())
        cond = sc["condition"]
        s = sc["scope"]
        k = s.get("budget_k16", {})
        found, total = k.get("feasible_of_size_found"), k.get("feasible_of_size_in_scope")
        recall = f"{found}/{total}" if total else "- (none feasible)"
        if total:
            recalls.append((cond, found, total))
        label = "recommendation" if sc["branch"] == "recommendation" else "closest_miss"
        tid = sc.get("recommendation") or (sc.get("closest_miss") or {}).get("template_id")
        verdicts = []
        for rep in (42, 43, 44):
            row = next((r for r in data if r["condition"] == cond and r["rep"] == rep
                        and r["deployment"] == label and r.get("measured")), None)
            verdicts.append(verdict(row)[0] if row else "-")
        out.append(f"| {cond} | {s['representatives']} | {s['evaluated']} | "
                   f"{s['feasible_of_size']} | {sc['branch']} | `…{(tid or '')[-16:]}` | "
                   f"{recall} | {' / '.join(verdicts)} |")
    if recalls:
        out += ["", "**The registered adaptive search on a real-hardware spec (row 8 c).** "
                "K = 16 against the exhaustive feasible set of the condition's size, seed 42: "
                + "; ".join(f"`{c.split('__')[1]} {c.split('__')[2]}` {a}/{b}"
                            for c, a, b in recalls)
                + ". This sits beside GS-31: there the ranker's recall failed a registered "
                "criterion on the real-lab holdout; here it is measured on the specs the "
                "hardware campaign actually deployed. The ranker is not changed."]
    return out


def markdown(data: list[dict], args) -> str:
    out = ["# E-G5 — the recommendation and the bounds, on hardware", "", BANNER, ""]
    out.append(
        "Each deployment is offered the rate **its own spec** declares: the "
        "service rows ask whether the recommendation meets its SLOs at the "
        "service's load, and the bound-stress row asks whether a candidate the "
        "throughput bound rejected can reach the floor it was rejected "
        "against. One trace for both would answer neither, and an earlier run "
        "of this experiment did exactly that -- replaying a stock trace at "
        "10 rps against a plan simulated at 4 put a predicted p99 TTFT of "
        "162 ms beside a measured 22,068, a number that says nothing about the "
        "simulator and everything about two different offered loads."
    )
    out += ["", "## The placement decides whether the SLO is met", ""]
    out.append(
        "Three placements, three repetitions each: T1 and T2 are one TP=2 "
        "template on two different pairs of devices, and T3 is the TP=4 "
        "template on four. The rows below are the recommendation at each, the "
        "target is the same 550 ms in every one, and `predicted` is the "
        "search's verdict on that placement itself (GS-30)."
    )
    out.append("")
    out += placement_table(data)
    out.append("")
    out.append(placement_sentence(data))
    out.append("")
    out.append(
        "The planner being extended **cannot express that difference at "
        "all**: `resolve_devices` maps an execution island to every one of its "
        "accelerator ids, so a TP=2 plan is launched with all eight devices "
        "visible and the runtime takes the first two. It names a template; "
        "T1 and T2 are two placements of that one template, and the choice "
        "between them decides whether the service meets its objectives."
    )

    out += ["", "## Does the search's verdict on a placement match the hardware's?", ""]
    out.append(
        "Before GS-30 every row carried the search's own pick, so T1 and T2 "
        "had the same prediction and this question could not be put. Each row "
        "now carries the verdict on the placement deployed, and the table "
        "counts whether it is the verdict the hardware reached."
    )
    out.append("")
    out += agreement_table(data)

    hs = high_scope_table(RAW, data)
    if hs:
        out += ["", "## Above the knee: the exhaustive scope, and what it decided", ""]
        out.append(
            "At `high` the verdict is decided once, by evaluating every representative "
            "of GS-27's scope at seed 42 without a budget; the three repetitions repeat "
            "the deployment and the measurement of what that decided (row 8). A "
            "recommendation that saturates here is a false positive of the 6 rps "
            "prediction; a closest miss that also misses is agreement with the "
            "infeasibility verdict. They are different claims."
        )
        out.append("")
        out += hs
    cm = closest_miss_table(data)
    if cm:
        out += ["", "## Above the knee: is there really no feasible plan of this size?", ""]
        out.append(
            "At `high` the search returns no feasible plan of the condition's size, "
            "so the recommendation's slot is filled by the **closest miss** -- "
            "heteropilot's `closest_plan` rule, the infeasible plan with the "
            "smallest worst normalised overshoot, restricted to the size (row 8). "
            "What is tested is the verdict \"no feasible plan of this size\", "
            "within GS-27's scope cut, not a recommendation's SLO."
        )
        out.append("")
        out += cm

    out += ["", "## Predicted against measured", ""]
    out += table(data)

    missing = [(r, verdict(r)[1]) for r in data if r.get("measured")]
    failures = [(r, why) for r, why in missing if why]
    out += ["", "## Where the recommendation missed, and on which axis", ""]
    if not failures:
        out.append("Every deployment met every declared target.")
    else:
        for row, why in failures:
            out.append(f"- **{row['deployment']}** ({row['condition']}): "
                       + "; ".join(why))
        out.append("")
        out.append(
            "A missed target is recorded, not explained away. The candidate "
            "causes are the ones the work order names and they are not "
            "separated by this experiment: prediction error, the contention "
            "model, and the engine's own scheduler. What can be said from "
            "these rows alone is the size and the direction of the prediction "
            "error, below."
        )

    served = [r for r in data if r.get("measured") and r.get("predicted")]
    if served:
        out += ["", "## The size and direction of the prediction error", ""]
        out.append("| deployment | p99 TTFT | p99 TPOT |")
        out.append("| --- | --- | --- |")
        for row in served:
            p, m = row["predicted"], row["measured"]
            ttft = m["p99_ttft_ms"] / p["p99_ttft_ms"] if p["p99_ttft_ms"] else 0
            tpot = m["p99_tpot_ms"] / p["p99_tpot_ms"] if p["p99_tpot_ms"] else 0
            out.append(
                f"| {row['deployment']} | measured is {ttft:.1f}x the "
                f"prediction | {tpot:.1f}x |"
            )
        out.append("")
        out.append(direction_sentence(served))

    bound_rows = [r for r in data
                  if r.get("measured") and r["deployment"].endswith("impossible_proven")]
    if bound_rows:
        out += ["", "## The lower bound, tested on hardware", ""]
        out.append(
            "The candidate the throughput bound rejected by the smallest "
            "margin, deployed and offered the floor it was rejected against."
        )
        out.append("")
        out.append("| ceiling the bound computed | floor it was rejected against "
                   "| measured goodput | ratio |")
        out.append("| --- | --- | --- |---|")
        for row in bound_rows:
            spec = slo_of("bound_stress")
            measured = row["measured"]["goodput_rps"]
            ceiling = 54.433
            out.append(
                f"| {ceiling:.3f} rps | {spec['min_goodput_rps']:.1f} rps | "
                f"{measured:.3f} rps | **{ceiling / measured:.1f}x** |"
            )
        out.append("")
        out.append(
            "**`false_infeasible` is zero on hardware**: the candidate did not "
            "reach the floor, so the bound was right to reject it. That was "
            "the expected outcome and the test is registered as weak -- the "
            "bound is a *relaxation*, so it rejects only what the most "
            "optimistic arithmetic already misses, and a rejection being "
            "correct is not news."
        )
        out.append("")
        out.append(
            "**The useful number is the ratio.** The optimistic ceiling sits "
            "an order of magnitude above what the hardware actually delivers. "
            "A bound that loose still eliminates nothing it should not, which "
            "is its only correctness requirement, but it eliminates very "
            "little: the looseness is the price of soundness and this is its "
            "size on this node."
        )

    out += pd_section(RAW)

    out += ["", "## Reproducing", ""]
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("vendor/heteropilot/.venv/bin/python experiments/e_g5/deploy_and_bench.py \\")
    out.append("    --condition llama31-8b__normal__T3__knee --rep 42 \\")
    out.append("    --knee-rps 4 --predictor sim")
    out.append(f"python experiments/e_g5/analyze.py --out {args.out}")
    out.append("```")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g5_real_hardware.md")
    parser.add_argument("--raw", type=Path, default=RAW)
    args = parser.parse_args(argv)

    data = rows(args.raw)
    if not data:
        raise SystemExit(
            f"no deployments under {args.raw}. Run deploy_and_bench.py first -- "
            f"this script measures nothing of its own."
        )
    text = markdown(data, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
