"""The E-G5 condition grid, as data. One definition, read by every script.

`MATRIX.md` is the argument; this is the enumeration. They are separate files
because a plan edited to match what ran is not a plan, and a grid retyped in
three scripts drifts in two of them.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The two models. `NousResearch/Meta-Llama-3.1-8B` is the gated
#: `meta-llama/Llama-3.1-8B`'s ungated mirror -- same weights, and the pattern
#: `NousResearch/Meta-Llama-3.1-*` is explicitly in a40.yaml's
#: `supported_models`. The substitution is recorded in every provenance record
#: rather than silently made.
MODELS = {
    "llama31-8b": {
        "hf_id": "NousResearch/Meta-Llama-3.1-8B",
        "planner_id": "meta-llama/Llama-3.1-8B",
        "weights_gb": 15.0,
        # `profiles/calibration/a40.accuracy.yaml`, three measured points.
        "accuracy_domain": True,
        "min_tp": 1,
    },
    "qwen3-32b": {
        "hf_id": "Qwen/Qwen3-32B",
        "planner_id": "Qwen/Qwen3-32B",
        "weights_gb": 61.0,
        # No A40 accuracy domain exists for it. Its rows are reported
        # UNCALIBRATED; creating a domain from this run is the circular
        # evaluation the work order forbids.
        "accuracy_domain": False,
        # 61 GB of bf16 weights on a 45 GB usable device. Arithmetic, so TP=1
        # is `impossible_proven` rather than merely unattractive.
        "min_tp": 2,
    },
}

#: Poisson (`burstiness = 1.0`) and bursty. heteropilot's own generator emits
#: Poisson arrivals only, so the burst trace is produced by re-spacing an
#: existing trace's arrivals -- see `make_workload.py`, which records that it
#: did so in the trace's own provenance.
PATTERNS = {"normal": 1.0, "burst": 0.2}

#: Below the knee, near it, above it. The absolute rps per model comes from
#: the pilot and is filled in by `--calibrate-levels`; these are the multiples
#: of the measured knee, so the axis means the same thing for both models.
LEVELS = {"low": 0.5, "knee": 1.0, "high": 1.5}

REPS = (42, 43, 44)


@dataclass(frozen=True)
class Topology:
    """One placement of one template, named by devices.

    **This is the part heteropilot cannot express.** `resolve_devices` maps an
    island to *all* of its accelerator ids, so a TP=2 plan on this node's
    single 8-GPU island is launched with `CUDA_VISIBLE_DEVICES=0,1,...,7` and
    vLLM takes the first two. The planner names a template; it cannot name a
    placement. The harness therefore sets the device list itself, and that
    override is exactly the quantity E-G5 measures the effect of.
    """

    key: str
    devices: tuple[int, ...]
    tp: int
    #: Measured, E-G4. What the wire between these devices actually does.
    link: str
    background: tuple[int, int] | None = None
    substitutes: str | None = None


TOPOLOGIES = {
    # The registered condition, unchanged: one node, aggregated.
    "T1": Topology(
        key="T1", devices=(0, 1), tp=2,
        link="NVLink NV4, measured 52.64 GB/s p2p / 19.34 GB/s busbw world 2",
    ),
    # Substitutes for "inter-node P/D over independent uplinks". Identical
    # engine, identical model, identical load; the only difference is a wire
    # 2.1x slower. This is the X-type vs Y-type contrast.
    "T2": Topology(
        key="T2", devices=(0, 2), tp=2,
        link="PCIe across the host bridge, measured 25.12 GB/s p2p",
        substitutes="inter-node P/D, independent uplinks (no second node, and "
                    "no disaggregation in planner/deploy/vllm_cuda.py)",
    ),
    # Substitutes for "inter-node P/D over a shared uplink + 60 % background".
    # The world-4 all-reduce is where this node's collective bandwidth really
    # does collapse -- 8.71 GB/s against 19.34 -- and it is measured.
    "T3": Topology(
        key="T3", devices=(0, 1, 2, 3), tp=4,
        link="TP=4 over two NVLink pairs bridged by PCIe, measured 8.71 GB/s "
             "busbw at world 4 against 19.34 at world 2",
        background=(5, 7),
        substitutes="inter-node P/D, shared uplink + 60 % background load",
    ),
}


def conditions(models=None, patterns=None, levels=None, topologies=None):
    """Every condition, in a fixed order. Sorted, so two runs enumerate alike."""
    for model in sorted(models or MODELS):
        for pattern in sorted(patterns or PATTERNS):
            for topo in sorted(topologies or TOPOLOGIES):
                for level in sorted(levels or LEVELS):
                    yield f"{model}__{pattern}__{topo}__{level}"


def parse(condition: str) -> tuple[str, str, str, str]:
    model, pattern, topo, level = condition.split("__")
    if model not in MODELS:
        raise SystemExit(f"unknown model {model!r}; have {sorted(MODELS)}")
    if pattern not in PATTERNS:
        raise SystemExit(f"unknown pattern {pattern!r}; have {sorted(PATTERNS)}")
    if topo not in TOPOLOGIES:
        raise SystemExit(f"unknown topology {topo!r}; have {sorted(TOPOLOGIES)}")
    if level not in LEVELS:
        raise SystemExit(f"unknown level {level!r}; have {sorted(LEVELS)}")
    return model, pattern, topo, level


#: **Two specs, because one cannot ask both questions.**
#:
#: Achieved goodput can never exceed offered load, so a `min_goodput_rps` high
#: enough to make `throughput_capacity` reject anything is a floor no candidate
#: can meet at the arrival rate it was measured under. Trying to verify the
#: recommendation and the lower bound with one spec made `recommended` None:
#: not a search failure, an arithmetic contradiction in the spec.
#:
#: So the recommendation and the marginal alternative are verified under S, and
#: the bound's rejection under B. Every row says which spec produced it.
SPECS = {
    "service": {
        # `min_goodput_rps` is 95 % of the MEASURED achieved goodput, not of
        # the offered rate. On a finite trace the decode tail drains after
        # arrivals stop -- 150 requests offered at 4.0 rps over 36.5 s of
        # arrivals complete over 58-61 s -- so achieved is 2.47-2.59 rps and a
        # floor of 95 % of *offered* (3.8) is unreachable by construction. It
        # made every candidate infeasible on goodput while TTFT and TPOT
        # passed comfortably. See preregistration entry 4.
        "ttft_max_ms": 550.0,
        "tpot_max_ms": 60.0,
        "arrival_rate_rps": 4.0,
        "min_goodput_rps": 2.3,
        "purpose": "recommendation and the feasible-marginal alternative (A)",
        "recommendation_column": "measured",
    },
    "bound_stress": {
        # Chosen so THROUGHPUT_UPPER_BOUND rejects tp1-dp1 (ceiling 10.527),
        # tp1-dp4 (42.106) and tp2-dp1 (54.433), leaving tp4-dp1 (101.081).
        # The tightest rejection is then tp2-dp1 at a margin of 1.0 %, and it
        # is dp=1, so `VllmCudaBackend.launch` can actually start it.
        "ttft_max_ms": 550.0,
        "tpot_max_ms": 60.0,
        "arrival_rate_rps": 55.0,
        "min_goodput_rps": 55.0,
        "purpose": "the impossible_proven alternative (B) only",
        # 55 rps is 14x the measured knee of 4 rps, so the recommendation
        # cannot meet it on hardware either -- and that is not this spec's
        # question. Saying so is not a failure being excused; it is the column
        # naming what it does not measure.
        "recommendation_column": "not applicable (bound verification only)",
    },
}

#: The measured knee, from `experiments/e_g5/raw/pilot/`. `deploy_and_bench.py`
#: refuses a guessed one.
KNEE_RPS = 4.0

#: Requests per replay. **The simulator and the hardware must use the same
#: number**, or `min_goodput_rps` means two different things: goodput is
#: `completed / elapsed` and the drain tail is a larger share of a short trace.
#: At 30 the simulator reported 1.96 rps where the hardware's 150 gave 2.47.
REQUESTS_PER_RUN = 150
