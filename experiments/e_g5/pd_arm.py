"""E-G5 inter-node P/D arm (preregistration, E-G5 inter-node P/D arm; GS-32).

Reached through `deploy_and_bench.py --mode pd`. **The deployment is performed
by this harness, not by heteropilot's `planner/deploy/`**, which cannot launch
a split architecture: it serves one engine and has no router (GS-28).

One run, for one condition and one repetition:

1. **Predict.** Search `real-s8s6.v2.yaml` for P/D templates with prefill on
   s8 and decode on s6, evaluate each at the placement deployed
   (`s8/gpu0` + `s6/gpu0`) with `evaluate_placement`, and pick the best. The
   same template is then evaluated on `real-s8s6-shared.v2.yaml`, whose one
   different field reserves 60 % of the s8 -> s6 NIC. The two predictions are
   what the registered criterion compares.
2. **Deploy** that template's knobs: prefill engine on s8 GPU 0 (`kv_producer`),
   decode engine on s6 GPU 0 (`kv_consumer`), `NixlConnector`.
3. **Load.** In `shared`, a background `ib_send_bw` stream from s8 to s6 at a
   0.6 duty cycle -- the E-G4(b) instrument, in the direction this arm's KV
   crosses. Then `pd_router.py` replays spec S's trace.
4. **Tear down**, always: both engines and the background.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from graphsearch import paths_root

ROOT = paths_root.GRAPHSEARCH_ROOT
HERE = Path(__file__).resolve().parent
RAW = HERE / "raw" / "pd"
FIXTURES = ROOT / "fixtures" / "clusters"
CLUSTER = FIXTURES / "real-s8s6.v2.yaml"
CLUSTER_SHARED = FIXTURES / "real-s8s6-shared.v2.yaml"

S8_IP, S6_IP, SSH_PORT = "192.168.210.108", "192.168.210.106", 10022
PREFILL_PORT, DECODE_PORT = 8100, 8200
S8_VLLM = "/home/swsok/heteropilot/.venv-vllm/bin/vllm"
S8_PY = "/home/swsok/heteropilot/.venv-vllm/bin/python"
S6_VLLM = "/home/swsok/.venv-vllm/bin/vllm"
#: nixl's wheel links OpenSSL 3; Ubuntu 20.04 ships 1.1.1. Both nodes carry a
#: copy here (experiments/pd_probe/raw/nixl/README.md).
OPENSSL3 = "/opt/nvidia/nsight-compute/2024.3.2/host/linux-desktop-glibc_2_11_3-x64"
CONDITIONS = ("pd-independent", "pd-shared")
DUTY = 0.6
BG_PORT = 18600
BG_BYTES = 8 << 20


def say(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def ssh(cmd: str, timeout: float = 120) -> str:
    return subprocess.run(
        ["ssh", "-p", str(SSH_PORT), "-o", "BatchMode=yes", S6_IP, cmd],
        capture_output=True, text=True, timeout=timeout, check=True,
    ).stdout


def gpu0_tenants() -> dict:
    q = "nvidia-smi -i 0 --query-compute-apps=pid --format=csv,noheader"
    local = subprocess.run(q.split(), capture_output=True, text=True).stdout.split()
    return {"s8": len(local), "s6": len(ssh(q).split())}


# --- 1. predict -----------------------------------------------------------

def predict(spec_path: Path, work: Path, args) -> dict:
    from types import SimpleNamespace

    from graphsearch.__main__ import cmd_plan_objects, evaluate_placement

    def plan_args(cluster: Path, sub: str):
        return SimpleNamespace(
            service=str(spec_path), cluster=str(cluster), profiles_root=str(ROOT),
            predictor=args.predictor, no_enable_pd=False, ranker="service_margin",
            num_requests=args.num_requests, seed=args.rep,
            cache_dir=str(work / sub / "cache"), work_dir=str(work / sub / "sim"),
            timeout=args.sim_timeout, max_workers=args.max_workers,
            contention="fluid", k_schedule=[4, 8, 16], search_mode="budget",
            budget_sims=args.budget_sims, budget_seconds=None, epsilon=0.0,
            max_embeddings_per_template=None, compression="exact", bounds="all",
            diversity=False, oracle=False, output=None, max_devices=2,
            # A declared modelling choice (GS-32). Each node is a full PCIe
            # mesh, so at the default of 8 one s8 -> s6 pair has 41,980 simple
            # paths and enumeration does not finish. The shortest inter-node
            # route, gpu -> nic -> nic -> gpu, is exactly 3 hops; a longer one
            # relays through another GPU, which does not forward NIC traffic.
            max_hops=3,
        )

    def pd_s8_to_s6(objs) -> list[str]:
        out = set()
        for r in objs.representatives:
            roles = {a.role.value: a.island_id for a in r.exemplar.template.assignments}
            if roles.get("prefill", "").endswith("-s8") and roles.get("decode", "").endswith("-s6"):
                out.add(r.template_id)
        return sorted(out)

    devices = {"s8/gpu0", "s6/gpu0"}
    base_args = plan_args(CLUSTER, "independent")
    base = cmd_plan_objects(base_args)
    table = []
    for tid in pd_s8_to_s6(base):
        v = evaluate_placement(base_args, base, tid, devices)
        table.append({"template_id": tid, "state": v.state, "feasible": v.feasible,
                      "search_state": v.search_state,
                      "p99_ttft_ms": v.plan.predicted.p99_ttft_ms if v.plan else None,
                      "p99_tpot_ms": v.plan.predicted.p99_tpot_ms if v.plan else None,
                      "plan": v.plan})
    judged = [t for t in table if t["plan"] is not None]
    if not judged:
        raise SystemExit("no P/D template with prefill on s8 and decode on s6 was "
                         "simulated to a result; there is nothing to deploy")
    # Feasible before infeasible, then the lower predicted p99 TTFT. Recorded
    # in full so the choice can be checked against the table.
    chosen = min(judged, key=lambda t: (not t["feasible"], t["p99_ttft_ms"]))
    shared_args = plan_args(CLUSTER_SHARED, "shared")
    shared = cmd_plan_objects(shared_args)
    sv = evaluate_placement(shared_args, shared, chosen["template_id"], devices)
    return {
        "chosen": chosen,
        "table": [{k: v for k, v in t.items() if k != "plan"} for t in table],
        "independent": _metrics(chosen["plan"]),
        "shared": _metrics(sv.plan) if sv.plan else None,
        "shared_state": sv.state,
    }


def _metrics(plan) -> dict:
    p = plan.predicted
    return {"p99_ttft_ms": p.p99_ttft_ms, "p50_ttft_ms": p.p50_ttft_ms,
            "p99_tpot_ms": p.p99_tpot_ms, "slo_goodput_rps": p.slo_goodput_rps}


# --- 2. deploy --------------------------------------------------------------

def serve_argv(vllm: str, plan, model: str, port: int, role: str) -> list[str]:
    k = plan.candidate.knobs
    return [
        vllm, "serve", model, "--host", "0.0.0.0", "--port", str(port),
        "--max-model-len", "8192",                  # preregistration row 6
        "--gpu-memory-utilization", "0.6",
        "--no-enable-prefix-caching",
        "--max-num-seqs", str(k.max_num_seqs),
        "--max-num-batched-tokens", str(k.max_num_batched_tokens),
        "--dtype", plan.candidate.dtype, "--kv-cache-dtype", k.kv_cache_dtype,
        "--kv-transfer-config",
        json.dumps({"kv_connector": "NixlConnector", "kv_role": role}),
    ]


def engine_env(host_ip: str, side_port: int) -> dict:
    return {
        "CUDA_VISIBLE_DEVICES": "0", "UCX_NET_DEVICES": "mlx5_0:1",
        "VLLM_NIXL_SIDE_CHANNEL_HOST": host_ip,
        "VLLM_NIXL_SIDE_CHANNEL_PORT": str(side_port),
        "HF_HUB_OFFLINE": "1",
    }


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


class Engines:
    """Prefill here, decode on s6. Torn down on exit, whatever happened."""

    def __init__(self, plan, model: str, out: Path, timeout: float):
        self.plan, self.model, self.out, self.timeout = plan, model, out, timeout
        self.local = None
        self.remote_pgid = None

    def __enter__(self):
        env = dict(os.environ, **engine_env(S8_IP, 5600))
        env["LD_LIBRARY_PATH"] = f"{OPENSSL3}:{env.get('LD_LIBRARY_PATH', '')}"
        self.prefill_argv = serve_argv(S8_VLLM, self.plan, self.model, PREFILL_PORT,
                                       "kv_producer")
        self._log = (self.out / "prefill.log").open("w")
        self.local = subprocess.Popen(
            self.prefill_argv, env=env, start_new_session=True,
            stdout=self._log, stderr=subprocess.STDOUT,
        )
        denv = " ".join(f"{k}={shlex.quote(v)}" for k, v in engine_env(S6_IP, 5700).items())
        self.decode_argv = serve_argv(S6_VLLM, self.plan, self.model, DECODE_PORT,
                                      "kv_consumer")
        remote = (f"LD_LIBRARY_PATH={OPENSSL3} {denv} setsid nohup "
                  + " ".join(shlex.quote(a) for a in self.decode_argv)
                  + " > /tmp/pd_decode.log 2>&1 < /dev/null & echo $!")
        self.remote_pgid = ssh(remote).strip()
        deadline = time.time() + self.timeout
        urls = (f"http://127.0.0.1:{PREFILL_PORT}", f"http://{S6_IP}:{DECODE_PORT}")
        while time.time() < deadline:
            if self.local.poll() is not None:
                raise RuntimeError("the prefill engine exited during start-up")
            if all(healthy(u) for u in urls):
                say("both engines healthy")
                return self
            time.sleep(5)
        raise RuntimeError(f"engines not healthy after {self.timeout:.0f} s")

    def __exit__(self, *exc):
        if self.local is not None and self.local.poll() is None:
            os.killpg(self.local.pid, 15)
            try:
                self.local.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(self.local.pid, 9)
        if getattr(self, "_log", None) is not None:
            self._log.close()
        if self.remote_pgid:
            with (self.out / "decode.log").open("w") as log:
                subprocess.run(["ssh", "-p", str(SSH_PORT), S6_IP,
                                f"kill -- -{self.remote_pgid} 2>/dev/null; sleep 5; "
                                f"kill -9 -- -{self.remote_pgid} 2>/dev/null; "
                                "cat /tmp/pd_decode.log"],
                               stdout=log, stderr=subprocess.STDOUT, timeout=120)
        time.sleep(10)          # let both GPUs release before the next run
        return False


# --- 3. the background ------------------------------------------------------

class NicBackground:
    """`ib_send_bw` from s8 to s6 at a target duty cycle, measured as it runs.

    The server loops on s6; each burst is one client run here, sized to about
    `DUTY` of a one-second period at the NIC's rate. The achieved duty cycle
    is the time spent transferring (bytes over the tool's reported rate)
    divided by the elapsed time, and it is what the raw file records -- a
    target is not a measurement.
    """

    def __init__(self):
        self.stop = threading.Event()
        self.busy = 0.0
        self.bursts: list[dict] = []
        self.t0 = self.t1 = None
        self.server_pgid = None

    def __enter__(self):
        common = f"--report_gbits -s {BG_BYTES} -n {self._iters()} -p {BG_PORT} -F -N"
        self.server_pgid = ssh(
            f"setsid nohup bash -c 'while true; do ib_send_bw {common}; done' "
            f"> /tmp/pd_bg_server.log 2>&1 < /dev/null & echo $!"
        ).strip()
        time.sleep(2)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.t0 = time.monotonic()
        self.thread.start()
        return self

    @staticmethod
    def _iters() -> int:
        # ~0.6 s of transfer at ~88 Gbit/s (11 GB/s) per 1 s period.
        return max(1, int(DUTY * 11.0e9 / BG_BYTES))

    def _loop(self):
        argv = ["ib_send_bw", "--report_gbits", "-s", str(BG_BYTES), "-n",
                str(self._iters()), "-p", str(BG_PORT), "-F", "-N", S6_IP]
        while not self.stop.is_set():
            start = time.monotonic()
            r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            gbit = None
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == str(BG_BYTES):
                    gbit = float(parts[3])
            if gbit:
                moved = BG_BYTES * self._iters()
                self.busy += moved * 8 / (gbit * 1e9)
            self.bursts.append({"t": round(start - self.t0, 3), "gbit_s": gbit,
                                "rc": r.returncode})
            # Pace to the target: sleep until busy/elapsed would fall to DUTY.
            elapsed = time.monotonic() - self.t0
            wait = self.busy / DUTY - elapsed
            if wait > 0:
                self.stop.wait(wait)

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=90)
        self.t1 = time.monotonic()
        ssh(f"kill -- -{self.server_pgid} 2>/dev/null; pkill -f 'ib_send_bw.*{BG_PORT}' ; true")
        return False

    def record(self) -> dict:
        span = (self.t1 or time.monotonic()) - self.t0
        return {"target_duty_cycle": DUTY,
                "achieved_duty_cycle": round(self.busy / span, 3) if span else None,
                "bursts": len(self.bursts),
                "median_gbit_s": sorted(b["gbit_s"] for b in self.bursts if b["gbit_s"])[
                    len([b for b in self.bursts if b["gbit_s"]]) // 2]
                if any(b["gbit_s"] for b in self.bursts) else None,
                "direction": "s8 -> s6 (client here, server on s6)",
                "instrument": "ib_send_bw, as E-G4(b)"}


# --- the run ----------------------------------------------------------------

def run_pd(args, C, service_spec, workload_at) -> int:
    if args.condition not in CONDITIONS:
        raise SystemExit(f"--mode pd takes --condition {' or '.join(CONDITIONS)}")
    out = (HERE.parent.parent / "outputs" / "e_g5" / "dry-run" / "pd"
           if args.dry_run else RAW) / args.condition / str(args.rep)
    work = ROOT / "outputs" / "e_g5" / "pd" / args.condition / str(args.rep)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    model = "llama31-8b"
    info = C.MODELS[model]
    S = C.SPECS["service"]
    rps = S["arrival_rate_rps"]
    spec_path = service_spec(model, "normal", "knee", rps, work / "service.yaml",
                             ttft_max_ms=S["ttft_max_ms"], tpot_max_ms=S["tpot_max_ms"],
                             min_goodput_rps=S["min_goodput_rps"])
    say(f"P/D arm {args.condition} rep {args.rep}: predicting")
    prediction = predict(spec_path, work, args)
    plan = prediction["chosen"]["plan"]
    say(f"chosen {plan.candidate.id}: independent "
        f"{prediction['independent']['p99_ttft_ms']:.1f} ms, shared "
        f"{(prediction['shared'] or {}).get('p99_ttft_ms')}")
    trace = workload_at(rps, model, work)
    record = {
        "banner": ("DRY RUN -- nothing was launched." if args.dry_run else
                   "REAL HARDWARE -- two nodes, s8 and s6."),
        "deployed_by": "this experiment harness (pd_arm.py, pd_router.py), NOT "
                       "heteropilot planner/deploy/, which has no router (GS-28, GS-32)",
        "condition": args.condition, "rep": args.rep, "offered_rps": rps,
        "trace": str(trace), "num_reqs": C.REQUESTS_PER_RUN,
        "placement": {"prefill": "s8/gpu0", "decode": "s6/gpu0"},
        "prediction": prediction | {"chosen": {k: v for k, v in prediction["chosen"].items()
                                               if k != "plan"}},
        "slo": {"ttft_max_ms": S["ttft_max_ms"], "tpot_max_ms": S["tpot_max_ms"]},
        "gpu0_tenants_before": gpu0_tenants(),
        "served_model": info["hf_id"],
        "ttft_definition": ("router prefill-send to first token of the decode "
                            "stream; includes the prefill, the KV pull across the "
                            "NIC and the decode instance's first step"),
    }
    if args.dry_run:
        record["state"] = "dry run"
    elif any(record["gpu0_tenants_before"].values()) and not args.allow_tenants:
        record["state"] = "refused: GPU 0 on s8 or s6 is not free"
    else:
        with Engines(plan, info["hf_id"], out, args.health_timeout) as eng:
            record["prefill_argv"], record["decode_argv"] = eng.prefill_argv, eng.decode_argv
            bg = NicBackground() if args.condition == "pd-shared" else None
            router = [S8_PY, "-u", str(HERE / "pd_router.py"),
                      "--prefill", f"http://127.0.0.1:{PREFILL_PORT}",
                      "--decode", f"http://{S6_IP}:{DECODE_PORT}",
                      "--model", info["hf_id"], "--trace", str(trace),
                      "--num-reqs", str(C.REQUESTS_PER_RUN), "--out", str(out / "pd")]
            if bg is not None:
                with bg:
                    r = subprocess.run(router, capture_output=True, text=True,
                                       timeout=args.bench_timeout)
                record["background"] = bg.record()
            else:
                r = subprocess.run(router, capture_output=True, text=True,
                                   timeout=args.bench_timeout)
            (out / "router.log").write_text(r.stdout + r.stderr)
            record["router_returncode"] = r.returncode
            record["router_summary"] = r.stdout.strip().splitlines()[-1:]
            record["state"] = "measured" if r.returncode == 0 else "failed"
    record["written_at"] = datetime.now(timezone.utc).isoformat()
    (out / "provenance.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
    say(f"wrote {out / 'provenance.json'} ({record['state']})")
    return 0
