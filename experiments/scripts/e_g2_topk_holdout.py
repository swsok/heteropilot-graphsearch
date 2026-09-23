"""E-G2 / G15-3: the ranker correction, checked on fixtures the diagnosis never saw.

**MockPredictor results. Not performance numbers.** Every figure below comes
from a deterministic mock that respects the same physics as the bounds; none
of it is a measurement or a simulation of any hardware.

The G15 diagnosis (`e_g2_ranker_diagnosis.md`) and the correction it led to
used **graph-toy-abcde and graph-toy-shared-nic only**. A correction that only
helps where it was derived is a fit to two fixtures, so the same E-G1b table
is produced here for two the diagnosis did not touch:

    graph-toy-asym       the designed failure condition for compression -- five
                         nodes, no two alike -- under the toy tight spec.
    heterogeneous-lab    heteropilot's own example cluster, under a tight copy
                         of heteropilot's own spec written before the corrected
                         ranker was run on it (see that file's header).

Both ranker variants run in the graphsearch arm -- `service_margin_v1` is the
pre-G15 estimate -- so before and after sit in adjacent rows. The completion
condition is `k=4 feasible_recall > 0` OR a smaller `first_feasible_at_sim`
for the corrected ranker; if neither holds here, that is the result, and the
ranker is not re-tuned to make it hold.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

import e_g1b_topk as base  # noqa: E402  (same directory as this script)

from graphsearch.ranker import DEFAULT_RANKER_VARIANT, RANKER_V1  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"

HOLDOUTS: dict[str, tuple[Path, Path, Path | None]] = {
    # name: (cluster, spec, profiles root)
    "graph-toy-asym": (
        FIXTURES / "clusters/graph-toy-asym.v2.yaml",
        FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml",
        None,
    ),
    "heterogeneous-lab": (
        paths_root.HETEROPILOT_ROOT / "examples/clusters/heterogeneous-lab.yaml",
        FIXTURES / "service_specs/heterogeneous-lab-llama31-8b-tight.yaml",
        paths_root.HETEROPILOT_ROOT,
    ),
}


def verdict(rows: list[dict]) -> list[str]:
    """Did the correction meet its completion condition, per fixture?"""
    out = []
    def pick(fixture: str, arm: str) -> dict:
        return next(
            r for r in rows
            if r["fixture"] == fixture and r["arm"] == arm and r["k"] == 4
        )

    for fixture in sorted({r["fixture"] for r in rows}):
        before = pick(fixture, base.ARM_LABEL[RANKER_V1])
        after = pick(fixture, base.ARM_LABEL[DEFAULT_RANKER_VARIANT])
        recall_up = (
            after["feasible_recall"] > 0
            and after["feasible_recall"] > before["feasible_recall"]
        )
        b, a = before["first_feasible_at_sim"], after["first_feasible_at_sim"]
        earlier = a is not None and (b is None or a < b)
        met = (after["feasible_recall"] > 0) or earlier
        out.append(
            f"- **{fixture}**, k=4: recall {before['feasible_recall']} → "
            f"{after['feasible_recall']}, first feasible at sim "
            f"{'-' if b is None else b} → {'-' if a is None else a}. "
            f"Completion condition {'MET' if met else 'NOT MET'}"
            f"{' (recall rose)' if recall_up else ''}"
            f"{' (found earlier)' if earlier else ''}."
        )
    return out


def markdown(rows: list[dict], counts: dict[str, tuple[int, int]]) -> str:
    out = ["# E-G2 — holdout: the corrected ranker on fixtures it never saw", "", base.BANNER, ""]
    out.append(
        "Diagnosed and corrected on **graph-toy-abcde** and **graph-toy-shared-nic** "
        "only (`e_g2_ranker_diagnosis.md`). Nothing below was looked at before the "
        "correction was fixed. `graphsearch (v1)` is `service_margin_v1`, the "
        "pre-G15 estimate; `graphsearch` is the corrected `service_margin`."
    )
    out.append("")
    out += base.table(rows)
    out.append("")
    out.append("## Completion condition, k=4")
    out.append("")
    out += verdict(rows)
    out.append("")
    out += base.corpus_notes(counts)
    out.append("")
    out.append("## Reproducing")
    out.append("")
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("python experiments/scripts/e_g2_topk_holdout.py \\")
    out.append("    --out experiments/results/e_g2_topk_holdout.md")
    out.append("```")
    out.append("")
    out += base.reading_notes()
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g2_topk_holdout.md")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    rows: list[dict] = []
    counts: dict[str, tuple[int, int]] = {}
    for name, (cluster, spec, profiles_root) in HOLDOUTS.items():
        if args.only and args.only != name:
            continue
        fixture_rows, counts[name] = base.run(
            name, cluster, spec, args.limit,
            variants=(RANKER_V1, DEFAULT_RANKER_VARIANT),
            profiles_root=profiles_root,
        )
        rows.extend(fixture_rows)

    text = markdown(rows, counts)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
