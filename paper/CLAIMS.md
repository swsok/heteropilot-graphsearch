# Claims audit

Every assertion the paper makes, the file that carries its evidence, what kind
of number that evidence is, and whether it is established yet. A sentence in
`sections/*.tex` that is not a row here does not go in the paper.

The columns are the four the work order fixes: claim, evidence file, source kind
(`mock` / `real-sim` / `hardware`), status. `—` in the evidence column means the
experiment has not run; such a row may not be written into the draft in the
indicative.

**Status vocabulary.** `Established` — the evidence file exists, its numbers
support the claim, and its provenance banner matches the source kind.
`Pending` — the experiment is registered in `docs/preregistration.md` and has
not produced its file. `Not established` — the experiment ran and did not
support the claim; the row stays, with the file, and the paper says so.
`Retracted` — a claim that was made and withdrawn; it stays here so the draft
cannot quietly reacquire it.

**A status may be qualified, and the qualification travels with the claim.**
E-G3's correctness row reads "Established, for the placements the simulator
judged" because `complete` is False on all three fixtures: 6–8 % of placements
came back `SIM_ERROR` and have no verdict either way. Dropping the clause would
turn a bounded result into an unbounded one, which is the failure this file
exists to prevent.

---

## The claims

| Claim | Evidence file | Source kind | Status |
| --- | --- | --- | --- |
| Exact equivalence compression folds a non-trivial fraction of the placement space on a symmetric cluster | `experiments/results/e_g1_toy_pilot.md` | mock | Established |
| Compression and bound-based elimination lose no feasible candidate: `false_infeasible = 0` | `experiments/results/e_g1_toy_pilot.md` | mock | Established |
| Compression merges no two placements the evaluator prices differently: `mismerged_pairs = 0` | `experiments/results/e_g1_toy_pilot.md` | mock | Established |
| On an asymmetric cluster the compression ratio is 1.0, and the corpus reports it rather than avoiding it | `experiments/results/e_g1_toy_pilot.md` | mock | Established |
| Under a binding SLO the adaptive search reaches higher feasible recall than heteropilot's surrogate top-K at k = 8 and k = 16 | `experiments/results/e_g1b_topk.md` | mock | Established |
| At k = 4 the adaptive search does **not** beat that surrogate — it ties on one holdout fixture and trails on the other | `experiments/results/e_g2_topk_holdout.md` | mock | Established |
| The ranker's goodput term must divide by a knob-aware throughput estimate, not by the elimination bound's optimistic ceiling | `experiments/results/e_g2_ranker_diagnosis.md` | mock | Established |
| The correction generalises to fixtures the diagnosis never saw | `experiments/results/e_g2_topk_holdout.md` | mock | Established |
| A ranker change cannot move either correctness number | `tests/test_oracle_agreement.py` | — (test) | Established |
| The correctness result survives replacing the mock with LLMServingSim | `experiments/results/e_g3_real_sim_oracle.md` | real-sim | Established, **for the placements the simulator judged** |
| The compression's own cost is smaller than the simulation time it saves | `experiments/results/e_g3_real_sim_oracle.md` (`saving_s`) | real-sim | Established |
| The compression ratio is a property of the graph, not of the predictor | `e_g1_toy_pilot.md` and `e_g3_real_sim_oracle.md` agree to four decimals on all three shared fixtures | mock + real-sim | Established |
| 6–8 % of placements fail to simulate at all (`SIM_ERROR`), and are reported as `unknown_measurement` rather than infeasible | `experiments/results/e_g3_real_sim_oracle.md` (`unjudged`, `complete`) | real-sim | Established as a limitation; cause **not** established |
| The cause of those `SIM_ERROR` failures | — (P1.5) | real-sim | Pending |
| A processor-sharing contention model predicts measured transfer time better than pricing each flow alone | `experiments/results/e_g4_microbench.md` | hardware | Established, **at location (a) only, and within 4–64 MiB**[^eg4] |
| The A40's intra-node PCIe path is **not** a shared resource: two concurrent peer copies between disjoint device pairs each sustain the single-copy rate | `experiments/results/e_g4_microbench.md` | hardware | Established |
| A two-rank and a four-rank all-reduce over one path are different measurements, so `world_size` belongs in the measurement key | `experiments/results/e_g4_microbench.md` (19.34 against 8.71 GB/s busbw) | hardware | Established |
| The recommended placement meets its SLOs on real hardware | — (E-G5, spec S) | hardware | Pending |
| The throughput upper bound is loose by at least 2.6x against measured capacity on this node | — (E-G5, spec B) | hardware | Pending |
| A candidate proved impossible really does miss the constraint it was proved to miss, on hardware | — (E-G5, boundary alternative) | hardware | Pending |
| Two placements differing only in which wire their tensor-parallel all-reduce crosses differ measurably in served TTFT | `experiments/e_g5/raw/pilot/` | hardware | Established, **intra-node, by a placement the planner cannot name**[^eg5p] |
| The same contrast holds across an inter-node NIC | — (E-G5, location (b)) | hardware | Pending[^locb] |
| The compression ratio and the search's own cost are reported as a function of device count and cluster symmetry | `experiments/results/e_g6_scale.md` | mock | Established, **report-only**[^eg6] |
| Dropping the shared boundary from the signature produces mis-merges | `experiments/results/e_g7_ablation.md` | mock | Established[^eg7] |
| The baseline comparison is fair: same candidate space, predictor and cache, with the template-level scoring credited generously to the baseline | `experiments/results/e_g7_baseline_fairness.md` | mock | Established |
| On a holdout fixed before the scaling grid ran, the invariant holds and the search reaches higher recall at k = 16 than heteropilot's surrogate | `experiments/results/e_g7_holdout.md` | mock | Established, **on the synthetic holdout only**[^eg7h] |

[^eg4]: The verdict computed on the topology `experiments/microbench/PLAN.md`
    registered — `as_planned` — is **FAIL**, at 93.1 % median error. That is a
    wrong declaration of which resource is shared, not a wrong model (GS-22):
    run on the declaration the measurements support, the same model is 1.8 %
    out, and on `bidirectional`, where the pairs genuinely do share endpoints,
    it is within 0.1–2.5 % of the wire against 48–50 % for null. The accuracy
    domain ends at 128 MiB bidirectional, where the pair reaches 1.33x a single
    direction and fluid is a third high (GS-23). The paper states the FAIL, the
    reason, and the boundary; it does not quote the 1.8 % as the result.

[^eg6]: Registered as report-only in `docs/preregistration.md`: E-G6 has **no
    success target**, only the failure condition `saving < 0` at symmetry 1.
    The grid is mock, and the one real-sim condition the research design asks
    for has **not** been run. Research design section 12 forbids presenting a
    128-device simulation as large-scale accuracy validation, and this row is
    written so it cannot be read that way.

[^eg7]: The first attempt found zero mis-merges, because a fixed tight spec
    made both placements infeasible and the oracle agreed they were equally
    bad. The threshold is now derived from the oracle itself, which is what the
    existing test does. The paper explains the derivation rather than quoting
    the count alone, because a mis-merge count depends on where the threshold
    sits.

[^eg7h]: `real-lab-holdout.v2` — the hardware fixture with one uplink
    reservation changed — does not exist, because P3 has not produced it. The
    result file reports that row as `not run` rather than omitting it. Half a
    holdout is not a holdout, and an omitted row reads as a row that passed.

[^eg5p]: Measured on this node's own wires, not across a NIC: TP=2 on the
    NVLink pair against TP=2 across the PCIe bridge, same model, trace, knobs
    and seed. At the knee the difference is 7.65x in p99 TTFT, and two
    independent knee curves show why — the placement moves the knee from 5 rps
    to 4, costing about 20 % of serving capacity. The claim is worth making
    because **heteropilot cannot express the difference at all**:
    `resolve_devices` maps an island to every one of its accelerator ids, so it
    names a template and never a placement. What is *not* claimed is that this
    is the inter-node P/D condition the matrix registered; see the next row.

[^locb]: One machine, one NIC, and `planner/deploy/vllm_cuda.py` builds the
    argv for "one aggregated engine" with no `kv_connector`. Two independent
    reasons, either sufficient. `experiments/e_g5/MATRIX.md` states both before
    any result does.

## Retracted

| Claim | Where it was withdrawn | Why |
| --- | --- | --- |
| The oracle can compare templates rather than placements | `docs/decisions.md` GS-9 | An oracle that does not see the placement makes the correctness check vacuous; retracted with numbers at G14. |
| The shared-NIC ablation cannot produce a detectable mis-merge, so keeping those placements apart is a bet on a contention model that does not exist yet | `docs/decisions.md` GS-9, second finding | Wrong, and for three findable reasons: `enable_pd` defaulted to False so no `PD_KV_TRANSFER` flow had ever been generated; the fixture had two nodes, so a P/D candidate crossed both uplinks either way round; and `bind_predictor` bound the compile hook but not the result hook. With `nodeZ`, `enable_pd=True` and both hooks bound, the counterexample comes out of the current code — `experiments/results/e_g7_ablation.md`. |

The draft writes a retracted claim as "the initial hypothesis was \dots, and the
measurement said otherwise", never by omission. A hypothesis that was tested and
failed is a result.

## Claims this paper does not make

Fixed by research design section 13, and checked at P6.1 against every sentence
of the draft:

1. **"The first to represent a cluster as a graph."** Helix does graph-based
   placement and scheduling already.
2. **"Top-K guarantees a global optimum."** It does not, heteropilot already has
   a Top-K, and this search's own contribution is that it *reports* what it
   never evaluated.
3. **Any mock figure quoted as performance.** Every fixture in this repository
   is fictional. A `mock` row above may support a claim about the *search* and
   never a claim about hardware.
4. **A simulation at 128 devices presented as large-scale accuracy validation.**
   Research design section 12 forbids it by name.
5. **A number computed from a `placeholder` input presented as measured.** The
   five provenance states never merge, and neither do the source kinds in the
   table above.
