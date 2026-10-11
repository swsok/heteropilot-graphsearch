#!/usr/bin/env python
"""Compare two profiler tp-directories key by key: is one a re-measurement of
the other's hardware, within noise?

**REAL HARDWARE**, both sides. Written for the A5000 tp=1 bundle: the committed
one (`vendor/heteropilot/profiler/perf/A5000/.../tp1`) against a re-profile on
`a5000-2` GPU 0 (`run_tp1_a5k2.sh`). It reports and does not decide: which
spread counts as "within noise" is stated in the result file it feeds, next to
the numbers, and not chosen here.

For each CSV the rows are matched on every column except the timed ones, so a
key present on one side only is counted, never silently dropped. The figure
compared:

    dense.csv, per_sequence.csv, attention.csv   time_us
    skew.csv                                     t_mean_us
    skew_fit.csv                                 alpha (absolute difference:
                                                 alpha is a fitted ratio near 0)

    python experiments/e_g8/profile/compare_bundles.py OLD_TP_DIR NEW_TP_DIR
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

#: file -> (the compared column, columns that are results rather than keys,
#: relative or absolute difference)
SPEC = {
    "dense.csv": ("time_us", {"time_us"}, "rel"),
    "per_sequence.csv": ("time_us", {"time_us"}, "rel"),
    "attention.csv": ("time_us", {"time_us"}, "rel"),
    "skew.csv": ("t_mean_us", {"t_mean_us", "t_max_us", "t_skew_us", "alpha"}, "rel"),
    "skew_fit.csv": ("alpha", {"alpha", "n_samples"}, "abs"),
}


def rows(path: Path, value: str, results: set[str]) -> dict[tuple, float]:
    with path.open() as f:
        reader = csv.DictReader(f)
        keys = [c for c in reader.fieldnames or [] if c not in results]
        return {tuple(r[k] for k in keys): float(r[value]) for r in reader}


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def compare(old: Path, new: Path) -> dict:
    out = {}
    for name, (value, results, kind) in SPEC.items():
        a, b = old / name, new / name
        if not (a.exists() and b.exists()):
            out[name] = {"missing": [str(p) for p in (a, b) if not p.exists()]}
            continue
        ra, rb = rows(a, value, results), rows(b, value, results)
        common = sorted(set(ra) & set(rb))
        if kind == "rel":
            d = [abs(rb[k] - ra[k]) / ra[k] for k in common if ra[k] > 0]
            signed = [(rb[k] - ra[k]) / ra[k] for k in common if ra[k] > 0]
        else:
            d = [abs(rb[k] - ra[k]) for k in common]
            signed = [rb[k] - ra[k] for k in common]
        out[name] = {
            "compared": value, "difference": kind, "keys_old": len(ra), "keys_new": len(rb),
            "keys_common": len(common), "only_old": len(set(ra) - set(rb)),
            "only_new": len(set(rb) - set(ra)),
            "p50": round(pct(d, 0.5), 4) if d else None,
            "p90": round(pct(d, 0.9), 4) if d else None,
            "p99": round(pct(d, 0.99), 4) if d else None,
            "max": round(max(d), 4) if d else None,
            "median_signed": round(statistics.median(signed), 4) if signed else None,
        }
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    result = compare(Path(argv[0]), Path(argv[1]))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
