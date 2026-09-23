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
