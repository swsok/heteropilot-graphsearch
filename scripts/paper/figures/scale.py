#!/usr/bin/env python
"""E-G6's three curves: wall time, VF2 seconds and compression ratio against size.

One line per symmetry level, because symmetry is the variable the contribution
depends on and averaging over it would hide the whole result. A single curve of
"cost against devices" would say the search scales some way it does not scale
for any actual cluster.

Reads `outputs/e_g6/scale.json` -- the numbers E-G6 already measured -- and
computes nothing. A figure that recomputed its own values could disagree with
the table beside it, and the reader would have no way to tell which was wrong.

Run through `make figures`, or:

    python scripts/paper/figures/scale.py --out-dir paper/figures
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: Each panel: the JSON key, the axis label, and whether a log y-axis helps.
PANELS = (
    ("t_total_s", "wall time (s)", True, "scale_walltime"),
    ("t_vf2_s", "VF2 (s)", True, "scale_vf2"),
    ("compression_ratio", "representatives / embeddings", True, "scale_ratio"),
)

#: Marker per symmetry, so the figure survives being printed in grey.
MARKERS = {0.0: "o", 0.5: "s", 1.0: "^"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=ROOT / "outputs/e_g6/scale.json")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "paper/figures")
    args = parser.parse_args(argv)

    if not args.json.exists():
        print(
            f"scale.py: {args.json} is missing -- run E-G6 first "
            f"(bash experiments/scripts/e_g6_run.sh). No figure written.",
            file=sys.stderr,
        )
        return 1

    try:
        import matplotlib
    except ModuleNotFoundError:
        print(
            "scale.py: matplotlib is not installed in this interpreter, so no "
            "figure was written. The E-G6 table is unaffected. Install it, or "
            "run `make figures` through an interpreter that has it.",
            file=sys.stderr,
        )
        return 1

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = json.loads(args.json.read_text())
    symmetries = sorted({row["symmetry"] for row in rows})
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for key, ylabel, logy, stem in PANELS:
        figure, axes = plt.subplots(figsize=(4.2, 3.0))
        drew = False
        for symmetry in symmetries:
            series = sorted(
                (r for r in rows if r["symmetry"] == symmetry and r.get(key) is not None),
                key=lambda r: r["devices"],
            )
            if not series:
                continue
            axes.plot(
                [r["devices"] for r in series],
                [r[key] for r in series],
                marker=MARKERS.get(symmetry, "x"),
                label=f"symmetry {symmetry:g}",
            )
            drew = True
        if not drew:
            plt.close(figure)
            continue

        axes.set_xlabel("devices")
        axes.set_ylabel(ylabel)
        axes.set_xscale("log", base=2)
        if logy:
            axes.set_yscale("log")
        axes.set_xticks([r["devices"] for r in rows])
        axes.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
        axes.grid(True, which="both", alpha=0.3, linewidth=0.5)
        axes.legend(fontsize=7, frameon=False)
        figure.tight_layout()

        out = args.out_dir / f"{stem}.pdf"
        figure.savefig(out, metadata={"CreationDate": None})
        plt.close(figure)
        print(f"{args.json} -> {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
