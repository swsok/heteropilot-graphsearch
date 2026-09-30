"""Two-call P/D probe: prefill on one endpoint, decode on another, KV over NIXL.

Not a proxy. It does by hand what a router would do, so that what is being
tested is the KV hand-off and not a router this repository does not have.
"""
import json
import sys
import time
import urllib.request

PREFILL, DECODE, MODEL = sys.argv[1], sys.argv[2], sys.argv[3]
PROMPT = "The InfiniBand fabric connecting these two nodes carries" * 20
MAX_TOKENS = 32

def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)

base = {"model": MODEL, "prompt": PROMPT, "temperature": 0.0, "stream": False}

t0 = time.perf_counter()
p = post(f"{PREFILL}/v1/completions",
         {**base, "max_tokens": 1, "kv_transfer_params": {"do_remote_decode": True}})
t_prefill = time.perf_counter() - t0
params = p.get("kv_transfer_params")
print("PREFILL_PARAMS", json.dumps(params, sort_keys=True)[:300], flush=True)
if not params:
    print("NO_KV_PARAMS -- the prefill instance did not hand anything off", flush=True)
    sys.exit(1)

t1 = time.perf_counter()
d = post(f"{DECODE}/v1/completions",
         {**base, "max_tokens": MAX_TOKENS, "kv_transfer_params": params})
t_decode = time.perf_counter() - t1
print(f"PREFILL_S {t_prefill:.3f}  DECODE_S {t_decode:.3f}", flush=True)
print("COMPLETION", json.dumps(d["choices"][0]["text"])[:300], flush=True)
print("PD_OK", flush=True)
