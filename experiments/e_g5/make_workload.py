#!/usr/bin/env python
"""Re-space an arrival trace, without touching a single request.

heteropilot's `workloads.generators sharegpt` emits **Poisson arrivals only**
(`--sps`, "Poisson-distributed"), and E-G5 needs two things it cannot give:

  * a load sweep, to find the knee `deploy_and_bench.py` refuses to run without
  * a bursty pattern, because `ServiceSpec.burstiness` exists and the matrix
    registers `normal` and `burst` as an axis

Both are produced here by rewriting **only `arrival_time_ns`**. Every request's
`input_tok_ids`, `input_toks` and `output_toks` are carried through untouched
and in the same order, so across a sweep the requests are *identical* and the
only variable is when they arrive. Resampling the dataset at each rate would
have changed the work as well as the load, and then a knee could be a change in
the request mix.

**Burstiness follows vLLM's own convention**: inter-arrivals are drawn from a
Gamma with shape `burstiness` and mean `1/rate`, so `burstiness = 1` is exactly
Poisson and smaller is burstier. Named after the field it fills rather than
invented here, and `burstiness = 1.0` reproduces the input's mean rate.

    python experiments/e_g5/make_workload.py \\
        --input vendor/heteropilot/workloads/sharegpt-llama-3.1-8b-300-sps10.jsonl \\
        --rps 2 --burstiness 1.0 --out outputs/e_g5/workloads/llama-300-rps2.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

NS = 1e9


def rescale(rows: list[dict], rps: float, burstiness: float, seed: int) -> list[dict]:
    """New arrivals for the same requests, in the same order.

    The first request arrives at the same offset the input gave it, so a
    rescaled trace and its source start the same way and differ only in pace.
    """
    rng = random.Random(seed)
    out: list[dict] = []
    # Gamma(shape=k, scale=1/(k*rate)) has mean 1/rate for every k, so the
    # offered rate is held fixed while only the variance changes. k=1 is the
    # exponential, i.e. Poisson arrivals.
    shape = burstiness
    scale = 1.0 / (shape * rps)
    clock = rows[0].get("arrival_time_ns", 0) / NS if rows else 0.0
    for row in rows:
        new = dict(row)
        new["arrival_time_ns"] = round(clock * NS)
        out.append(new)
        clock += rng.gammavariate(shape, scale)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--rps", type=float, required=True)
    parser.add_argument("--burstiness", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = [
        json.loads(line)
        for line in args.input.read_text().splitlines()
        if line.strip()
    ]
    rescaled = rescale(rows, args.rps, args.burstiness, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rescaled) + "\n"
    )

    span = (rescaled[-1]["arrival_time_ns"] - rescaled[0]["arrival_time_ns"]) / NS
    achieved = (len(rescaled) - 1) / span if span > 0 else float("inf")
    # Provenance beside the trace, because a re-spaced trace is not the file it
    # came from and a reader must be able to tell.
    args.out.with_suffix(".provenance.json").write_text(json.dumps({
        "derived_from": str(args.input),
        "method": (
            "arrival_time_ns rewritten from a Gamma(shape=burstiness, "
            "mean=1/rps) inter-arrival process; every other field carried "
            "through untouched and in the same order"
        ),
        "requests": len(rescaled),
        "target_rps": args.rps,
        "achieved_rps": round(achieved, 4),
        "burstiness": args.burstiness,
        "seed": args.seed,
        "note": (
            "the requests are IDENTICAL to the source trace's; only when they "
            "arrive differs, so across a sweep the only variable is load"
        ),
    }, indent=2, sort_keys=True) + "\n")
    print(f"{args.out}  {len(rescaled)} reqs, {achieved:.3f} rps achieved "
          f"(target {args.rps}), burstiness {args.burstiness}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
