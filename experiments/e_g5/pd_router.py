"""E-G5 inter-node P/D arm: replay a trace through a prefill and a decode
instance, and record per-request timestamps in `bench run`'s schema.

**An experimental instrument, not a serving component** (GS-32). heteropilot's
`planner/deploy/` has no router, so a disaggregated deployment cannot be
launched through it (GS-28); this does, for measurement only, what a router
would do: for each request, a prefill call with `max_tokens: 1` and
`kv_transfer_params: {"do_remote_decode": true}`, then the real request to the
decode instance carrying the parameters the prefill returned.

It replays requests the way `bench run` does (`bench/core/runner.py`): each at
its trace arrival offset, greedy, `min_tokens = max_tokens = output_toks`,
`ignore_eos`. It writes `requests.jsonl` with the fields heteropilot's
`bench/core/validate.py::_bench_latencies` reads, so E-G5's analysis computes
TTFT, TPOT and goodput for this arm with the same code it uses for the others.

**TTFT here is registered** (preregistration, E-G5 inter-node P/D arm): from
the moment the router sends the prefill call to the first token of the decode
stream. It includes the prefill, the KV pull across the NIC and the decode
instance's first step. `arrival_time` and `queued_ts` are both that send time;
every timestamp is one monotonic clock.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx


async def one(client, idx: int, req: dict, t0: float, args, out: list) -> None:
    target = t0 + req["arrival_time_ns"] / 1e9
    delay = target - time.monotonic()
    if delay > 0:
        await asyncio.sleep(delay)
    n_out = int(req["output_toks"])
    base = {
        "model": args.model, "prompt": list(req["input_tok_ids"]),
        "temperature": 0.0, "ignore_eos": True,
    }
    rec = {
        "request_id": f"pd-{idx}", "input_toks": int(req["input_toks"]),
        "output_toks": n_out, "scheduled_ts": None,
        "first_token_ts": None, "last_token_ts": None,
        "prefill_done_ts": None, "streamed_tokens": 0, "error": None,
    }
    t_send = time.monotonic()
    rec["arrival_time"] = rec["queued_ts"] = t_send
    try:
        r = await client.post(f"{args.prefill}/v1/completions", json={
            **base, "max_tokens": 1, "min_tokens": 1, "stream": False,
            "kv_transfer_params": {"do_remote_decode": True},
        })
        r.raise_for_status()
        params = r.json().get("kv_transfer_params")
        rec["prefill_done_ts"] = time.monotonic()
        if not params:
            raise RuntimeError("the prefill instance returned no kv_transfer_params")
        async with client.stream("POST", f"{args.decode}/v1/completions", json={
            **base, "max_tokens": n_out, "min_tokens": n_out, "stream": True,
            "kv_transfer_params": params,
        }) as s:
            s.raise_for_status()
            async for line in s.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                choice = (json.loads(line[6:]).get("choices") or [{}])[0]
                if choice.get("text"):
                    now = time.monotonic()
                    if rec["first_token_ts"] is None:
                        rec["first_token_ts"] = now
                    rec["last_token_ts"] = now
                    rec["streamed_tokens"] += 1
    except Exception as exc:  # recorded, never retried: a retry hides a failure
        rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
    out.append(rec)


async def run(args) -> list[dict]:
    lines = Path(args.trace).read_text().splitlines()
    requests = [json.loads(line) for line in lines if line.strip()][: args.num_reqs]
    out: list[dict] = []
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as client:
        t0 = time.monotonic()
        await asyncio.gather(*(one(client, i, r, t0, args, out)
                               for i, r in enumerate(requests)))
    return sorted(out, key=lambda r: int(r["request_id"].split("-")[1]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prefill", required=True, help="http://host:port")
    ap.add_argument("--decode", required=True, help="http://host:port")
    ap.add_argument("--model", required=True)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--num-reqs", type=int, required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args(argv)
    records = asyncio.run(run(args))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "requests.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
    )
    failed = sum(1 for r in records if r["error"])
    short = sum(1 for r in records if not r["error"] and r["streamed_tokens"] != r["output_toks"])
    print(f"requests {len(records)}, failed {failed}, token count off {short}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
