"""P4.2: three load levels for E-G6, derived from heteropilot's own trace.

**Synthetic. Not a workload anybody observed.** The token distributions come
from heteropilot's committed ShareGPT trace, which is real conversation data;
the ARRIVAL TIMES here are rescaled to hit three target rates and are this
script's invention. A result computed from these files is a result about the
search at three load levels, not a statement about what any service receives.

**Why rescaling rather than `python -m workloads.generators sharegpt`.** That
generator needs the source dataset and a tokenizer, so it needs network and a
model download, and it would give three traces whose *content* differed as well
as their rate. E-G6 varies cluster size and symmetry; the load level is a
control, and a control that changes two things at once is not one. Rescaling
one trace keeps the prompts, the completions and their correlation identical
across the three levels and moves only the arrivals -- which is the variable
being swept.

JSONL carries no comments, so the banner cannot go in the trace itself. Each
trace is written with a `.meta.json` beside it, and the directory gets a
README; the analysis reads the meta file and refuses a trace that has none.

    python experiments/scripts/e_g6_traces.py --out outputs/e_g6/traces
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graphsearch import paths_root

#: heteropilot's committed trace. Real conversations, already tokenised for
#: Llama-3.1-8B, and in the simulator's own JSONL format -- so nothing here
#: has to re-derive a format that repository already fixed.
SOURCE = (
    paths_root.HETEROPILOT_ROOT
    / "workloads"
    / "sharegpt-llama-3.1-8b-300-sps10.jsonl"
)

#: Requests per second. Three levels spanning an order of magnitude, because
#: the question is whether the search's cost depends on load at all -- and two
#: points a factor of two apart could not tell a dependence from noise.
LEVELS = {"low": 2.0, "mid": 10.0, "high": 40.0}

README = """\
# E-G6 load traces — GENERATED, and synthetic in the part that matters

Three JSONL traces at {levels} requests/second.

**The prompts and completions are heteropilot's committed ShareGPT trace**
(`workloads/sharegpt-llama-3.1-8b-300-sps10.jsonl`) — real conversation data,
already tokenised, unchanged here including the correlation between input and
output length.

**The arrival times are not observed.** They are rescaled by
`experiments/scripts/e_g6_traces.py` so that the same 300 requests arrive at
three different rates. That is the variable E-G6 sweeps; everything else is
held fixed on purpose, because a control that changes two things at once is
not a control.

Each trace has a `.meta.json` beside it recording the source, the target rate,
the achieved rate and this warning. The analysis refuses a trace with no meta
file — a trace whose provenance was lost is not usable as a control.

Regenerate:

```bash
python experiments/scripts/e_g6_traces.py --out {out}
```
"""


def rescale(rows: list[dict], target_rps: float) -> list[dict]:
    """The same requests, arriving at `target_rps`.

    Linear on the arrival axis: the first request stays at t=0 and the span is
    scaled so `len(rows) / span` is the target. Burstiness -- the shape of the
    inter-arrival distribution -- is therefore preserved exactly, which is the
    point. A regenerated Poisson process at each rate would have changed the
    shape as well as the rate, and E-G6 could not then say which one the curve
    responded to.
    """
    if len(rows) < 2:
        return [dict(row) for row in rows]
    base = rows[0]["arrival_time_ns"]
    span = rows[-1]["arrival_time_ns"] - base
    if span <= 0:
        return [dict(row) for row in rows]
    wanted_span = len(rows) / target_rps * 1e9
    factor = wanted_span / span
    out = []
    for row in rows:
        copy = dict(row)
        copy["arrival_time_ns"] = round((row["arrival_time_ns"] - base) * factor)
        out.append(copy)
    return out


def achieved_rps(rows: list[dict]) -> float:
    span = rows[-1]["arrival_time_ns"] - rows[0]["arrival_time_ns"]
    return len(rows) / (span / 1e9) if span > 0 else float("inf")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="outputs/e_g6/traces")
    parser.add_argument("--source", type=Path, default=SOURCE)
    args = parser.parse_args(argv)

    if not args.source.exists():
        raise SystemExit(
            f"{args.source} is missing. Run `git submodule update --init` "
            f"first; this reuses heteropilot's committed trace rather than "
            f"downloading a dataset."
        )
    rows = [json.loads(line) for line in args.source.read_text().splitlines() if line]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, target in sorted(LEVELS.items()):
        scaled = rescale(rows, target)
        path = out / f"e_g6-{name}-{target:g}rps.jsonl"
        path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in scaled) + "\n"
        )
        path.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "banner": (
                        "SYNTHETIC ARRIVALS. Prompts and completions are "
                        "heteropilot's committed ShareGPT trace, unchanged. "
                        "The arrival times were rescaled by "
                        "experiments/scripts/e_g6_traces.py and are not "
                        "observed. Not a measurement of any service."
                    ),
                    "level": name,
                    "target_rps": target,
                    "achieved_rps": round(achieved_rps(scaled), 6),
                    "requests": len(scaled),
                    "source_trace": str(
                        args.source.relative_to(paths_root.GRAPHSEARCH_ROOT)
                        if args.source.is_relative_to(paths_root.GRAPHSEARCH_ROOT)
                        else args.source
                    ),
                    "held_fixed": (
                        "prompt and completion lengths, their correlation, and "
                        "the shape of the inter-arrival distribution"
                    ),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(
            f"{path}  {len(scaled)} requests at "
            f"{achieved_rps(scaled):.3f} rps (target {target:g})"
        )

    (out / "README.md").write_text(
        README.format(
            levels=", ".join(f"{v:g}" for v in sorted(LEVELS.values())),
            out=args.out,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
