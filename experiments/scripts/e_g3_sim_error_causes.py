#!/usr/bin/env python
"""Why the simulator refused: the causes behind E-G3's `SIM_ERROR` count.

**REAL SIM.** Every figure comes from re-running E-G3's oracle arm with the
simulator's working directory preserved and reading the tracebacks it left.
Nothing here is a measurement of hardware.

E-G3 reports a number of placements the oracle could not reach a verdict on and
records them as `unknown_measurement`. That was correct and it was also all it
said: the result file states outright that "the failures are reported, not
explained". This explains them.

**One label was covering two causes with different meanings**, which is the
finding:

  `FileNotFoundError`  no profile data exists for that tensor-parallel degree
                       on that hardware. Nothing was measured, and the
                       simulator says so rather than guessing. This is
                       `unknown_measurement` in its purest sense and the
                       remedy is to profile, not to re-run.

  `RuntimeError`       the simulator's memory model detected a genuine
                       resource exhaustion mid-run -- a decode instance out of
                       KV -- and raised instead of returning a verdict. The
                       placement may well be infeasible; nothing here proves
                       it, because the bound that would is deliberately
                       optimistic.

Merging them under one count would hide that the first is a gap in the
measurement set and the second is a gap in how the evaluator reports what it
already knows.

    python experiments/scripts/e_g3_sim_error_causes.py \\
        --work-dir outputs/eg3-diag --out experiments/results/e_g3_sim_error_causes.md
"""

from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

ROOT = paths_root.GRAPHSEARCH_ROOT

BANNER = (
    "> **REAL SIM — LLMServingSim.** Every figure comes from re-running "
    "E-G3's oracle arm with the simulator's working directory preserved and "
    "reading the tracebacks it left. No hardware was run."
)

#: What each exception class means for the five states, written once here so a
#: reader does not have to infer it from a traceback.
MEANING = {
    "FileNotFoundError": (
        "**No profile data exists** for that tensor-parallel degree on that "
        "hardware. The simulator refuses rather than extrapolating, which is "
        "the right refusal. `unknown_measurement` in its purest sense: the "
        "remedy is to run the profiler, and re-running the experiment "
        "unchanged would fail identically."
    ),
    "RuntimeError": (
        "The simulator's **memory model detected a real resource exhaustion** "
        "mid-run and raised instead of returning a verdict. The placement may "
        "well be infeasible -- but nothing here proves it, and promoting a "
        "crash to `impossible_proven` would be exactly the confusion the five "
        "states exist to prevent."
    ),
}


def classify(work_dir: Path) -> dict[str, list[dict]]:
    """Every simulation that produced no CSV, with its exception and message."""
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for sims in sorted(work_dir.glob("*/oracle/sims")):
        fixture = sims.parent.parent.name
        for run in sorted(sims.iterdir()):
            if not run.is_dir() or (run / "sim1.csv").exists():
                continue
            log = run / "sim1.log"
            text = log.read_text(errors="replace") if log.exists() else ""
            match = None
            for line in reversed(text.splitlines()):
                match = re.match(r"^([A-Za-z_]*(?:Error|Exception)): (.*)$", line)
                if match:
                    break
            out[fixture].append({
                "candidate": re.sub(r"_[0-9a-f]{12}$", "", run.name),
                "exception": match.group(1) if match else "unknown",
                "message": (match.group(2) if match else "")[:200],
            })
    return out


def markdown(found: dict[str, list[dict]], args) -> str:
    out = ["# E-G3 — why the simulator refused", "", BANNER, ""]
    out.append(
        "E-G3 records a count of placements the oracle could not judge and "
        "reports them as `unknown_measurement`. Its own result file says the "
        "failures are reported and not explained. This file explains them, and "
        "the explanation is that **one label was covering two causes with "
        "different meanings**."
    )

    out += ["", "## What failed, and with what", ""]
    out.append("| fixture | failures | exception | distinct candidates |")
    out.append("| --- | --- | --- | --- |")
    for fixture in sorted(found):
        by_exc = collections.Counter(f["exception"] for f in found[fixture])
        for exc, count in sorted(by_exc.items()):
            distinct = len({
                f["candidate"] for f in found[fixture] if f["exception"] == exc
            })
            out.append(
                f"| {fixture} | {count} | `{exc}` | {distinct} |"
            )

    seen = sorted({f["exception"] for rows in found.values() for f in rows})
    out += ["", "## What each one means", ""]
    for exc in seen:
        out.append(f"### `{exc}`")
        out.append("")
        out.append(MEANING.get(exc, "Not characterised."))
        sample = next(
            f for rows in found.values() for f in rows if f["exception"] == exc
        )
        out.append("")
        out.append(f"> `{sample['message']}`")
        out.append("")

    out += ["## What does not change", ""]
    out.append(
        "**Both stay `unknown_measurement`.** A missing profile is not a "
        "property of the placement, and a crash is not a verdict. Promoting "
        "either to `impossible_proven` would assert something no bound "
        "proved, which is the confusion the five states exist to prevent "
        "(work order rule 4)."
    )
    out.append("")
    out.append(
        "**The memory bound is not at fault for the second.** "
        "`graphsearch/bounds.py::_check_memory` checks weights plus **one "
        "median request's** KV and declares that relaxation in its own proof "
        "-- \"one median-length request only\". It cannot reject on "
        "steady-state KV without assuming a concurrency the most optimistic "
        "arithmetic does not force, and a bound that did would no longer be a "
        "relaxation. The candidates it let through and the simulator then "
        "killed are the gap between the two, which is exactly what the "
        "simulation is for."
    )

    out += ["", "## Reproducing", ""]
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("for f in graph-toy-abcde graph-toy-shared-nic heterogeneous-lab; do")
    out.append("  vendor/heteropilot/.venv/bin/python \\")
    out.append("      experiments/scripts/e_g3_real_sim_oracle.py --only $f \\")
    out.append("      --work-dir outputs/eg3-diag/$f --cache-dir outputs/eg3-diag/$f/cache")
    out.append("done")
    out.append("python experiments/scripts/e_g3_sim_error_causes.py "
               f"--work-dir {args.work_dir} --out {args.out}")
    out.append("```")
    out.append("")
    out.append(
        "The cache is deliberately not shared with E-G3's own: a cached "
        "success would hide the failure this file is about."
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True,
                        help="a directory of <fixture>/oracle/sims trees")
    parser.add_argument(
        "--out", default="experiments/results/e_g3_sim_error_causes.md"
    )
    args = parser.parse_args(argv)

    found = classify(args.work_dir)
    if not found:
        raise SystemExit(
            f"no failed simulations under {args.work_dir}. Re-run E-G3's "
            f"oracle arm with --work-dir preserved; this script reads the "
            f"tracebacks and measures nothing of its own."
        )
    text = markdown(found, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
