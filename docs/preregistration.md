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

**Numeric targets marked `[user to confirm]` are not yet registered.** An
experiment whose target is still a placeholder may be *run*, and its numbers
reported, but its verdict line reads `undecided (target not registered)` — never
"passed". Filling one in is an append-only change log entry with a date.

Registered 2026-09-23, before E-G3 ran. Experiment ids E-G3 through E-G7 are
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

*Registered 2026-09-23, before any `--predictor sim` run of this search.*

### Hypothesis

Exact equivalence compression and the bound-based elimination preserve the
oracle's answer **when the predictor is LLMServingSim rather than the mock**.
Everything published so far (E-G1, E-G1b, E-G2) was produced against a
deterministic mock which respects the same physics as the bounds — which is what
makes a disagreement meaningful, and also what makes it a weaker test than the
real simulator, whose behaviour the bounds do not get to define.

Specifically: with the real simulator in place of the mock, on the three
fixtures below, `false_infeasible` and `mismerged_pairs` stay 0, the compression
ratio is within measurement noise of E-G1's, and the wall-time saving is
positive.

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

1. `false_infeasible = 0` and `mismerged_pairs = 0` on all three fixtures.
   **Not negotiable and not a target — an invariant.**
2. `feasible_recall = 1.0` in the proposed arm at K = all representatives.
3. `saving > 0` on at least the two fixtures whose compression ratio is below
   1.0 (`abcde`, `shared-nic`). `asym` is the designed ratio-1.0 case and is
   expected to save nothing; a negative saving there is reported, not excused.
4. Compression ratio within `[user to confirm: e.g. ±0.05 absolute]` of E-G1's
   mock-predictor figure for the same fixture. *The ratio is a property of the
   graph and the enumerated space, not of the predictor, so a difference here
   means the sim run enumerated something different and is a bug, not a
   finding.*

### Failure interpretation

- **Either correctness number non-zero** → stop, diagnose, report. E-G3 provides
  `--diagnose-pair a b`, which re-simulates the pair under the same node
  ordering: if the two runs of the *same* placement differ, the cause is
  simulator non-determinism (instance numbering, `config_builder` ordering) and
  the finding is about the harness; if they agree and the pair still differs,
  the equivalence relation is wrong and the finding is about the contribution.
  The md says which, in those words.
- **`saving ≤ 0` on a compressible fixture** → this is §12's second named
  failure condition, *the isomorphism check costs more than the simulation it
  saves*. The registered response is the one §12 gives: demote exact compression
  from a contribution to a **cache key**, and move the paper's focus onto the
  adaptive search under a simulation budget. Recorded in `docs/decisions.md` as
  a GS-n, not quietly absorbed.
- **Recall below 1.0 at K = all** → the bounds rejected something the oracle
  kept, which is case one wearing different clothes.

---

## E-G4 — the shared-resource contention model, against a microbenchmark

*Registered 2026-09-23, before `FluidContentionModel` was written and before any
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

`[user to confirm]`. The work order's own illustration is **p50 ≤ 15 %, p90 ≤
30 %** for the fluid model, with the null model's error strictly larger under
conditions 2, 4 and 5 (the conditions in which contention exists at all). Until
a number is entered here by the user in the change log below, E-G4's verdict
line reads `undecided (target not registered)`.

Under conditions 1 and 3 the two models are expected to agree exactly, by
construction. That is a *check on the implementation*, not evidence for the
model: if they differ there, the fluid model is wrong in a way that has nothing
to do with contention.

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

*Registered 2026-09-23, before any deployment.*

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

`[user to confirm]`, with these shapes:

1. The recommendation meets both SLOs in `[user to confirm: e.g. ≥ 90 %]` of
   conditions where any candidate does.
2. Predicted p99 TTFT within `[user to confirm: e.g. ±25 %]` of measured.
3. **Every** `impossible_proven` boundary candidate that is deployed does in
   fact miss the constraint it was proved to miss. A single counterexample is a
   `false_infeasible` on real hardware and stops the experiment under the common
   invariant above.
4. In condition (iii), the TTFT difference between the X-form and Y-form
   placements is larger than the repetition range of either.

### No circular evaluation

Calibration uses **existing** accuracy domains only. No new accuracy domain is
fitted from E-G5's data, and no data file listed in E-G4's change log as used
for model fitting may be used here. A predictor tuned on the data it is then
validated against reports its own tuning, and this rule is what stops the paper
claiming it measured something.

### Failure interpretation

A recommendation that violates an SLO is **recorded as a failure with its
numbers**, together with the candidate causes separated as far as the data
allows: prediction error (compare predicted vs measured for that same
placement), contention model (does the fluid model's prediction differ, and in
which direction), scheduler (does the measured p99 move with load level in a way
the model does not). No cause is asserted without the comparison that
distinguishes it.

---

## E-G6 — scalability

*Registered 2026-09-23, before the synthetic generator was written.*

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

1. The 128-device, symmetry-1 case completes within `[user to confirm: e.g. 30
   minutes]` wall time on the A40 node.
2. Compression ratio falls monotonically as symmetry rises (ratio 1.0 at
   symmetry 0 is expected and is not a failure).
3. `saving > 0` at symmetry 1 for every size.

### Failure condition, stated in advance

**`ratio ≈ 1` under asymmetry with `saving < 0`** is §12's first named failure
condition — *the cluster is asymmetric, so the compression ratio is low* — and
it is an expected region of the parameter space, not a surprise. It is reported
as the boundary of where the contribution applies. The registered response if it
holds at *every* symmetry level, including 1: exact compression is demoted to a
cache key and the paper's claim narrows to the adaptive budget, the same
response as E-G3's.

A simulation result at this scale is **never** presented as large-scale hardware
accuracy validation. §12 says so; it is repeated here because the temptation is
real and the number would look good.

---

## E-G7 — holdout, ablation, and baseline fairness

*Registered 2026-09-23. The holdout set is fixed **now**, before P4 runs and
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

1. Holdout: correctness invariant holds; recall at matched simulation count is
   no worse than heteropilot's surrogate at `[user to confirm: which k]`.
2. Ablation: `no_boundary` shows `mismerged_pairs > 0` where `full` shows 0.
3. Ablation: `no_compression` shows the same correctness numbers as `full` and
   strictly more simulations. *If it shows the same simulation count, the
   compression is doing nothing on that fixture and the row says so.*

### Failure interpretation

- **The holdout's recall is materially worse than the diagnosis fixtures'** →
  the ranker was fitted to the diagnosis corpus. Reported as such; the claim
  about the ranker narrows to those fixtures.
- **`no_boundary` shows `mismerged_pairs = 0`** → the counterexample is not
  reachable in the corpus as built, which makes contribution A unsupported by
  experiment. The registered response is to say so and to look for a fixture in
  which it is reachable, *reporting that the original corpus did not contain
  one* — not to declare the contribution safe because nothing broke.

---

## Change log (append-only)

| # | date | what changed | why |
| --- | --- | --- | --- |
| 1 | 2026-09-23 | Initial registration: the common invariant, known limitations, and E-G3 through E-G7. All numeric targets marked `[user to confirm]`. | P0.4 of `WORK_ORDER_paper.md`. Written before E-G3 ran and before `FluidContentionModel`, the synthetic generator and the E-G7 arms existed. |
