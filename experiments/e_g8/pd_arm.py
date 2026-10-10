"""E-G8: prefill/decode across two different accelerators, `s8` (A40) and
`a5k2` (`a5000-2` GPU 0) -- revision R5.2.

**REAL HARDWARE when it runs; DRY RUN when asked.** E-G5's inter-node P/D arm
(`experiments/e_g5/pd_arm.py`) generalised from one fixed direction (prefill
`s8`, decode `s6`) to either direction between two unlike nodes:

    D1   prefill s8   (A40)        -> decode a5k2 (RTX A5000)
    D2   prefill a5k2 (RTX A5000)  -> decode s8   (A40)

What is the same as E-G5, on purpose, so the arms compare: the router
(`experiments/e_g5/pd_router.py`, imported unchanged), spec S and its trace,
the template rule (row 5's "feasible first, then the lower predicted p99 TTFT,
at the placement deployed", applied once, row 7 a), `NixlConnector` with the
KV in GPU memory at both ends (the GPUDirect path, GS-39), and the background
instrument (`ib_send_bw` at a 0.6 duty cycle, E-G4(b)) on the NIC the KV
crosses.

What differs, and is recorded per run because it is a condition:

- the A5000's `--gpu-memory-utilization` is 0.9, not 0.6: at 0.6 its 24 GB
  leaves less than the 16 GB of weights (R5.0);
- each node's HCA (`mlx5_0` on `s8`, `mlx5_1` on `a5k2`);
- the pre-run check of `a5k2` GPU 0's BAR1 (`../pd_probe/a5000/gpu0_rebar.sh`),
  whose output is kept with the run.

Modes:

    --mode select  --direction D1      choose the template once (row 7 a)
    --mode predict --direction D1      the prediction at the run's rate
    --mode sim-ceiling --direction D1  report-only: the highest pilot rate with a verdict
    --mode run     --direction D1 --condition independent --rep 1 [--dry-run]

Nothing here is registered: what the run measures and how it is judged is
preregistration row 11, written before the first validation request.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from graphsearch import paths_root

paths_root.ensure_importable()

ROOT = paths_root.GRAPHSEARCH_ROOT
HERE = Path(__file__).resolve().parent
E_G5 = ROOT / "experiments" / "e_g5"
sys.path.insert(0, str(E_G5))
import conditions as C  # noqa: E402

FIXTURES = ROOT / "fixtures" / "clusters"
CLUSTER = FIXTURES / "real-s8a5k.v2.yaml"
CLUSTER_SHARED = {"D1": FIXTURES / "real-s8a5k-shared-d1.v2.yaml",
                  "D2": FIXTURES / "real-s8a5k-shared-d2.v2.yaml"}
RAW = HERE / "raw"
PILOT = RAW / "pilot"
REBAR_CHECK = ROOT / "experiments" / "pd_probe" / "a5000" / "gpu0_rebar.sh"
OPENSSL3 = "/opt/nvidia/nsight-compute/2024.3.2/host/linux-desktop-glibc_2_11_3-x64"
CONDITIONS = ("independent", "shared")
DUTY = 0.6
BG_PORT, BG_BYTES = 18600, 8 << 20


@dataclass(frozen=True)
class Node:
    name: str               # the fixture's node id
    ib_ip: str
    ssh: str | None         # None: this is the node the harness runs on
    hca: str
    vllm: str
    python: str
    gpu_memory_utilization: float
    side_port: int
    env_extra: tuple[tuple[str, str], ...] = ()

    @property
    def local(self) -> bool:
        return self.ssh is None


S8 = Node("s8", "192.168.210.108", None, "mlx5_0",
          "/home/swsok/heteropilot/.venv-vllm/bin/vllm",
          "/home/swsok/heteropilot/.venv-vllm/bin/python", 0.6, 5600,
          # nixl's wheel links OpenSSL 3; s8 runs Ubuntu 20.04 (1.1.1).
          (("LD_LIBRARY_PATH", OPENSSL3),))
A5K2 = Node("a5k2", "192.168.210.112", "swsok@192.168.100.112", "mlx5_1",
            "/home/swsok/.venv-eg8/bin/vllm", "/home/swsok/.venv-eg8/bin/python",
            0.9, 5700)
NODES = {"s8": S8, "a5k2": A5K2}
DIRECTIONS = {"D1": (S8, A5K2), "D2": (A5K2, S8)}       # (prefill, decode)
PREFILL_PORT, DECODE_PORT = 8100, 8200


def say(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def sh(node: Node, cmd: str, timeout: float = 120, check: bool = True) -> str:
    argv = (["bash", "-c", cmd] if node.local else
            ["ssh", "-o", "BatchMode=yes", node.ssh, cmd])
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          check=check).stdout


def gpu0_state(node: Node) -> dict:
    q = ("nvidia-smi -i 0 --query-compute-apps=pid --format=csv,noheader | wc -l; "
         "nvidia-smi -i 0 --query-gpu=uuid,memory.used --format=csv,noheader")
    lines = sh(node, q).strip().splitlines()
    return {"tenants": int(lines[0]), "gpu0": lines[1] if len(lines) > 1 else None}


# --- 1. select and predict -------------------------------------------------

def devices() -> frozenset:
    return frozenset({"s8/gpu0", "a5k2/gpu0"})


def plan_args(spec_path: Path, cluster: Path, sub: Path, args, seed: int):
    return SimpleNamespace(
        service=str(spec_path), cluster=str(cluster), profiles_root=str(ROOT),
        predictor=args.predictor, no_enable_pd=False, ranker="service_margin",
        num_requests=args.num_requests, seed=seed,
        cache_dir=str(sub / "cache"), work_dir=str(sub / "sim"),
        timeout=args.sim_timeout, max_workers=args.max_workers,
        contention="fluid", k_schedule=[4, 8, 16], search_mode="budget",
        budget_sims=args.budget_sims, budget_seconds=None, epsilon=0.0,
        max_embeddings_per_template=None, compression="exact", bounds="all",
        diversity=False, oracle=False, output=None, max_devices=2,
        max_hops=3,     # gpu -> nic -> nic -> gpu, as E-G5 (GS-32)
    )


def pd_templates(objs, direction: str) -> list[str]:
    prefill, decode = DIRECTIONS[direction]
    out = set()
    for r in objs.representatives:
        roles = {a.role.value: a.island_id for a in r.exemplar.template.assignments}
        if (roles.get("prefill", "").endswith(f"-{prefill.name}")
                and roles.get("decode", "").endswith(f"-{decode.name}")):
            out.add(r.template_id)
    return sorted(out)


def embedding(objs, template_id: str):
    for r in objs.representatives:
        if r.template_id != template_id:
            continue
        for e in [r.exemplar, *r.embeddings]:
            if e.devices == devices():
                return e
    return None


def select_template(direction: str, spec_path: Path, work: Path, args, seed: int = 42):
    from graphsearch.__main__ import cmd_plan_objects, evaluate_placement

    pa = plan_args(spec_path, CLUSTER, work / "select", args, seed)
    objs = cmd_plan_objects(pa)
    table = []
    for tid in pd_templates(objs, direction):
        v = evaluate_placement(pa, objs, tid, devices())
        table.append({
            "template_id": tid, "state": v.state, "feasible": v.feasible,
            "p99_ttft_ms": v.plan.predicted.p99_ttft_ms if v.plan else None,
            "p99_tpot_ms": v.plan.predicted.p99_tpot_ms if v.plan else None,
        })
    judged = [t for t in table if t["p99_ttft_ms"] is not None]
    if not judged:
        return unjudged_selection(direction, table, work / "select", args, seed)
    chosen = min(judged, key=lambda t: (not t["feasible"], t["p99_ttft_ms"]))
    return {"direction": direction, "chosen": chosen["template_id"], "seed": seed,
            "state": "evaluated", "rule_applied": True,
            "table": table, "all_infeasible": not any(t["feasible"] for t in table),
            "predictor": args.predictor,
            "rule": "feasible first, then the lower predicted p99 TTFT, at "
                    "s8/gpu0 + a5k2/gpu0 (row 5), applied once (row 7 a)"}


MIRROR = {"D1": "D2", "D2": "D1"}
PD_ID = re.compile(r"^pd\((?P<p>\S+) P \+ (?P<d>\S+) D\)(?P<knobs>-.*)$")


def mirror_template_id(template_id: str) -> str:
    """The same knobs with the prefill and decode islands swapped."""
    m = PD_ID.match(template_id)
    if m is None:
        raise SystemExit(f"{template_id} is not a P/D template id")
    return f"pd({m['d']} P + {m['p']} D){m['knobs']}"


def sim_errors(sim_dir: Path) -> list[str]:
    """The simulator's own error lines, for the record of why there is no verdict."""
    found = set()
    for log in sorted(sim_dir.glob("sims/pd_*/sim*.log")):
        for line in log.read_text(errors="replace").splitlines():
            if line.startswith("RuntimeError:"):
                found.add(re.sub(r"\d+\.\d+MB", "<n>MB", line.strip()))
    return sorted(found)


def unjudged_selection(direction: str, table: list[dict], sub: Path, args,
                       seed: int) -> dict:
    """No P/D template has a verdict, so row 5's rule cannot be applied here.

    The template is fixed instead as the mirror image of the one the rule chose
    in the other direction, which must already be selected. The prediction is
    `unknown_measurement`: an unevaluated placement is not an infeasible one."""
    other = selection_path(MIRROR[direction], args)
    if not other.exists():
        raise SystemExit(f"{direction}: no P/D template was simulated to a result, and "
                         f"{other} (whose mirror image would be used) is missing")
    source = json.loads(other.read_text())
    if not source.get("rule_applied", True):
        raise SystemExit(f"{direction}: {other} is itself a mirror; nothing to mirror")
    chosen = mirror_template_id(source["chosen"])
    if chosen not in {t["template_id"] for t in table}:
        raise SystemExit(f"{direction}: the mirror {chosen} is not among {direction}'s templates")
    return {"direction": direction, "chosen": chosen, "seed": seed,
            "state": "unknown_measurement", "rule_applied": False,
            "table": table, "all_infeasible": None, "predictor": args.predictor,
            "mirror_of": {"direction": MIRROR[direction], "template_id": source["chosen"],
                          "selection": str(other.relative_to(ROOT))},
            "simulator_errors": sim_errors(sub / "sim"),
            "rule": ("row 5's rule was NOT applied: no template has a simulator verdict "
                     "at s8/gpu0 + a5k2/gpu0. The template is the mirror image of the "
                     f"one the rule chose in {MIRROR[direction]}."),
            "reason": ("the simulator's memory model exhausts the decode instance's KV "
                       "and raises instead of returning a verdict -- the same cause as "
                       "E-G3's C14 (e_g3_sim_error_causes.md)")}


def predict_at(direction: str, template_id: str, spec_path: Path, work: Path, args,
               trace: Path, num_reqs: int, seed: int = 42) -> dict:
    """E-G5's two numbers per condition: the simulator's p99 TTFT, and the
    fluid model's KV transfer time over this placement's path, as a
    per-request mean over the prompts actually replayed."""
    from graphsearch.__main__ import cmd_plan_objects, evaluate_placement
    from graphsearch.adapter import apply_pd_transfer_cost_embedded
    from graphsearch.contention import contention_model

    reqs = [json.loads(x) for x in Path(trace).read_text().splitlines() if x.strip()]
    mean_prompt = statistics.mean(r["input_toks"] for r in reqs[:num_reqs])
    out = {"direction": direction, "template_id": template_id,
           "mean_prompt_tokens": mean_prompt, "predictor": args.predictor}
    for name, cluster in (("independent", CLUSTER), ("shared", CLUSTER_SHARED[direction])):
        pa = plan_args(spec_path, cluster, work / name, args, seed)
        objs = cmd_plan_objects(pa)
        v = evaluate_placement(pa, objs, template_id, devices())
        emb = embedding(objs, template_id)
        if emb is None:
            raise SystemExit(f"{name}: {template_id} has no embedding at {sorted(devices())}")
        # The fluid model prices the KV transfer from the path alone, so it has
        # a number even where the simulator returned no verdict.
        xfer_p50 = fluid_xfer_ms_p50(emb, objs.graph, contention_model("fluid"))
        if v.plan is not None:
            _, info = apply_pd_transfer_cost_embedded(
                emb, v.plan.predicted, objs.spec, objs.graph,
                contention=contention_model("fluid"))
            assert abs(info["xfer_ms_p50"] - xfer_p50) < 1e-9
        p50_tokens = objs.spec.traffic.input_tokens.p50
        per_token = xfer_p50 / p50_tokens
        out[name] = {
            "state": v.state, "detail": v.detail,
            "p99_ttft_ms": v.plan.predicted.p99_ttft_ms if v.plan else None,
            "p99_tpot_ms": v.plan.predicted.p99_tpot_ms if v.plan else None,
            "feasible": v.feasible,
            "xfer_ms_p50": xfer_p50, "p50_prompt_tokens": p50_tokens,
            "xfer_ms_per_token": per_token, "xfer_ms_mean": per_token * mean_prompt,
        }
    out["predicted_interval_change_ms"] = (
        out["shared"]["xfer_ms_mean"] - out["independent"]["xfer_ms_mean"])
    ttfts = [out[c]["p99_ttft_ms"] for c in CONDITIONS]
    out["predicted_p99_ttft_change_ms"] = (
        None if None in ttfts else ttfts[1] - ttfts[0])
    return out


def fluid_xfer_ms_p50(emb, graph, contention) -> float:
    """The p50 KV transfer time over the embedding's path, exactly as
    `apply_pd_transfer_cost_embedded` computes it before it touches metrics."""
    from graphsearch.demand import FlowKind

    flows = [f for f in emb.flows if f.kind is FlowKind.PD_KV_TRANSFER]
    times = contention.transfer_times_ns(flows, graph) if flows else {}
    return max(times.values(), default=0.0) / 1e6


SIM_CEILING_LADDER = (4.0, 3.0, 2.0, 1.5, 1.0)   # the run's rate, then the knee pilot's


def sim_ceiling(direction: str, template_id: str, work: Path, args) -> dict:
    """Report-only: the highest rate on the pilot ladder at which the simulator
    returns a verdict for this placement, descending until one does. Not a
    criterion of anything; reported beside the measured onset of preemption."""
    from graphsearch.__main__ import cmd_plan_objects, evaluate_placement

    steps = []
    for rps in SIM_CEILING_LADDER:
        # Spec S's own floor at every step: the question is whether the
        # simulator returns a verdict at all, which the floor does not decide.
        spec = _spec(rps, work, floor=C.SPECS["service"]["min_goodput_rps"])
        pa = plan_args(spec, CLUSTER, work / direction / f"ceiling-rps{rps:g}",
                       args, 42)
        v = evaluate_placement(pa, cmd_plan_objects(pa), template_id, devices())
        steps.append({"rps": rps, "state": v.state, "feasible": v.feasible,
                      "p99_ttft_ms": v.plan.predicted.p99_ttft_ms if v.plan else None,
                      "p99_tpot_ms": v.plan.predicted.p99_tpot_ms if v.plan else None,
                      "detail": v.detail if v.plan is None else ""})
        say(f"{direction} ceiling: {rps:g} rps -> {v.state}")
        if v.plan is not None:
            break
    judged = [s["rps"] for s in steps if s["state"] == "evaluated"]
    return {"direction": direction, "template_id": template_id, "report_only": True,
            "ladder": list(SIM_CEILING_LADDER), "steps": steps,
            "highest_judged_rps": max(judged) if judged else None,
            "note": ("descends the ladder and stops at the first rate with a verdict; "
                     "None means no rate on the ladder had one")}


# --- 2. deploy ----------------------------------------------------------------

def serve_argv(node: Node, plan, model: str, port: int, role: str) -> list[str]:
    k = plan.candidate.knobs
    return [
        node.vllm, "serve", model, "--host", "0.0.0.0", "--port", str(port),
        "--max-model-len", "8192",
        "--gpu-memory-utilization", str(node.gpu_memory_utilization),
        "--no-enable-prefix-caching",
        "--max-num-seqs", str(k.max_num_seqs),
        "--max-num-batched-tokens", str(k.max_num_batched_tokens),
        "--dtype", plan.candidate.dtype, "--kv-cache-dtype", k.kv_cache_dtype,
        "--kv-transfer-config",
        json.dumps({"kv_connector": "NixlConnector", "kv_role": role,
                    "kv_buffer_device": "cuda"}),
    ]


def engine_env(node: Node) -> dict:
    return {"CUDA_VISIBLE_DEVICES": "0", "UCX_NET_DEVICES": f"{node.hca}:1",
            "VLLM_NIXL_SIDE_CHANNEL_HOST": node.ib_ip,
            "VLLM_NIXL_SIDE_CHANNEL_PORT": str(node.side_port),
            "HF_HUB_OFFLINE": "1", **dict(node.env_extra)}


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def scrape_metrics(url: str) -> str:
    try:
        with urllib.request.urlopen(f"{url}/metrics", timeout=10) as r:
            return r.read().decode()
    except Exception as exc:
        return f"# scrape failed: {exc!r}\n"


class Engine:
    """One vLLM instance on one node, in its own process group, always torn down."""

    def __init__(self, node: Node, argv: list[str], log: Path):
        self.node, self.argv, self.log = node, argv, log
        self.proc = None
        self.pgid = None

    def start(self) -> None:
        env = engine_env(self.node)
        if self.node.local:
            self._fh = self.log.open("w")
            self.proc = subprocess.Popen(self.argv, env=dict(os.environ, **env),
                                         start_new_session=True,
                                         stdout=self._fh, stderr=subprocess.STDOUT)
        else:
            e = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            remote = (f"{e} setsid nohup " + " ".join(shlex.quote(a) for a in self.argv)
                      + " > /tmp/eg8_engine.log 2>&1 < /dev/null & echo $!")
            self.pgid = sh(self.node, remote).strip()

    def alive(self) -> bool:
        if self.node.local:
            return self.proc is not None and self.proc.poll() is None
        return sh(self.node, f"kill -0 {self.pgid} 2>/dev/null && echo y || true",
                  check=False).strip() == "y"

    def stop(self) -> None:
        if self.node.local:
            if self.proc is not None and self.proc.poll() is None:
                os.killpg(self.proc.pid, 15)
                try:
                    self.proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(self.proc.pid, 9)
            if getattr(self, "_fh", None) is not None:
                self._fh.close()
        elif self.pgid:
            out = sh(self.node, f"kill -- -{self.pgid} 2>/dev/null; sleep 5; "
                     f"kill -9 -- -{self.pgid} 2>/dev/null; cat /tmp/eg8_engine.log; "
                     "rm -f /tmp/eg8_engine.log", timeout=120, check=False)
            self.log.write_text(out)


class Engines:
    def __init__(self, direction: str, plan, model: str, out: Path, timeout: float):
        prefill, decode = DIRECTIONS[direction]
        self.prefill = Engine(prefill, serve_argv(prefill, plan, model, PREFILL_PORT,
                                                  "kv_producer"), out / "prefill.log")
        self.decode = Engine(decode, serve_argv(decode, plan, model, DECODE_PORT,
                                                "kv_consumer"), out / "decode.log")
        self.urls = {"prefill": f"http://{prefill.ib_ip}:{PREFILL_PORT}",
                     "decode": f"http://{decode.ib_ip}:{DECODE_PORT}"}
        self.timeout = timeout

    def __enter__(self):
        self.prefill.start()
        self.decode.start()
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            for e in (self.prefill, self.decode):
                if not e.alive():
                    raise RuntimeError(f"the {e.node.name} engine exited during start-up")
            if all(healthy(u) for u in self.urls.values()):
                say("both engines healthy")
                return self
            time.sleep(5)
        raise RuntimeError(f"engines not healthy after {self.timeout:.0f} s")

    def __exit__(self, *exc):
        self.prefill.stop()
        self.decode.stop()
        time.sleep(10)          # let both GPUs release before the next run
        return False


# --- 3. the background --------------------------------------------------------

class NicBackground:
    """`ib_send_bw` from the prefill node to the decode node -- the direction
    the KV crosses -- at a target duty cycle, measured as it runs (E-G5's
    instrument, either way round). The server loops on the receiver; each
    burst is one client run on the sender."""

    def __init__(self, direction: str):
        self.sender, self.receiver = DIRECTIONS[direction]
        self.stop_event = threading.Event()
        self.busy = 0.0
        self.bursts: list[dict] = []
        self.t0 = self.t1 = None
        self.server_pgid = None

    @staticmethod
    def iters() -> int:
        # ~0.6 s of transfer per 1 s period at ~55 Gbit/s (R5.0: 52.6-58.0).
        return max(1, int(DUTY * 6.9e9 / BG_BYTES))

    def _common(self, node: Node) -> str:
        return (f"--report_gbits -s {BG_BYTES} -n {self.iters()} -p {BG_PORT} -F -N "
                f"-d {node.hca}")

    def __enter__(self):
        loop = f"while true; do ib_send_bw {self._common(self.receiver)}; done"
        self.server_pgid = sh(self.receiver,
                              f"setsid nohup bash -c {shlex.quote(loop)} "
                              f"> /tmp/eg8_bg_server.log 2>&1 < /dev/null & echo $!").strip()
        time.sleep(2)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.t0 = time.monotonic()
        self.thread.start()
        return self

    def _loop(self):
        cmd = f"ib_send_bw {self._common(self.sender)} {self.receiver.ib_ip}"
        while not self.stop_event.is_set():
            start = time.monotonic()
            try:
                text = sh(self.sender, cmd, timeout=60, check=False)
            except subprocess.TimeoutExpired:
                text = ""
            gbit = None
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == str(BG_BYTES):
                    gbit = float(parts[3])
            if gbit:
                self.busy += BG_BYTES * self.iters() * 8 / (gbit * 1e9)
            self.bursts.append({"t": round(start - self.t0, 3), "gbit_s": gbit})
            wait = self.busy / DUTY - (time.monotonic() - self.t0)
            if wait > 0:
                self.stop_event.wait(wait)

    def __exit__(self, *exc):
        self.stop_event.set()
        self.thread.join(timeout=90)
        self.t1 = time.monotonic()
        # The process GROUP, never a `pkill -f` pattern (E-G5: a pattern naming
        # ib_send_bw also matches the remote shell, which then kills itself).
        sh(self.receiver, f"kill -- -{self.server_pgid} 2>/dev/null; true",
           timeout=60, check=False)
        return False

    def record(self) -> dict:
        span = (self.t1 or time.monotonic()) - self.t0
        rates = sorted(b["gbit_s"] for b in self.bursts if b["gbit_s"])
        return {"target_duty_cycle": DUTY,
                "achieved_duty_cycle": round(self.busy / span, 3) if span else None,
                "bursts": len(self.bursts),
                "median_gbit_s": rates[len(rates) // 2] if rates else None,
                "direction": f"{self.sender.name} -> {self.receiver.name}",
                "instrument": "ib_send_bw, as E-G4(b)"}


# --- the run ------------------------------------------------------------------

def raw_root(args) -> Path:
    """Where selection and prediction files go. A mock-predictor rehearsal
    writes under outputs/, never beside the files row 11 registers."""
    return RAW if args.predictor == "sim" else ROOT / "outputs" / "e_g8" / "mock-raw"


def selection_path(direction: str, args) -> Path:
    return raw_root(args) / f"selection-{direction}.json"


def _service_tools():
    import deploy_and_bench as dab

    return dab.service_spec, dab.workload_at


#: The goodput floor at each rate a spec is built for, by row 4's own rule:
#: 95 % of the lowest measured goodput (E-G5's definition) across the pilots
#: at that rate, rounded down to 0.1 -- as row 8 did for `low` and `high`.
#: 4 rps is spec S's 2.3, used to select. 1 rps, the run rate (row 11), is
#: from `raw/pilot/knee-rps1/`: D1 0.904, D2 0.875 -> 0.831 -> 0.8. Not
#: 0.575 x offered, the proportional rule GS-36 rejected.
GOODPUT_FLOOR = {4.0: 2.3, 1.0: 0.8}


def goodput_floor(rps: float) -> float:
    if rps not in GOODPUT_FLOOR:
        raise SystemExit(f"no goodput floor registered at {rps:g} rps (row 11)")
    return GOODPUT_FLOOR[rps]


def _spec(rps: float, work: Path, floor: float | None = None) -> Path:
    service_spec, _ = _service_tools()
    S = C.SPECS["service"]
    floor = goodput_floor(rps) if floor is None else floor
    return service_spec("llama31-8b", "normal", "knee", rps,
                        work / f"service-rps{rps:g}-floor{floor:g}.yaml",
                        ttft_max_ms=S["ttft_max_ms"], tpot_max_ms=S["tpot_max_ms"],
                        min_goodput_rps=floor)


def _template(template_id: str, spec_path: Path):
    from graphsearch.__main__ import _load, _templates

    spec, cluster, profiles, islands, _graph = _load(SimpleNamespace(
        service=str(spec_path), cluster=str(CLUSTER), profiles_root=str(ROOT),
        no_enable_pd=False))
    for t in _templates(spec, cluster, islands, profiles, True, max_devices=2):
        if t.id == template_id:
            return SimpleNamespace(candidate=t)
    raise SystemExit(f"no template {template_id} on {CLUSTER.name}")


def rebar_check() -> str:
    """`gpu0_rebar.sh`'s output: a5k2 GPU 0's BAR1 before the run (32 GB
    expected since the BIOS update; the script changes nothing then)."""
    r = subprocess.run(["bash", str(REBAR_CHECK)], capture_output=True, text=True,
                       timeout=180, check=False)
    return r.stdout + r.stderr


def run(args) -> int:
    work = ROOT / "outputs" / "e_g8"
    work.mkdir(parents=True, exist_ok=True)
    S = C.SPECS["service"]
    d = args.direction

    if args.mode == "select":
        sel = select_template(d, _spec(S["arrival_rate_rps"], work), work / d, args)
        sel["written_at"] = datetime.now(timezone.utc).isoformat()
        out = selection_path(d, args)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(sel, indent=2, sort_keys=True) + "\n")
        say(f"{d}: selected {sel['chosen']} ({sel['state']}, rule applied: "
            f"{sel['rule_applied']}); wrote {out}")
        return 0

    if not selection_path(d, args).exists():
        raise SystemExit(f"{selection_path(d, args)} is missing: run --mode select first")
    template_id = json.loads(selection_path(d, args).read_text())["chosen"]
    rps = args.rps if args.rps is not None else S["arrival_rate_rps"]
    _, workload_at = _service_tools()
    trace = workload_at(rps, "llama31-8b", work)
    # A prediction needs the registered floor at its rate; a run uses the spec
    # only to rebuild the template, whose knobs no floor touches.
    spec_path = (_spec(rps, work) if args.mode == "predict" else
                 _spec(rps, work, floor=GOODPUT_FLOOR.get(rps, S["min_goodput_rps"])))

    if args.mode == "sim-ceiling":
        ceil = sim_ceiling(d, template_id, work, args)
        ceil["written_at"] = datetime.now(timezone.utc).isoformat()
        out = raw_root(args) / f"sim-ceiling-{d}.json"
        out.write_text(json.dumps(ceil, indent=2, sort_keys=True) + "\n")
        say(f"{d}: highest rate with a verdict {ceil['highest_judged_rps']}; wrote {out}")
        return 0

    if args.mode == "predict":
        pred = predict_at(d, template_id, spec_path, work / d / f"predict-rps{rps:g}",
                          args, trace, C.REQUESTS_PER_RUN)
        pred["offered_rps"] = rps
        pred["min_goodput_rps"] = goodput_floor(rps)
        out = raw_root(args) / f"prediction-{d}-rps{rps:g}.json"
        out.write_text(json.dumps(pred, indent=2, sort_keys=True) + "\n")
        say(f"{d}: predicted interval change {pred['predicted_interval_change_ms']:+.3f} ms; "
            f"wrote {out}")
        return 0

    if args.condition not in CONDITIONS:
        raise SystemExit(f"--mode run takes --condition {' or '.join(CONDITIONS)}")
    base = (work / "dry-run" if args.dry_run else
            PILOT / args.pilot_label if args.pilot_label else RAW / "runs")
    out = base / d / args.condition / str(args.rep)
    out.mkdir(parents=True, exist_ok=True)
    info = C.MODELS["llama31-8b"]
    plan = _template(template_id, spec_path)
    prefill, decode = DIRECTIONS[d]
    say(f"{d} {args.condition} rep {args.rep} at {rps:g} rps, template {template_id}"
        + (f" [pilot {args.pilot_label}]" if args.pilot_label else "")
        + (" [DRY RUN]" if args.dry_run else ""))
    record = {
        "banner": ("DRY RUN -- nothing was launched." if args.dry_run else
                   "REAL HARDWARE -- two nodes, s8 (A40) and a5k2 (a5000-2 GPU 0)."),
        "experiment": "E-G8", "direction": d,
        "deployed_by": "this experiment harness (e_g8/pd_arm.py, e_g5/pd_router.py), "
                       "NOT heteropilot planner/deploy/, which has no router (GS-28)",
        "pilot": args.pilot_label, "validation_set": not args.pilot_label and not args.dry_run,
        "condition": args.condition, "rep": args.rep, "offered_rps": rps,
        "trace": str(trace), "num_reqs": C.REQUESTS_PER_RUN,
        "template_id": template_id,
        "selection": str(selection_path(d, args).relative_to(ROOT)),
        "placement": {"prefill": f"{prefill.name}/gpu0", "decode": f"{decode.name}/gpu0"},
        "gpu_memory_utilization": {n.name: n.gpu_memory_utilization for n in (prefill, decode)},
        "kv_buffer_device": "cuda (both ends; GPUDirect RDMA, GS-39)",
        "slo": {"ttft_max_ms": S["ttft_max_ms"], "tpot_max_ms": S["tpot_max_ms"],
                "min_goodput_rps": GOODPUT_FLOOR.get(rps)},
        "served_model": info["hf_id"],
        "ttft_definition": ("router prefill-send to first token of the decode stream; "
                            "includes the prefill, the KV pull across the NIC and the "
                            "decode instance's first step"),
        "interval_definition": ("prefill response received to first token of the decode "
                                "stream: the KV pull and the decode instance's first step"),
    }
    if args.dry_run:
        record["state"] = "dry run"
        record["argv"] = {"prefill": serve_argv(prefill, plan, info["hf_id"], PREFILL_PORT,
                                                "kv_producer"),
                          "decode": serve_argv(decode, plan, info["hf_id"], DECODE_PORT,
                                               "kv_consumer")}
    else:
        record["gpu0_before"] = {n.name: gpu0_state(n) for n in NODES.values()}
        record["a5k2_bar1_check"] = rebar_check()
        busy = any(v["tenants"] for v in record["gpu0_before"].values())
        bar_ok = "already 32GB" in record["a5k2_bar1_check"] or "result: resized" in \
            record["a5k2_bar1_check"]
        if busy and not args.allow_tenants:
            record["state"] = "refused: GPU 0 on s8 or a5k2 is not free"
        elif not bar_ok:
            record["state"] = "refused: a5k2 GPU 0's BAR1 is not 32 GB"
        else:
            with Engines(d, plan, info["hf_id"], out, args.health_timeout) as eng:
                record["prefill_argv"], record["decode_argv"] = eng.prefill.argv, eng.decode.argv
                router = [S8.python, "-u", str(E_G5 / "pd_router.py"),
                          "--prefill", eng.urls["prefill"], "--decode", eng.urls["decode"],
                          "--model", info["hf_id"], "--trace", str(trace),
                          "--num-reqs", str(C.REQUESTS_PER_RUN), "--out", str(out / "pd")]
                bg = NicBackground(d) if args.condition == "shared" else None
                if bg is not None:
                    with bg:
                        r = subprocess.run(router, capture_output=True, text=True,
                                           timeout=args.bench_timeout)
                    record["background"] = bg.record()
                else:
                    r = subprocess.run(router, capture_output=True, text=True,
                                       timeout=args.bench_timeout)
                (out / "router.log").write_text(r.stdout + r.stderr)
                # The third metric (KV exhaustion) reads the engines' own
                # counters, scraped while they are still up.
                for role, url in eng.urls.items():
                    (out / f"{role}.metrics.txt").write_text(scrape_metrics(url))
                record["router_returncode"] = r.returncode
                record["router_summary"] = r.stdout.strip().splitlines()[-1:]
                record["state"] = "measured" if r.returncode == 0 else "failed"
            record["gpu0_after"] = {n.name: gpu0_state(n) for n in NODES.values()}
    record["written_at"] = datetime.now(timezone.utc).isoformat()
    (out / "provenance.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
    say(f"wrote {out / 'provenance.json'} ({record['state']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=("select", "predict", "sim-ceiling", "run"),
                    required=True)
    ap.add_argument("--direction", choices=sorted(DIRECTIONS), required=True)
    ap.add_argument("--condition", choices=CONDITIONS, default=None)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--rps", type=float, default=None)
    ap.add_argument("--pilot-label", default=None,
                    help="write under raw/pilot/<label>: excluded from validation")
    ap.add_argument("--dry-run", action="store_true", help="launch nothing")
    ap.add_argument("--allow-tenants", action="store_true")
    ap.add_argument("--predictor", choices=("mock", "sim"), default="sim")
    ap.add_argument("--num-requests", type=int, default=C.REQUESTS_PER_RUN)
    ap.add_argument("--max-workers", type=int, default=16)
    ap.add_argument("--budget-sims", type=int, default=16)
    ap.add_argument("--sim-timeout", type=float, default=1800)
    ap.add_argument("--health-timeout", type=float, default=900)
    ap.add_argument("--bench-timeout", type=float, default=1800)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
