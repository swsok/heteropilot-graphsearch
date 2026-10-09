"""NIXL initiator, bandwidth form: warm up, then time a fixed iteration count."""
import base64
import json
import statistics
import sys
import time

import torch
from nixl._api import nixl_agent, nixl_agent_config

META = sys.argv[1]
SIZES = [1 << 20, 4 << 20, 16 << 20, 64 << 20, 256 << 20]
# Optional cap, bytes: a GPU whose BAR1 is smaller than the largest size (the
# RTX A5000s expose 256 MiB) cannot register a buffer that large for RDMA.
if len(sys.argv) > 2:
    SIZES = [n for n in SIZES if n <= int(sys.argv[2])]
WARMUP, ITERS = 5, 30
with open(META) as _f:
    info = json.load(_f)
agent = nixl_agent("initiator", nixl_agent_config(backends=["UCX"]))
agent.add_remote_agent(base64.b64decode(info["meta"]))
big = torch.full((max(SIZES),), 7, dtype=torch.uint8, device="cuda:0")
agent.register_memory(agent.get_reg_descs([big]))

print(f"{'bytes':>10} {'median_s':>12} {'Gbit/s':>9}")
for n in SIZES:
    view = big[:n]
    h = agent.initialize_xfer("WRITE", agent.get_xfer_descs([view]),
                              agent.get_xfer_descs([(info["addr"], n, info["dev"])], "VRAM"),
                              "target", b"probe")
    samples = []
    for i in range(WARMUP + ITERS):
        t0 = time.perf_counter()
        state = agent.transfer(h)
        while state != "DONE":
            state = agent.check_xfer_state(h)
            if state == "ERR":
                print("XFER_ERR", flush=True)
                sys.exit(1)
        if i >= WARMUP:
            samples.append(time.perf_counter() - t0)
    m = statistics.median(samples)
    print(f"{n:>10} {m:>12.6f} {n*8/m/1e9:>9.2f}", flush=True)
