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
