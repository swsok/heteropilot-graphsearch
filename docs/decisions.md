# Decisions (GS-n)

This repository's own decisions. Anything that changes heteropilot is recorded
there instead, in `docs/deviations.md`, under the `D120–D129` block this work
order claimed — the two logs do not overlap and neither renumbers the other.

Format: number · date · decision · why · what it affects.

---

## GS-1 — two repositories, heteropilot pinned as a submodule · 2026-09-23

**Decision.** The graph search lives here; heteropilot takes only the hook PRs
H1–H3 and is vendored at `vendor/heteropilot`, pinned to
`3e1f7f73d0364afe7db2af30cd4cec1a7d5b5c65` (H4). Imports go one way,
`graphsearch` → `planner`, never back.

**Why.** Two reasons, and the second is the one that decides it.

The physics is not reproducible outside heteropilot: `planner/util/memory.py`
calls upstream's `serving/core/memory_model.py`, and a real prediction needs
`serving/` plus the `astra-sim` submodule. Copying `planner/` alone would get as
far as a mock predictor and no further.

More importantly, heteropilot's golden tests guard the contracts this work
touches — `ServiceSpec`, the `RejectionStage` values, plan-id assignment, the
envelope cache key, the predictor's compile path. Those have to change *inside*
heteropilot, where "the default path is byte-identical" can be proved. A
monkeypatch from here would bypass that proof entirely.

**Precedent.** ScenarioLab, split out the same way on 2026-09-03 (heteropilot
`WORK_ORDER_consolidation.md` STEP 3, `docs/deviations.md` D24): submodule,
`HETEROPILOT_ROOT`, `PYTHONPATH`, one-way import.

**Affects.** Everything. heteropilot is read-only here; a change to it is a PR
there followed by a submodule bump here.

---

## GS-2 — networkx is this repo's dependency, and its version is part of a signature · 2026-09-23

**Decision.** Use networkx (`>=3.2`) for max-flow, VF2 subgraph isomorphism and
Weisfeiler–Lehman hashing. Do not add it to heteropilot (recorded there as
D123). Record the running version in `Signature.tool_version`.

**Why.** heteropilot walks its cluster with a hand-rolled BFS and says what that
does not do (`path_aware=False`, `contention_modeled=False`). The three
algorithms above are not worth reimplementing and are exactly what networkx
provides.

The version is in the signature because **a WL hash is only comparable against
itself**. The same graph hashed by two networkx releases may differ, so an
upgrade can silently re-cut every equivalence class. Without the version in the
key, a cache entry written before the upgrade would be served after it, and the
compression report would describe a partition that no longer exists.

**A cache written under one version is not readable under another**, and that
is the whole point of putting the version in the key: the entry is missed
rather than misread. Anyone carrying an envelope cache across a networkx
upgrade should expect it to go cold, and should prefer that to a hit that
answers about a partition the code no longer computes.

**The floor stays at `>=3.2`, and not by preference.** `networkx>=3.5` needs
Python >=3.11; heteropilot pins 3.10 and this repository's CI matches it, so
raising the floor would make the repository uninstallable rather than
stricter. `tool_version` already does what a higher floor was wanted for.
Raise it the day the interpreter moves. `pyproject.toml` silences the hashing
`FutureWarning` from `networkx.algorithms.graph_hashing` only -- the warning
is correct and already acted on, and scoping it to that module keeps a hashing
warning from anywhere else visible.

**Affects.** `graphsearch/equivalence.py`, `graphsearch/paths.py`,
`requirements.txt`, `pyproject.toml`, the cache signature, and the
reproducibility claim.

---

## GS-3 — replica symmetry is folded by the canonical key, not by construction · 2026-09-23

> **Superseded by GS-25 (2026-09-29).** The premise below — that a counter
> collapsed by construction is "structurally zero" — is wrong: the figure is a
> closed form and can be computed. Kept as written, because a superseded
> decision that has been edited is not a record of what was decided.

**Decision.** `_ordered_groupings` enumerates replica orderings and lets
`canonical_only` collapse them, rather than emitting each partition once by
fixing the lowest device into the first group.

**Why.** Collapsing by construction makes `EmbeddingStats.skipped_symmetric`
structurally zero. A counter that cannot move is not evidence that symmetry was
removed — it is a claim with nothing behind it, and the compression numbers this
work reports are exactly the kind of claim that needs evidence. Enumerating the
orderings makes the count real, and `canonical_only=False` then measures how
much symmetry a cluster had.

The cost is a factor of `replicas!`, paid in building lists rather than in
simulation, which is the cheap side of this pipeline by orders of magnitude.

**Affects.** `graphsearch/embeddings.py`; the `skipped_symmetric` column of
every compression table.

---

## GS-4 — the work order's `dp=2 tp=1 -> 3` reads as `tp=2 dp=2` · 2026-09-23

**Decision.** G5's test asserts 3 for `tp=2 dp=2` and 6 for `tp=1 dp=2`, and
says in its docstring that the work order's example names the other one.

**Why.** For an island of n devices, R replicas of D each, the count is
`C(n, RD) x (RD)! / (D!^R R!)`. On four devices that is 3 for (R=2, D=2) —
partitioning four labelled devices into two unordered pairs — and 6 for
(R=2, D=1). The work order's STEP G5 test (iv) pairs the number 3 with the
parameters `dp=2 tp=1`, which the arithmetic does not support.

Rather than pick one, the test asserts both readings and states the formula, so
a future change to enumeration cannot quietly move the denominator of every
compression ratio.

**Affects.** `tests/test_embeddings.py`. No code change; the enumeration was
already correct.

---

## GS-5 — the bucket key is the prediction key, not the template id · 2026-09-23

**Decision.** `compress` buckets by `(prediction_key, wl_hash, attr_histogram,
tool_version)`, where `prediction_key` is `CandidateConfig.signature()` with the
island ids removed — model, dtype, serving architecture, topology mode and the
vLLM knobs.

**Why.** The work order's STEP G6 specifies `(template.id, wl_hash,
attr_histogram)`. Measured on the §9 fixture, that produces **192 embeddings →
84 representatives**: exactly one per template, because two placements on
different islands are different templates and can never share a bucket. The
saving this work exists to get is precisely that merge — the research design
counts node A and node B as one representative.

It cannot be dropped entirely either. The candidate graph carries hardware,
topology, roles and parallelism, but **not** the knobs, the serving
architecture, the dtype or the model. Two templates differing only in
`max_num_seqs` have identical graphs and simulate differently, so a
signature-only key would merge them — a real mis-merge, of exactly the kind VF2
is there to prevent. `test_knobs_are_in_the_bucket_key_though_not_in_the_graph`
pins it.

With the prediction key the same fixture gives **192 → 42**, ratio 0.219.

**Affects.** `graphsearch/equivalence.py`; every compression ratio this work
reports.

---

## GS-6 — §9's scope is a cross-node TP group, which the planner cannot generate · 2026-09-23

**Decision.** The §9 test asserts the five classes and their multiplicities
`[2,2,4,4,16]`, and states in its docstring that the planner reaches them by a
different route than the research design describes.

**Why.** §9 enumerates "a single TP group over two of the ten accelerators", so
its 45 device pairs include pairs spanning two nodes. heteropilot permits TP
only within an island and islands are node-local (`CLAUDE.md`, *Execution
Island*), so that candidate does not exist.

What the generator produces instead is two single-device replicas across the
two nodes — the same device pair, working together, under the parallelism label
the planner's rules allow. The compression is the same operation on the same
pairs, and all five of §9's rows come out with the multiplicities it states.

The planner's space is also **richer** than §9's illustrative scope: an
intra-node pair exists as `tp=2` (one group) *and* as `tp=1, dp=2` (two
replicas), and those are different candidates with different representatives.
That is why the full count per prediction key is seven, `[2,2,2,2,4,4,16]`, and
§9's subset of it is five.

**Affects.** `tests/test_equivalence.py`; how the §9 numbers should be quoted in
the paper — as a reproduction of the compression, not of the candidate space.

---

## GS-7 — a representative is dispatched under its embedding id, not its template id · 2026-09-23

**Decision.** Anything that hands representatives to
`planner.optimizer.exhaustive.evaluate_candidates` must give each one a
`CandidateConfig` whose `id` is the exemplar's embedding id. G9's driver does
this, and `tests/test_bounds.py` already does.

**Why.** Several representatives routinely share one template — two placements
of the same template with different boundaries are different representatives,
which is the entire point of G5 and G6. Dispatching them under the template id
produces duplicates, and `planner/util/parallel.py` refuses those outright:

    ValueError: predict_all requires unique candidate ids

It refuses for a good reason. Its per-candidate isolation (run directory,
`--run-id`) and its returned mapping both key on `candidate.id`, so duplicates
would race and silently drop a result — a plan built from another
representative's metrics, with nothing in the output to show it.

Found by the G7 relaxation test rather than reasoned about in advance.

**Affects.** `graphsearch/adaptive.py` (G9), `graphsearch/oracle.py` (G12), and
anything else that batches representatives into heteropilot's evaluator.

---

## GS-8 — the MVP adapter cannot express a shared resource, and says so on every plan · 2026-09-23

**Decision.** `compile_embedded` replaces only `link_bw` and `link_latency`
with this placement's path bottleneck, and returns a `TopologyLossReport`
naming every shared resource the config could not express. Any plan whose
report is non-empty carries a caveat. `contention.py` ships an interface and a
null implementation, and the model's name travels in every record.

**Why.** heteropilot's `docs/deviations.md` D3 records that the legacy cluster
config carries no topology graph. For graph search the consequence is sharper
than for the planner: **two placements differing only in whether they cross a
contended uplink compile to the same simulator input**, so the simulator
returns the same prediction for both — and a difference G6 was careful to
preserve is lost at the last step.

A flow-level contention model is out of scope for the MVP. The alternative to
losing the fact quietly is to name it, which is what the report does.

**What this costs a reader.** A `graphsearch` comparison of two such
representatives compares their *bounds and their cost*, not their simulated
performance, because the simulator gave both the same answer. That is a real
limit on what the first paper can claim from simulation alone, and it is why
the contention experiment is listed as work that follows a `ContentionModel`
implementation rather than as something the MVP measures.

**Affects.** `graphsearch/adapter.py`, `graphsearch/contention.py`; the
provenance block of every plan; heteropilot **D124**, which records the same
thing from the other side.

---

## GS-9 — the oracle must see the placement, or the correctness check is vacuous · 2026-09-23

**Decision.** `run_oracle` binds the predictor to every embedding before
evaluating, through `bind_predictor`. `run_proposed` binds each batch the same
way. A predictor with no binding hook is used as-is, and `bind_predictor` is a
named function rather than a silent `getattr` so that weakening is visible.

**Why.** Without it the oracle judges **templates**, not placements: every
embedding of one template gets identical metrics, so two members of a
representative can never disagree and `mismerged_pairs` is structurally zero.
A correctness check that cannot fail is not one, and this one would have
reported success for any equivalence rule at all.

Found while writing G12's ablation test, which produced no mis-merge no matter
what was dropped from the labels.

**And a second finding, recorded because it bounds what G12 can prove.** Even
with the predictor bound, the shared-NIC ablation produces **no detectable
mis-merge**. `include_boundary=False` folds nodeX and nodeY although X holds 6
of its 10 GB/s, and the oracle does not object — correctly, because the uplink
that distinguishes them appears only on the `INGRESS` and `EGRESS` paths, which
are `on_critical_path: "none"`. Its utilisation never reaches a metric.

So the compression keeping those two apart is a **bet on a contention model
that does not exist yet**, not a difference the MVP can demonstrate. The
instrument is therefore tested directly — a representative holding two
placements the oracle judged differently must be reported, with both ids named.

**Retracted 2026-09-23 — the second finding above was wrong.** It is kept, not
deleted, because a retracted conclusion that quietly disappears teaches nothing
about how it was reached. The cause was not a missing contention model. It was
two omissions and one more binding:

1. `grep -rn enable_pd graphsearch tests experiments` returned nothing. The
   `CandidateGenerator` default `enable_pd=False` stood everywhere, so a
   `PD_KV_TRANSFER` flow had never been generated anywhere in the pipeline.
   The only traffic crossing an uplink was `INGRESS`/`EGRESS`, whose critical
   path is `"none"` — which is exactly what the retracted paragraph observed,
   and then generalised into a property of the model.
2. `graph-toy-shared-nic` had two nodes. A P/D candidate between X and Y
   crosses BOTH uplinks whichever way round it runs, so there was nothing to
   compare. The research design's §5 counterexample needs two prefill pairs
   talking to the same third decode partner.
3. `bind_predictor` bound the compile hook and not the result hook, so
   heteropilot's class-default transfer figure stood — and that figure is
   identical for every placement of a template.

With `nodeZ` added, `enable_pd=True`, and both hooks bound, the counterexample
comes out of the current code:

```
oracle p99 TTFT: P-on-X -> D-on-Z  527.6 ms     (MOCK, fictional)
                 P-on-Y -> D-on-Z  470.9 ms
                 SLO taken at the midpoint, 499.3 ms

include_boundary=True : reps=2  mismerged_pairs=[]                  correct=True
include_boundary=False: reps=1  mismerged_pairs=[['pd-nodeX-Z@bd1c59407606',
                                                  'pd-nodeY-Z@ba17b8accbfa']]
                                                                    correct=False
```

The 56.7 ms is the KV handoff crossing a wire with 6 of its 10 GB/s already
taken instead of a free one. Under an SLO between the two figures the oracle
judges them differently, and `tests/test_oracle_agreement.py::
test_dropping_the_boundary_produces_a_mismerge` fails if the ablation stops
merging them, if exact compression starts merging them, or if the handoff stops
being priced over its own path. The SLO is read off the oracle rather than
written into the test, because a threshold that drifts past both TTFTs stops
separating them and goes green for the wrong reason.

So the compression keeping those two apart is **not** a bet on future work. The
reservation arithmetic, the boundary signature and the mis-merge detector were
all already working; what was missing was a flag, a third node, and a hook.

**Affects.** `graphsearch/oracle.py`; what an E-G experiment may claim from a
`mismerged_pairs: 0` row — a zero from a run with no P/D candidates is the
absence of a test, not a pass. See GS-8, GS-11 and heteropilot D124/D125.


---

## GS-10 — the CLI is a second entry point, not a wrapper · 2026-09-23

**Decision.** `python -m graphsearch plan` calls the same functions
`planner plan` calls, in a different order, and prints heteropilot's own render
output followed by a `Graph search:` block. `planner/__main__.py` is not
modified and not wrapped.

**Why.** A wrapper would have to intercept the planner's arguments and its
output, and would then own a format it does not control. Calling the parts
directly keeps heteropilot's CLI exactly as it was — a reader who knows that
output sees it unchanged, and can see precisely what the graph search added
underneath.

**The mock banner is not optional.** `--predictor mock` is the default and
every run prints a banner saying the figures are fictional. The mock respects
the same physics as the bounds, which is what makes an oracle disagreement mean
something, but the distance between a fictional number and a quoted result is
one copy-paste. `experiments/results/` repeats the banner in every report, and
heteropilot's `docs/CLAIMS.md` does not carry any of these numbers.

**`--bounds none` keeps the exact checks.** It turns off the *relaxations* —
`comm_latency` and `throughput_capacity` — and leaves `compat` and `memory` on.
Those two are exact: a candidate that fails them is not a candidate, and
dropping them would not be a looser search but a wrong one.

**Affects.** `graphsearch/__main__.py`, `graphsearch/render.py`,
`experiments/scripts/e_g1_toy_pilot.py`.


---

## GS-11 — graphsearch generates P/D candidates by default · 2026-09-23

**Decision.** Every entry point here — `python -m graphsearch plan`, `compare`,
`oracle.run_proposed`, the pilot script and the test helpers — builds its
templates with `enable_pd=True`. heteropilot's own CLI leaves it off, and that
stays as it is. `--no-enable-pd` restores heteropilot's default for anyone who
wants to compare like with like.

**Why.** The research contribution is a compression that preserves the shared
boundary a placement crosses, and the only traffic a latency target charges for
that can cross a node boundary is the P/D KV handoff. Every other cross-node
flow in the model is `INGRESS`/`EGRESS`, whose critical path is `"none"`. With
P/D off the pipeline generates no such flow, the boundary never reaches a
metric, and the compression has nothing to demonstrate — which is precisely how
GS-9's retracted second finding came to be written.

A default that differs from the vendored repository's is worth stating once
rather than discovering, so it is here and in `__main__._templates`' docstring.

**Affects.** `graphsearch/__main__.py`, `graphsearch/oracle.py`,
`tests/test_oracle_agreement.py`, `experiments/scripts/e_g1_toy_pilot.py`.


---

## GS-12 — the ranker's goodput term divides by an estimate, not by the bound's ceiling · 2026-09-23

**What was wrong.** E-G1b: under a spec whose SLO binds, `AdaptiveSearch` with
the service-margin ranker recommended nothing at k=4 on both fixtures and found
its first feasible candidate at simulation 5. E-G2 (`e_g2_ranker_diagnosis.md`)
diagnosed it on graph-toy-abcde and graph-toy-shared-nic only, with three
hypotheses answered in numbers:

- **H-b — supported, and the cause.** Every false positive in the ranker's
  comfortable band was a `max_num_seqs=32` placement whose `s128`/`s256`
  siblings on the same devices were feasible. `goodput_ratio` divided by the
  bound's optimistic ceiling, which admits as many sequences as the KV cache
  holds and never reads the knob — so it read 0.085 for a placement the mock
  ran at 2.48× its capacity, where queueing drove the TTFT to 5.8× the SLO.
  Confusion matrix on the ranked representatives: tp 8 / **fp 4** / fn 0 / tn 66
  (abcde) and 8 / **4** / 0 / 48 (shared-nic). Goodput residual
  `actual/predicted` p50 5.19, p90 12.86, max 29.09.
- **H-a — premise true, remedy immaterial.** The TTFT estimate is 0 for every
  non-P/D placement against an actual of up to 13.3×, but a prefill roofline
  pass covers at most 4.4 % of that TTFT; the rest is queueing, which is
  utilisation, which is H-b's term. Adding the prefill term alone flips 0
  verdicts.
- **H-c — not supported.** Feasible and infeasible members of the band have the
  same `risk_proxy` to three decimals (0.527 vs 0.526) and the same cost; there
  is no margin gradient a δ-tier could sort on. `DiversityQuota` does not help
  either (0 → 0 feasible in the top four): it spreads over structures, and the
  misclassification is inside one.

**Decision.** `features_for` gains a `variant`. `service_margin` (the default)
divides `goodput_ratio` by `greedy.estimate`'s knob-aware throughput
(`proxy_throughput_tps / output_tokens.p50`) and adds one prefill roofline pass
(weights once + p50 prompt KV, from `memutil`) to the TTFT term; which terms
went in is written into the new `RankFeatures.basis`. `service_margin_v1` keeps
the original terms and is the baseline every claim here is measured against:
`--ranker service_margin_v1` on the CLI, and
`tests/test_ranker.py::test_v1_reproduces_the_pre_g15_order_exactly` pins its
order on shared-nic to a file frozen from `main` at 9751f4f. No constant was
tuned: the correction replaces a denominator with the estimator heteropilot's
own stage-5 physics already computes, and H-c's δ was not introduced because
the data showed nothing for it to sort on.

**The bound keeps the ceiling, on purpose.** A relaxation must be optimistic; a
ranker must guess well. They now disagree by design, in one direction only:
`test_the_corrected_goodput_is_never_more_optimistic_than_the_ceiling` pins that
the ranker never calls comfortable what the ceiling would not — the direction
that would let it rank comfortably what a bound has proved impossible.

**Holdout.** The correction was checked on two fixtures the diagnosis never saw,
with the holdout spec for heterogeneous-lab written before the corrected ranker
ran on it (`e_g2_topk_holdout.md`):

| fixture | k=4 recall v1 → corrected | first feasible at sim | k=16 recall |
| --- | --- | --- | --- |
| graph-toy-asym | 0.1 → 0.2 | 3 → 1 | 0.5 → 0.8 |
| heterogeneous-lab | 0.125 → 0.25 | 3 → 1 | 0.5 → 1.0 |

Both meet the completion condition. Read honestly: at k=4 the corrected ranker
only ties heteropilot's surrogate on asym (0.2) and still trails it on the lab
(0.25 vs 0.375); it overtakes at k=8 on both and is alone at 1.0 on the lab at
k=16. E-G1b re-run: k=4 recall 0.0 → 0.5 and first feasible 5 → 1 on both
diagnosis fixtures; the pre-G15 table is recomputed with `service_margin_v1` at
the bottom of that file on every run rather than pasted.

**The ranker is still a heuristic and still only orders.** Nothing here reaches
a verdict: `false_infeasible` and `mismerged_pairs` are 0 before and after, and
`tests/test_oracle_agreement.py` is the proof that a ranker change cannot move
them — if it ever does, the ranker has leaked into a judgement.

**Affects.** `graphsearch/ranker.py`, `graphsearch/adaptive.py::build_ranker`,
`graphsearch/oracle.py::run_proposed`, `graphsearch/__main__.py` (`--ranker`),
`experiments/scripts/e_g1b_topk.py`, `e_g2_ranker_diagnosis.py`,
`e_g2_topk_holdout.py`, `fixtures/service_specs/heterogeneous-lab-llama31-8b-tight.yaml`.


---

## GS-13 — `plan` judged templates, because it never bound the predictor · 2026-09-23

**What was wrong.** `graphsearch/oracle.py` built its `AdaptiveSearch` with
`bind_embeddings=` and `embedded_pd_cost=`; `graphsearch/__main__.py::cmd_plan`
built one with neither. So `compare` told the predictor which devices each
candidate ran on and `plan` did not, and the two answered different questions
from the same fixtures:

- with no binder, `AdaptiveSearch._evaluate` skips the bind entirely, so the
  predictor sees a `CandidateConfig` and nothing else. Every embedding of one
  template gets the same metrics.
- that is exactly the condition GS-9 was retracted over. Two placements alike
  in every local attribute and differing only in which contended uplink they
  cross come back identical — the one distinction the equivalence relation
  exists to preserve, lost at the last step, in the entry point a reader is
  most likely to run.
- the P/D handoff fell back to heteropilot's class default, which is a property
  of the template and not of the path, so `--k-schedule` runs of the
  counterexample fixture could not have produced the counterexample.

Nothing detected it because nothing printed it. `E-G1`, `E-G1b` and `E-G2` all
go through `oracle.run_proposed`, which was correct; only the CLI was affected,
and the CLI's output has no number in it that a binder would visibly move on the
abcde fixture.

**Decision.** `cmd_plan` installs the same binder `run_proposed` installs, via
`oracle.binder_for` and `oracle.prices_pd_on_the_path` — the same two functions,
made public rather than reimplemented, so the two entry points cannot drift
again. `oracle._binder` and `oracle._prices_pd_on_the_path` are renamed; they
had no callers outside that module.

**And the reason it was invisible is fixed too.** `adapter.bind` now counts what
its hooks did — `batches`, `bound`, `compile_seen`, `compile_applied`,
`result_seen`, `result_applied` — cumulatively across every batch, and
`SearchAudit.hook_calls` carries them into `provenance.graph_search` and into
the rendered block. `compile_applied == 0` against the real simulator is the
signature of this defect, and `experiments/scripts/e_g3_smoke.sh` fails on it by
name. Against the mock, `compile` stays 0 by design — the mock reads the
placement directly and never asks for a simulator config — so `bound` is the
number that answers the question there, and all four are printed rather than
summarised into a verdict.

`SearchAudit` also gains `topology_loss`, summarising every
`TopologyLossReport` the compile hook produced: how many representatives were
compiled, how many lost a shared resource, which resources, which flows were
priced analytically, and the contention model's name. An empty dict is a real
answer (nothing was compiled); an absent key would be indistinguishable from a
run that dropped a shared resource silently.

**Affects.** `graphsearch/__main__.py`, `graphsearch/oracle.py`,
`graphsearch/adapter.py`, `graphsearch/adaptive.py`, `graphsearch/render.py`,
`tests/test_cli.py`, `tests/test_adapter.py`,
`experiments/scripts/e_g3_smoke.sh`.


---

## GS-14 — `--predictor sim` is reachable, and only from the simulator's own venv · 2026-09-23

**What was wrong.** `--predictor sim` raised `SystemExit` unconditionally. The
first branch explained that `vendor/heteropilot/.venv` did not exist; the second
explained that the run had to be launched through it — and the second ran even
when it had been. There was no code path to a real simulator at all, so P1's
"run the same correctness check under LLMServingSim" had nothing to run.

**Decision.** `_require_the_simulator_venv` separates the two failures, because
the fix differs: build the venv, or relaunch through it. The second check is
`Path(sys.prefix) == vendor/heteropilot/.venv`, and it is not pedantry — since
heteropilot D27 the Chakra converter runs in-process, so the interpreter that
started the run decides which protobuf converts the trace. A venv without
`protobuf>=7.35.1` raises at the first conversion instead of converting wrongly
(D26/D27), which is the failure mode worth having.

`_sim_environment` then builds the trace, the envelope cache and the predictor
**in heteropilot's own shape**: `generate_trace(spec, …, num_requests, seed)`,
`EnvelopeCache(dir, spec, accelerator_of=…, link_bw_gbps=…, trace_digest=…,
topology_level=1)`, `LLMServingSimPredictor(trace, work_dir=…, timeout_s=…)`.
Not a second convention: `EnvelopeKey` is heteropilot's, and a cache directory
shared between `python -m planner plan` and `python -m graphsearch plan` must
agree about what a hit is. `--num-requests` and `--seed` therefore default to
heteropilot's own 300 and 42, and
`tests/test_cli.py::test_the_trace_defaults_match_heteropilots_own` reads those
two constants out of `planner/__main__.py` so a drift in either is caught rather
than discovered as a cache that never hits.

The per-representative graph signature the cache already used (D126) is
unchanged, and it is what keeps two representatives differing only in a shared
resource from colliding on one `EnvelopeKey`.

**`--max-workers` does not touch determinism.** `evaluate_candidates` runs the
simulations concurrently and assembles the results sequentially in candidate
order, so plan ids and every appended list are byte-identical to a serial run.
That is heteropilot's guarantee, restated here because this is the first caller
in this repository to use it.

**Affects.** `graphsearch/__main__.py`, `graphsearch/adaptive.py`
(`max_workers`), `tests/test_cli.py`.


---

## GS-15 — the stages are timed, and no stopwatch reaches a provenance block · 2026-09-28

**Why timings at all.** E-G3's registered criterion is `saving >= 0`, where

```
saving = t_sim_oracle - (t_sim_proposed + t_hash + t_vf2 + t_bounds)
```

Every term has to be measured or the column is an assertion. The compression's
own cost is charged to the compression; a saving counting only the simulations
that were skipped would be the compression ratio wearing a stopwatch.

**Who measures what.** `enumerate` and `bounds` are wall-clocked by
`run_proposed`, which runs them. `hash` and `vf2` come from
`CompressionReport.as_timings()` rather than a clock around `compress`, because
that call also builds the conflict matrix and that is not a cost of the
compression. `rank` and `sim` are measured by `AdaptiveSearch`, which runs
them. The caller seeds its four into the search, the search adds its two, and
`SearchAudit.timings` carries all six plus `search`.

`hash` and `vf2` are separate terms and stay separate: hashing is linear in
embeddings and VF2 is quadratic inside a bucket, so a lumped number could not
say which one ate the budget — which is the first question `saving < 0` raises.

**And none of it is serialised.** Rule 7 says the same input twice must give
byte-identical output. A wall-clock never does. So `timings` is an attribute of
`SearchAudit` and is **not** in `as_provenance()`, and E-G3's harness — which
holds the audit in-process — writes them into its own results file, where a
number that changes between runs is the point.

**This removed an existing hole rather than only avoiding a new one.**
`CompressionReport.as_dict()` carried `vf2_seconds`, and `as_dict()` is what
`plan --output` writes into `provenance.compression`. Two runs of the same
command therefore produced different files, for a reason unconnected to the
plan. The seconds left that dict; `as_timings()` is how a caller asks for them,
and `tests/test_cli.py::test_two_plan_runs_write_byte_identical_yaml` pins the
property where a reader would notice it breaking.

**Affects.** `graphsearch/equivalence.py`, `graphsearch/adaptive.py`,
`graphsearch/oracle.py`, `tests/test_adaptive.py`, `tests/test_cli.py`.


---

## GS-16 — the oracle's cache is keyed per embedding id, or it audits the compression with the compression's answer · 2026-09-28

**What was wrong, and it was measured rather than reasoned.** The first
real-simulator run of E-G3 on `graph-toy-shared-nic` reported **288 oracle
simulations and left 48 files in its cache directory**. It had simulated 48
placements and copied the other 240.

`EnvelopeKey` describes parallelism and hardware; it cannot describe which
shared resources a placement crosses, so the oracle arm needs a signature or
every embedding of a template collides on one key. The signature it was first
given was the graph signature — the one the *proposed* arm uses, and the one
`compress` folds by. Consequence: every embedding of one equivalence class
shared a cache entry, the second and later members were handed the first's
metrics, and **`mismerged_pairs` could not have been anything but 0**. The
oracle was auditing the compression using the compression's own answer. That is
GS-9's mistake one level up, and it would have read as a pass.

The wall time said so too, which is what prompted the look: `t_oracle` 240.7 s
for "288" simulations against `t_proposed` 253.6 s for 60, a 5x difference in
seconds-per-simulation that no stage of the pipeline could explain.

**Decision.** `run_oracle`'s cache key leads with the **embedding id**:
`f"{embedding_id}:{wl_hash}:{schema_version}:{tool_version}"`. One placement,
one entry, every time. It costs the oracle exactly the simulations the
compression would have saved — which is what makes it a baseline rather than a
second copy of the thing under test. The graph signature stays beside the id so
an entry still cannot answer across a networkx release that hashes the same
graph differently, or across a schema change.

The proposed arm is unchanged: there, one representative is one simulation by
construction, and sharing an entry between two representatives that really are
isomorphic is the saving being claimed rather than a leak.

`tests/test_oracle_agreement.py::test_the_oracle_cache_gives_every_placement_its_own_entry`
pins it by counting files against placements on the counterexample fixture, and
asserts first that the fixture folds something — a fixture that folds nothing
cannot test the property and would pass vacuously.

**No published result was affected.** E-G1, E-G1b and E-G2 run without a cache
at all. The only run that had this defect is the first E-G3 rehearsal, whose
numbers were discarded and never committed.

**Affects.** `graphsearch/oracle.py`, `tests/test_oracle_agreement.py`,
`experiments/scripts/e_g3_real_sim_oracle.py`.


---

## GS-17 — a simulator error is `unknown_measurement`, not an infeasible verdict · 2026-09-28

**What was wrong.** `run_oracle` ended with

```python
for embedding in embeddings:
    result.feasible.setdefault(embedding.id, False)
```

One line, and it is work order rule 4 — *unevaluated is not infeasible* —
being broken in the one place the whole correctness argument is taken. Any
placement the evaluator did not classify was recorded as **infeasible**: a
`SIM_ERROR`, a timeout, a crash. The mock never fails, so nothing caught it
until the real simulator ran.

**What it cost, measured.** The first complete `--predictor sim` E-G3 on
`graph-toy-shared-nic`: 288 placements, **18 came back `SIM_ERROR`**. Recorded
as infeasible, they disagreed with the feasible members of their own
equivalence classes, and `compare` reported

```
mismerged_pairs = 96      correct = False
```

The equivalence relation had done nothing wrong. Ninety-six pairs of
"the compression merged two placements the oracle judged differently" were
ninety-six pairs of *one placement judged and one placement crashed*. Under
rule 5 that is a stop-and-report, and the report would have been about the
wrong thing.

**Decision.** `OracleResult` gains `unjudged: dict[str, str]` — embedding id to
the reason there is no verdict — and `feasible` now contains **only** the
placements the simulator actually judged. `compare` skips any pair with an
unjudged member, counts those separately as `unjudged_pairs`, and reports
`unjudged` and a new `complete` flag beside `correct`:

- **`correct`** is still `false_infeasible == 0 and mismerged_pairs == 0`. It
  is about whether anything is WRONG.
- **`complete`** is `unjudged == 0`. It is about whether the run proved as much
  as it set out to.

They are separate because the responses are separate. An incorrect run means a
bound or an equivalence is defective. An incomplete run means the simulator
fell over, which is a fact about this run and about LLMServingSim, and is
reported as such rather than laundered into a verdict about placements.

After the fix, the same fixture, same cache, same 18 failures:

```
false_infeasible = 0   mismerged_pairs = 0   correct = True
unjudged = 18          unjudged_pairs = 6    complete = False
```

**The 18 failures are not explained yet, and are not claimed to be.** They are
reported, per fixture, in `experiments/results/e_g3_real_sim_oracle.md`, and
E-G3's correctness claim covers the placements that were judged — the row says
how many that was.

**Affects.** `graphsearch/oracle.py`,
`experiments/scripts/e_g3_real_sim_oracle.py`, `tests/test_oracle_agreement.py`.


---

## GS-18 — `livelock_watch` guards one simulation, not a driver that spawns many · 2026-09-28

**What happened.** The work order says to wrap E-G3's oracle harness in
heteropilot's `livelock_watch.sh`. Wrapped the obvious way, it **killed a
healthy run at 901 seconds**:

```
livelock_watch: NO PROGRESS -- not one progress line in 900s.
livelock_watch: the run never started reporting.
```

Sixty-six simulations had already completed and eight more were running at that
moment.

**Why.** The D23 detector reads `Running Instance[...]` lines from the wrapped
command's **own stdout**. Those lines belong to `python -m serving`. This
harness does not print them: it calls `LLMServingSimPredictor`, which starts
each simulation as a subprocess and captures its output into that simulation's
own log. So the watchdog watches a driver that never speaks, and `-g`'s grace
timer fires with a verdict that says the opposite of what is happening.

Left on, it does not protect the run. It ends it, and it mislabels a working
harness as a dead one — which is worse than no watchdog, because the exit code
means "harness finding" and a reader would go looking for a bug that is not
there.

**Decision.** The wrapper uses `livelock_watch.sh -g 0 -s 0 -t "$CEILING"`,
asking it for the one thing it can still do here and nothing it cannot:

- **the wall-clock ceiling** (`-t`, exit 124, `timeout`'s own code), and
- **the process-group kill**, which is why it is still `livelock_watch` and not
  a bare `timeout`: it launches under `setsid`, so a kill reaches the
  `python -m serving` children as well as the driver. A bare `timeout` would
  orphan them.

What protects an individual simulation is the predictor's own `timeout_s`
(`--timeout`, heteropilot's default 900 s **per simulation**). That is the
right layer: one hung simulation is abandoned and the other 287 continue,
which is exactly the behaviour a 288-placement oracle arm needs.

And a long run is no longer silent. The harness prints a progress line per
fixture and per arm to stderr — loading, templates, each arm's finish with its
simulation count and wall time, the correctness verdict. A human watching the
log can now make the judgement the watchdog cannot.

**Not a change to heteropilot.** `livelock_watch.sh` is correct for what it was
written for — a single simulator run whose ticks reach stdout — and is used
unmodified. What changed is this repository's understanding of where it
applies. The header of `experiments/scripts/e_g3_oracle_run.sh` carries the
whole reason so the flags are not "cleaned up" by someone who has not hit it.

**Affects.** `experiments/scripts/e_g3_oracle_run.sh`,
`experiments/scripts/e_g3_real_sim_oracle.py`.


---

## GS-19 — a full cache hit is the wrong target when simulations fail · 2026-09-28

**What the work order asks.** P1.4: re-run the same command and check
`cache_hits == simulations_run`, and that the number of cache files equals the
number of representatives evaluated.

**Neither identity holds, and neither is a defect.** `EnvelopeCache.put`
returns early on a result that is not `ok`, so a placement whose simulation
errored is never written and misses again on every re-run. A corpus containing
`SIM_ERROR`s can never be fully warm. The identities that do hold, and that the
report states so a reader can do the arithmetic:

```
cache_hits == simulations_run - failures_in_that_arm
files      == placements_simulated - unjudged
```

Both reconcile exactly on the E-G3 corpus:

```
proposed  186 simulated -  24 failed   = 162 cached  ->  162 files
oracle    930 placements - 66 unjudged = 864 judged  ->  864 files
```

with 864 distinct `candidate_id` owners across 864 oracle files and **zero
files claimed twice**. A file claimed twice is a placement served another's
metrics, which is GS-16 reappearing, so it is counted rather than assumed.

**The check that matters is the third one.** `EnvelopeKey` carries model,
dtype, the per-island `accelerator|role|tp|pp|ep|dp` segments, the scheduler
config, the network class and the workload bucket. It carries **no island id
and no shared resource**. Two placements on different nodes with the same
accelerator and knobs therefore collide on one key, and the graph signature
(D126) is the only thing separating their cache entries. Verified on all three
fixtures, from the cache files themselves rather than by recomputing a key:
every file records the `candidate_id` that wrote it, so a placement that
simulated successfully and owns no file was overwritten by another.

**The pair is found, not hard-coded** — a fixture edit that removed the
counterexample would otherwise leave the check passing against a pair that no
longer has the property. Which made a real bug visible: the finder first
grouped by `template_id` and reported *"no such pair"* for
`graph-toy-shared-nic`, the fixture where the property holds by construction.
Two placements on different nodes are different templates; the *key* does not
know that, and grouping by template id asks a narrower question and answers the
wrong one. Grouped by the `EnvelopeKey` digest, all three fixtures produce a
pair, and shared-nic's is `nodeX` against `nodeY` — the counterexample itself.
`tests/test_cache_keying.py` pins both halves: that the condition exists in the
corpus, and that no such pair shares a signature.

**Affects.** `experiments/scripts/e_g3_cache_check.py`,
`tests/test_cache_keying.py`,
`experiments/results/e_g3_real_sim_oracle.md`.


---

## GS-20 — the contention model is fluid, not packet-level, and candidates do not contend with each other · 2026-09-28

**What `FluidContentionModel` is.** Processor sharing over shared resources: at
any instant the active flows on a resource split `capacity - reserved` equally,
and a flow's rate is the minimum over the resources on its path, its own link
bottleneck included. Event-driven — rates are recomputed whenever a flow starts
or finishes — and **not packet-level**: no queue, no window, no loss, no burst.
Named in every record, because a result computed under it may not be compared
against one computed under `null` without saying so.

**What contends with what.** Two things, and deliberately not a third:

1. an **external reservation**, treated as a permanently active flow and taken
   off capacity before anything else;
2. **flows inside one candidate** that overlap in time — the several P/D
   transfers of a `dp > 1` deployment.

**Candidates do not contend with each other.** They are alternatives; the search
evaluates many and deploys one. Pricing two as if both were running would model
a cluster nobody is going to build.

**It is not max-min fair, and that is a choice rather than an oversight.** A
flow held back elsewhere on its path does not return its unused share: each
resource splits flatly, `available / active`. Max-min fairness would give the
unbottlenecked flow more, so this model is the pessimistic of the two. Stated
rather than silently improved, because it is the model E-G4's numbers will be
produced under.

**A bound may never use it.** A pruning stage rejects only when the most
optimistic arithmetic already misses the constraint, and fluid is by
construction never faster than null — sharing a resource cannot speed a flow
up. `null` stays the bounds' model, and
`test_fluid_is_never_faster_than_null` pins the direction rather than a
docstring asserting it.

---

### Where the work order and the code disagree, and the code wins

**P2.5 asks for a test** that the `X -> Z` and `Y -> Z` representatives of
`graph-toy-shared-nic` differ in TTFT under `fluid` and **agree under `null`**.

**They differ under both, and the contention model is not why.** X's uplink has
6 of its 10 GB/s held by something outside the deployment.
`effective_bottleneck_bytes_per_s` subtracts that, and *both* models use it —
the reservation has been subtracted since G3 and is D124, not P2.5. The two
representatives were never going to agree under `null`.

What `fluid` actually changes is the case the same paragraph of the work order
names and the test sentence does not: **a candidate whose own flows overlap on
one resource.** That needs `dp > 1`, and therefore more than two devices, which
is why the two-device corpus shows no difference at all. Measured, on
`graph-toy-shared-nic` at `total_devices <= 4`, a `dp = 2` P/D candidate whose
two KV transfers cross the same uplinks:

| | TTFT ratio |
| --- | --- |
| `null` | 1.379346 |
| `fluid` | 2.337483 |

Twelve such representatives, every one of them slower under `fluid`.

So the tests assert what is true instead of what was asked:

- `test_two_concurrent_transfers_contend_under_fluid_and_not_under_null` — the
  property the model exists for, on the real pipeline;
- `test_one_transfer_alone_is_priced_the_same_by_both` — why most of the corpus
  is untouched, so a run that changed everywhere would read as a bug;
- `test_the_reservation_separates_the_counterexample_under_both_models` — the
  X/Y difference pinned to the reservation, so a later reader cannot
  re-attribute it to contention.

**The default path is unchanged**, which is the other half of P2.5. `--contention`
defaults to `null`; `--contention null` is byte-identical to passing nothing
(`test_selecting_null_explicitly_changes_nothing`), and E-G1 and E-G1b both
re-run byte-identical on this branch.

**Affects.** `graphsearch/contention.py`, `graphsearch/ranker.py`,
`graphsearch/adaptive.py`, `graphsearch/adapter.py`, `graphsearch/oracle.py`,
`graphsearch/__main__.py`, `tests/test_contention.py`, `tests/test_cli.py`.


---

## GS-21 — the conflict matrix is not built unless someone asked for it · 2026-09-28

**Measured, on the way to E-G6.** On a synthetic 32-device cluster
(8 nodes × 4 devices, 9,024 embeddings), `compress` took **52.1 s**, of which:

| | seconds |
| --- | --- |
| hashing | 4.0 |
| VF2 | 3.1 |
| **`conflict_matrix`** | **32.3** |
| the rest | ~13 |

`conflict_matrix` is O(n²) over **embeddings** — it produced 4,898,400 pairs
here — and **the entire search pipeline throws it away**:

```python
representatives, _, report = compress(embeddings, graph)
```

in `oracle.run_proposed`, in `__main__.cmd_plan`, in every experiment script.
The only reader anywhere is `restore.max_concurrent_for`, which takes one as a
parameter and is not called from the search path.

**Why it matters beyond speed.** E-G6 plots the compression's cost against
cluster size, and §12's first failure condition is *the isomorphism check
costing more than the simulation it saves*. Charging a discarded O(n²)
byproduct to "the compression" would not have made the curve slow — it would
have made it **wrong**, and wrong in the direction of failing our own
contribution. At 128 devices the term grows sixteenfold.

**Decision.** `CompressionPolicy.conflicts` (default `True`, so no existing
caller changes behaviour). `run_proposed` and `cmd_plan` pass `False`.

**Opting out returns `UncomputedConflicts`, not an empty matrix.** An empty
`conflicts` reads as *"none of these placements clash"*, and a caller acting on
it would deploy two candidates that cannot coexist. That is
`unevaluated is not infeasible` one level down, so reading one raises with a
message naming the flag rather than answering plausibly.

**Result:** 52.1 s → **7.2 s**, and what remains is 4.0 s hashing plus 3.1 s
VF2 — exactly the two terms E-G3's `saving` formula charges. E-G1 re-runs
byte-identical, and the full suite passes.

**Affects.** `graphsearch/equivalence.py`, `graphsearch/oracle.py`,
`graphsearch/__main__.py`.

---

## GS-22 — E-G4 falsified a topology declaration, not the contention model · 2026-09-28

**Decision.** The registered E-G4 verdict on this node is **FAIL**, and the
correction is to `fixtures/clusters/*.v2.yaml`, not to
`graphsearch/contention.py`. No line of the fluid model changes.

**Why.** `experiments/microbench/PLAN.md` fixed, before anything was measured,
that GPU0-2 and GPU1-3 "share one PCIe host bridge — this is the shared
uplink". Measured (`experiments/results/e_g4_microbench.md`), two concurrent
copies over those two pairs each got **25.11 GB/s** against **25.12 GB/s** for
the same copy alone. No contention at any size in the grid. A third process
saturating 1-3 at a measured duty cycle of 0.60 did not move the 0-2 figure
either. 25.1 GB/s is a PCIe 4.0 x16 running out of lanes: the bottleneck is the
**endpoint's own x16 port**, and two copies between disjoint device pairs share
nothing.

Run on that declaration the fluid model is 93.1 % out at the median. Run on the
declaration the data supports it is 1.8 % out, **with no change to the model** —
and on `bidirectional`, where the pairs really do share endpoints, it is within
0.1 to 2.5 % of the wire from 4 to 64 MiB against 48-50 % for null. A model
that predicts contention correctly wherever contention exists has not been
falsified by a case where the contention was declared in the wrong place.

The distinction is the decision. "Fluid: 100 % error" would have invited a
rewrite of the model; what the data asks for is one line of YAML. Collapsing
the two would have produced either a model bent to fit a topology error or a
topology quietly edited to save a model, and the log would have recorded
neither.

**What it affects.** `experiments/results/e_g4_microbench.md` reports both
declarations side by side and judges on the registered one. Every A40 cluster
fixture declaring a per-bridge `shared_resource` for peer traffic is wrong in
the same way and must declare per-endpoint ports instead. The
`as_measured` declaration is **fitted** on the eight raw files listed in that
result and in `docs/preregistration.md`, and is excluded from P3's validation
set (work order P2.4).

---

## GS-23 — the fluid model's accuracy domain stops at 128 MiB bidirectional · 2026-09-28

**Decision.** Record the band above 128 MiB as the boundary of the fluid
model's measured accuracy. Do not fit a capacity to cover it.

**Why.** 0→2 and 2→0 concurrently contend by exactly the processor-sharing
factor from 4 to 64 MiB — fluid within 0.1 to 2.5 %. At 128 MiB and above the
pair reaches 16.7 GB/s per direction, an aggregate of 33.4 GB/s over a path
carrying 25.1 GB/s one way: **1.33x a single direction where everything below
gives 1.0x**, and fluid is then a third high. This measurement does not
establish what starts overlapping the two directions at large transfers, and
naming a cause would be inventing one.

A shared resource declared at 33.4 GB/s would make the table read clean. It
would also be a capacity chosen because it reproduces the answer, which is not
a measurement of anything, and the next node's prediction would be wrong
silently. `unknown_measurement` and `evaluated` do not merge (work order rule
4), and "outside the domain" is the first of those.

**What it affects.** The band table in `e_g4_microbench.md`. Any P/D KV
transfer above 128 MiB over a shared endpoint pair is predicted conservatively
(too slow) rather than accurately, and that is stated wherever the number is
used.

---

## GS-24 — four defects in the harness, all found by running it · 2026-09-28

**Decision.** Record what the microbenchmark harness got wrong before it
produced a single usable number, because three of the four would have produced
output that looked fine.

1. **`occupancy_stable` was False on every run.** The `after` snapshot was
   taken while this process still held a CUDA context on every device it
   touched, so the run always found *itself* in `after` and never in `before`.
   The analysis is specified to refuse a run whose occupancy changed
   mid-flight; it would have refused every run ever taken on a perfectly quiet
   node. Fixed by excluding our own pid and comparing sets.
2. **The `numa_pinned` claim could not be checked on the memory half, and
   PLAN.md said to check it in a place where it never shows.**
   `Mems_allowed_list` is the *cpuset* allowance; `--membind` installs a
   *mempolicy*. Under `numactl --cpunodebind=0 --membind=0` this node reports
   `Mems_allowed_list: 0-1` and `numactl --show` reports `membind: 0`. The
   harness now reads `/proc/self/numa_maps` and **refuses** `numa_pinned` when
   it says `default` — the "pin both halves or neither" mistake now fails
   loudly instead of mislabelling a figure.
3. **`--condition collective` ran peer copies.** It was in `CONDITIONS`, so
   argparse accepted it, and `measure()` has no branch for it: the file would
   have carried p2p timings under `condition_means: "all-reduce, varying world
   size"`. It now refuses and names `run_collective.sh`.
4. **The background load reported `wall_s: 0.0` and
   `achieved_duty_cycle: null` for every size.** `as_dict()` was called
   *inside* the `with`, and `wall_s` is assigned only when the generator thread
   leaves its loop, which `__exit__` is what causes. The correct call below it
   was guarded by `background is None`, which the dead value had already made
   false. The record's own note says the analysis "uses achieved_duty_cycle and
   never target_util" — so all three background conditions carried a target
   nobody could check instead of a measurement. After the fix the generator
   reports a sustained duty cycle of 0.585 to 0.600 against its 0.6 target.

**Why record it.** The same pattern as GS-16, GS-17 and the `diagnose_pair`
bug: a check that cannot fail and a check that cannot pass are both worthless,
and neither announces itself. Defects 1 and 4 were invisible in the console
output; defect 3 would have been invisible in the result file. All four were
found by running the harness, not by reading it.

**What it affects.** `experiments/microbench/run_pair.py`, `PLAN.md`'s
verification recipe, and the three `bg60` raw files, which were re-measured
after the fix.

---

## GS-25 — the symmetry counter is a closed form; enumeration is its test · 2026-09-29

**Supersedes GS-3.**

**Decision.** `_ordered_groupings` emits one ordering per set partition (the
lowest remaining device fixes the next group). `EmbeddingStats.skipped_symmetric`
is filled from `_symmetry_multiplier` — `produced x (prod_a R_a! - 1)` — and is
the same number the enumerate-then-fold path produced. The old generator
survives as `_enumerate_all_orderings`, serving `canonical_only=False` and
standing as the formula's evidence in `tests/test_embeddings.py`.

**Why GS-3 was wrong.** Its premise was that collapsing by construction makes
the counter "structurally zero", so "a counter that cannot move is not evidence
that symmetry was removed". The first half is the mistake: the counter is
structurally zero only if you decline to compute it. R interchangeable replicas
give each canonical partition exactly R! orderings, and assignments are
independent, so a template's complete placements fold in groups of
`prod_a R_a!`. That is not an estimate of the enumerated figure — it is the
same figure, and it can be had where enumeration does not finish.

The demand behind GS-3 was right and is kept: the number must be checkable.
It is now checked rather than performed. `tests/test_embeddings.py` asserts
formula == enumeration on four toy shapes on every run, and on the
seven-device cut of `real-a40x8` — **81,432 re-orderings over 768 placements**
— under `pytest -m slow`.

**What forced it.** Measured 2026-09-29 on `fixtures/clusters/real-a40x8.v2.yaml`:

| devices | kept | re-orderings | enumerate-then-fold | canonical |
| --- | --- | --- | --- | --- |
| 5 | 192 | 1,764 | 0.34 s | 0.10 s |
| 6 | 1,014 | 12,138 | 9.14 s | 5.57 s |
| 7 | 768 | 81,432 | 50.97 s | 5.78 s |
| 8 | — | — | **did not finish in 180 s** | see below |

The ratio of discarded to kept reaches **106:1** at seven devices: the walk
spent about ninety-nine percent of its work building placements it then threw
away. `replicas!` was "the cheap side of this pipeline by orders of magnitude"
on fixtures of 288 and 528 embeddings, which is what GS-3 had. It is not cheap
on a real eight-device node, and E-G5 could not plan at all.

**And a budget that was not one.** The `max_embeddings_per_template` check sat
*after* the duplicate test, so a re-ordering returned before ever reaching it:
the cap bounded the OUTPUT while the walk ran on. Measured at seven devices,
`cap=8` took **57.0 s against 50.9 s uncapped** — a cap that made enumeration
slower. The check now precedes the duplicate test, and
`test_a_budget_now_bounds_the_walk_and_not_just_the_output` asserts a cap is
never slower.

**The kept set is unchanged, and that is checked rather than argued.**
`_locality_score` sorts its ranks, so every ordering of one partition scores
alike and `groups` breaks the tie lexicographically — which is precisely the
ordering the canonical generator emits. E-G1, E-G1b and E-G2 re-run byte for
byte after the change.

**Affects.** `graphsearch/embeddings.py`; the `skipped_symmetric` column of
every compression table (values unchanged); `pyproject.toml` gains a `slow`
marker; `docs/preregistration.md` records the change with the kept set
verified unchanged.

---

## GS-26 — one graph's paths are computed once, not once per placement · 2026-09-29

**Decision.** `graphsearch/paths.py` keeps a single-entry memo of the derived
device graph, the admitted edges and the answered `(src, dst)` pairs for the
graph most recently asked about. `clear_path_cache()` drops it.

**Why.** GS-25 made the enumeration walk instant and the eight-device cluster
still would not plan. The diagnosis separated the two costs and they are not
the same thing at all: `real-a40x8` has **6,744 canonical placements, counted
in 0.0 s**. Every remaining second was in `_build` — about **267 ms per
placement** — and inside it `path_set`, which rebuilt `_device_graph` and
`admitted_edges` on every call and re-ran `shortest_simple_paths` for pairs it
had already answered. `_build` calls it once per flow per placement, so the
same few dozen questions were asked thousands of times. A near-complete
eight-device graph has on the order of two thousand simple paths between any
pair, and enumerating those is the cost.

| | before | after |
| --- | --- | --- |
| `real-a40x8`, 8 devices | **did not finish in 1800 s** | **156.95 s**, 6,744 embeddings |
| per embedding | ~267 ms | ~23 ms |

**Why it is safe.** `ResourceGraph` and `PathPolicy` are both frozen, so the
same question has the same answer for as long as the entry lives. The memo is
keyed by object identity **with a strong reference held beside it**, so the id
cannot be recycled onto a different graph while the entry is alive — the one
way an identity-keyed cache silently answers for the wrong cluster. One entry,
because enumeration works through one graph at a time and an unbounded cache of
resource graphs is a leak.

E-G1, E-G1b and E-G2 re-run byte for byte, which is the check that matters: a
cache that changed an answer would change one of those tables.

**A test of mine that this broke, and how.**
`test_a_budget_now_bounds_the_walk_and_not_just_the_output` compared the wall
time of a capped run against an uncapped one. With this memo the uncapped run
warms the cache the capped run then reads, so the second is fast for a reason
that has nothing to do with the budget, and the test passed or failed on noise.
It now counts the complete placements each walk reaches, which is deterministic
and is what the budget fix is actually about. **A timing assertion is a claim
about a machine; a counter is a claim about the algorithm.**

**Affects.** `graphsearch/paths.py`, `tests/test_paths.py`,
`tests/test_embeddings.py`.

---

## GS-27 — a placement contrast needs a candidate smaller than the node · 2026-09-29

**Decision.** Each E-G5 topology condition scopes the planner to its own device
count (`_templates(..., max_devices=n)`), and the recommendation placed is the
best plan **of that size**. What the cut removes is `excluded_by_scope` and is
recorded in every raw file.

**Why.** The first dry run of `deploy_and_bench.py` emitted this:

```
CUDA_VISIBLE_DEVICES=0,2 vllm serve ... --tensor-parallel-size 8
```

Two devices visible, eight ranks requested. vLLM would refuse it instantly, and
the harness would have been "verified" without ever producing a runnable
command. The bug was not the override; it was a category error in the design.

**A topology condition names a PLACEMENT, and a placement has a fixed device
count.** T2 is "this template, on gpu0 and gpu2" — it is not a template of its
own. Asked without a scope, the search on an eight-GPU node recommends an
eight-device plan, and an eight-device plan on an eight-device node has
**exactly one placement**. There is then no contrast to measure, and T1 against
T2 is not a question that can be put.

So the contrast is only available for candidates smaller than the node, and the
honest way to get one is to ask the planner a well-posed question — "the best
plan using at most two devices" — rather than to take its unconstrained answer
and force it onto two devices.

**What this costs, stated rather than hidden.** The rows E-G5 reports are the
best plan *of the size the condition places*, not the best plan on the node.
Those are different claims and the result file says which one it is making.
Larger plans are `excluded_by_scope` in these rows: not considered, never
considered and rejected (work order rule 4).

**A second thing the dry run showed.** With `max_devices=2` the search returned
**one** two-device candidate, so the boundary alternative is `not applicable`
for that condition. Recorded as such rather than filled with a candidate of a
different size, which would have made the two columns answer different
questions. It also means `false_infeasible`'s real-hardware test needs a
condition whose scope admits more than one candidate, and the matrix has to
say which conditions those are.

**Side effect worth having.** Planning a scoped condition takes **40 s** where
the unscoped plan took 3:13, because the space it enumerates is far smaller.

**Affects.** `graphsearch/__main__.py` (`_templates` gains `max_devices`),
`experiments/e_g5/deploy_and_bench.py`, `experiments/e_g5/MATRIX.md`.

## GS-28 — the disaggregation path exists; what is missing here is a router · 2026-09-30

**Decision.** The paper stops claiming that inter-node P/D needs a path that
does not exist. `conclusion.tex` says instead that it needs a router the
deployment layer does not have, which is the true statement and the narrower
one. `limits.tex` is unchanged, because it already said "the deployment
backend" and not "vLLM". The survey and the measurements behind this are in
`docs/inter_node_pd_options.md`.

**Why.** The claim was checked and it failed. vLLM 0.19.0, as installed,
parses `--kv-transfer-config`, accepts `kv_producer` / `kv_consumer`, and
registers five KV connectors. It was then run: prefill on `s8` GPU 0 handed
fourteen KV block ids to decode on GPU 1, which pulled them over NIXL and
produced the completion (`experiments/pd_probe/raw/vllm_pd/`). The
transport was measured across the two machines at 77.90 Gbit/s GPU to GPU over
`rc_mlx5`, byte content verified (`experiments/pd_probe/raw/nixl/`).

What actually blocks the hardware arm is in this repository's own dependency.
`planner/deploy/vllm_cuda.py` refuses a non-aggregated role, refuses a non-local
host, and refuses a plan with more than one assignment because that "needs a
router" --- and there is no router anywhere under `planner/deploy/`. A P/D
deployment is two engines and something in front of them, and only the third
of those three is real work. The probe above got its result by making the two
HTTP calls by hand, which is precisely the thing a router would do.

**Two findings worth keeping, because neither was expected.**

The disaggregated answer is not the aggregated answer. Greedy, prefix caching
off, three prompts: two identical, one diverging after 57 of 66 characters,
reproducibly, while two aggregated engines on *different GPUs* agree exactly
and each is repeatable. So a P/D arm and an aggregated arm do not produce the
same token stream, and any comparison between them has to say so. The first
run of that test appeared to show agreement and did not: prefix caching had
moved the aggregated baseline between two calls of the same harness, which is
the confound `--no-enable-prefix-caching` (D127) now removes.

`nixl` is pinned to 0.9.0, and not for a feature. 1.3.2 and 1.4.1 ship a
`nixl_ep` package built for torch 2.11 to 2.13; this environment is torch 2.10;
vLLM's `has_nixl_ep()` is a `find_spec` presence check that cannot see the
missing binary, and the import it guards is unconditional. Installing either
stops vLLM starting **at all**, on a dense model with no MoE layer. 0.9.0 has
no `nixl_ep` and needs no workaround.

**What it affects.** `paper/sections/conclusion.tex`, `paper/CLAIMS.md` (C18),
`docs/inter_node_pd_options.md`, and the two raw directories named above. It
does not change any experiment already run.

## GS-29 — inter-node P/D runs here; the divergence grows with the distance · 2026-09-30

**Decision.** GS-28's claim is now backed by the inter-node case rather than
by the intra-node case plus a transport measurement. `s8` prefill handed
fourteen KV blocks to `s6` decode across the InfiniBand subnet and the decode
instance produced the completion, at 0.058 s for the prefill call and 0.917 s
for the decode. `experiments/pd_probe/raw/vllm_pd_two_node/`.

**Why it is a separate entry.** Because a number changed, and in the direction
that matters. Within one node the disaggregated answer differed from the
aggregated one on one of three prompts; **across two nodes it differs on two of
three**, deterministically over three repetitions of the whole set. The control
holds in both: two *aggregated* engines, one per machine, give the same answer
to the prompt the disaggregated path gets wrong, and each is repeatable alone.
So neither the machine nor noise is the variable.

No mechanism is claimed. Prefill batch shape, block layout and the transfer
itself are all candidates and nothing measured here separates them. What is
recorded is that the perturbation is real, reproducible, and larger across the
fabric than across a bus.

**A replication that was not planned.** `s6` was first brought up with
`nixl==1.4.1` and its engine refused to start with
`ModuleNotFoundError: nixl_ep_cpp_torch210`, through the same import chain
GS-28 recorded on `s8` --- because the pin had been applied to the wrong
virtualenv on that machine. Two machines configured hours apart failed
identically. The trap in GS-28 is therefore a property of the wheel against
torch 2.10, not of one installation.

**What it affects.** `docs/inter_node_pd_options.md`,
`experiments/pd_probe/`. It does **not** close `\pending{E-G5: inter-node P/D}`:
this is a probe of the serving stack, and E-G5's arm still needs the router
that `planner/deploy/` does not have.

## GS-30 — the identical T1/T2 predictions are a harness artefact, not a simulator finding · 2026-09-30

**Decision.** E-G5's three topology conditions are rerun, and the harness is
changed to ask the search for the prediction **of the placement it is about to
deploy**. The identical `p99_ttft_ms` across T1, T2 and all three repetitions
is withdrawn as evidence for anything about the simulator.

**Why, and what was ruled out.** Two hypotheses were put and **both were
falsified**, in this order:

| checked | result |
| --- | --- |
| the compile hook was never bound (GS-13 family) | **no** --- `compile_applied 8/8` on a cold cache |
| the simulator does not respond to TP all-reduce bandwidth (D3/D124) | **no** --- at tp2, p99 TTFT runs 23383 / 26160 / 31708 / 119710 ms for `link_bw` 112.5 / 25.12 / 10.05 / 1.0 GB/s |

The graph does distinguish the placements: `compile_embedded` puts them in
three classes on this cluster, 112.5 GB/s for the four NVLink pairs, 25.12 for
the PCIe ones, and 10.05 for those crossing an uplink the holdout reserves.

So the cause is elsewhere, and it is in this repository. `run_plan` passes
`max_devices=len(topology.devices)` and **no placement at all**, so T1 and T2
are the same search with the same arguments: same candidate id, same
prediction, and the second run served entirely from cache. The placement is
applied afterwards as `placement_override`, with no second prediction. Under
the budget the harness uses, every feasible plan came out on an NVLink pair and
194 placements --- including T2's `(gpu0, gpu2)` --- were **unevaluated**, not
rejected. The harness therefore prints a feasible NVLink placement's numbers
beside a measurement taken at a placement the search never judged.

That is a defect of the same family as GS-13 but not the same defect: the hook
is bound and applied, and what is missing is the step that asks for the
placement's own verdict. For T2 the honest raw value is `unknown_measurement`,
not a feasible candidate's metrics, and the rerun must record it as such.

**Three readings of my own were wrong before this one, and each was caught by a
control rather than by reading code.** A warm cache reported `compile_applied
0` and looked exactly like an unbound hook. A bandwidth sweep run on a
`tp1-dp2` candidate showed no response, because tensor-parallel degree one has
no all-reduce to respond with. And "not feasible" was written where the audit
said `unevaluated`, which is the one distinction this project does not allow to
blur.

**The difference between the instruction and the registration, recorded here as
`CLAUDE.md` requires.** The work order for this step described the holdout as a
variant of "the two-node YAML (s8, s6)". No such fixture exists --- the P3
fixture is `real-a40x8.v2.yaml`, one node --- and the registration
(`docs/preregistration.md`, E-G7 holdout 2) requires the variant to be derived
from the committed real fixture by one field "so that what is being held out is
the *topology condition* and not a different cluster". The registered reading
was followed: `real-lab-holdout.v2.yaml` is `real-a40x8.v2.yaml` with
`shared_resources[port-gpu0].reserved` 0.0 -> 15.07 GB/s and nothing else,
derived by `experiments/scripts/make_holdout_fixture.py`. The two-node fixture
belongs to E-G5's P/D arm, where it is a cluster and not a holdout.

**The altered port is one the candidates actually cross, and this was checked
rather than assumed.** `gpu0-gpu2` declares `shared_resource: port-gpu0`;
`gpu0-gpu1` declares none, because NVLink does not traverse the PCIe port. So
the single field moves T2's path from 25.12 to 10.05 GB/s and leaves T1 at
112.50. Exhaustively --- 210 representatives per cluster, **0 unevaluated on
either** --- it changes the answer: 64 feasible plans become 52. The twelve
that leave are the six placements containing `gpu0` over PCIe, at two
templates, and they are **evaluated and rejected**, not unevaluated. A holdout
built on `port-gpu7` would have moved nothing, which is why the check was made.

**What it affects.** `experiments/e_g5/deploy_and_bench.py` and E-G5's three
conditions (rerun), `experiments/results/e_g7_holdout.md`,
`fixtures/clusters/real-lab-holdout.v2.yaml`,
`experiments/scripts/make_holdout_fixture.py`, and paper §8.7, which must not
carry the withdrawn claim.

## GS-31 — the registered recall criterion fails on the real-lab holdout, and the ranker claim narrows · 2026-09-30

**Decision.** E-G7 success criterion 3 --- "`full` arm `feasible_recall` at
k = 16 >= heteropilot arm's at k = 16" --- is **not met** on
`real-lab-holdout`. The registered response is taken as written: the ranker was
fitted to the diagnosis corpus, and the claim about it narrows to those
fixtures and `synth-holdout-1`. The paper's C26 splits into C26 (the invariant,
which holds on both) and C32 (the recall, which does not).

| fixture | `full` at k = 16 | heteropilot at k = 16 | criterion |
| --- | --- | --- | --- |
| synth-holdout-1 | 0.625 | 0.0312 | met |
| real-lab-holdout | **0.1429** | **0.5** | **not met** |

**Why it is reported rather than explained.** The failure interpretation was
written into `docs/preregistration.md` before the fixture existed, precisely so
that this table could not be met with an argument invented afterwards. The
honest reading is that heteropilot's template-level surrogate, credited
generously because it cannot name a placement at all, retrieves more feasible
placements at the registered budget on this graph than this search does.

**What does not fail.** Criterion 1 holds on the same fixture: 384 embeddings
to 210 representatives, `false_infeasible` 0, `mismerged_pairs` 0, `unjudged`
0, complete. So the failure is of the **ranking**, not of the correctness, and
the two are separate claims with separate evidence. Reporting them as one
number would have hidden a pass inside a fail or the reverse.

**The result file did not say any of this, and now does.** It printed the two
arms as rows and left the comparison to the reader, which is a criterion that
can only fail by inspection --- the same shape of defect as GS-24's harness
checks. `e_g7_holdout.py` now computes the verdict per fixture, prints
**met** / **NOT met**, and on a failure quotes the registered response rather
than paraphrasing it.

**Scope.** k = 4 and k = 8 are report-only under the registration and were not
judged, although they point the same way (0.0714 against 0.5 at k = 8). The
`no_boundary` arm, which is criterion 2, is unaffected by this entry.

**What it affects.** `paper/CLAIMS.md` (C26, new C32, footnote `eg7h`),
`paper/sections/eval.tex`, `experiments/scripts/e_g7_holdout.py`,
`experiments/results/e_g7_holdout.md`.

## GS-32 — the inter-node P/D arm is deployed by the harness, and five instructions met the code · 2026-09-30

**Decision.** E-G5's inter-node P/D arm is run by `deploy_and_bench.py --mode
pd` (`experiments/e_g5/pd_arm.py`), which launches the prefill engine on `s8`
GPU 0 and the decode engine on `s6` GPU 0 itself and drives them with
`experiments/e_g5/pd_router.py`. **The harness router is an experimental
instrument, not a serving component.** A router in heteropilot's
`planner/deploy/` is follow-up work, recorded there as D128 ("deploy has no
P/D router"), and no hook PR (H5) is made for it now.

The arm was registered before its first request (preregistration change-log
rows 5 and 6). Five points of the work order met the code, and in each the
code won, as `CLAUDE.md` requires:

1. **The background generator.** The order named `run_pair.py
   --background-util 0.6`. That is location (a)'s PCIe generator and does not
   cross the NIC, so it cannot load this path. The background is E-G4(b)'s own
   instrument, `ib_send_bw`, run at a 0.6 duty cycle whose achieved value is
   measured and recorded (`NicBackground`).
2. **`bandwidth_unit: Gbit/s`.** heteropilot never reads that field: it is in
   the v2 allowlist (`planner/inventory.py:530`) and nowhere else, and
   `planner/topology.py` returns `link.bandwidth_gbps` as GB/s. A link written
   `100` + `Gbit/s` would read as 12.5 GB/s in graphsearch (whose
   `schema.py` converts) and as 100 GB/s in heteropilot --- one file, two
   numbers eight times apart. The InfiniBand links are written in GB/s
   (12.5 = 100 Gbit/s), which both repositories read the same way.
3. **"The inter-node link is 77.9 Gbit/s".** `LinkMeasurement`'s contract is
   that `bandwidth_gbps` "stays whatever its datasheet says and is never
   edited" (heteropilot absolute rule A3); the measured figure sits beside it.
   So the link carries the port's 100 Gbit/s as `vendor_spec` and the NIXL
   GPU-to-GPU 77.90 Gbit/s as a `measurement`, which is how `real-a40x8`
   already carries NVLink (112.5 declared, 52.64 measured).
4. **The direction E-G4(b) measured.** `run_nic.py` puts the `ib_send_bw`
   server on the near node and the client --- the sender --- on the peer, and
   E-G4(b) ran with `s8` near. Its 88.61 Gbit/s single stream is therefore
   **s6 -> s8**, a fact no raw file states; it was recovered from the code.
   This arm's KV crosses the other way (the decode instance on `s6` reads the
   prefill instance's blocks on `s8`). `run_nic.py --reverse` now sends from
   the near node, records a `direction` field, and writes a `*-to-*`
   directory that `analyze.py::nic_results` keeps apart from the other
   direction, where it would otherwise have replaced E-G4(b)'s `single`
   silently. Until that measurement exists, the fixture declares
   `nic-s8-to-s6` as a `placeholder` carrying the other direction's figure.
5. **`--max-model-len 4096`.** One of the 150 requests is 4197 tokens and
   would be refused in this arm only. Raised to 8192 before any request was
   sent (row 6).

**The two-node fixture is generated, not typed.**
`experiments/e_g5/build_cluster_s8s6.py` writes `real-s8s6.v2.yaml` from the
raw files, reusing `build_cluster.py` for each node and
`experiments/microbench/analyze.py` for the NIC and collective figures. `s6`
is the same model of machine but not the machine E-G4 measured, so its copied
intra-node figures are downgraded to `placeholder` and `s8`'s measurements are
not attached to its links. `real-s8s6-shared.v2.yaml` differs by one field:
`nic-s8-to-s6` reserved at 60 % of its capacity, the prediction side of the
registered criterion.

**How the deployed configuration is chosen.** The search on `real-s8s6`
produces twelve cross-node P/D templates. The six with prefill on `s8` and
decode on `s6` are each evaluated at the deployed placement with
`evaluate_placement`; the best (feasible first, then the lower predicted p99
TTFT) is deployed in **both** conditions, so that the NIC load is the only
difference between them. The whole table is kept in every raw file.

**Addendum, before the first request: the path cap.** At the library's
default `max_hops` of 8, enumeration on `real-s8s6` does not finish: each node
is a full PCIe mesh, so one `s8` -> `s6` GPU pair has 41,980 simple paths
(`nx.shortest_simple_paths`), and `_transit_closure` walks every edge of every
one. `plan` gains `--max-hops`; its default leaves every existing experiment's
policy unchanged, and the aggregated E-G5 conditions pass `None`. The P/D arm
declares **3**: the shortest inter-node route, gpu -> nic -> nic -> gpu, is
exactly three hops, and every longer one relays through another GPU, which
does not forward NIC traffic. At 3, embedding takes 1.8 s and compression 13 s.
The flag-parity test caught the harness not passing the new flag before any
run used it.

**Addendum: the s8 -> s6 direction was measured.** `run_nic.py --reverse`,
same instrument: 89.12 Gbit/s median (s6 -> s8 was 88.61). The fixture now
carries both directions as `measured`. With `analyze.py`'s new direction
filter switched off, E-G4's `single` row silently became 89.12 --- which is
the evidence that the filter is needed, not a guess that it might be.

**Addendum, after the first run: two instrument defects, and the first run
discarded.** The first `pd-independent` run completed 150 of 150 requests, but
eight of them streamed fewer chunks than their target length, always short.
The router had taken the first token at the first chunk with *non-empty*
text; a token can decode to an empty string (part of a multi-byte character),
so whenever the first token was such a fragment, TTFT was stamped one token
late. That is a bias in the measured quantity, not a counting nicety. The
router now counts a chunk with empty text as a token unless it only closes the
stream, and records the server's own `completion_tokens` through
`stream_options.include_usage` to check each request's length. The first
`pd-shared` run then failed while stopping its background: the teardown's
`pkill -f 'ib_send_bw...'` matched the remote shell that ran it, which killed
itself (ssh 255); the engines were still torn down by the outer context. It
now kills the background's process group only and cannot raise. Tested on its
own before the rerun: achieved duty cycle 0.601 against 0.6, 87.91 Gbit/s per
burst, nothing left running on `s6`. **Both first runs are discarded, and all
six are run with the corrected instrument**, so no row mixes two instruments.

**What it affects.** `experiments/e_g5/{pd_arm,pd_router,build_cluster_s8s6,
deploy_and_bench}.py`, `experiments/microbench/{run_nic,analyze}.py`,
`fixtures/clusters/real-s8s6{,-shared}.v2.yaml`, heteropilot D128.

## GS-33 — the P/D arm ran, and at the registered load it cannot answer its question · 2026-09-30

**Result.** All six runs completed: 150 of 150 requests each, no failures,
every request's length confirmed by the server. The inter-node P/D path works
under load. The registered criterion is **not computable**, for two reasons
the design did not anticipate, and it is reported that way rather than as met.

**The repetitions were not replicates.** Each repetition re-ran the search
with its own seed and deployed the template it chose. Repetitions 42 and 44
chose `max_num_seqs` 32; repetition 43 chose 128. Within a repetition both
conditions deployed the same template, as registered, but the criterion reads
the spread *across* independent repetitions as noise --- and that spread
(52 s) was a configuration difference. Computed mechanically it said "met",
and it would have for any outcome. `analyze.py` now refuses the verdict when
the repetitions deployed different templates.

**The deployed configuration saturates at 4.0 rps.** Goodput is 0.27--0.39 of
the offered rate in every run; requests queue for the whole trace and p99
TTFT is 25--77 s, against a predicted 472--597 ms. One A40 decode instance
with 32 or 128 sequences cannot hold the concurrency this trace needs (about
four requests a second of about six hundred output tokens each). In that regime
the NIC's load is invisible: paired by repetition, the shared condition moved
p99 TTFT by -374, +5 and -95 ms, against a predicted +51 ms each time, and the
KV transfer it would slow is a few milliseconds per request.

Every P/D template was predicted **infeasible** before the run (TPOT 160.7 ms
against 60), and the registered selection rule --- feasible first, then the
lower predicted TTFT --- therefore picked among infeasible candidates. The
planner said the deployment would miss its SLO; it did, by far more than it
predicted on TTFT and by far less on TPOT (41--97 ms measured).

**What a valid rerun needs, which is a registration change and not taken
here.** A fixed template across repetitions, and an offered rate below that
template's measured capacity, found by a knee pilot as E-G5's aggregated arm
did. Both change row 5 and must be registered before the rerun's first
request.

**What it affects.** `experiments/e_g5/analyze.py`,
`experiments/results/e_g5_real_hardware.md`, `paper/sections/limits.tex`.
The `\pending{E-G5: inter-node P/D}` stays pending.

## GS-34 — inter-node P/D contention, measured: far smaller than the model predicts · 2026-10-01

**Result, under preregistration row 7.** Template fixed
(`…s32-t8192`), 1 rps from the knee pilot, three ABAB pairs, every request
paired with itself across the two conditions. All six runs: 150/150 requests,
no failures, every length confirmed by the server, background duty cycle
0.600 in each shared run.

| pair | KV interval, independent | shared | change | predicted |
| --- | --- | --- | --- | --- |
| 42 | 216.40 ms | 219.36 ms | +2.96 ms | +14.45 ms |
| 43 | 218.22 ms | 220.26 ms | +2.05 ms | +14.45 ms |
| 44 | 217.77 ms | 217.48 ms | -0.28 ms | +14.45 ms |

Mean change **+1.57 ms** (SD 1.67 ms across pairs) against a predicted
**+14.45 ms**: ratio **0.11**, same sign, outside the registered 0.5--2 band.
**The criterion is not met.** p99 TTFT moved -1.4, +9.6 and -9.5 ms against a
predicted +50.9 ms. With three pairs the measured effect is not
distinguishable from zero; that it is far below the prediction is.

**What this does and does not say.** The model enters the background as a
standing reservation of its duty cycle, so it slows the transfer 2.5x; a
competing flow at that duty cycle would, under processor sharing, slow it
about 1.6x (+5.8 ms) --- both stated in row 7 before the run. The hardware is
below even that. Candidate reasons (RDMA READ against SEND arbitration, the
pull overlapping other work, the transfer not being on the interval's
critical path) are not separated by anything measured here, and none is
offered as the explanation.

**On the paper.** The last `\pending` is replaced by this result (C30), the
conclusion no longer says the inter-node case waits on a router, and the
claim is written as a miss.

## GS-35 — the `burst` pattern meant two opposite things, and neither reached the hardware · 2026-10-01

**Decision.** Before E-G5's matrix is widened to the `burst` pattern and the
`low` / `high` levels, two defects in how a pattern reaches the two halves of
a condition are fixed, and the goodput floor is made per level.

**1. The hardware trace ignored the pattern.** `workload_at` passed
`--burstiness 1.0` to `make_workload.py` whatever the condition said, while
the simulator's spec carried the pattern's value. A `burst` condition would
have been predicted on one arrival process and measured on another. It now
passes the pattern; a Poisson trace keeps its old file name, so every row
already measured still names its trace.

**2. `burstiness` is reciprocal between the two generators.**
`make_workload.py` follows vLLM: Gamma inter-arrivals with shape =
`burstiness`, smaller is burstier. heteropilot's `planner/util/workload.py`
draws shape = **1 / burstiness**, so there larger is burstier. The matrix's
`burst = 0.2` is vLLM's convention (coefficient of variation sqrt(5) = 2.24);
written into heteropilot's spec as 0.2 it is shape 5 (CV 0.45) --- arrivals
*smoother than Poisson*. Even with defect 1 fixed, a `burst` condition would
have simulated smoothness and measured bursts. `conditions.PATTERNS` is now
documented as the Gamma shape, `spec_burstiness` writes 1/shape into the spec,
and `test_the_burst_pattern_means_the_same_thing_to_both_generators` draws
from both real generators and requires the same CV; with the old spec value it
fails at 0.447 against 2.236.

**3. The goodput floor was the knee's at every level.** Spec S's
`min_goodput_rps` = 2.3 is row 4's rule --- 95 % of the lowest measured
achieved goodput across T1, T2, T3 --- applied at 4 rps. At 2 rps no
deployment can complete 2.3 requests a second, so every candidate would be
infeasible on goodput by construction. `conditions.goodput_floor(level)`
refuses a level with no registered floor. The `low` and `high` floors are
measured by a pilot (normal pattern, T1--T3, seed 42, floor 0.01, written to
`raw/pilot-levels/` and excluded from validation) and registered in row 8 by
row 4's own rule, before the widened matrix's first request.

**What it affects.** `experiments/e_g5/{conditions,deploy_and_bench}.py`,
`tests/test_e_g5_harness.py`, preregistration row 8.

## GS-36 — the goodput floor follows row 4, and it changes which candidates the search looks at · 2026-10-01

**The instruction and the registration disagreed, and the registration was
followed.** The work order for E-G5's widening gave the floor as "row 4's rule
(offered x 0.95)". Row 4 records that 95 % of *offered* (3.8 at the knee) was
drafted, found unreachable by construction --- a finite trace's drain tail
keeps achieved goodput below offered even with no queue --- and replaced
before registration by **95 % of the lowest measured achieved goodput across
T1, T2, T3** (2.3). Confirmed with the user, who identified the instruction as
a misquotation. Every level uses row 4's actual rule: `low` 1.6 from its pilot,
`knee` 2.3 unchanged, `high` from a pilot that deploys the knee's
recommendation template at 6 rps on each placement, since at `high` there is
no recommendation of its own to measure.

**The floor's value changes the candidate set the ranker sends to the
simulator.** At `high`, T1, seed 42, budget 16: with a floor of 0.01 the
sixteen representatives evaluated were all infeasible (p99 TTFT 3409 ms and
up); with no floor, a different sixteen were evaluated and four were predicted
feasible (`tp2-dp1-s256-t8192` among them). Nothing about those four changed:
the floor enters the ranker's goodput-ratio term and so reorders which
representatives fill the budget. A near-zero floor is therefore not "no
floor" to the search. This is recorded as a property of the ranker for later
diagnosis; the ranker is not changed (GS-31's narrowing stands). Searches run
with 0.01 or with no floor are not used for any registered result.

**Consequence for the design.** "The search returns no feasible plan of this
size at `high`" was a statement about a budget, not about the space. Row 8
therefore evaluates `high`'s scope exhaustively, once, and reports the
registered budget's recall against it.

## GS-37 — the widened E-G5 matrix: the TP=4 group is the simulator's blind spot · 2026-10-02

**What ran.** Row 8's 45 added conditions, all completed with no refusal and
no failure. Another tenant held all eight GPUs on both nodes from 18:05 to
about 22:32 on 2026-10-01; nothing was measured beside it --- a watcher
started the grid only after ten quiet minutes, and every provenance file
records zero GPU tenants after its run.

**Verdict agreement, by pattern and level** (rows whose deployed placement was
simulated to a verdict, against the hardware's):

| pattern | level | rows | agree |
| --- | --- | --- | --- |
| normal | low | 19 | 19 |
| normal | knee | 27 | 21 |
| normal | high | 27 | 20 |
| burst | low | 15 | 9 |
| burst | knee | 15 | 9 |
| burst | high | 21 | 15 |

**The four-way group is predicted to meet its target almost everywhere and
misses it almost everywhere.** T3's recommendation is predicted *met* at every
level of both patterns; the hardware meets it only at normal-low (394 ms) and
misses at normal-knee (1.9 s), normal-high (13.3 s), burst-low (1.3 s),
burst-knee (8.5 s) and burst-high (17.1 s). At `high` that is, in row 8 (e)'s
words, a **false positive of the 6 rps prediction**, six rows of six. The two
TP=2 placements are predicted correctly far more often; the one T1 exception is
`normal-high`, where seeds 43 and 44 were predicted to miss (554, 841 ms) and
the hardware met (497, 501 ms) --- a false negative, the opposite direction.

**The closest miss: right direction, wrong axes.** burst-high T1 and T2 have no
feasible plan of their size in the exhaustive scope; the closest miss
(`tp1-dp2-s128-t8192`, `worst_overshoot` 0.29, the same candidate as
heteropilot's `closest_plan`) missed on hardware in 6 of 6 rows --- the
infeasibility verdict holds --- but on the predicted axes in 0 of 6: predicted
TTFT and goodput, measured TTFT and TPOT.

**K = 16 against the exhaustive scope** (row 8 c, seed 42): normal T1 and T2
4/4; normal T3 16/676, every candidate it evaluated being feasible, so bounded
by the budget rather than missed; **burst T3 0/172**.

**Conditions with nothing to deploy.** normal-low seeds 42 and 44 (T1, T2) and
burst-low and burst-knee (T1, T2, every seed) returned no feasible candidate of
the condition's size within K = 16, so only their bound-stress rows were
measured. For normal-low the cause is measured: the simulator predicts an SLO
goodput of 1.525 at seed 42 against a floor of 1.6 that row 4's rule derived
from the *hardware's* 1.714, so every candidate fails on goodput by
prediction. For burst-low and burst-knee it is not diagnosed here, and those
levels were not evaluated exhaustively.

**Two defects, recorded and not fixed mid-run.**

- *Pooling would have rewritten the paper.* The analysis grouped every
  recommendation by placement regardless of level, so with the widened rows
  the paper's T2/T1 ratio macro moved from 8.3 to 1.6 and the agreement macros
  from 21/27 to 93/124. The primary tables now read normal x knee only, and the
  widened matrix has its own section and column names; the macros are back to
  their registered values.
- *The feasible-marginal alternative repeats the recommendation.*
  `feasible_marginal` excludes the recommendation's **embedding** id but not its
  **template**, so it can select the same template at another placement, which
  the condition then deploys at the same devices: the two rows are one
  configuration measured twice. That has been so since the first E-G5 run.

**What it affects.** `experiments/e_g5/analyze.py`,
`experiments/results/e_g5_real_hardware.md`, the raw directories of the 45
conditions. The paper's numbers are unchanged; the widened findings are for P7
to place.

## GS-38 — the adapter told the simulator T3's first NVLink pair; four post-hoc analyses · 2026-10-02

**The check, and its two numbers.** The T3 simulator configuration
(`outputs/e_g5/*__T3__*/*/sim/sims/*/cluster.json`) carried **`link_bw` =
112.5 GB/s**. That is neither the path's bottleneck as the graph carries it
(25.12, the PCIe p2p figure) nor the busbw E-G4 condition 5 measured at world 4
(**8.71**): it is gpu0-gpu1's NVLink edge capacity. `_flow_bottleneck` read
`flow.allowed_paths[0]` only, and a TP flow carries one path set per rank pair
(six for TP=4), the first being gpu0-gpu1. It also never consulted
`Link.measurement_for`, so heteropilot's `(collective, world_size)` selection
(S3/D112) was bypassed for every TP group. **An adapter defect, not a predictor
limit.**

**Fix.** `graphsearch/adapter.py` `_tp_bottleneck`: the minimum over every
pair's best path, each link replaced by its measured `all_reduce` busbw at
`world_size = tp` where the fixture has one, else the edge capacity net of its
shared resource as before. What the simulator is told now: T1 112.5 -> **39.24**,
T2 25.12 -> **19.34**, T3 112.5 -> **8.71** (`tests/test_adapter_tp_bottleneck.py`).
The work order's "T1 52.3" is the NVLink pair's *p2p* figure (52.64); its
`all_reduce` world-2 measurement is 39.24, and that is what an all-reduce group
is given. `conditions.py`'s T1 description had the PCIe figure (19.34) as
NVLink's busbw; the label is corrected for later runs, and the raw files that
recorded it are left as written.

**Re-prediction, post hoc, no deployment** (`experiments/e_g5/repredict.py`,
`raw/repredict-gs38.json`): every deployed row, 124, simulated again at its own
placement, seed and spec with a fresh cache. The envelope key bands `link_bw`
(`network_class`), and the corrected figures fall in other bands, so the old
cache could not have answered; a fresh one is used regardless. A first pass at
14-way parallelism lost 12 T3 simulations to the harness's 1800 s timeout (the
simulations finished after the predictor had given up); a second pass at 6-way
with 7200 s evaluated them, and no row the first pass evaluated changed.
Recommendation and closest-miss rows, all patterns and levels:

| placement | rows | original agrees | re-prediction agrees | false positives, original -> re |
| --- | --- | --- | --- | --- |
| T1 | 10 | 8 | 6 | 0 -> 0 |
| T2 | 10 | 10 | 10 | 0 -> 0 |
| T3 | 18 | 3 | 17 | 15 -> 0 |

T3's fifteen false positives are gone: every T3 row the hardware missed is now
predicted to miss. The magnitude is still short at high load (burst-high
predicted 9.7-12.2 s against 16.7-17.2 s measured; normal-knee 0.74-1.34 s
against 1.83-2.05 s) and normal-low seed 43 becomes a false negative (597 ms
predicted, 394 measured). **T1 gets worse**: NVLink at 39.24 instead of 112.5
moves normal-knee seeds 42, 43 and normal-high seed 43 to predicted misses that
the hardware met (597, 572, 655 ms predicted; 405, 421, 497 measured). The
hardware columns and every registered verdict are unchanged; the paper's
macros read the registered predictions and do not move.

**burst T1/T2 at low and knee: no recommendation, diagnosed** from the registered
runs' cached predictions (`floor_diagnosis.py`, run under the pre-GS-38 adapter so
that every lookup hit, cache misses 0). **Every evaluated candidate of size 2
failed p99 TTFT** in all twelve rows; none failed on goodput alone; the lowest
predicted p99 TTFT among them is 607 ms against 550. At knee they fail goodput
too. **Not the normal-low goodput-floor artifact**, and relaxing the floor
recovers nothing.

**Floor sensitivity, analysis only.** Re-judging the same cached predictions at
1.4, 1.5 and 1.6 (latency verdicts as the run's feasibility reports gave them,
goodput re-tested): the only conditions whose answer depends on the floor are
**normal-low T1 and T2, seeds 42 and 44**, where a recommendation exists at 1.4
and 1.5 (16 feasible of size 2) and none at 1.6 -- its template,
`tp2-dp1-s128-t2048`, is the one seed 43 deployed. Every other condition has the
same answer and the same template at every floor tried. This is the property of
a floor derived from the hardware (row 4) and applied to a simulator whose
goodput prediction is lower than the hardware's: at low load the floor sits
between the two. The evaluated set is the registered floor's; a run made at
another floor would reorder the ranker's budget (GS-36).

**`feasible_marginal` must be a different template.** The condition deploys
every row at its own placement, so another embedding of the recommendation's
template is the same deployment; 26 of the 32 measured marginal rows were
exactly that (all but normal- and burst-T3-high). The rule now excludes the recommendation's template for later
runs (`tests/test_e_g5_harness.py`); the measured rows are labelled *duplicate
of recommendation* in the results and are not redeployed.

**From the review of this change.** A measured figure is capped by its
shared resource's availability (it was taken on an idle link), and converted
with the link's declared unit; a template with pp > 1, whose TP flow's
participants are tp x pp ranks, keeps the first-pair figure and says so in the
basis rather than being given a wrong world size. None of these touches an
E-G5 number: the a40x8 reservations are zero, its units GB/s, and no E-G5
template has pp > 1 -- the test still gives 39.24 / 19.34 / 8.71. The selector
is asked with binding `unknown`, which ignores binding; every a40x8
measurement is `numa_pinned`, so it chooses the same figure.

**Not fixed here, recorded.** The same first-pair read remains in
`embeddings._resource_demand`, `contention.py` (both fluid models) and
`ranker.py`'s cut margin. Those decide demand, contention and order, not what the
simulator is told, and changing them would change which candidates the
registered runs reached; they are left for a step of their own.

**What it affects.** `graphsearch/adapter.py`, `experiments/e_g5/{repredict,
floor_diagnosis,analyze,deploy_and_bench,conditions}.py`,
`experiments/results/e_g5_real_hardware.md`, preregistration row 9.

## GS-39 — E-G8 needs no heteropilot claim PR, and its KV path waits on BAR1 · 2026-10-09

**Decision.** E-G8 is claimed by the existing `E-G*` row of heteropilot's
`CLAUDE.md` id table, so revision R5 opens no docs-only PR there. Its KV path is
not registered until the user chooses between the GPUDirect path (which needs
the A5000's BAR1 enlarged) and the host-staged one (`kv_buffer_device: cpu` at
both ends).

**Why.** `WORK_ORDER_revision.md` R5 asks for E-G8 to be added to "the E-G*
claim list, as E-G3 to E-G7 were". The real table has one row,
`` `E-G*` | `WORK_ORDER_graph_search.md` (claimed 2026-09-22) — runs in
`swsok/heteropilot-graphsearch` ``. E-G3 to E-G7 were never listed one by one.
`tests/test_experiment_ids.py` there reads ids defined in that repository's
work orders, and E-G8 is defined in this one. The real code wins
(CLAUDE.md); a row per id would contradict the tag rule the table exists to
state.

The R5.0 probes (`experiments/pd_probe/a5000/README.md`) showed four things.
vLLM 0.19's `NixlConnector` registers the whole KV cache with the NIC. Every
A5000 here boots with a 256 MiB BAR1, too small for that registration.
A mixed pair (`cuda` on the A40, `cpu` on the A5000) fails its handshake.
`cpu`/`cpu` works but stages KV through host memory at both ends, a different
path from E-G5's. The GPUDirect path does work on `a5000-2` GPU 0 once its
BAR1 is resized to 32 GB at run time. That resize does not survive a reboot,
and `a5000-1`'s BIOS setting has not yet taken effect. The path is part of
what row 11 registers, so it is decided before the first request and not
after.

**What it affects.** `WORK_ORDER_revision.md` R5 (the claim PR is not made),
row 11's conditions, and `experiments/pd_probe/a5000/`.

**Decided the same day (user).** E-G8 runs on `a5000-2` GPU 0 over the
GPUDirect path, which is E-G5's path. `a5000-1` is not used, because its BIOS
setting did not take. BAR1 is resized by hand with
`experiments/pd_probe/a5000/gpu0_rebar.sh` before every run, and its output
goes into the run's raw files. A boot-time unit doing the same unbind hung
the node, and a load-time hook was declined as boot persistence.
