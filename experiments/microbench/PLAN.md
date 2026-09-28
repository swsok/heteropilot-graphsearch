# E-G4 — the contention microbenchmark, planned before it runs

> **No measurement in this file.** It is what will be measured, on which
> hardware, under which conditions, and what each number will be allowed to
> say. The criteria it is judged against were registered in
> `docs/preregistration.md` on 2026-09-28, before `FluidContentionModel`
> existed; nothing here may loosen them.

**The question.** `FluidContentionModel` (GS-20) claims that flows sharing a
resource split it. `NullContentionModel` claims they do not interfere at all.
One of those is closer to a real wire. This measures which, and by how much.

**The answer this cannot give.** Whether the *simulator* is accurate. E-G4
compares a transfer-time model against a stopwatch on real hardware; it says
nothing about LLMServingSim, about TTFT, or about any placement decision. Those
are E-G5's.

---

## 1. The hardware, as observed

`bash vendor/heteropilot/scripts/whichnode.sh` first, every time. The plan below
is written for the **A40 node** whose `accel serials` line begins
`GPU-11e5c5fd…`; on any other machine the device numbers below are fiction.

Topology from `nvidia-smi topo -m`, observed 2026-09-28:

```
         GPU0 GPU1 GPU2 GPU3 GPU4 GPU5 GPU6 GPU7 NIC0
GPU0..3   ── NUMA node 0 ──                      SYS
GPU4..7                    ── NUMA node 1 ──     NODE / PHB
NVLink pairs: (0,1) (2,3) (4,5) (6,7)   — NV4 each
```

What that buys, condition by condition:

| structure | device pairs | why it is in the matrix |
| --- | --- | --- |
| **NVLink pair** | 0–1, 2–3, 4–5, 6–7 | the fast path; a control, not a contention case |
| **Same NUMA, across the bridge** | 0–2, 1–3 | two pairs share one PCIe host bridge — **this is the shared uplink** |
| **Across NUMA** | 0–4, 1–5 | `SYS`: PCIe plus the UPI hop between sockets |
| **NIC0** | reachable from GPU4–7 (`NODE`, `PHB` to GPU6) | the only NIC, and it is on NUMA 1 |

**Location (b), between nodes, needs a second machine and this node has one
NIC.** Until an A5000 or RNGD node is reachable over that NIC with the same
environment built, location (b) is **not runnable**, and the result file will
say `not run` rather than leaving the row blank. A blank reads as zero.

### The node is shared, and a measurement taken while it is shared says so

Observed 2026-09-28: GPUs 4–7 at 99 % with ~8.8 GB each, held by `root` running
`pretrain_gpt.py` (Megatron-DeepSpeed) in a long-lived container. GPUs 0–3 idle.

A bandwidth figure measured while another tenant drives half the machine is not
wrong — it is **measured under a condition the `REAL HARDWARE` banner does not
state**. So:

- `run_pair.py` records `nvidia-smi --query-compute-apps` into every raw file,
  before and after the run. The measurement labels itself.
- `LOG.md` has a column for it and the analysis refuses to merge a run whose
  occupancy changed mid-flight.
- **Prefer GPUs 0–3** while the tenant holds 4–7. They are on one NUMA node and
  give the NVLink pair (0,1) and the across-bridge pair (0,2) — which is
  conditions 1–4 at location (a), the whole of what this node can answer today.

---

## 2. The matrix

**5 conditions × 2 locations × 9 message sizes × ≥10 repetitions.**

| # | condition | how | contention expected |
| --- | --- | --- | --- |
| 1 | single transfer | one copy, nothing else running | none — the control |
| 2 | two flows, **same** resource | two concurrent copies over the same bridge | **yes** — the case the model exists for |
| 3 | two flows, **independent** resources | two concurrent copies over disjoint bridges | none — the implementation check |
| 4 | bidirectional | A→B and B→A at once | yes, and asymmetrically |
| 5 | collective, varying world size and size | all-reduce at world 2 and 4 | yes, and not by the same factor |

**Message sizes.** 1 MiB to 256 MiB, doubling: 1, 2, 4, 8, 16, 32, 64, 128, 256.
The band matters — heteropilot's `MSG_SIZE_CLASS_BYTES` calls below 1 MiB
`small`, 1–4 MiB `mid`, and 4 MiB and up `bulk`. This grid starts exactly on
the `mid` floor and crosses into `bulk` at 4 MiB, so it spans two classes and
**each figure is filed under the class its own bytes fall in**, never under one
label for the whole sweep. Nothing here lands in `small`; a figure in that band
would need a finer grid and is out of scope, which is why no `small` row will
appear in the result.

`run_pair.py` classes each size with heteropilot's own `msg_size_class_of`
rather than a local copy of the boundaries, and
`tests/test_microbench_harness.py` pins that. A second definition would drift,
and `LinkMeasurement` would then reject data that was correctly measured.

**Repetitions: ≥ 10, and the spread is reported, not just the median.**
heteropilot's `docs/nodes/a40.md` records two runs of a single parallel trial
disagreeing by 38 %. A single trial on this node is not a measurement.

**Background load** (conditions 2 and 4, and wherever the matrix says so): a
separate process holding the same resource at a **target occupancy of 60 %**,
driven by `run_pair.py --background-util 0.6`. Target, not achieved: the script
records what it actually sustained, and the analysis uses *that*, because a
generator that missed its target and a model that missed its prediction are two
different failures and must not cancel.

---

## 3. What is recorded

Every figure becomes a heteropilot `LinkMeasurement`, every field filled:

```yaml
collective: all_reduce | all_gather | p2p    # what was actually run
msg_size_class: small | mid | bulk           # from THIS figure's own bytes
binding: numa_pinned | unpinned | unknown    # `unknown` is compared against nothing
bus_bw_gbps: <the busbw plateau, GB/s>       # not the wire rate
world_size: <how many ranks took part>
source: measured
method: "torch <ver> + NCCL <ver>, run_pair.py --concurrent 2 --share same"
msg_bytes: [...]                             # checked against msg_size_class
date: "YYYY-MM-DD"
raw: experiments/microbench/raw/<date>-<serial>/<label>.json
note: "<the spread across repetitions, and anything odd>"
```

Three of those fields are load-bearing and the schema enforces them:

- **`world_size` is part of the key.** heteropilot's own A40 bridge measures
  19.29 GB/s for a two-rank all-reduce and 8.8 for a four-rank one — one wire,
  2.2× apart. Filing one under the other's key is the substitution the key
  exists to stop.
- **`msg_bytes` must fall inside `msg_size_class`**, or the load fails. A
  `bulk` label over a 1 MiB sweep is rejected rather than believed.
- **`source: measured` must name its `method`.** An unattributed number is not
  a measurement.

Raw artefacts go to `experiments/microbench/raw/<date>-<node-serial>/`, are
committed, and are what `raw:` points at. **The JSON is the evidence; the YAML
is the claim.**

---

## 4. What the numbers will be compared against

For each (location, condition, message size), both models predict a transfer
time for the same flows over the same graph, and the error is
`|predicted − measured| / measured` at p50 and p90.

Registered in `docs/preregistration.md` (E-G4) before any of this ran:

| # | criterion |
| --- | --- |
| 1 | under **shared** conditions, fluid's error is p50 ≤ 15 %, p90 ≤ 30 % |
| 2 | under **independent** conditions, null and fluid differ by ≤ 5 % |
| 3 | under **shared** conditions, fluid's error is smaller than null's |

The 15 / 30 are the order of magnitude of heteropilot D29's own measured
simulator TPOT error (+11.6 % at served concurrency 3.9, −18 % at 76): a
transfer-time model must not be worse than the simulator it feeds. Criterion 2
is a check on the implementation, not evidence for the model — conditions 1 and
3 have no contention, so the two models are the same arithmetic and a
difference there is a defect.

**All three are provisional and are re-registered after a one-shot pilot** —
one location, one message size — appended to the pre-registration's change log
with its date and numbers.

### If the model has to be changed to fit

Allowed **once**, and only with both of: a `GS-n` saying what changed and why,
and a change-log entry in the pre-registration listing **every raw file used to
fit it**. Those files are then excluded from E-G5. A model validated on the
data that shaped it measures nothing.

---

## 5. Running it

**This is the user's step.** Claude Code wrote `run_pair.py` and this plan and
stops here; no number below the line gets filled in from that side.

```bash
bash vendor/heteropilot/scripts/whichnode.sh          # record the serials
python experiments/microbench/run_pair.py --help      # the conditions it takes
```

`run_pair.py` needs **torch with CUDA**, which neither `vendor/heteropilot/.venv`
(simulator only, no torch) nor the system python has. Build it the way
heteropilot does, in a venv of its own, and run `run_pair.py` through that
interpreter:

```bash
cd vendor/heteropilot && bash scripts/install-vllm.sh   # brings torch in
```

Fill `LOG.md` as you go — one row per run, node serial included. The analysis
(`analyze.py`, P2.4) starts only after the raw files are committed, and reads
them; it never reads this file.

---

## 6. What this plan does not cover

- **Location (b)**, between nodes, until a second node with the same
  environment is reachable. Reported as `not run`.
- **RNGD and ATOM.** `planner/deploy` has no FuriosaAI backend, and the NPU
  node has no NVIDIA GPU, so neither instrument here applies to it.
- **Anything about placement quality.** E-G4 measures a transfer-time model.
  Whether a better transfer-time model produces better placements is E-G5's
  question, and answering it from this data would be assuming the thing the
  whole pipeline exists to test.
