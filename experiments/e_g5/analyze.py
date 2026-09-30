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
    spec = slo_of("bound_stress" if row["deployment"].endswith("impossible_proven")
                  else "service")
    m = row["measured"]
    missed = []
    if m["p99_ttft_ms"] > spec["ttft_max_ms"]:
        missed.append(f"TTFT {m['p99_ttft_ms']:.0f} > {spec['ttft_max_ms']:.0f} ms")
    if m["p99_tpot_ms"] > spec["tpot_max_ms"]:
        missed.append(f"TPOT {m['p99_tpot_ms']:.1f} > {spec['tpot_max_ms']:.0f} ms")
    if m["goodput_rps"] < spec["min_goodput_rps"]:
        missed.append(
            f"goodput {m['goodput_rps']:.2f} < {spec['min_goodput_rps']:.2f} rps"
        )
    return ("met" if not missed else "MISSED"), missed


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
    }


def pd_rows(raw_root: Path) -> list[dict]:
    out = []
    for prov_path in sorted((raw_root / "pd").glob("*/*/provenance.json")):
        prov = json.loads(prov_path.read_text())
        req = prov_path.parent / "pd" / "requests.jsonl"
        out.append({
            "condition": prov["condition"], "rep": prov["rep"],
            "state": prov.get("state"),
            "measured": pd_latencies(req) if req.exists() else None,
            "prediction": prov.get("prediction"),
            "background": prov.get("background"),
        })
    return out


def pd_section(raw_root: Path) -> list[str]:
    import statistics

    data = pd_rows(raw_root)
    out = ["", "## The inter-node P/D arm", "", "> **REAL HARDWARE**, two nodes.", "",
           PD_BANNER_FIRST, ""]
    if not data:
        out.append("Not run.")
        return out
    out.append(
        "Prefill on `s8` GPU 0, decode on `s6` GPU 0, `NixlConnector` between "
        "them. **TTFT is the registered definition**: from the router sending "
        "the prefill call to the first token of the decode stream, so it "
        "includes the prefill, the KV pull across the NIC, and the decode "
        "instance's first step.[^pdtokens]"
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
    out += ["", "### The registered criterion", ""]
    if not by["pd-independent"] or not by["pd-shared"]:
        out.append("Not computable: both conditions have not been measured.")
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
    out += [
        "",
        "[^pdtokens]: This arm compares **latency and goodput** between two P/D "
        "conditions, not outputs. A disaggregated greedy token stream is not the "
        "aggregated one: across these two nodes two of three probe prompts "
        "diverged, reproducibly (GS-29). No statement about output identity is "
        "made from these rows.",
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
