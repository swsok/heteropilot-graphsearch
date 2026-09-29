# Section map

Which section says what, from which research-design section, on which evidence,
and which claim ids in `CLAIMS.md` license its sentences.

**A section may write a claim in the indicative only if that claim's row reads
`Established`.** A `Pending` row is written as "Table N reports ..." -- a form
that does not change when the result arrives -- and is marked `\pending{E-G5}`.
The macro sets a margin note in the draft and is redefined to a compile error
for the final build, so a forgotten placeholder cannot be submitted.

Every paragraph carries a `% claim: C<n>` comment. `make check` reads those and
refuses a paragraph whose claim is not `Established`, unless the paragraph also
carries `% pending`.

| # | file | design section | content and evidence | claims | left blank |
| --- | --- | --- | --- | --- | --- |
| 1 | `intro.tex` | 1, 13 | the problem (heterogeneous clusters, several bus kinds, minimum-cost placement under SLOs is expensive to simulate); the observation (repeated structure folds by exact equivalence, but only if the shared boundary is preserved -- design section 5's counterexample); contributions A/B/C with their numbers; one sentence on what is heteropilot's and what is new | C1, C2, C3, C11, C24, C26 | the E-G5 sentence |
| 2 | `background.tex` | HeteroPilot `CLAUDE.md`, 4 | the execution-island abstraction; island-level enumeration is already an implicit compression; `EnvelopeCache` twin merging is an *approximate* one (design section 0); LLMServingSim and D3 (the simulator has no link graph) | — | — |
| 3 | `problem.tex` | 2 | inputs (model, traffic, SLO, price, runtime); candidate = a complete runnable plan; objective = cost per hour; the constraint table; the five states and "unevaluated is not infeasible" | C2, C3 | — |
| 4 | `graph.tex` | 3 | vertex kinds; bytes/s normalisation and the v1/v2 schemas; the shared-resource auxiliary vertex and its incidence; path sets, cut capacity, boundary context. Foreshadows E-G4: **which resource is shared is settled by measurement, not by declaration** | C15, C16 | — |
| 5 | `candidates.tex` | 4, 5 | template to embedding (canonical folding, the closed form for `skipped_symmetric` -- GS-25); candidate-graph labels (role, tp, price, power, boundary resources); WL bucket then VF2 to decide; never merge on a hash; why the bucket key is the prediction key (GS-5); representative dispatch id (GS-7); the conflict matrix and `multiplicity != max_concurrent`. Design section 9's worked example (45 -> 8 -> 5 -> 3) as one figure | C1, C3, C4, C12, C24 | — |
| 6 | `search.tex` | 6, 7 | the five checks and each one's relaxations; the "if it is not a relaxation, demote it" rule; the cut bound replacing heteropilot stages 4-5 (D122); the service-margin ranker (risk proxy, cost, diversity) and the G15 correction to its goodput denominator (GS-12); the K schedule, budget and certify modes, `SearchAudit`; restore and the reservation re-check | C2, C5, C6, C7, C8, C9 | — |
| 7 | `adapter.tex` | 8 | `compile_embedded` and `TopologyLossReport` (what was *not* passed on, D124/GS-8); the hook that prices P/D before the verdict (D125); the cache signature (D126/GS-16); `FluidContentionModel` -- processor sharing, and candidates do not contend with each other (GS-20) | C10, C13, C15 | — |
| 8 | `eval.tex` | 12 | 8.1 setup (fixtures, specs, three predictors, pre-registration). 8.2 correctness -- E-G3 (real sim; `correct` 3/3, `complete` False 3/3 with the unjudged counts, saving). 8.3 compression and its cost -- E-G1 and E-G6 against device count and symmetry, and the asymmetric failure condition. 8.4 contribution A -- E-G7's ablation. 8.5 search quality -- E-G1b, E-G2, E-G7 holdout. 8.6 the contention model -- E-G4. 8.7 hardware -- **the E-G5 slot** | C1–C13, C15–C17, C21, C23–C26 | 8.7 entirely; 8.2's SIM_ERROR cause; 8.6's location (b) row; 8.5's real-lab holdout row |
| 9 | `related.tex` | 13 | Helix, Vidur, DistServe, LLMServingSim 2.0, Frontier -- two lines each: what overlaps, what differs | — | the 2026 H2 candidates |
| 10 | `limits.tex` | 11, 12, 13 | the MVP adapter cannot pass shared resources to the simulator; fluid is not packet-level and stops at 128 MiB; hardware covers GPU nodes only (no furiosa deploy backend); learned rankers, mixed TP and KV conversion are future work; the certificate is bounded by the declared candidate space and the evaluation model | C13, C14, C15, C22 | — |
| 11 | `conclusion.tex` | — | one sentence per contribution; the hardware result is `\pending` | C1, C2, C24 | E-G5 |

## The reuse table

Contribution C needs it and it is written by hand into `tables/reuse.tex`,
because none of it is a measurement: three columns for heteropilot modules
reused, hooks H1-H5 with their deviation ids (D120-D126), and the thirteen new
`graphsearch` modules.

## What this paper does not claim

`CLAIMS.md` fixes five, and `make check` greps the draft for the two the
research design names outright: that this is the first graph representation of
a cluster, and that a Top-K procedure guarantees a global optimum.
