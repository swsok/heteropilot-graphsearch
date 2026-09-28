"""E-G7 P5.1: the two holdout clusters, fixed before P4 ran and never tuned against.

**MockPredictor results. Not performance numbers.** Every figure comes from a
deterministic mock; no number here is a measurement or a simulation of any
hardware, and the synthetic cluster's every field is `source: placeholder`.

`docs/preregistration.md` fixed this set on 2026-09-28, before E-G6's grid ran
and before anything in it was looked at:

  1. **synth-holdout-1** -- `cluster_gen --nodes 8 --devices-per-node 8
     --symmetry 0.25 --seed 20260923`. Symmetry 0.25 is not in E-G6's
     {0, 0.5, 1} grid and 20260923 is not E-G6's seed, so nothing fitted on
     that grid was fitted on this.
  2. **real-<lab>-holdout.v2** -- the P3 hardware fixture with one uplink
     reservation changed. **P3 has not run**, that fixture does not exist, and
     this row is reported as `not run` rather than omitted. An omitted row
     reads as a row that passed.

**No ranker, no delta, no bound and no threshold was modified after the set was
fixed.** The arms here are exactly E-G1b's, run through E-G1b's own functions
so the table format is identical by construction rather than by care.

    python experiments/scripts/e_g7_holdout.py \\
        --out experiments/results/e_g7_holdout.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

import e_g1b_topk as base  # noqa: E402  (same directory as this script)

from graphsearch.oracle import (  # noqa: E402
    compare,
    run_oracle,
    run_proposed,
    table_row,
)
from graphsearch.ranker import DEFAULT_RANKER_VARIANT, RANKER_V1  # noqa: E402
from graphsearch.synth.cluster_gen import build_parser as gen_parser  # noqa: E402
from graphsearch.synth.cluster_gen import resolve as gen_resolve  # noqa: E402
from graphsearch.synth.cluster_gen import write as gen_write  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"

#: Exactly what the pre-registration names. Changing any of these numbers
#: changes which cluster is held out, which is the one thing a holdout may not
#: have done to it.
SYNTH_HOLDOUT = {
    "nodes": 8,
    "devices_per_node": 8,
    "symmetry": 0.25,
    "seed": 20260923,
    "uplink_kinds": 3,
}

#: The P3 fixture this would be derived from. Absent until P3 runs.
REAL_HOLDOUT = FIXTURES / "clusters" / "real-lab-holdout.v2.yaml"


def synth_cluster(out_root: Path) -> Path:
    """Generate the registered holdout, byte-identically, every time."""
    out = out_root / "synth-holdout-1"
    args = gen_resolve(
        gen_parser().parse_args(
            [
                "--nodes", str(SYNTH_HOLDOUT["nodes"]),
                "--devices-per-node", str(SYNTH_HOLDOUT["devices_per_node"]),
                "--symmetry", str(SYNTH_HOLDOUT["symmetry"]),
                "--seed", str(SYNTH_HOLDOUT["seed"]),
                "--uplink-kinds", str(SYNTH_HOLDOUT["uplink_kinds"]),
                "--cluster-id", "synth-holdout-1",
                "--out", str(out),
            ]
        )
    )
    return gen_write(args)


def invariant_row(name: str, path: Path, spec_path: Path, limit: int) -> dict:
    """The two correctness numbers on the holdout. Criterion 1, computed.

    `e_g1b_topk.row` carries recall, regret and the first-feasible ordinal and
    **no correctness columns** -- that table was never about them. Reusing it
    and then checking a `correct` key it does not set would have been a test
    that cannot fail, which is worse than no test: it reads as a passing
    invariant on every future run.
    """
    spec, cluster, profiles, islands, graph = base.world(path, spec_path, ROOT)
    templates = base.templates_of(spec, cluster, islands, profiles, limit)
    by_id = {i.id: i for i in islands}

    oracle = run_oracle(
        spec, cluster, by_id, profiles, base.mock(),
        graph=graph, templates=templates,
    )
    proposed = run_proposed(
        spec, cluster, by_id, profiles, base.mock(),
        graph=graph, templates=templates,
    )
    comparison = compare(oracle, proposed)
    ratio = (
        len(proposed.representatives) / len(oracle.embeddings)
        if oracle.embeddings
        else None
    )
    return table_row(
        name,
        comparison,
        {
            "embeddings": len(oracle.embeddings),
            "representatives": len(proposed.representatives),
            "compression_ratio": None if ratio is None else round(ratio, 4),
        },
    )


INVARIANT_COLUMNS = [
    "fixture", "embeddings", "representatives", "compression_ratio",
    "false_infeasible", "mismerged_pairs", "correct", "unjudged", "complete",
]


def invariant_table(rows: list[dict]) -> list[str]:
    def cell(row: dict, key: str) -> str:
        value = row.get(key)
        if isinstance(value, list):
            return str(len(value))
        return "-" if value is None else str(value)

    out = ["| " + " | ".join(INVARIANT_COLUMNS) + " |"]
    out.append("| " + " | ".join("---" for _ in INVARIANT_COLUMNS) + " |")
    for row in rows:
        out.append("| " + " | ".join(cell(row, c) for c in INVARIANT_COLUMNS) + " |")
    return out


def markdown(
    rows: list[dict],
    invariants: list[dict],
    counts: dict,
    missing: list[str],
    args,
) -> str:
    out = ["# E-G7 — holdout", "", base.BANNER, ""]
    out.append(
        "The holdout set was fixed in `docs/preregistration.md` on 2026-09-28, "
        "before E-G6's grid ran and before anything in it was looked at. No "
        "ranker, no δ, no bound and no threshold was modified afterwards."
    )
    out.append("")
    out += ["## Criterion 1 — the invariant, on the holdout", ""]
    out += invariant_table(invariants)
    out.append("")
    out.append(
        "`correct` is `false_infeasible == 0 and mismerged_pairs == 0`. It is "
        "a **condition, not a target** (pre-registration, common section): a "
        "False here is a bound or an equivalence being wrong, and the "
        "registered response is to stop and report, never to relax the test."
    )
    out.append("")
    out += ["## Criterion 3 — recall against heteropilot's surrogate", ""]
    out += base.table(rows)
    out.append("")
    out.append(
        "**Registered at k = 16**, and only there. E-G1b is where this arm "
        "reached recall 1.0, so k = 16 is the operating point the claim is "
        "about; at small K the corrected ranker is already known to tie or "
        "trail (GS-12), and registering that as a target would have been "
        "registering a result already in doubt. k = 4 and k = 8 are "
        "report-only."
    )

    if missing:
        out += ["", "## Not run", ""]
        for name in missing:
            out.append(f"- **{name}** — the fixture does not exist yet.")
        out.append("")
        out.append(
            "`real-<lab>-holdout.v2` is the P3 hardware fixture with one uplink "
            "reservation changed, and **P3 has not run**. The row is reported "
            "as not run rather than omitted: an omitted row reads as a row "
            "that passed, and half a holdout is not a holdout. E-G7's holdout "
            "claim covers the synthetic cluster only until this exists."
        )

    out += ["", "## What was held out, exactly", ""]
    out.append(
        "| | value | why it is outside what was fitted |\n"
        "| --- | --- | --- |\n"
        f"| `--symmetry` | {SYNTH_HOLDOUT['symmetry']} | E-G6's grid is "
        "{0, 0.5, 1}; this is in none of them |\n"
        f"| `--seed` | {SYNTH_HOLDOUT['seed']} | E-G6's grid uses 20260928 |\n"
        f"| `--nodes` x `--devices-per-node` | {SYNTH_HOLDOUT['nodes']} x "
        f"{SYNTH_HOLDOUT['devices_per_node']} = "
        f"{SYNTH_HOLDOUT['nodes'] * SYNTH_HOLDOUT['devices_per_node']} devices "
        "| E-G6 uses 4 devices per node; this shape was never enumerated |"
    )
    out.append("")
    out.append(
        "The cluster is **not committed**. It is regenerated from these "
        "arguments byte for byte, which `tests/test_cluster_gen.py` pins — "
        "and a committed holdout is a holdout somebody can edit."
    )

    out += ["", "## Reproducing", ""]
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("python experiments/scripts/e_g7_holdout.py \\")
    out.append(f"    --out {args.out}")
    out.append("```")
    out.append("")
    out += base.corpus_notes(counts)
    out.append("")
    out += base.reading_notes()
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g7_holdout.md")
    parser.add_argument("--json-out", default="outputs/e_g7/holdout.json")
    parser.add_argument("--synth-root", default="outputs/e_g7/clusters")
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args(argv)

    rows: list[dict] = []
    counts: dict[str, tuple[int, int]] = {}
    missing: list[str] = []

    invariants: list[dict] = []

    path = synth_cluster(Path(args.synth_root))
    invariants.append(
        invariant_row(
            "synth-holdout-1",
            path,
            FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml",
            args.limit,
        )
    )
    fixture_rows, counts["synth-holdout-1"] = base.run(
        "synth-holdout-1",
        path,
        FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml",
        args.limit,
        variants=(RANKER_V1, DEFAULT_RANKER_VARIANT),
        profiles_root=ROOT,
    )
    rows.extend(fixture_rows)

    if REAL_HOLDOUT.exists():
        invariants.append(
            invariant_row(
                "real-lab-holdout",
                REAL_HOLDOUT,
                FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml",
                args.limit,
            )
        )
        fixture_rows, counts["real-lab-holdout"] = base.run(
            "real-lab-holdout",
            REAL_HOLDOUT,
            FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml",
            args.limit,
            variants=(RANKER_V1, DEFAULT_RANKER_VARIANT),
            profiles_root=ROOT,
        )
        rows.extend(fixture_rows)
    else:
        missing.append("real-lab-holdout.v2")

    text = markdown(rows, invariants, counts, missing, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps({"topk": rows, "invariant": invariants}, indent=2) + "\n"
        )

    # Criterion 1, from the table that actually carries the two numbers.
    bad = [r["fixture"] for r in invariants if not r["correct"]]
    if bad:
        print(
            f"\nE-G7 holdout: NOT correct on {', '.join(bad)}. Do not relax "
            f"the test -- stop and report (work order rule 5)."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
