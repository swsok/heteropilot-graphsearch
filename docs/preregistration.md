# Pre-registration

**Append-only.** An entry is written *before* the experiment it describes runs,
and it is never edited afterwards. If a criterion turns out to be wrong, a new
entry supersedes it and says which entry it supersedes; the superseded entry
stays exactly as it was. The change log at the bottom records every addition.

This exists for one reason: a success criterion chosen after seeing the numbers
is not a criterion. The work order's rule 4 binds this file and rule 6 binds
what happens when the result disagrees with the hypothesis — it gets written
down as it came out, with the paper's focus moved the way §12 of the research
design says to move it.

**Most entries here register no numeric target at all, on purpose.** Where the
research design says a figure has to come from a pilot, or where there is no
basis today for choosing one, the metric is listed as **report-only**: it is
measured, tabulated and discussed, and no pass/fail is claimed from it. A target
invented to have one would be a criterion chosen for the comfort of having a
criterion.

What *is* registered as a threshold is registered because something outside this
file fixes it — the correctness invariant (research design §11), a §12 failure
condition, or a measured error range from heteropilot. Each one carries its
**근거 (basis)** line saying which.

Registered 2026-09-28, before E-G3 ran. Experiment ids E-G3 through E-G7 are
claimed for this file; E-G1, E-G1b and E-G2 are spent (`experiments/results/`).

---

## Common — the correctness invariant

Across **every** experiment in this file, under every arm, every fixture and
every budget:

```
false_infeasible = 0
mismerged_pairs  = 0
```

- **`false_infeasible`** — a candidate some stage of this search called
  `impossible_proven` which the oracle then found feasible. A pruning stage is a
  *relaxation* of the feasibility test: it may reject only when the most
  optimistic arithmetic already misses a constraint the spec declares. One
  non-zero here means a bound is not a relaxation, which is a defect in the
  claim, not a tuning parameter.
- **`mismerged_pairs`** — two placements folded into one equivalence class that
  the oracle prices differently. Exact equivalence is proved by VF2, never by
  hash alone; a non-zero here means the signature lost a property the metrics
  depend on.

**If either is non-zero, the run stops and is reported.** The test is not
relaxed, the labelling is not loosened, and the number is not explained away in
a footnote. This is rule 5 of the work order, and it is the reason every other
number in this repository is worth reading.

**근거.** Correctness is not a target; it is a *condition* (research design
§11). A target is something a result may fall short of and still be a result.
These two may not, which is why they are registered once here rather than
restated as a threshold in each entry below.

`unevaluated` is not `infeasible`. The five states — `impossible_proven`,
`excluded_by_scope`, `deferred_heuristic`, `unknown_measurement`, `evaluated` —
never merge, in any table this file governs. A budget is a property of the
search, not of the hardware.

### Known limitations at registration time

Carried forward from G15 (GS-12), recorded here so no later entry can present
them as new findings:

1. **The corrected ranker does not beat heteropilot's surrogate at k=4.** On the
   two holdout fixtures it ties on `graph-toy-asym` (0.2 vs 0.2) and trails on
   `heterogeneous-lab` (0.25 vs 0.375). It overtakes at k=8 on both and is alone
   at recall 1.0 on the lab at k=16. Any claim about the ranker that does not
   name the k it holds at is out of bounds.
2. **A recommendation does exist at k=4** on all three binding-spec fixtures
   (`graph-toy-abcde`, `graph-toy-shared-nic`, `graph-toy-asym`, spec
   `*-tight.yaml`), verified at 96a3e87 before this file was written. The
   pre-G15 failure the E-G2 diagnosis describes — nothing recommended at k=4 —
   is fixed and is not a live limitation. The ranker is not to be touched again
   for any result in this file; `--ranker service_margin_v1` stays available as
   the baseline every claim about the correction is measured against.
3. **Every fixture in this repository is fictional** unless its header says
   otherwise. A result computed from one is a result about the search, never a
   measurement of hardware.

---

## E-G3 — the real simulator as oracle

*Registered 2026-09-28, before any `--predictor sim` run of this search.*

### Hypothesis

Exact equivalence compression and the bound-based elimination preserve the
oracle's answer **when the predictor is LLMServingSim rather than the mock**.
Everything published so far (E-G1, E-G1b, E-G2) was produced against a
deterministic mock which respects the same physics as the bounds — which is what
makes a disagreement meaningful, and also what makes it a weaker test than the
real simulator, whose behaviour the bounds do not get to define.

Specifically: with the real simulator in place of the mock, on the three
fixtures below, `false_infeasible` and `mismerged_pairs` stay 0 and the
wall-time saving is non-negative. The compression ratio is expected to land near
E-G1's, since it is a property of the graph and the enumerated space rather than
of the predictor — but that expectation is **not** a criterion below, only a
thing worth noticing if it fails.

### Fixtures

| fixture | why it is in the corpus |
| --- | --- |
| `graph-toy-abcde.v2` | §9's worked example; the compression ratio the design predicts |
| `graph-toy-shared-nic.v2` (3 nodes) | the counterexample: two placements alike in everything but the contended uplink they cross |
| heteropilot `heterogeneous-lab` | not written for this search; the nearest thing to an out-of-sample cluster available before P3 |

Arms: **oracle** (every embedding simulated; no compression, no bounds, no
top-K) and **proposed** (exact compression + bounds + adaptive, K = every
representative, so the comparison isolates compression and bounds rather than
the budget).

### Metrics

- the two correctness numbers (above);
- `compression_ratio` = representatives / embeddings;
- `sims_oracle`, `sims_proposed`;
- `feasible_recall`, `cost_regret`;
- `saving = t_sim_oracle − (t_sim_proposed + t_hash + t_vf2 + t_bounds)`, from
  `SearchAudit.timings`. The compression's own cost is charged to the
  compression, which is the only way the saving means anything;
- cache behaviour: on a rerun of the identical command, `cache_hits ==
  simulations_run`, and the number of cache files equals the number of
  representatives evaluated.

### Success criterion

1. **The invariant holds on all three fixtures.** Not a target — a condition.
2. **`saving ≥ 0`** on every fixture, where
   `saving = t_sim_oracle − (t_sim_proposed + t_hash + t_vf2 + t_bounds)`.
   That is: the time spent compressing and eliminating did not exceed the
   simulation time it bought back.

**Report-only, no target:** compression ratio, `feasible_recall`, `cost_regret`,
`sims_oracle`, `sims_proposed`, and the cache behaviour. They are tabulated and
discussed; no pass or fail is claimed from any of them.

**근거.** A compression-ratio target is exactly what research design §12 says
to register *after* the pilot ("수치 개선 목표는 파일럿 후 별도 사전 등록"), so
registering one now would be inventing it. `saving < 0` is different: it is one
of §12's three named failure conditions — *the isomorphism check costs more than
the simulation it saves* — so the threshold is not chosen here, it is read off
§12. It is the only criterion in this entry that is not the invariant.

### Failure interpretation

- **Either correctness number non-zero** → stop, diagnose, report. E-G3 provides
  `--diagnose-pair a b`, which re-simulates the pair under the same node
  ordering: if the two runs of the *same* placement differ, the cause is
  simulator non-determinism (instance numbering, `config_builder` ordering) and
  the finding is about the harness; if they agree and the pair still differs,
  the equivalence relation is wrong and the finding is about the contribution.
  The md says which, in those words.
- **`saving < 0` on any fixture** → §12's second named failure condition, *the
  isomorphism check costs more than the simulation it saves*. The registered
  response, chosen now rather than after seeing the number: **the result md
  carries the proposal to demote exact compression from a contribution to a
  cache key and to move the paper's focus onto the contention model and the
  adaptive search.** Recorded in `docs/decisions.md` as a GS-n, not quietly
  absorbed. `graph-toy-asym` is the designed ratio-1.0 fixture and is expected
  to save little; it is still held to `saving ≥ 0`, because a compression that
  folds nothing should also cost nothing much.
- **Recall below 1.0 at K = all** → the bounds rejected something the oracle
  kept, which is case one wearing different clothes. Reported as such even
  though recall itself carries no target.

---

## E-G4 — the shared-resource contention model, against a microbenchmark

*Registered 2026-09-28, before `FluidContentionModel` was written and before any
microbenchmark was run.*

### Hypothesis

A processor-sharing ("fluid") model of a shared resource — at any instant the
active flows on a resource split `capacity − reserved` equally, and a flow's
rate is the minimum over the resources on its path — predicts measured transfer
time on real hardware materially better than the `null` model this repository
has used so far, which prices every flow as if it had the path to itself.

The null model is not a placeholder that was quietly improved: it is the model
E-G1, E-G1b and E-G2 were computed under, and results from the two models may
not be compared without saying which produced which. Both are named in every
record.

### Conditions

Five, each at both locations, over a message-size grid of 1 MiB to 256 MiB
doubling, ≥10 repetitions:

| # | condition |
| --- | --- |
| 1 | a single transfer |
| 2 | two flows over the **same** NIC / uplink |
| 3 | two flows over **independent** NICs / uplinks |
| 4 | bidirectional |
| 5 | a collective, varying participant count and size |

Locations: **(a)** within one A40 node, sharing the PCIe uplink; **(b)** between
nodes, sharing the NIC. Background load where the condition calls for it: a
separate process holding the same uplink at a target occupancy of 60 %.

Every figure is recorded as a heteropilot `LinkMeasurement` — `collective`,
`world_size`, `msg_size_class`, `binding`, `bus_bw_gbps`, `method`, `msg_bytes`,
`date`, `raw` — because each of those fields is a condition the number holds
under, and a figure that does not state a condition cannot be used to refuse a
deployment.

### Metrics

Transfer-time prediction error, `|predicted − measured| / measured`, reported at
p50 and p90 over the grid, separately for the null model and the fluid model,
separately per location and condition.

### Success criterion

Three, all on the transfer-time prediction error `|predicted − measured| /
measured`:

1. **Shared conditions** (two flows over one NIC or uplink; the background-load
   conditions): the fluid model's error is **p50 ≤ 15 %, p90 ≤ 30 %**.
2. **Independent conditions** (separate NICs or uplinks, no contention): the
   null and fluid models differ by **≤ 5 %**. This asks whether the model adds
   nothing where there is nothing to add.
3. **Under the shared conditions the fluid model's error is smaller than the
   null model's.** A model that meets (1) without beating the model it replaces
   has not earned its place.

**근거 (basis) for 15 / 30.** They are the same order of magnitude as the
simulator's own measured error: heteropilot D29 records the LLMServingSim TPOT
error on the RNGD card at **+11.6 % at served concurrency 3.9 and −18 % at 76**.
The claim being registered is therefore modest and checkable — *a transfer-time
model must not be worse than the simulator it feeds*. Nothing about 15 and 30 is
derived from the physics, and they are not tuned to anything measured here.

**근거 for the ≤ 5 % in (2).** Conditions 1 and 3 have no contention, so the two
models are the same arithmetic; a difference there is an implementation defect,
not evidence about contention. Five per cent is slack for measurement noise, not
for modelling.

**These three values are provisional and are re-registered after a one-shot
pilot** — one location, one message size — appended to the change log below with
its date and its numbers. If the pilot shows 15 / 30 to be the wrong order of
magnitude for this hardware, the new entry says so and supersedes this one; the
pilot's own data is then listed as fitting data and excluded from E-G5.

### Failure interpretation

- **The fluid model does not beat the null model** → the contention model is not
  a contribution and does not enter the paper as one. The `--contention` flag
  stays, defaulting to `null`, and the limitation is stated: this search does
  not model shared-resource contention, which is precisely what
  `TopologyLossReport` already reports on every plan.
- **Both models are far off** → §12's third named failure condition, *path-model
  error dominates the ranking differences*. Registered response: the paper
  narrows to exact compression plus the adaptive budget, and the contention work
  is reported as a negative result with its numbers.
- **The model had to be changed to fit the data** → allowed, once, and only with
  both of: a `GS-n` in `docs/decisions.md` saying what changed and why, and a
  change log entry *here* listing every raw data file used to fit it. Those
  files are then **excluded from E-G5's validation set**. A model validated on
  the data that shaped it measures nothing.

---

## E-G5 — real hardware

*Registered 2026-09-28, before any deployment.*

### Hypothesis

The placement this search recommends meets the service's SLOs on real hardware,
and the boundary alternative it ranks just below the recommendation does
measurably worse — and, in the shared-uplink condition specifically, two
placements that differ *only* in which contended uplink they cross differ
measurably in TTFT. That last one is the research counterexample, measured.

### Matrix

2 models × 2 load patterns (steady, burst) × 3 topology conditions × 3 load
levels × 3 repetitions = 108 conditions, each deployed twice (the recommendation
and one boundary alternative) = 216 deployments. The reduced plan, if equipment
time does not allow it, is 2 load levels → 144 deployments; which plan was run
is stated in the result file.

Topology conditions: (i) single node, aggregated; (ii) across nodes, P/D on
independent uplinks; (iii) across nodes, P/D sharing one uplink with 60 %
background load.

**Boundary alternative** is defined here, before the data: the
next-ranked `feasible` candidate whose `risk_proxy` is closest to 1, **plus**
the `impossible_proven` candidate that missed its bound by the smallest margin.
The second one is the point: deploying it tests whether the lower bound was
actually safe. It is `false_infeasible`, adjudicated by hardware rather than by
the oracle.

### Metrics

Predicted vs measured p99 TTFT, p99 TPOT and goodput; SLO attainment; per-request
logs; the provenance block of the plan that produced each deployment. Measured
percentiles use heteropilot's `planner/util/percentile.py` (linear
interpolation), median of 3 repetitions with the range reported — never a single
trial, which heteropilot's own node documentation records disagreeing by 38 %
between two runs.

### Success criterion

**(a) Report-only, no target.** The fraction of conditions in which the
recommended placement simultaneously meets p99 TTFT, p99 TPOT and
`slo.min_goodput_rps` on hardware. It is the headline number and it carries no
threshold, because there is no basis today for choosing one; a figure like
"≥ 90 %" registered now would be a number picked to be met.

**(b) 100 %, and this one is a criterion.** Of the boundary candidates that were
rejected as `impossible_proven` and then deployed anyway, **every one must in
fact violate the constraint it was proved to violate.** A single one that meets
its SLOs on hardware means the lower bound that rejected it was not a
relaxation, and that bound is **demoted to a heuristic** — moved out of
`impossible_proven` and into `deferred_heuristic` — with a GS-n recording it.

**(c) Report-only, with one exception.** The relative error between predicted
and measured p99 is tabulated, not scored. The exception: for a condition that
falls inside an existing accuracy domain, an error outside that domain's own
stated range is marked **"prediction failure"** in the table. The domain made a
claim about its error; exceeding it is that claim failing, and is reportable
without any new threshold being invented.

**근거.** (a) has no basis for a number, so it gets none. (b) is the hardware
edition of the common invariant — `false_infeasible = 0` adjudicated by a
deployment instead of by the oracle — and an invariant does not come in
percentages, so 100 % is not a chosen target but the only value it can take.
(c) re-uses a bound that already exists rather than adding one.

### No circular evaluation

Calibration uses **existing** accuracy domains only. No new accuracy domain is
fitted from E-G5's data, and no data file listed in E-G4's change log as used
for model fitting may be used here. A predictor tuned on the data it is then
validated against reports its own tuning, and this rule is what stops the paper
claiming it measured something.

### Failure interpretation

A recommendation that violates an SLO is **recorded with its numbers**. Under
(a) that is a datum, not a verdict — but it is reported together with the
candidate causes, separated as far as the data allows: prediction error (compare predicted vs measured for that same
placement), contention model (does the fluid model's prediction differ, and in
which direction), scheduler (does the measured p99 move with load level in a way
the model does not). No cause is asserted without the comparison that
distinguishes it.

---

## E-G6 — scalability

*Registered 2026-09-28, before the synthetic generator was written.*

### Hypothesis

The search's wall time grows acceptably with cluster size, and the compression
that makes it affordable is a function of cluster *symmetry* — so the honest
result is a curve per symmetry level, not a single number.

### Grid

`graphsearch/synth/cluster_gen.py`, everything `source: placeholder`:
{32, 64, 128} devices × symmetry {0, 0.5, 1} = 9 clusters, fixed seeds recorded
in the result file. Load: 3 levels from heteropilot's `workloads/generators`,
each trace headed by the line saying it is synthetic. Predictor: mock for all
nine; **one** condition (32 devices, symmetry 1) additionally under
`--predictor sim` with the cache, to anchor the mock curve to something.

### Metrics

Wall time; VF2 seconds; compression ratio; the count of representatives in
`excluded_by_scope` under `--max-embeddings-per-template N`; simulations run.

### Success criterion

**None. Every metric in this entry is report-only**: wall time, VF2 seconds,
compression ratio and the `excluded_by_scope` count, each per device count and
per symmetry level.

**근거.** An absolute wall-time target — "128 devices within 30 minutes" —
is a statement about the machine it ran on, not about the search. The same code
on a different node would pass or fail the same threshold for reasons that have
nothing to do with the contribution. The curve is the result; a line drawn
across it would be decoration.

What *is* registered is the failure condition below, because §12 fixes it.

### Failure condition, stated in advance

**`saving < 0` at `symmetry = 1`** fires §12's first named failure condition.
Symmetry 1 is the most favourable case the generator can produce — every node
identical, so the compression has the most to fold — and a compression that
cannot pay for itself there cannot pay for itself anywhere. The registered
response is E-G3's: exact compression is demoted to a cache key and the paper's
claim narrows to the contention model and the adaptive budget.

`ratio ≈ 1` at `symmetry = 0` is **not** a failure. It is the designed
behaviour of an asymmetric cluster — no two placements can be isomorphic — and
it is in the grid so the number gets reported rather than avoided. The boundary
of where the contribution applies is a result about the contribution.

A simulation result at this scale is **never** presented as large-scale hardware
accuracy validation. §12 says so; it is repeated here because the temptation is
real and the number would look good.

---

## E-G7 — holdout, ablation, and baseline fairness

*Registered 2026-09-28. The holdout set is fixed **now**, before P4 runs and
before any of it is looked at.*

### The holdout set, fixed at registration

Two fixtures, neither of which may be inspected, tuned against, or used to
choose any parameter before E-G7 runs:

1. **`synth-holdout-1`** — from `graphsearch/synth/cluster_gen.py` with
   `--nodes 8 --devices-per-node 8 --symmetry 0.25 --seed 20260923`. Symmetry
   0.25 is *not* in E-G6's {0, 0.5, 1} grid and the seed is not among E-G6's;
   neither the generator's defaults nor any E-G6 curve may be fitted to it.
2. **`real-<lab>-holdout.v2`** — the P3 hardware fixture with exactly one
   change: the uplink reservation on one node altered from its measured value.
   The variant is derived mechanically from the committed real fixture; the
   change is a single field, recorded in the result file, so that what is being
   held out is the *topology condition* and not a different cluster.

No ranker, no δ, no bound and no threshold is modified after this point on the
basis of anything seen in either. Table format follows E-G1b.

### Ablation arms

| arm | what it removes |
| --- | --- |
| `full` | — (the search as it ships) |
| `no_boundary` | `include_boundary=False` — the signature stops carrying the shared-resource boundary |
| `no_compression` | `--compression off` |
| `no_bounds` | `--bounds none` — the *relaxations*; compat and memory are exact checks and stay |
| `ranker=binned` | heteropilot's `BinnedRooflineRanker` |
| `ranker=service_margin_v1` | the pre-G15 estimate |
| `no_diversity` | `DiversityQuota` off |
| `contention=null` / `contention=fluid` | the two models, everything else held |

Columns: the two correctness numbers, compression ratio, simulations,
`feasible_recall`, `cost_regret`, `first_feasible_at_sim`.

### Registered prediction

**`no_boundary` produces `mismerged_pairs > 0` on `graph-toy-shared-nic.v2`.**
This is the direct evidence for contribution A — that the equivalence relation
must carry the shared boundary — and it is registered as a prediction *before*
the arm runs so that its confirmation is a test and not a demonstration. The
appendix carries the offending pair's ids and their TTFTs.

This is the one arm where a non-zero `mismerged_pairs` does **not** stop the
experiment: it is the arm whose whole purpose is to produce one, by removing the
property that prevents it. Every other arm is bound by the common invariant.

### Baseline fairness

heteropilot's own `search(surrogate=BinnedRooflineRanker, top_k)`, its `oracle()`
and a greedy baseline, run over the **same** candidate space, the same predictor
and the same cache. Two things stated in the paper, not buried:

- heteropilot's arm ranks and judges **templates**, not placements, so one
  verdict is credited to every placement of that template. That is generous to
  the baseline, deliberately, because it cannot name a placement and there is no
  stricter reading that would be fair to it.
- heteropilot's `docs/surrogate_topk_regret.md` documents cases its Top-K misses
  even at K=50. Those are reproduced here rather than cited, because a baseline's
  weakness quoted from its own repository is not evidence.

### Success criterion

1. **The invariant holds on both holdout clusters.** A condition, not a target.
2. **The `no_boundary` arm shows `mismerged_pairs > 0` where `full` shows 0.**
   This is the existence proof for contribution A: removing the shared boundary
   from the signature must actually merge two placements the evaluator prices
   differently. A zero here does **not** vindicate the contribution — it means
   the holdout contains no structure in which the counterexample is reachable,
   and the registered response is to **re-examine the holdout selection**, say
   so in the result file, and report contribution A as unsupported by these
   fixtures.
3. **`full` arm `feasible_recall` at k = 16 ≥ heteropilot arm's at k = 16.**
   Equal counts as met.

**Report-only:** recall at k = 4 and k = 8, `cost_regret`,
`first_feasible_at_sim`, compression ratio, and the simulation counts.

**근거 for pinning it at k = 16.** E-G1b is where this arm reached recall
1.0, so k = 16 is the operating point the claim is actually about. At small K
the corrected ranker ties on one holdout fixture and trails on the other (the
known limitation recorded at the top of this file), and that may well survive
the G15 correction — registering a small-K target would be registering a result
already known to be in doubt. The claim being made is about the larger budget,
and this is it, stated before the run rather than chosen from the table.

### Failure interpretation

- **The holdout's recall is materially worse than the diagnosis fixtures'** →
  the ranker was fitted to the diagnosis corpus. Reported as such; the claim
  about the ranker narrows to those fixtures.
- **`no_boundary` shows `mismerged_pairs = 0`** → the counterexample is not
  reachable in these fixtures, which makes contribution A unsupported by this
  experiment. The registered response is criterion 2's: re-examine the holdout
  selection, look for a fixture in which the structure is reachable, and report
  that the ones chosen did not contain it — never to declare the contribution
  safe because nothing broke.

---

## Change log (append-only)

| # | date | what changed | why |
| --- | --- | --- | --- |
| 1 | 2026-09-28 | **Initial registration.** The common invariant, the known limitations, and E-G3 through E-G7 with every criterion and its 근거. **E-G4's 15 / 30 / 5 and E-G5(a) are to be appended after their pilots.** | P0.4 of `WORK_ORDER_paper.md`. Written before E-G3 ran, and before `FluidContentionModel`, the synthetic cluster generator and the E-G7 arms existed. Most metrics are registered as report-only on purpose: research design §12 says numeric improvement targets are registered *after* the pilot, so inventing them now would defeat the point of registering anything. |
