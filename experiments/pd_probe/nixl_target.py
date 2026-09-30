"""NIXL target: register a CUDA buffer, publish metadata, wait for a remote write."""
import base64
import json
import sys
import time

import torch
from nixl._api import nixl_agent, nixl_agent_config

NBYTES = int(sys.argv[1])
OUT = sys.argv[2]
agent = nixl_agent("target", nixl_agent_config(backends=["UCX"]))
buf = torch.zeros(NBYTES, dtype=torch.uint8, device="cuda:0")
agent.register_memory(agent.get_reg_descs([buf]))
xfer = agent.get_xfer_descs([buf])
with open(OUT, "w") as f:
    json.dump({"meta": base64.b64encode(agent.get_agent_metadata()).decode(),
               "descs": base64.b64encode(agent.get_serialized_descs(xfer)).decode(),
               "addr": buf.data_ptr(), "dev": buf.device.index}, f)
print("TARGET_READY", flush=True)
deadline = time.time() + 300
seen = 0
while time.time() < deadline:
    if agent.check_remote_xfer_done("initiator", b"probe"):
        seen += 1
        if seen == 1:
            got = int(buf[:8388608].sum().item())
            print(f"TARGET_GOT first_notif_sum={got}", flush=True)
    time.sleep(0.01)
print(f"TARGET_DONE notifs={seen}", flush=True)
