#!/usr/bin/env python
"""P3.2: one E-G5 condition, end to end. Plan, deploy, load, collect.

**REAL HARDWARE when it runs.** `--dry-run` writes every config file and the
exact commands and launches nothing, which is how the harness is checked
without spending device time.

    python experiments/e_g5/deploy_and_bench.py \\
        --condition llama31-8b__normal__T2__knee --rep 42 --dry-run

Four stages, in order, and the first one can stop the other three:

  0. **preconditions** -- no other tenant on any GPU, the load average, the
     node's accel serials, and `git -C vendor/heteropilot status --porcelain`
     empty. Refused rather than warned about. A figure measured beside another
     tenant is not wrong; it is measured under a condition the `REAL HARDWARE`
     banner does not state, and a result produced against an edited submodule
     is not a result about heteropilot.
  1. **plan** -- `python -m graphsearch plan --predictor sim` on
     `fixtures/clusters/real-a40x8.v2.yaml`, giving the recommendation and the
     boundary alternative.
  2. **deploy** -- heteropilot's own `build_serve_command`, with one override.
  3. **load** -- `python -m bench run`, then per-request logs and provenance
     into `experiments/e_g5/raw/<condition>/<rep>/`.

**The one override, and why it is the experiment rather than a workaround.**
`planner/deploy/base.py::resolve_devices` maps an island to *all* of its
accelerator ids, so a TP=2 plan on this node's single 8-GPU island launches
with `CUDA_VISIBLE_DEVICES=0,1,...,7` and vLLM silently takes the first two.
heteropilot names a *template*; it cannot name a *placement*. T1 and T2 run the
same template on devices (0,1) and (0,2) -- an NVLink pair measured at 52.64
GB/s and a PCIe bridge measured at 25.12 -- and the planner cannot tell them
apart. Whether that difference shows up in served TTFT is the question E-G5
exists to answer, so the harness sets the device list and records that it did.

Nothing is monkeypatched. `build_serve_command` is called as it stands and the
env it returns is overridden afterwards, in this repository, which is the same
boundary every other script here keeps.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

sys.path.insert(0, str(Path(__file__).parent))
import conditions as C  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
HETEROPILOT = ROOT / "vendor" / "heteropilot"
CLUSTER = ROOT / "fixtures" / "clusters" / "real-a40x8.v2.yaml"
RAW = ROOT / "experiments" / "e_g5" / "raw"
WORK = ROOT / "outputs" / "e_g5"

#: The interpreter with torch+CUDA and vLLM. Not this repo's `.venv` (no
#: torch) and not the simulator's (`vendor/heteropilot/.venv`, also no torch).
VLLM_PY = Path(
    os.environ.get("E_G5_VLLM_PYTHON", "/home/swsok/heteropilot/.venv-vllm/bin/python")
)


def say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


# --- stage 0: the preconditions ------------------------------------------

def gpu_tenants(exclude_pid: int | None = None) -> list[dict]:
    """Every compute process on every GPU except ours, with its owner."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-compute-apps=pid,process_name,used_gpu_memory",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    tenants = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or (exclude_pid and parts[0] == str(exclude_pid)):
            continue
        owner = subprocess.run(
            ["ps", "-o", "user=", "-p", parts[0]],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
        tenants.append({"pid": parts[0], "process": parts[1],
                        "used_mib": parts[2], "user": owner})
    return tenants


def node_serials() -> str:
    script = HETEROPILOT / "scripts" / "whichnode.sh"
    if not script.exists():
        return "unknown"
    out = subprocess.run(["bash", str(script)], capture_output=True,
                         text=True, timeout=120, check=False).stdout
    for line in out.splitlines():
        if "accel serials" in line:
            return line.split(":", 1)[1].strip()
    return "unknown"


def submodule_is_pristine() -> tuple[bool, str]:
    out = subprocess.run(
        ["git", "-C", str(HETEROPILOT), "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    return (not out), out


def preconditions(args) -> dict:
    """Refuse, rather than warn. Every one of these is in `MATRIX.md` §4."""
    tenants = gpu_tenants(os.getpid())
    pristine, dirt = submodule_is_pristine()
    record = {
        "gpu_tenants_before": tenants,
        "loadavg_before": [round(x, 2) for x in os.getloadavg()],
        "node_serials": node_serials(),
        "submodule_pristine": pristine,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    problems = []
    if tenants and not args.allow_tenants:
        who = "; ".join(f"{t['user']} pid {t['pid']} {t['process']} "
                        f"({t['used_mib']})" for t in tenants)
        problems.append(
            f"another tenant holds a GPU: {who}. A figure measured beside it "
            f"is measured under a condition the REAL HARDWARE banner does not "
            f"state. Wait, or pass --allow-tenants and accept that every row "
            f"of this run is labelled contaminated."
        )
    if not pristine:
        problems.append(
            f"vendor/heteropilot is not pristine:\n{dirt}\nA result produced "
            f"against an edited submodule is not a result about heteropilot."
        )
    if not VLLM_PY.exists():
        problems.append(
            f"{VLLM_PY} does not exist. Set E_G5_VLLM_PYTHON to an interpreter "
            f"with torch+CUDA and vLLM."
        )
    record["problems"] = problems
    return record


# --- stage 1: the plan ----------------------------------------------------

def service_spec(
    model: str, pattern: str, level: str, rps: float, out: Path,
    ttft_max_ms: float, tpot_max_ms: float, min_goodput_rps: float,
) -> Path:
    """One spec per (model, pattern, level). Generated, never hand-edited."""
    info = C.MODELS[model]
    text = f"""\
# E-G5 condition spec. GENERATED by experiments/e_g5/deploy_and_bench.py.
#
# model {model} / pattern {pattern} / level {level}
#
# The traffic shape is heteropilot's own ShareGPT trace statistics, which is
# what `python -m bench run` will actually replay. `arrival_rate_rps` is the
# level's multiple of this model's measured knee, so the axis means the same
# thing for both models.
#
# ---- the SLO is DERIVED from measurement, with stated headroom ----------
#
# An earlier version of this file used round numbers (2000 ms / 50 ms) chosen
# by nobody in particular. They did not bind: the bounds eliminated 0 of 1302
# representatives, so there was no `impossible_proven` candidate and therefore
# no real-hardware test of `false_infeasible` at all. A bound can only reject
# when the most optimistic arithmetic already misses, so a loose SLO produces
# exactly that.
#
#   ttft  {ttft_max_ms} ms  = T1's measured p99 at the knee x 1.5. T1-class
#                     placements (365.2 ms) clear it; T2-class (2793.3 ms)
#                     do not. This is the axis the placement question lives on.
#   tpot  {tpot_max_ms} ms  = about 10 % above the measured 50.95-55.06 ms band,
#                     deliberately NOT a deciding axis: both placements pass,
#                     so a verdict cannot come from it by accident.
#   goodput {min_goodput_rps} rps = chosen inside the registered interval; see
#                     `docs/preregistration.md` entry 4.
#
# The runs it was derived from are named in that entry and are EXCLUDED from
# E-G5's validation set: a limit fitted on a measurement cannot also be tested
# by it.
service:
  model: {info['planner_id']}
  dtype: bfloat16
  kv_cache_dtype: auto

traffic:
  arrival_rate_rps: {rps}
  input_tokens:
    p50: 731
    p95: 2470
    p99: 2884
  output_tokens:
    p50: 632
    p95: 780
  burstiness: {C.PATTERNS[pattern]}
  prefix_share_ratio: 0.0

slo:
  ttft:
    percentile: 99
    max_ms: {ttft_max_ms}
  tpot:
    percentile: 99
    max_ms: {tpot_max_ms}
  min_goodput_rps: {min_goodput_rps}

objective:
  primary: minimize_active_accelerators
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return out


def run_plan(spec_path: Path, work: Path, args):
    """Plan IN PROCESS, because the deploy stage needs objects, not JSON.

    `python -m graphsearch plan` writes a YAML summary, and a summary cannot be
    launched: `VllmCudaBackend.launch` wants a `DeploymentPlan`. Re-deriving one
    by parsing the summary would be a second, quietly different code path, and
    the first time the two disagreed the deployment would not match the plan it
    claims to be.

    So this calls the same pipeline `cmd_plan` calls, with the same arguments,
    and `tests/test_e_g5_harness.py` pins that the flags stay in step.
    """
    from types import SimpleNamespace

    from graphsearch.__main__ import cmd_plan_objects

    args_for_plan = SimpleNamespace(
        service=str(spec_path), cluster=str(CLUSTER),
        profiles_root=str(ROOT), predictor=args.predictor,
        no_enable_pd=False, ranker="service_margin",
        num_requests=args.num_requests, seed=args.rep,
        cache_dir=str(WORK / "cache"), work_dir=str(work / "sim"),
        timeout=args.sim_timeout, max_workers=args.max_workers,
        contention="fluid", k_schedule=[4, 8, 16],
        search_mode="budget", budget_sims=args.budget_sims,
        budget_seconds=None, epsilon=0.0,
        max_embeddings_per_template=None, compression="exact",
        bounds="all", diversity=False, oracle=False, output=None,
        # The topology condition names a placement, and a placement has a fixed
        # device count -- so the planner is asked "what is the best plan using
        # at most this many devices", and its answer is what gets placed. Left
        # unbounded, the search on an eight-GPU node recommends an eight-device
        # plan, which has exactly ONE placement and therefore no contrast to
        # measure (GS-27). This is `excluded_by_scope`, recorded in every raw
        # file, never a judgement that larger plans are worse.
        max_devices=len(C.TOPOLOGIES[args.topology_key].devices),
    )
    return cmd_plan_objects(args_for_plan)


def candidates_of_size(objects, devices: int) -> list:
    """Ranked candidates that use exactly `devices` accelerators, best first.

    **A topology condition names a PLACEMENT, and a placement has a fixed
    device count.** T2 is "this template, on gpu0 and gpu2"; it is not a
    template of its own. So the condition can only be applied to a candidate
    that uses two devices, and asking for the recommendation regardless
    produced the command the first dry run emitted:

        CUDA_VISIBLE_DEVICES=0,2 vllm serve ... --tensor-parallel-size 8

    -- two devices visible, eight ranks requested. vLLM would refuse it
    instantly, and a harness that emits it has not been checked. Selecting by
    device count is what makes T1 and T2 two placements of ONE template, which
    is the comparison E-G5 exists to make: the planner cannot tell them apart,
    and everything else about them is equal by construction.
    """
    out = []
    recommended = objects.output.recommended
    for entry in [recommended, *(getattr(objects.output, "alternatives", []) or [])]:
        if entry is None:
            continue
        plan_obj = getattr(entry, "plan", entry)
        if plan_obj.candidate.total_devices == devices:
            out.append(entry)
    return out


#: Bound stages whose rejection is worth putting on hardware.
#:
#: **`MEMORY_INFEASIBLE` is deliberately not here.** Memory is an exact check --
#: the weights either fit in the device or they do not -- so deploying a
#: memory-rejected candidate tells you nothing about whether the *lower bound*
#: is safe. It tells you that arithmetic is arithmetic. The stages below reject
#: on an optimistic estimate, which is where a bound can be wrong, and that is
#: what `false_infeasible` is about.
TESTABLE_STAGES = ("throughput_upper_bound", "topology_infeasible",
                   "analytical_lower_bound")


def plan_for(entry, spec):
    """A `DeploymentPlan` for anything the selection can return.

    The recommendation arrives as a `ScoredPlan` and already has one. The two
    boundary alternatives do not: A is a `RankFeatures` and B a
    `Representative`, and **neither was ever simulated** -- A was ranked below
    the recommendation and B was rejected by a bound before any predictor saw
    it. There is therefore no predicted metric for them, and this fills
    `predicted` with the SLO targets themselves rather than with a guess, so
    that a reader of the raw file cannot mistake the field for a prediction.

    That is the whole point of deploying them: B in particular is a candidate
    the planner said **cannot** work, and the measurement decides whether the
    bound was right.
    """
    from planner.plan import DeploymentPlan, PredictedMetrics

    if isinstance(entry, DeploymentPlan):
        return entry
    existing = getattr(entry, "plan", None)
    if existing is not None:
        return existing

    template = entry.exemplar.template
    ttft = spec.slo.ttft.max_ms
    tpot = spec.slo.tpot.max_ms
    return DeploymentPlan(
        plan_id=f"boundary-{template.id}",
        model=spec.service.model,
        candidate=template,
        # NOT a prediction. These are the spec's own targets, written here so
        # the field is filled with something whose provenance is obvious. The
        # raw record says `predicted_is_slo_target: true` beside it.
        predicted=PredictedMetrics(
            p50_ttft_ms=ttft, p95_ttft_ms=ttft, p99_ttft_ms=ttft,
            p50_tpot_ms=tpot, p95_tpot_ms=tpot, p99_tpot_ms=tpot,
            throughput_tps=0.0,
            slo_goodput_rps=spec.slo.min_goodput_rps or 0.0,
            slo_attainment=0.0,
            completed_requests=0, completed_tokens=0,
        ),
    )


def sim_risk(plan, spec) -> float:
    """The binding constraint, from the SIMULATOR's p99s rather than a proxy.

        max(p99_ttft / ttft_max, p99_tpot / tpot_max, goodput_floor / goodput)

    The ranker's `risk_proxy` is an estimate built to ORDER candidates cheaply,
    and on this cluster it tied **280 feasible candidates at exactly 0.6137** --
    its goodput term does not vary with placement, so it cannot separate them.
    That is an observation about the ranker, recorded in the result file and
    left for a G15 follow-up; it is not fixed here. But it makes the proxy
    useless for picking "the one that only just works", so the marginal
    alternative is chosen on what the simulator actually predicted.
    """
    predicted = plan.predicted
    ratios = [
        predicted.p99_ttft_ms / spec.slo.ttft.max_ms,
        predicted.p99_tpot_ms / spec.slo.tpot.max_ms,
    ]
    floor = spec.slo.min_goodput_rps
    if floor and predicted.slo_goodput_rps > 0:
        ratios.append(floor / predicted.slo_goodput_rps)
    return max(ratios)


def feasible_marginal(objects, spec, devices: int, exclude: str | None):
    """Alternative A: the evaluated candidate the simulator put closest to 1.

    Drawn from `audit.feasible_plans` -- every candidate the evaluator judged
    feasible, with its predicted metrics -- not from `output.alternatives`,
    which is the Pareto frontier and was a single point here.

    Deploying it asks whether the ORDER is real: if the thing ranked below the
    recommendation does as well on hardware, the ordering was not carrying
    information.
    """
    plans = [
        plan for plan in getattr(objects.audit, "feasible_plans", [])
        if plan.candidate.total_devices == devices
        and plan.candidate.id != exclude
    ]
    if not plans:
        return None, (
            f"no evaluated feasible candidate of {devices} devices below the "
            f"recommendation (the search evaluated "
            f"{objects.audit.evaluated} representative(s) and found "
            f"{len(objects.audit.feasible_ids)} feasible overall)"
        )
    scored = [(abs(sim_risk(plan, spec) - 1.0), plan) for plan in plans]
    _, best = min(scored, key=lambda t: (t[0], t[1].candidate.id))
    risk = sim_risk(best, spec)
    return best, (
        f"feasible-marginal on SIMULATED p99 (risk {risk:.4f}, closest to 1 "
        f"of {len(plans)} evaluated feasible at this size)"
    )


def tightest_eliminated(objects, devices: int):
    """Alternative B: the candidate an OPTIMISTIC bound rejected by the least.

    **This reads `BoundVerdict.eliminated` and `BoundProof.bound_value` /
    `.threshold`, because those are the fields that exist.** An earlier version
    looked for `.state == "impossible_proven"` and `.margin`; `Rejection`
    carries `candidate_id`, `stage`, `reason` and `BoundVerdict` carries
    `status`, `stage`, `proofs`. Neither has either attribute, so the branch
    was dead -- it answered "none available" whatever the search found, and
    would have kept doing so after a bound started rejecting things. A
    `getattr(x, "margin", None)` against a field that does not exist fails
    silently and forever.

    Memory rejections are skipped (see `TESTABLE_STAGES`). The margin is the
    smallest relative gap over the candidate's proofs: how close the most
    optimistic arithmetic came to clearing the threshold it missed. Deploying
    the tightest one and measuring its goodput against the declared floor is
    `false_infeasible`'s real-hardware test.
    """
    best = None
    for rep in objects.representatives:
        verdict = objects.verdicts.get(rep.rep_id)
        if verdict is None or not verdict.eliminated:
            continue
        template = rep.exemplar.template
        # **Not filtered to the topology's device count.** B asks about the
        # BOUND, not about placement: the question is whether a candidate the
        # arithmetic called impossible in fact works, and that candidate is
        # whichever the bound rejected by the least. Forcing it to the
        # topology's size picked tp1-dp4 (margin 30.6 %) over tp2-dp1
        # (margin 1.0 %), which is a far weaker test of the same bound.
        #
        # It must however be LAUNCHABLE: `VllmCudaBackend.launch` refuses
        # `dp_replicas > 1` and `pp_size > 1` outright (multi-engine needs a
        # router, out of scope). A tightest rejection that cannot be started
        # is not a test, so those are skipped and the skip is reported.
        if any(a.dp_replicas != 1 or a.pp_size != 1 for a in template.assignments):
            continue
        if template.total_devices > devices:
            continue
        stage = verdict.stage.value if verdict.stage else ""
        if stage not in TESTABLE_STAGES:
            continue
        margins = [
            (abs(pr.bound_value - pr.threshold) / abs(pr.threshold), pr)
            for pr in verdict.proofs if pr.threshold
        ]
        if not margins:
            continue
        margin, proof = min(margins, key=lambda m: m[0])
        if best is None or margin < best[0]:
            best = (margin, rep, verdict, proof)
    return best


def boundary_alternatives(objects, spec, devices: int, recommended_id):
    """Both kinds, because they ask different questions (MATRIX.md section 2).

    A returns a candidate the search called feasible; B returns one a bound
    called impossible. Reporting only whichever happens to exist would let a
    row answer a question the column heading does not name.
    """
    out = {}
    marginal, why_a = feasible_marginal(objects, spec, devices, recommended_id)
    out["feasible_marginal"] = {
        # Already a DeploymentPlan, carrying the predictions it was chosen on.
        "representative": marginal,
        "why": why_a,
        "sim_risk": None if marginal is None else sim_risk(marginal, spec),
        "candidate_id": None if marginal is None else marginal.candidate.id,
        "predicted": None if marginal is None else {
            "p99_ttft_ms": marginal.predicted.p99_ttft_ms,
            "p99_tpot_ms": marginal.predicted.p99_tpot_ms,
            "slo_goodput_rps": marginal.predicted.slo_goodput_rps,
        },
    }

    tightest = tightest_eliminated(objects, devices)
    if tightest is None:
        eliminated = sum(1 for v in objects.verdicts.values() if v.eliminated)
        out["impossible_proven"] = {"features": None, "why": (
            f"no candidate of {devices} devices was eliminated by an "
            f"optimistic bound ({eliminated} of {len(objects.verdicts)} "
            f"eliminated overall; memory rejections are excluded on purpose "
            f"-- an exact check's rejection says nothing about a bound's "
            f"safety)"
        )}
    else:
        margin, rep, verdict, proof = tightest
        out["impossible_proven"] = {
            "representative": rep,
            "why": (
                f"impossible_proven, tightest: stage {verdict.stage.value}, "
                f"margin {margin:.4f}, bound {proof.bound_value:.3f} "
                f"{proof.unit} against a ceiling of {proof.threshold:.3f}"
            ),
            "margin": margin,
            "stage": verdict.stage.value,
            "bound_value": proof.bound_value,
            "ceiling": proof.threshold,
        }
    return out


# --- stage 2: the deployment, which IS the load generator -----------------

#: Plan knobs `python -m bench run` cannot express, with what vLLM resolves
#: them to instead. Measured on vllm 0.19.0 by constructing `AsyncEngineArgs`
#: and reading `create_engine_config()`; the version is recorded so a change
#: shows up as a mismatch rather than as a silent drift.
#:
#: `bench run` builds an `AsyncEngineArgs` from nine fields and no more. It is
#: not a client of a served endpoint -- it *is* the engine -- which is why this
#: harness runs it instead of `vllm serve`, and why anything the plan says that
#: these nine cannot carry has to be reported rather than dropped.
VLLM_VERSION_CHECKED = "0.19.0"
#: `enable_prefix_caching` is NOT here any more: heteropilot D127 (hook H4)
#: gave `bench run` a `--no-enable-prefix-caching` flag, so the plan's value
#: can be carried. What remains are the knobs that still have no flag.
INEXPRESSIBLE = {
    # plan field -> (what vLLM resolves to when bench says nothing)
    "block_size": 16,
    "enable_chunked_prefill": True,
    "prioritize_prefill": False,
}


def knob_loss(plan_obj) -> list[dict]:
    """Plan knobs `bench run` cannot pass on, and whether that changes the run.

    The same discipline the simulator adapter uses: name what could not be
    expressed instead of dropping it. A knob whose plan value happens to equal
    what vLLM would choose anyway is recorded as harmless; one that differs
    means **the configuration measured is not the configuration planned**, and
    the harness refuses rather than producing a row labelled with a plan it did
    not run.
    """
    knobs = plan_obj.candidate.knobs
    out = []
    for field, resolved in sorted(INEXPRESSIBLE.items()):
        planned = getattr(knobs, field, None)
        if planned is None:
            continue
        out.append({
            "knob": field,
            "planned": planned,
            "vllm_resolves_to": resolved,
            "differs": planned != resolved,
            "checked_against_vllm": VLLM_VERSION_CHECKED,
        })
    # pipeline parallelism is on the assignment, not the knobs, and bench has
    # no flag for it at all.
    pp = max(a.pp_size for a in plan_obj.candidate.assignments)
    out.append({
        "knob": "pipeline_parallel_size",
        "planned": pp,
        "vllm_resolves_to": 1,
        "differs": pp != 1,
        "checked_against_vllm": VLLM_VERSION_CHECKED,
    })
    return out


def background_load(topo: C.Topology, args):
    """T3's 60 % background, from the E-G4 harness. Target, not achieved.

    `run_pair.py` records what it actually sustained and the analysis uses
    that: a generator that missed its target and a model that missed its
    prediction are different failures and must not cancel.
    """
    if topo.background is None or args.dry_run:
        return None
    src, dst = topo.background
    argv = [
        str(VLLM_PY), str(ROOT / "experiments" / "microbench" / "run_pair.py"),
        "--condition", "single", "--pairs", f"{src}-{dst}",
        "--share", "independent", "--binding", "unpinned",
        "--background-util", "0.6", "--background-pair", f"{src}-{dst}",
        "--iters", "1000000", "--sizes", "256",
        "--label", f"e_g5-background-{src}-{dst}",
        "--out-root", str(WORK / "background"),
    ]
    say(f"background: 60 % target on gpu{src}-gpu{dst}")
    return subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def bench_command(plan_obj, topo: C.Topology, model: str, workload: Path,
                  out_dir: Path, seed: int) -> tuple[list[str], dict]:
    """`bench run` carrying as much of the plan as its nine fields allow.

    **There is no `vllm serve` step.** An earlier version of this harness
    started one and then ran `bench run`, which builds its own in-process
    `AsyncLLM`: two engines on the same devices, and the second failed to
    initialise. `bench run` is the deployment.
    """
    knobs = plan_obj.candidate.knobs
    assignment = plan_obj.candidate.assignments[0]
    argv = [
        str(VLLM_PY), "-u", "-m", "bench", "run",
        "--model", C.MODELS[model]["hf_id"],
        "--dataset", str(workload),
        "--output-dir", str(out_dir),
        "--tensor-parallel-size", str(assignment.tp_size),
        "--data-parallel-size", str(assignment.dp_replicas),
        "--max-num-seqs", str(knobs.max_num_seqs),
        "--max-num-batched-tokens", str(knobs.max_num_batched_tokens),
        "--dtype", plan_obj.candidate.dtype,
        "--kv-cache-dtype", knobs.kv_cache_dtype,
        "--seed", str(seed),
        # D127: the plan's value, carried. Before hook H4 `bench run` had no
        # flag for this and vLLM's own default (True) applied, so a run of a
        # plan that says False measured a configuration nobody had asked for.
        ("--enable-prefix-caching" if knobs.enable_prefix_caching
         else "--no-enable-prefix-caching"),
        # The SAME count the simulator replayed: goodput is
        # `completed / elapsed` and the drain tail is a larger share of a short
        # trace, so two counts make one floor two different constraints.
        "--num-reqs", str(C.REQUESTS_PER_RUN),
    ]
    if knobs.max_model_len is not None:
        argv += ["--max-model-len", str(knobs.max_model_len)]

    placed = ",".join(str(d) for d in topo.devices)
    override = {
        # `planner/deploy/base.py::resolve_devices` maps an island to ALL of
        # its accelerator ids, so heteropilot names a TEMPLATE and never a
        # PLACEMENT. This is the quantity under test.
        "heteropilot_would_use": "every device of the island",
        "this_harness_uses": placed,
        "why": f"{topo.key}: {topo.link}",
        "planner_model": plan_obj.model,
        "served_model": C.MODELS[model]["hf_id"],
        "model_substitution": (
            "the planner keeps the gated id its profiles name; the engine is "
            "given the ungated mirror of the same weights"
            if C.MODELS[model]["hf_id"] != plan_obj.model else None
        ),
    }
    return argv, override


def workload_at(rps: float, model: str, work: Path) -> Path:
    """A trace re-spaced to `rps`, generated if it is not already there.

    `make_workload.py` rewrites only `arrival_time_ns`: every request's tokens
    are carried through untouched and in the same order, so across conditions
    the work is identical and only the load differs. Generating it here rather
    than requiring a flag means the rate a row was measured at is the rate its
    spec declared, by construction rather than by care.
    """
    stock = HETEROPILOT / "workloads" / (
        "sharegpt-llama-3.1-8b-300-sps10.jsonl" if model == "llama31-8b"
        else "sharegpt-qwen3-32b-300-sps10.jsonl"
    )
    out = ROOT / "outputs" / "e_g5" / "workloads" / f"{model}-rps{rps:g}.jsonl"
    if not out.exists():
        subprocess.run(
            [sys.executable, str(ROOT / "experiments" / "e_g5" / "make_workload.py"),
             "--input", str(stock), "--rps", str(rps), "--burstiness", "1.0",
             "--out", str(out)],
            check=True, capture_output=True, cwd=ROOT,
        )
        say(f"generated {out.name}")
    return out


def measure(source, plan_obj, label: str, topo: C.Topology, model: str,
            workload: Path, out_dir: Path, args, offered: float = 0.0) -> dict:
    """One deployment: run the load, collect, tear down. Always tears down."""
    out_dir.mkdir(parents=True, exist_ok=True)
    argv, override = bench_command(
        plan_obj, topo, model, workload, out_dir / "bench", args.rep
    )
    losses = knob_loss(plan_obj)
    record = {
        "label": label,
        "placement_override": override,
        "bench_argv": argv,
        "knob_loss": losses,
        "offered_rps": offered,
        "workload": str(workload),
        "plan_id": plan_obj.plan_id,
        "candidate_id": plan_obj.candidate.id,
        "predicted": {
            "p99_ttft_ms": plan_obj.predicted.p99_ttft_ms,
            "p99_tpot_ms": plan_obj.predicted.p99_tpot_ms,
            "slo_goodput_rps": plan_obj.predicted.slo_goodput_rps,
        },
    }
    (out_dir / "bench.cmd").write_text(
        " ".join(shlex.quote(a) for a in argv) + "\n"
    )

    divergent = [entry for entry in losses if entry["differs"]]
    if divergent and not args.allow_knob_loss:
        record["state"] = "refused: the configuration measured would not be "\
                          "the configuration planned"
        record["why"] = (
            "`bench run` builds an AsyncEngineArgs from nine fields and cannot "
            "carry " + ", ".join(
                f"{d['knob']} (plan {d['planned']}, vLLM would use "
                f"{d['vllm_resolves_to']})" for d in divergent
            ) + ". Measuring anyway would produce a row labelled with a plan "
            "that was not run. Pass --allow-knob-loss to accept it, and every "
            "row then carries this list."
        )
        say(f"{label}: REFUSED -- " + ", ".join(d["knob"] for d in divergent))
        return record

    if args.dry_run:
        record["state"] = "dry run"
        return record

    background = None
    try:
        background = background_load(topo, args)
        say(f"{label}: bench on devices {override['this_harness_uses']}")
        env = dict(
            os.environ,
            CUDA_VISIBLE_DEVICES=override["this_harness_uses"],
            PYTHONPATH=str(HETEROPILOT),
            HF_HUB_OFFLINE="1",
        )
        result = subprocess.run(
            argv, cwd=HETEROPILOT, env=env, capture_output=True, text=True,
            timeout=args.bench_timeout,
        )
        (out_dir / "bench.log").write_text(result.stdout + result.stderr)
        record["returncode"] = result.returncode
        record["state"] = "measured" if result.returncode == 0 else "failed"
        if result.returncode != 0:
            record["why"] = (
                "the load generator exited non-zero. Recorded as a failed "
                "deployment, not retried until it passes: a condition that "
                "only works on the third attempt is a condition that does not "
                "work."
            )
    finally:
        if background is not None:
            background.terminate()
            try:
                background.wait(timeout=30)
            except subprocess.TimeoutExpired:
                background.kill()
    return record


# --- the driver -----------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", required=True,
                        help="model__pattern__topology__level, e.g. "
                             "llama31-8b__normal__T2__knee")
    parser.add_argument("--rep", type=int, default=C.REPS[0])
    parser.add_argument("--rps", type=float, default=None,
                        help="absolute arrival rate; default is the level's "
                             "multiple of --knee-rps")
    parser.add_argument("--knee-rps", type=float, default=None,
                        help="this model's MEASURED knee. Required unless "
                             "--rps is given: there is no defensible default, "
                             "and a guessed one would put every level's label "
                             "on the wrong load.")
    parser.add_argument("--ttft-max-ms", type=float, default=550.0,
                        help="DERIVED: T1's measured p99 at the knee x 1.5")
    parser.add_argument("--tpot-max-ms", type=float, default=60.0,
                        help="DERIVED: ~10 %% above the measured band, so this "
                             "axis does not decide")
    parser.add_argument("--min-goodput-rps", type=float, default=43.0,
                        help="DERIVED: inside the registered interval "
                             "(10.527, 101.081); see preregistration entry 4")
    parser.add_argument("--workload", type=Path, default=None)
    parser.add_argument("--predictor", choices=("mock", "sim"), default="sim")
    parser.add_argument("--num-requests", type=int, default=C.REQUESTS_PER_RUN)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--budget-sims", type=int, default=16)
    parser.add_argument("--sim-timeout", type=float, default=1800)
    parser.add_argument("--health-timeout", type=float, default=900)
    parser.add_argument("--bench-timeout", type=float, default=1800)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dry-run", action="store_true",
                        help="write every config file and command; launch "
                             "nothing and touch no GPU")
    parser.add_argument("--allow-knob-loss", action="store_true",
                        help="deploy although `bench run` cannot carry a "
                             "knob the plan sets. Every row then carries "
                             "the list of what diverged.")
    parser.add_argument("--allow-tenants", action="store_true",
                        help="proceed although another tenant holds a GPU. "
                             "Every row is then labelled contaminated.")
    args = parser.parse_args(argv)

    model, pattern, topo_key, level = C.parse(args.condition)
    topo = C.TOPOLOGIES[topo_key]
    info = C.MODELS[model]
    args.topology_key = topo_key

    if topo.tp < info["min_tp"]:
        raise SystemExit(
            f"{model} needs tp>={info['min_tp']} ({info['weights_gb']} GB of "
            f"bf16 weights on 45 GB usable devices) and {topo_key} is tp="
            f"{topo.tp}. impossible_proven, not a budget: the combination is "
            f"excluded from the grid rather than merely unattempted."
        )
    if args.rps is None and args.knee_rps is None:
        raise SystemExit(
            "pass --rps, or --knee-rps from the pilot. There is no defensible "
            "default: a guessed knee puts 'low', 'knee' and 'high' on three "
            "loads that are not those things, and every row would then be "
            "labelled with a condition it was not run under."
        )

    out_dir = RAW / args.condition / str(args.rep)
    work = WORK / args.condition / str(args.rep)
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    say(f"condition {args.condition} rep {args.rep}"
        + ("  [DRY RUN]" if args.dry_run else ""))

    pre = preconditions(args)
    if pre["problems"] and not args.dry_run:
        for problem in pre["problems"]:
            print(f"REFUSED: {problem}", file=sys.stderr)
        (out_dir / "refused.json").write_text(json.dumps(pre, indent=2) + "\n")
        return 1
    for problem in pre["problems"]:
        say("(dry run) would refuse: " + problem.splitlines()[0])

    rps = args.rps if args.rps is not None else args.knee_rps * C.LEVELS[level]
    # Two specs, two questions. See `conditions.SPECS`.
    service = C.SPECS["service"]
    stress = C.SPECS["bound_stress"]

    spec_path = service_spec(
        model, pattern, level, rps, work / "service.yaml",
        ttft_max_ms=service["ttft_max_ms"], tpot_max_ms=service["tpot_max_ms"],
        min_goodput_rps=service["min_goodput_rps"],
    )
    stress_path = service_spec(
        model, pattern, level, stress["arrival_rate_rps"],
        work / "bound-stress.yaml",
        ttft_max_ms=stress["ttft_max_ms"], tpot_max_ms=stress["tpot_max_ms"],
        min_goodput_rps=stress["min_goodput_rps"],
    )

    say(f"planning S ({args.predictor}) at {rps:.2f} rps, "
        f"goodput floor {service['min_goodput_rps']}")
    objects = run_plan(spec_path, work, args)
    say(f"planning B (bound-stress) at {stress['arrival_rate_rps']} rps, "
        f"goodput floor {stress['min_goodput_rps']}")
    stress_objects = run_plan(stress_path, work / "stress", args)

    # **The trace must offer the rate the spec declared**, or the predicted and
    # measured columns answer different questions. The stock trace is sps10;
    # replaying it against a plan simulated at 4 rps put the hardware deep into
    # saturation and made a predicted p99 TTFT of 162 ms sit beside a measured
    # 22,068 -- a number that says nothing about the simulator, only about two
    # different offered loads.
    # Each deployment is offered the rate ITS OWN spec declares: S's rows ask
    # whether the recommendation meets its SLOs at the service's load, and B's
    # asks whether a candidate the bound rejected can reach the floor it was
    # rejected against. One trace for both would answer neither.
    workload = args.workload

    # The condition names a placement, so only candidates with that many
    # devices can carry it. See `candidates_of_size`.
    devices = len(topo.devices)
    sized = candidates_of_size(objects, devices)
    recommended_id = (
        getattr(sized[0], "plan", sized[0]).candidate.id if sized else None
    )
    # A from S (the service question), B from the bound-stress spec.
    alternatives = boundary_alternatives(objects, objects.spec, devices,
                                         recommended_id)
    stress_alt = boundary_alternatives(
        stress_objects, stress_objects.spec, devices, None
    )
    alternatives["impossible_proven"] = stress_alt["impossible_proven"]
    alternative_kind = "; ".join(
        f"{k}: {v['why']}" for k, v in sorted(alternatives.items())
    )
    chosen = [("recommendation", sized[0] if sized else None)]
    for kind in ("feasible_marginal", "impossible_proven"):
        entry = alternatives[kind]
        rep = entry.get("representative")
        chosen.append((f"boundary:{kind}", rep))

    deployments = []
    for label, entry in chosen:
        if entry is None:
            kind = label.split(":", 1)[-1]
            deployments.append({
                "label": label,
                "state": "not applicable to this topology",
                "detail": alternatives.get(kind, {}).get("why"),
                "why": (
                    f"{topo.key} places {len(topo.devices)} devices, and the "
                    f"search returned no candidate of that size for the "
                    f"{label} slot. Recorded rather than forced: a TP=8 plan "
                    f"launched on two visible devices is not this condition "
                    f"measured badly, it is a different condition that does "
                    f"not run."
                ),
                "boundary_kind": alternative_kind if label == "boundary" else None,
            })
            continue
        source = stress_objects if label.endswith("impossible_proven") else objects
        plan_obj = plan_for(entry, source.spec)
        offered = float(source.spec.traffic.arrival_rate_rps)
        trace = workload or workload_at(offered, model, work)
        need = plan_obj.candidate.total_devices
        if need > len(topo.devices):                        # pragma: no cover
            raise SystemExit(
                f"internal: selected a {need}-device candidate for "
                f"{topo.key}, which places {len(topo.devices)}"
            )
        # B may be smaller than the condition's placement, because its size is
        # decided by which rejection is tightest, not by the topology. It takes
        # the first `need` of the condition's devices so it still runs on the
        # wires the condition names.
        placed = topo if need == len(topo.devices) else replace(
            topo, devices=tuple(topo.devices[:need])
        )
        deployments.append(measure(
            source, plan_obj, label, placed, model, trace,
            out_dir / label, args, offered=offered,
        ))

    record = {
        "banner": (
            "DRY RUN -- nothing was launched and no number here is a "
            "measurement. Configs and commands are recorded exactly as they "
            "would run."
            if args.dry_run else
            "REAL HARDWARE -- node serials in `preconditions`."
        ),
        "condition": args.condition,
        "model": model, "pattern": pattern, "topology_key": topo_key,
        "level": level, "rep": args.rep,
        "arrival_rate_rps": rps,
        "hf_model": info["hf_id"], "planner_model": info["planner_id"],
        "model_substitution_note": (
            "the planner is given the gated `meta-llama/...` id that "
            "heteropilot's profiles name; the engine serves the ungated "
            "NousResearch mirror of the same weights"
            if info["hf_id"] != info["planner_id"] else None
        ),
        "has_accuracy_domain": info["accuracy_domain"],
        "calibration": (
            "existing a40.accuracy.yaml only; no new domain may be created "
            "from this run"
            if info["accuracy_domain"] else
            "UNCALIBRATED -- no A40 accuracy domain exists for this model, "
            "and creating one from this run is the circular evaluation the "
            "work order forbids"
        ),
        "scope_cut": {
            "max_devices": len(topo.devices),
            "state": "excluded_by_scope",
            "why": (
                "the topology condition places this many devices, so the "
                "planner was asked for the best plan of that size. Larger "
                "plans were not considered -- not considered and rejected "
                "(GS-27)."
            ),
        },
        "topology": {
            "key": topo.key, "devices": list(topo.devices), "tp": topo.tp,
            "link": topo.link, "substitutes": topo.substitutes,
            "background_pair": list(topo.background) if topo.background else None,
        },
        "boundary_alternative_kind": alternative_kind,
        "deployments": deployments,
        "preconditions": pre,
        "gpu_tenants_after": gpu_tenants(os.getpid()),
        "loadavg_after": [round(x, 2) for x in os.getloadavg()],
        "dry_run": args.dry_run,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "provenance.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str) + "\n"
    )
    say(f"wrote {out_dir / 'provenance.json'}")
    if args.dry_run:
        say("dry run complete: nothing was launched, no GPU was touched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
