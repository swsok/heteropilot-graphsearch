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
| The correctness result survives replacing the mock with LLMServingSim | — (E-G3) | real-sim | Pending |
| The compression's own cost is smaller than the simulation time it saves | — (E-G3, `saving` column) | real-sim | Pending |
| A processor-sharing contention model predicts measured transfer time better than pricing each flow alone | — (E-G4) | hardware | Pending |
| The recommended placement meets its SLOs on real hardware | — (E-G5) | hardware | Pending |
| A candidate proved impossible really does miss the constraint it was proved to miss, on hardware | — (E-G5, boundary alternative) | hardware | Pending |
| Two placements differing only in which contended uplink they cross differ measurably in TTFT | — (E-G5, condition iii) | hardware | Pending |
| The search scales to 128 devices within a stated wall-time budget | — (E-G6) | mock | Pending |
| Dropping the shared boundary from the signature produces mis-merges | — (E-G7, `no_boundary` arm) | mock | Pending |
| The baseline comparison is fair: same candidate space, predictor and cache, with the template-level scoring credited generously to the baseline | — (E-G7) | mock | Pending |

## Retracted

| Claim | Where it was withdrawn | Why |
| --- | --- | --- |
| The oracle can compare templates rather than placements | `docs/decisions.md` GS-9 | An oracle that does not see the placement makes the correctness check vacuous; retracted with numbers at G14. |

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
