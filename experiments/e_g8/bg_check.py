"""The background instrument alone, no engines: does it reach its duty cycle?

**REAL HARDWARE** (the NIC only). Runs `NicBackground` for a fixed time in
one direction and writes what it achieved. Row 11 records the D2 result
after the loop was moved onto the sender.

    python experiments/e_g8/bg_check.py --direction D2 [--seconds 120]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--direction", choices=("D1", "D2"), required=True)
    ap.add_argument("--seconds", type=float, default=120)
    args = ap.parse_args(argv)
    spec = importlib.util.spec_from_file_location("e_g8_pd_arm", HERE / "pd_arm.py")
    arm = importlib.util.module_from_spec(spec)
    sys.modules["e_g8_pd_arm"] = arm
    spec.loader.exec_module(arm)

    started = datetime.now(timezone.utc).isoformat()
    with arm.NicBackground(args.direction) as bg:
        time.sleep(args.seconds)
    out = HERE / "raw" / "bg-check" / f"{args.direction}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    rec = {"banner": "REAL HARDWARE -- the NIC only, no engines", "started": started,
           "seconds": args.seconds, **bg.record(), "burst_log": bg.bursts}
    out.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in rec.items() if k != "burst_log"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
