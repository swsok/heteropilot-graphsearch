"""Is the P/D answer the same as the aggregated answer? Greedy, so it must be."""
import json
import sys
import urllib.request

PREFILL, DECODE, MODEL = sys.argv[1], sys.argv[2], sys.argv[3]
PROMPTS = [
    "InfiniBand differs from Ethernet in three ways. First,",
    "The capital of France is Paris, and the capital of Japan is",
    "def fibonacci(n):\n    if n <= 1:\n        return n\n    return",
]
def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)

ok = True
for prompt in PROMPTS:
    base = {"model": MODEL, "prompt": prompt, "temperature": 0.0,
            "stream": False, "max_tokens": 24}
    # aggregated: the decode instance on its own, no hand-off
    agg = post(f"{DECODE}/v1/completions", base)["choices"][0]["text"]
    # disaggregated: prefill elsewhere, KV pulled across
    p = post(f"{PREFILL}/v1/completions",
             {**base, "max_tokens": 1, "kv_transfer_params": {"do_remote_decode": True}})
    d = post(f"{DECODE}/v1/completions",
             {**base, "kv_transfer_params": p["kv_transfer_params"]})["choices"][0]["text"]
    same = agg == d
    ok &= same
    print(f"{'SAME' if same else 'DIFFER'}  {prompt[:38]!r}")
    if not same:
        print(f"   aggregated: {agg[:90]!r}")
        print(f"   disagg    : {d[:90]!r}")
print("EQUIV_OK" if ok else "EQUIV_FAIL")
