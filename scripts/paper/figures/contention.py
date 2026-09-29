#!/usr/bin/env python
"""E-G4: the fluid model's error against message size, and where it ends.

Two things the table states and a curve shows better. The bidirectional error
is near zero from 4 to 64 MiB and jumps at 128 -- an accuracy *domain*, not a
single error figure -- and the null model is wrong by roughly half wherever
contention exists, which is the case for having a contention model at all.

Reads `outputs/e_g4/microbench.json`, which `analyze.py` already wrote, and
computes nothing. A figure that recomputed its own values could disagree with
the table beside it, and the reader would have no way to tell which was wrong.

    python scripts/paper/figures/contention.py --out-dir paper/figures
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "outputs" / "e_g4" / "microbench.json"

#: Only the declaration the measurements support. The registered verdict is
#: computed on the other one and is a table's job, not a figure's: a curve of
#: an error that comes from a wrong topology would illustrate the wrong thing.
DECLARATION = "as_measured"

CONDITIONS = (
    ("a-cond4-bidirectional-0-2", "bidirectional, shares endpoints"),
    ("a-cond2-two-same-bridge", "two flows, disjoint ports"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "paper" / "figures")
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"contention.py: {args.source} is absent; skipping", file=sys.stderr)
        return 0
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        print("contention.py: matplotlib is not installed; skipping",
              file=sys.stderr)
        return 0

    rows = json.loads(args.source.read_text())["rows"]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(figsize=(4.6, 3.0))

    for label, legend in CONDITIONS:
        for model, style in (("fluid", "-o"), ("null", "--s")):
            points = sorted(
                (r["msg_bytes"] >> 20, r[f"err_{model}_p50"])
                for r in rows
                if r["declaration"] == DECLARATION and r["label"] == label
                and r["flow"] == "0-2"
            )
            if not points:
                continue
            axes.plot([m for m, _ in points], [100 * e for _, e in points],
                      style, lw=1.4, ms=4, label=f"{model}, {legend}")

    axes.set_xscale("log", base=2)
    axes.set_xlabel("message size (MiB)")
    axes.set_ylabel("p50 error against the wire (percent)")
    axes.grid(alpha=0.25, lw=0.5)
    axes.legend(fontsize=6.5, loc="upper left")
    figure.tight_layout()
    out = args.out_dir / "contention_error.pdf"
    figure.savefig(out)
    plt.close(figure)
    print(f"{args.source.name} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
