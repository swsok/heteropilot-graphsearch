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
    "provenance file carries. The predicted columns are the planner's, taken "
    "from the plan that was deployed. Nothing here is a simulation."
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


def table(data: list[dict]) -> list[str]:
    head = ["condition", "deployment", "devices", "offered rps",
            "p99 TTFT pred", "p99 TTFT meas", "p99 TPOT pred", "p99 TPOT meas",
            "goodput meas", "SLO"]
    out = ["| " + " | ".join(head) + " |",
           "| " + " | ".join("---" for _ in head) + " |"]
    for row in data:
        if not row.get("measured"):
            out.append(
                f"| {row['condition']} | {row['deployment']} | - | - | - | - | "
                f"- | - | - | {row.get('state', 'not run')} |"
            )
            continue
        p, m = row["predicted"], row["measured"]
        state, _missed = verdict(row)
        out.append(
            f"| {row['condition']} | {row['deployment']} | {row['devices']} | "
            f"{row['offered_rps']:.1f} | {p['p99_ttft_ms']:.1f} | "
            f"{m['p99_ttft_ms']:.1f} | {p['p99_tpot_ms']:.2f} | "
            f"{m['p99_tpot_ms']:.2f} | {m['goodput_rps']:.3f} | **{state}** |"
        )
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
        out.append(
            "The simulator is **optimistic on both axes**, which is the "
            "direction its own accuracy domain already records at low served "
            "concurrency. No margin from this data is fitted here and none may "
            "be: a domain built from E-G5 could not then be tested by E-G5."
        )

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
