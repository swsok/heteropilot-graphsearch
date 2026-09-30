# E-G5 — the real-hardware matrix

STEP P3.1 of `WORK_ORDER_paper.md`. What will be deployed, what cannot be, and
what each row costs in machine time.

**Nothing in this file is a measurement.** It is the plan. Results go to
`experiments/results/e_g5_real_hardware.md`, and the run log to
`experiments/e_g5/LOG.md`.

---

## 0. The node, and the two things it cannot do

One machine: 8 × NVIDIA A40 (46 GB each, ~45 usable), 64 cores, 503 GiB,
driver 560.35.05 / CUDA 12.8. NVLink `NV4` pairs (0,1) (2,3) (4,5) (6,7);
GPU0-3 on NUMA 0, GPU4-7 on NUMA 1; across NUMA is `SYS`. One NIC, on NUMA 1.

Two constraints decide most of this document, and both were found by reading
the code rather than by assuming:

**(A) A second node exists as of 2026-09-29, so this is no longer a reason.**
`s6` is another eight-GPU A40 machine on the same InfiniBand subnet, reachable
over ssh. E-G4's location (b) has been measured across it. What follows is
therefore struck as a reason for E-G5's conditions 2 and 3, and only (B)
remains --- which is sufficient on its own.

**(B) heteropilot cannot deploy a disaggregated P/D pair.**
`planner/deploy/vllm_cuda.py::build_serve_command` says so in its own
docstring — "the `vllm serve` argv + env for **one aggregated engine**" — and
builds no `--kv-transfer-config`, no `kv_connector`, no producer/consumer
role. Disaggregation would need a fifth hook PR in that repository, and
`vendor/heteropilot` is read-only here.

(A) no longer holds; (B) does, and it alone removes conditions 2 and 3. So
**the registered topology axis is still two-thirds undeployable**, for one
reason instead of two. Stated here rather than discovered in the results.

Writing both reasons down separately is what makes this legible now: had they
been merged into "we cannot run inter-node P/D", the arrival of a second node
would have looked like it changed everything, and it changes exactly half.

### What is run instead, and why it answers the same question

The scientific content of conditions 2 and 3 is *does a placement's position in
the interconnect change served latency, and does the planner predict it*. That
does not require two nodes or P/D; it requires two placements that differ only
in which wire they use. This node has exactly that, and E-G4 measured the wires
(`experiments/results/e_g4_microbench.md`):

| | registered condition | substituted condition | what makes it the same question |
| --- | --- | --- | --- |
| **T1** | single node, aggregated | TP=2 on the **NVLink pair** (0,1) — 52.64 GB/s measured | unchanged; this is the registered condition |
| **T2** | inter-node P/D, independent uplinks | TP=2 **across the PCIe bridge** (0,2) — 25.12 GB/s measured | identical engine, identical model, identical load; the *only* difference is a wire 2.1x slower. This is the X-type vs Y-type contrast the research design's counterexample is about |
| **T3** | inter-node P/D, shared uplink + 60 % background | TP=4 on {0,1,2,3} — busbw **8.71 GB/s** at world 4 against 19.34 at world 2 (E-G4 condition 5) — **plus** `run_pair.py --background-util 0.6` on a pair sharing an endpoint with the island | the shared-resource case, with a genuinely shared resource: the world-4 all-reduce is where this node's collective bandwidth actually collapses, and it is measured, not declared |

**This substitution is a deviation and is labelled as one everywhere it
appears.** T2 and T3 are *not* inter-node P/D and no row will say they are.
What they establish is narrower than the registered claim and is stated
narrowly: that placement position changes served latency on real hardware, and
whether the planner predicted the change. The inter-node P/D claim stays
`not run` until there is a second node and a disaggregation hook.

---

## 1. The axes

| axis | levels | values |
| --- | --- | --- |
| model | 2 | `NousResearch/Meta-Llama-3.1-8B`, `Qwen/Qwen3-32B` |
| load pattern | 2 | normal (Poisson, `burstiness = 1.0`), burst (`burstiness = 0.2`) |
| topology | 3 | T1 NVLink pair · T2 across bridge · T3 world-4 + 60 % background |
| load level | 3 | below knee · near knee · above knee (per model, from the pilot) |
| repetitions | 3 | seeds 42, 43, 44 |

**2 × 2 × 3 × 3 × 3 = 108 conditions.** Each gets a recommendation **and** a
boundary alternative: **216 deployments.**

### The models, and why these two

`NousResearch/Meta-Llama-3.1-8B` — the weights are cached locally and the
pattern `NousResearch/Meta-Llama-3.1-*` is explicitly in
`profiles/accelerators/a40.yaml::supported_models`. It is profiled on this real
A40 at TP=1/2/4, and it is **the only model with an A40 accuracy domain**
(`profiles/calibration/a40.accuracy.yaml`, three measured points). The configs
in heteropilot name `meta-llama/Llama-3.1-8B`, which is gated and not
downloadable here; the NousResearch mirror is the same weights and the
substitution is recorded in every provenance record rather than silently made.

`Qwen/Qwen3-32B` — profiled on this real A40 at TP=1/2, 61 GB of bf16 weights,
so **TP=1 does not fit** on 45 GB usable devices and TP≥2 is forced. That is
useful rather than inconvenient: it is a candidate whose feasibility is decided
by memory rather than by latency, which is a different part of the bound.

> **Qwen3-32B has no A40 accuracy domain.** P3.4's calibration therefore applies
> to the Llama rows only. Qwen rows are reported **uncalibrated** and say so in
> the table. Creating a domain from this run is forbidden — that is the circular
> evaluation the work order rules out, and it would make E-G5 evaluate a margin
> fitted on E-G5.

### Unsupported combinations, marked rather than omitted

| combination | status | why |
| --- | --- | --- |
| RNGD (furiosa) P/D | **excluded_by_scope** | `planner/deploy/` has `vllm_cuda`, `vllm_ascend`, `kubernetes`. There is no furiosa backend, and this node has no NPU of any kind (`docs/nodes/a40.md`). |
| inter-node P/D, any model | **unknown_measurement** | no disaggregation in the deploy backend (§0). A second node exists as of 2026-09-29, so that half of the reason is gone. Not `impossible_proven`: nothing here shows it cannot work, only that it was not run. |
| Qwen3-32B at TP=1 | **impossible_proven** | 61 GB of bf16 weights on a 45 GB usable device. Arithmetic, not a budget. |
| Qwen3-32B calibrated p99 | **unknown_measurement** | no A40 accuracy domain for it, and this run may not create one. |

The five states do not merge (work order rule 4). "Not run" is not "cannot
work", and a budget is not a property of the hardware.

---

## 1b. What the topology axis can and cannot ask (GS-27)

A topology condition names a **placement**, and a placement has a fixed device
count. T2 is "this template, on gpu0 and gpu2"; it is not a template of its own.

That has a consequence this matrix has to state. Asked without a scope, the
search on an eight-GPU node recommends an **eight-device** plan — and an
eight-device plan on an eight-device node has **exactly one placement**. There
is no contrast to measure, and T1 against T2 is not a question that can be put
at all. The first dry run of the harness made this concrete by emitting
`CUDA_VISIBLE_DEVICES=0,2 vllm serve ... --tensor-parallel-size 8`, which vLLM
would refuse instantly.

So each condition **scopes the planner to its own device count** and places the
best plan of that size. Two things follow, and both are reported in every row
rather than assumed:

- **The rows are the best plan _of the size the condition places_**, not the
  best plan on the node. Larger plans are `excluded_by_scope` — not
  considered, never considered and rejected.
- **A condition whose scope admits only one candidate has no boundary
  alternative.** Measured: at `max_devices=2` the search returned one
  two-device candidate, so that condition's boundary column reads
  `not applicable` rather than being filled with a candidate of a different
  size, which would make the two columns answer different questions.

The second point bites §2's `false_infeasible` test, which needs a *second*
candidate to deploy. It is available only in conditions whose scope admits
more than one, and T3 (four devices) is where the matrix expects to find them.

---

## 2. The boundary alternative

Every condition deploys two candidates, and the second is the point of the
experiment.

1. **The recommendation** — rank 1 from
   `python -m graphsearch plan --predictor sim`.
2. **The boundary alternative** — *one* of these two, alternating by condition
   so both are covered across the matrix:
   - **feasible-marginal**: of the candidates judged feasible below rank 1, the
     one whose `risk_proxy` is closest to 1. This asks whether the ranker's
     ordering is real or whether the next one down does just as well.
   - **the tightest `impossible_proven`**: the candidate the lower bound
     rejected by the smallest margin. **This is the real-hardware test of
     `false_infeasible`.** If it is deployed and meets the SLO, the bound
     rejected something that worked, the invariant is broken on hardware, and
     the registered response is to stop and report — never to relax the test
     (work order rule 5, pre-registration common section).

The second kind is why 216 and not 108. A bound that is never tested against a
machine is a bound nobody has checked.

---

## 3. Time, per condition and in total

**Measured on 2026-09-29 unless marked as an estimate.** The first version of
this section was all estimates and two of them were wrong by more than an order
of magnitude, so each row now says which it is.

| stage | Llama-3.1-8B TP=2 | Qwen3-32B TP=2 | source |
| --- | --- | --- | --- |
| `graphsearch plan --predictor sim` | **> 25 min, unbounded** | not measured | measured; see below |
| engine start + 150 requests + teardown | **110-170 s** | ~4x, estimate | measured, 45 runs |
| engine start + 300 requests at 2.5x knee | **~130 s** | ~4x, estimate | measured, 9 runs |
| engine start alone (weights + CUDA graphs) | **~40 s** | ~200 s, estimate | measured |

**The planning stage is the problem, and it is not a small one.** A plan on
`real-a40x8.v2.yaml` had not finished after **25 minutes** of single-core CPU,
with the resident set still growing, under both `--predictor sim` and
`--predictor mock` — so the cost is enumeration and compression, not
simulation. Measured on the same cluster: `CandidateGenerator` returns **90
templates in 0.0 s**, and enumerating their embeddings is what does not
terminate quickly. The earlier estimate in this table was "~60 s", which was a
guess and is now struck.

The reason is structural rather than a bug: this node is **one island of eight
peer-capable devices** with `max_tp_candidates = [1, 2, 4, 8]` and P/D enabled,
so the placement space is far larger than any toy fixture's (E-G1b's are 528
and 288 embeddings; E-G7's 64-device holdout was 36,480). It is the same
scaling E-G6 measured, met on real hardware.

Three levers exist and the choice between them is a research decision, not a
scheduling one, so it is recorded rather than taken silently:

- `--max-embeddings-per-template` bounds the space, and the bound must be
  reported: capped enumeration makes untouched placements
  `unknown_measurement`, never `excluded_by_scope`.
- **Plan once per condition, not once per repetition.** The three reps of a
  condition differ only in the bench seed, so they share a plan. This alone
  divides the planning cost by three and changes no result.
- `--no-enable-pd` would cut it hard and is **not** acceptable: P/D is the
  research question.

**Until this is resolved the measured deployment cost stands and the planning
cost does not**, so no total for the full matrix is quoted here. Quoting one
built on a stage that has never finished would be inventing the number this
table exists to avoid.

### What the deployment side costs, now that it is measured

At ~140 s per deployment including engine start and teardown:

- 108 Llama deployments = **4.2 h**
- 108 Qwen deployments, at an estimated 4x for 61 GB of weights = **17 h**
- **Deployment total ~21 h**, plus planning, plus re-runs of any condition
  whose recorded occupancy or load average shows contamination.

### The reduced plan

Drop the load-level axis from 3 to 2 (low and high — the knee itself is the
least informative of the three, because that is where variance is highest and
three repetitions cannot resolve it):

**2 x 2 x 3 x 2 x 3 = 72 conditions -> 144 deployments, ~14 h of deployment.**

If that is still too long the next cut is **Qwen3-32B**, not repetitions.
Repetitions are what make a number a measurement: `docs/nodes/a40.md` records
two runs of one parallel trial disagreeing by 38 %. Dropping to Llama only is
**36 conditions -> 72 deployments, ~2.8 h** and costs one model, which the
table can say plainly; dropping repetitions costs the meaning of every row.

### The load levels, measured

`deploy_and_bench.py` refuses to run without `--knee-rps` because a guessed
knee puts `low`, `knee` and `high` on three loads that are not those things.
Measured for Llama-3.1-8B at TP=2 on devices (0,1), 150 requests, the same
requests re-spaced at each rate:

| target rps | achieved | p50 TTFT ms | p99 TTFT ms | p99 TPOT ms |
| --- | --- | --- | --- | --- |
| 0.5 | 0.479 | 84.3 | 277.6 | 19.89 |
| 1 | 0.957 | 89.4 | 289.5 | 22.52 |
| 2 | 1.914 | 114.5 | 305.0 | 30.62 |
| 4 | 3.829 | 176.0 | 414.4 | 51.00 |
| 6 | 5.743 | 223.0 | **12690.5** | 51.56 |

p99 TTFT rises 4 % , 5 % and 36 % across the first four steps and then **30x**.
The knee is between 4 and 6 rps, so **knee = 4**, low = 2, high = 6.

This also dates the earlier placement runs: they replayed the stock
`sharegpt-llama-3.1-8b-300-sps10.jsonl` trace, which is **2.5x the knee**.
Every p99 TTFT there was ~51 s and almost all of it queueing. Those runs are
kept and labelled as the saturated point; they are not the whole story, and the
grid above covers the three registered levels.

---

## 4. Preconditions, checked by the harness and not by memory

`deploy_and_bench.py` refuses to deploy unless all of these hold, and writes
them into every raw record:

- **No other tenant holds any GPU.** `nvidia-smi --query-compute-apps` before
  and after, with the owner of each pid. A figure measured beside another
  tenant is not wrong — it is measured under a condition the `REAL HARDWARE`
  banner does not state. Registered as an E-G5 precondition in
  `docs/preregistration.md`.
- **`os.getloadavg()` before and after.** This box idles near 1.0 with no
  tenant and near 9 with one; E-G6's grid was contaminated twice, and the
  lesson recorded there was that contamination which is only remembered does
  not survive into the data.
- **Node serials** from `scripts/whichnode.sh` — the `accel serials` line,
  which identifies the machine. The `detected node` line is a node *kind* and
  identifies nothing.
- **`git -C vendor/heteropilot status --porcelain` is empty.** A result
  produced against an edited submodule is not a result about heteropilot.

---

## 5. What the analysis may and may not do (P3.4)

- Calibration uses the **existing** accuracy domain only
  (`profiles/calibration/a40.accuracy.yaml`, opt-in via
  `plan --accuracy-domain`). **No new domain may be created from this data**,
  and no existing one may be widened to fit it. That is the circular
  evaluation the work order forbids: a margin fitted on E-G5 cannot then be
  tested by E-G5.
- The eight E-G4 raw files are the **fitted set** for the contention model's
  topology declaration (`docs/preregistration.md`, change-log row 2) and are
  excluded from E-G5's validation. E-G5 measures served TTFT and TPOT, not bus
  bandwidth, so this costs nothing.
- A recommendation that violates its SLO is **recorded as a violation**, with
  the candidate causes named (prediction error · contention model · the
  engine's scheduler) and not resolved by picking whichever is most flattering.
