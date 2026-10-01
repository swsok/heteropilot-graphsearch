#!/usr/bin/env python
"""E-G4 location (b): the inter-node NIC, with `ib_send_bw`.

**REAL HARDWARE.** Two A40 nodes, one Mellanox MT4123 each, on one InfiniBand
subnet. Every figure carries the serials of both ends.

`run_pair.py` measures location (a) with device-to-device peer copies, which is
the right instrument for a bus inside one machine and no instrument at all for
a wire between two. This uses `perftest`, which is what both nodes have, and
records the tool and its arguments in every raw file: `nccl-tests` and a torch
probe are not interchangeable evidence, and neither are these (heteropilot
D116 makes the same point about a different pair of tools).

**Which of the registered conditions this can answer, and which it cannot.**

    1 single             one stream                        yes
    2 two-same           two streams over the same NIC     yes
    3 two-independent    two streams over disjoint NICs    NO -- one NIC/node
    4 bidirectional      both directions at once (-b)      yes
    5 collective         all-reduce over IB                deferred: NCCL needs
                                                           torch on both nodes
                                                           and s6 has none

Condition 3 is reported as impossible on this hardware rather than omitted. It
is not `not run`: each node has exactly one InfiniBand device, so there is no
pair of disjoint NICs to put two flows on. That is a property of the machines
and it is stated as one.

    python experiments/microbench/run_nic.py --peer s6 --condition single
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HETEROPILOT = ROOT / "vendor" / "heteropilot"

#: The same grid PLAN.md registers for location (a), in bytes, so the two
#: locations are read on one axis.
SIZES_MIB = [1, 2, 4, 8, 16, 32, 64, 128, 256]

CONDITIONS = {
    "single": "one stream, nothing else on the wire (the control)",
    "two-same": "two concurrent streams over the SAME NIC",
    "bidirectional": "both directions at once (ib_send_bw -b)",
}

#: Not a condition this hardware can run, and the reason is not shyness.
IMPOSSIBLE = {
    "two-independent": (
        "each node has exactly one InfiniBand device (Mellanox MT4123), so "
        "there is no pair of disjoint NICs to put two flows on. This is a "
        "property of the machines, not an experiment that was skipped."
    ),
    "collective": (
        "an all-reduce over IB needs NCCL, which needs torch on both nodes; "
        "the peer node has no such environment yet. Deferred, not impossible."
    ),
}


def say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def ssh(peer: str, port: int, command: str, timeout: float = 120) -> str:
    return subprocess.run(
        ["ssh", "-p", str(port), "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=20", peer, command],
        capture_output=True, text=True, timeout=timeout, check=False,
    ).stdout


def serials(peer: str | None, port: int) -> str:
    """`accel serials` for one end. What identifies the MACHINE."""
    script = HETEROPILOT / "scripts" / "whichnode.sh"
    if peer is None:
        if not script.exists():
            return "unknown"
        out = subprocess.run(["bash", str(script)], capture_output=True,
                             text=True, check=False).stdout
    else:
        out = ssh(peer, port, "nvidia-smi --query-gpu=uuid --format=csv,noheader")
        return "+".join(sorted(out.split())) [:64] or "unknown"
    for line in out.splitlines():
        if "accel serials" in line:
            return line.split(":", 1)[1].strip()
    return "unknown"


def ib_device(peer: str | None, port: int) -> dict:
    """Which IB device, and what rate it reports. Read, never assumed."""
    command = "ibstat 2>/dev/null"
    text = (ssh(peer, port, command) if peer else
            subprocess.run(["bash", "-c", command], capture_output=True,
                           text=True, check=False).stdout)
    name = re.search(r"CA '([^']+)'", text)
    rate = re.search(r"Rate:\s*(\d+)", text)
    state = re.search(r"State:\s*(\w+)", text)
    return {
        "device": name.group(1) if name else "unknown",
        "rate_gbit_s": int(rate.group(1)) if rate else None,
        "state": state.group(1) if state else "unknown",
    }


def parse_bw(text: str) -> dict | None:
    """The BW line of an `ib_send_bw` run: bytes, iterations, peak, average.

    perftest prints a fixed-width table; the row wanted is the one whose first
    field is the message size. Parsed rather than eyeballed because the average
    and the peak are different numbers and quoting the wrong one would overstate
    a wire by a few per cent, quietly.
    """
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0].isdigit() and fields[1].isdigit():
            try:
                return {
                    "msg_bytes": int(fields[0]),
                    "iterations": int(fields[1]),
                    "peak_gbit_s": float(fields[2]),
                    "average_gbit_s": float(fields[3]),
                    "msg_rate_mpps": float(fields[4]),
                }
            except ValueError:
                continue
    return None


#: Bytes to move per point, so every size takes about the same wall time.
#: Roughly five seconds at the measured ~90 Gbit/s.
BYTES_PER_POINT = 56_000_000_000


def iterations_for(size: int) -> int:
    """A fixed ITERATION COUNT, not a duration, and the difference matters.

    `ib_send_bw -D <seconds>` produced numbers that are not possible: 192.69
    Gbit/s on a 100 Gbit/s link, and a message rate that barely changed when
    the message size doubled -- which is the tell, since a saturated wire must
    halve its message rate when each message doubles. Re-measured with `-n` the
    same points are 93.98 / 94.05 / 97.89 and the message rate halves exactly.
    So the duration mode is not trusted here and the iteration mode is.
    """
    return max(100, min(50_000, BYTES_PER_POINT // max(1, size)))


def one_stream(peer: str, port: int, size: int, ib_port: int, args,
               bidirectional: bool = False) -> dict:
    """One `ib_send_bw` pair: a server here, a client on the peer.

    **`-b` reports PER DIRECTION, not the sum.** Established by reading the
    NIC's own counters across a run: 1,500 messages of 8 MiB left 12.66 GB in
    `port_xmit_data` and 12.66 GB in `port_rcv_data`, both matching the 12.58
    GB expected each way, while the tool reported 94.73 Gbit/s -- close to the
    88.58 it reports for one direction alone, and half of what a sum would be.
    The wire is genuinely full duplex.
    """
    common = ["--report_gbits", "-s", str(size), "-n", str(iterations_for(size)),
              "-p", str(ib_port), "-F", "-N"]
    if bidirectional:
        common.append("-b")

    if getattr(args, "reverse", False):
        # --reverse: the server on the PEER and the client -- the sender --
        # here, so the data crosses here -> peer. Same tool, same arguments,
        # the other direction of the same port.
        remote = " ".join(shlex.quote(c) for c in ["ib_send_bw", *common])
        server = subprocess.Popen(
            ["ssh", "-p", str(args.ssh_port), "-o", "BatchMode=yes", peer, remote],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(2.5)                  # ssh plus bind, before dialling
        client_out = subprocess.run(
            ["ib_send_bw", *common, args.peer_ip], capture_output=True, text=True,
            timeout=args.duration + 120,
        ).stdout
    else:
        server = subprocess.Popen(
            ["ib_send_bw", *common],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(1.5)                  # let the server bind before dialling
        remote = " ".join(shlex.quote(c) for c in ["ib_send_bw", *common, args.local_ip])
        client_out = ssh(peer, args.ssh_port, remote,
                         timeout=args.duration + 120)
    try:
        server_out, _ = server.communicate(timeout=args.duration + 60)
    except subprocess.TimeoutExpired:
        server.kill()
        server_out, _ = server.communicate()

    return {
        "ib_port": ib_port,
        "server": parse_bw(server_out),
        "client": parse_bw(client_out),
        "server_raw_tail": server_out.strip().splitlines()[-3:],
    }


def gpu_tenants(peer: str | None, port: int) -> int:
    """How many compute processes hold a GPU at that end.

    The NIC measurement does not use the GPUs, but a node under load is not the
    node the banner describes, and the load average alone cannot tell a busy
    neighbour from a busy us.
    """
    command = ("nvidia-smi --query-compute-apps=pid --format=csv,noheader "
               "2>/dev/null | wc -l")
    text = (ssh(peer, port, command) if peer else
            subprocess.run(["bash", "-c", command], capture_output=True,
                           text=True, check=False).stdout)
    try:
        return int(text.strip() or 0)
    except ValueError:
        return -1


def load_average(peer: str | None, port: int) -> float | None:
    text = (ssh(peer, port, "cat /proc/loadavg") if peer else
            Path("/proc/loadavg").read_text())
    try:
        return round(float(text.split()[0]), 2)
    except (ValueError, IndexError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", required=True,
                        choices=sorted(CONDITIONS) + sorted(IMPOSSIBLE))
    parser.add_argument("--peer", required=True, help="ssh host of the far node")
    parser.add_argument("--ssh-port", type=int, default=10022)
    parser.add_argument("--local-ip", required=True,
                        help="this node's IB address, which the peer dials")
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES_MIB)
    parser.add_argument("--duration", type=int, default=5,
                        help="seconds per size, per stream")
    parser.add_argument("--label", required=True)
    parser.add_argument("--out-root", type=Path, default=None)
    parser.add_argument("--allow-tenants", action="store_true")
    parser.add_argument(
        "--reverse", action="store_true",
        help="put the ib_send_bw server on the peer and send from here. Without "
             "it the peer sends and the data crosses peer -> here, which is the "
             "direction E-G4(b)'s 2026-09-29 files measured.",
    )
    parser.add_argument("--peer-ip", default=None,
                        help="the peer's InfiniBand IP; required with --reverse")
    args = parser.parse_args(argv)

    if args.reverse and not args.peer_ip:
        parser.error("--reverse needs --peer-ip")
    if args.condition in IMPOSSIBLE:
        print(f"{args.condition}: {IMPOSSIBLE[args.condition]}", file=sys.stderr)
        return 2

    here = {"serials": serials(None, args.ssh_port),
            "ib": ib_device(None, args.ssh_port),
            "hostname": socket.gethostname()}
    there = {"serials": serials(args.peer, args.ssh_port),
             "ib": ib_device(args.peer, args.ssh_port),
             "hostname": ssh(args.peer, args.ssh_port, "hostname").strip()}
    if there["ib"]["state"] != "Active" or here["ib"]["state"] != "Active":
        print(f"refusing: an InfiniBand port is not Active "
              f"(here {here['ib']}, there {there['ib']})", file=sys.stderr)
        return 1

    tenants = {"here": gpu_tenants(None, args.ssh_port),
               "there": gpu_tenants(args.peer, args.ssh_port)}
    if (tenants["here"] or tenants["there"]) and not args.allow_tenants:
        print(f"refusing: GPU tenants present {tenants}. A figure measured "
              f"beside another job is measured under a condition the REAL "
              f"HARDWARE banner does not state.", file=sys.stderr)
        return 1

    say(f"{args.condition}: {here['hostname']} <-> {there['hostname']} over "
        f"{here['ib']['device']} ({here['ib']['rate_gbit_s']} Gbit/s)")

    load_before = {"here": load_average(None, args.ssh_port),
                   "there": load_average(args.peer, args.ssh_port)}
    started = time.time()
    results: dict[str, dict] = {}
    for mib in args.sizes:
        size = mib << 20
        if args.condition == "two-same":
            # Two streams, two IB service ports, one physical NIC. Started
            # together so they overlap; each reports its own bandwidth.
            import concurrent.futures as cf
            with cf.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(one_stream, args.peer, args.ssh_port, size,
                                18515 + i, args)
                    for i in range(2)
                ]
                streams = [f.result() for f in futures]
        elif args.condition == "bidirectional":
            streams = [one_stream(args.peer, args.ssh_port, size, 18515, args,
                                  bidirectional=True)]
        else:
            streams = [one_stream(args.peer, args.ssh_port, size, 18515, args)]

        results[f"{mib}MiB"] = {"msg_bytes": size, "streams": streams}
        shown = "  ".join(
            f"{s['server']['average_gbit_s']:.2f}" if s.get("server") else "?"
            for s in streams
        )
        say(f"  {mib:4d} MiB  {shown} Gbit/s")

    # `ib_send_bw -b` does not consistently report per direction. The NIC's own
    # counters settle the semantics for a single run -- 1,500 messages of 8 MiB
    # left 12.66 GB in `port_xmit_data` AND 12.66 GB in `port_rcv_data` while
    # the tool said 94.73, so that reading is per direction -- but some points
    # come back at almost exactly twice their neighbours, which is the same
    # measurement reported as a sum. Those points are FLAGGED, not dropped and
    # not quietly kept: a figure whose unit is uncertain is
    # `unknown_measurement`, and the raw file says which ones they are.
    if args.condition == "bidirectional":
        values = sorted(
            s["server"]["average_gbit_s"]
            for block in results.values() for s in block["streams"]
            if s.get("server")
        )
        if values:
            median = values[len(values) // 2]
            for key, block in results.items():
                for stream in block["streams"]:
                    got = (stream.get("server") or {}).get("average_gbit_s")
                    if got and got > 1.6 * median:
                        stream["suspect"] = (
                            f"{got:.2f} is {got / median:.2f}x the condition's "
                            f"median of {median:.2f}; `ib_send_bw -b` appears "
                            f"to have reported the SUM of both directions for "
                            f"this point rather than one of them. The unit is "
                            f"uncertain, so the figure is unknown_measurement "
                            f"and is excluded from any summary."
                        )
                        say(f"  {key}: SUSPECT {got:.2f} "
                            f"({got / median:.2f}x median)")

    payload = {
        "banner": (
            "REAL HARDWARE -- two nodes, serials for both ends below. Raw "
            "throughput only; this file contains no prediction and no verdict."
        ),
        "label": args.label,
        "condition": args.condition,
        "condition_means": CONDITIONS[args.condition],
        "location": "(b) inter-node NIC",
        "tool": "perftest ib_send_bw",
        "method": (
            "ib_send_bw --report_gbits -s <size> -n <iterations> -F -N"
            + (" -b" if args.condition == "bidirectional" else "")
            + ("; two streams on ports 18515,18516"
               if args.condition == "two-same"
               else "; one stream on port 18515")
        ),
        "near": here,
        "far": there,
        # Which way the bytes went. The server is the receiver; the client, the
        # sender. Recorded because the E-G4(b) files of 2026-09-29 do not say it
        # and it had to be recovered from the code.
        "direction": (
            f"{here['hostname']} -> {there['hostname']} (client here, server on the peer)"
            if args.reverse else
            f"{there['hostname']} -> {here['hostname']} (client on the peer, server here)"
        ),
        "gpu_tenants": tenants,
        "loadavg_before": load_before,
        "loadavg_after": {"here": load_average(None, args.ssh_port),
                          "there": load_average(args.peer, args.ssh_port)},
        "iterations_per_size": {
            f"{m}MiB": iterations_for(m << 20) for m in args.sizes
        },
        "bidirectional_reports": (
            "per direction, not the sum -- established from the NIC's own "
            "port_xmit_data and port_rcv_data counters across a run"
        ),
        "date": date.today().isoformat(),
        "wall_s": round(time.time() - started, 2),
        "sizes": results,
        "not_run_here": IMPOSSIBLE,
    }
    root = args.out_root or (
        Path(__file__).parent / "raw" / (
            f"{payload['date']}-nic-{here['hostname']}-to-{there['hostname']}"
            if args.reverse else
            f"{payload['date']}-nic-{here['hostname']}-{there['hostname']}"
        )
    )
    root.mkdir(parents=True, exist_ok=True)
    out = root / f"{args.label}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
