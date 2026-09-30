"""Control: two ENGINES, both aggregated, different GPUs. Same prompt, greedy."""
import json
import sys
import urllib.request

A, B, MODEL = sys.argv[1], sys.argv[2], sys.argv[3]
PROMPT = "def fibonacci(n):\n    if n <= 1:\n        return n\n    return"
def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)
base = {"model": MODEL, "prompt": PROMPT, "temperature": 0.0, "stream": False, "max_tokens": 24}
a1 = post(f"{A}/v1/completions", base)["choices"][0]["text"]
a2 = post(f"{A}/v1/completions", base)["choices"][0]["text"]
b1 = post(f"{B}/v1/completions", base)["choices"][0]["text"]
print("A repeatable (같은 엔진 두 번):", a1 == a2)
print("A == B (다른 GPU, 둘 다 통짜):", a1 == b1)
if a1 != b1:
    print("  A:", repr(a1[:90]))
    print("  B:", repr(b1[:90]))
