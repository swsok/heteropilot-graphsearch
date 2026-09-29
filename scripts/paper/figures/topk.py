#!/usr/bin/env python
"""Feasible recall against K, for both arms, on both holdout fixtures.

The table beside this figure carries the same numbers; the figure exists
because the shape is the argument. Recall rises with budget for the graph
search and stalls for the surrogate, and at K = 4 the search is *behind* --
which the curve shows without the reader having to compare two rows.

Reads `experiments/results/*.md` and computes nothing. A figure that recomputed
its own values could disagree with the table beside it, and the reader would
have no way to tell which was wrong.

    python scripts/paper/figures/topk.py --out-dir paper/figures
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "experiments" / "results"

#: Which file, and what to call it. The holdout is the one fixed before the
#: scaling grid ran; E-G1b's corpus is the one the ranker was corrected on, and
#: the two are never averaged together.
SOURCES = (
    ("e_g2_topk_holdout.md", "holdout"),
    ("e_g7_holdout.md", "synthetic holdout"),
)

#: The arm names as the results files spell them, mapped to what the legend
#: says. `graphsearch (v1)` is the pre-correction ranker and is drawn so the
#: correction is visible rather than asserted.
ARMS = {
    "oracle": ("oracle", "k", 1.5),
    "heteropilot": ("heteropilot surrogate", "s", 1.0),
    "graphsearch": ("graph search", "o", 1.8),
    "graphsearch (v1)": ("graph search (pre-G15)", "^", 1.0),
}


def rows_of(path: Path) -> list[dict]:
    """Every row of the file's first table, as dicts."""
    header, out = None, []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if header and out:
                break
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if header is None:
            header = cells
            continue
        out.append(dict(zip(header, cells, strict=False)))
    return out


def number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "paper" / "figures")
    args = parser.parse_args(argv)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        print("topk.py: matplotlib is not installed; skipping", file=sys.stderr)
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for filename, label in SOURCES:
        path = RESULTS / filename
        if not path.exists():
            print(f"topk.py: {filename} is absent; skipping", file=sys.stderr)
            continue
        rows = rows_of(path)
        fixtures = sorted({r.get("fixture", "") for r in rows} - {""})
        if not fixtures:
            continue

        figure, axes = plt.subplots(
            1, len(fixtures), figsize=(4.2 * len(fixtures), 3.0), squeeze=False
        )
        for column, fixture in enumerate(fixtures):
            ax = axes[0][column]
            for arm, (legend, marker, width) in ARMS.items():
                points = [
                    (number(r.get("k", "")), number(r.get("feasible_recall", "")))
                    for r in rows
                    if r.get("fixture") == fixture and r.get("arm") == arm
                ]
                points = sorted(
                    (k, v) for k, v in points if k is not None and v is not None
                )
                if not points:
                    continue
                if arm == "oracle":
                    # One point at an enormous K; a horizontal reference reads
                    # better than a marker far off the right edge.
                    ax.axhline(points[0][1], ls=":", lw=1.0, color="grey")
                    ax.text(0.02, points[0][1], " oracle", va="bottom",
                            ha="left", fontsize=7, color="grey",
                            transform=ax.get_yaxis_transform())
                    continue
                ax.plot([k for k, _ in points], [v for _, v in points],
                        marker=marker, lw=width, ms=4, label=legend)
            ax.set_xlabel("$K$ (representatives simulated)")
            if column == 0:
                ax.set_ylabel("feasible recall")
            ax.set_title(fixture, fontsize=8)
            ax.set_ylim(-0.03, 1.05)
            ax.grid(alpha=0.25, lw=0.5)
        axes[0][-1].legend(fontsize=7, loc="lower right")
        figure.tight_layout()
        out = args.out_dir / f"topk_{label.replace(' ', '_')}.pdf"
        figure.savefig(out)
        plt.close(figure)
        print(f"{path.name} -> {out}")
        written += 1
    # Zero either way: a missing results file is a skip with a message, not a
    # build failure. `make figures` says how many it ran.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
