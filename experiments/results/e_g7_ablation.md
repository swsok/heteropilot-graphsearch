# E-G7 — ablation

> **MockPredictor results. Not performance numbers.** Every figure here comes from a deterministic mock that respects the same physics as the bounds; none of it is a measurement or a simulation of any hardware.

| fixture | arm | false_infeasible | mismerged_pairs | correct | compression_ratio | representatives | simulations | feasible_recall | cost_regret | first_feasible_at_sim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| graph-toy-shared-nic | full | 0 | 0 | True | 0.2083 | 60 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | no_boundary | 0 | 0 | True | 0.1042 | 30 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | no_compression | 0 | 0 | True | 1.0 | 288 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | no_bounds | 0 | 0 | True | 0.2083 | 60 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | ranker=service_margin_v1 | 0 | 0 | True | 0.2083 | 60 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | contention=fluid | 0 | 0 | True | 0.2083 | 60 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | full | 0 | 0 | True | 0.1477 | 78 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | no_boundary | 0 | 0 | True | 0.1477 | 78 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | no_compression | 0 | 0 | True | 1.0 | 528 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | no_bounds | 0 | 0 | True | 0.1477 | 78 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | ranker=service_margin_v1 | 0 | 0 | True | 0.1477 | 78 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | contention=fluid | 0 | 0 | True | 0.1477 | 78 | 16 | 1.0 | 0.0 | 1 |

## What each arm removes

| arm | removes |
| --- | --- |
| `full` | nothing -- the search as it ships |
| `no_boundary` | the shared-resource boundary, from the signature |
| `no_compression` | the folding entirely; one representative per placement |
| `no_bounds` | the RELAXATIONS. compat and memory are exact checks and stay |
| `ranker=service_margin_v1` | the G15 correction |
| `contention=fluid` | nothing; it ADDS the fluid model |

## Criterion 2 — contribution A, on the pair it is about

The corpus-wide `no_boundary` row above **cannot** answer this, and reading it as if it could was the first version's mistake. `mismerged_pairs` compares feasibility verdicts and costs, not metrics: under the fixed tight spec both placements sit far above the 50 ms TTFT, both are infeasible, the verdicts agree — so the fold happens and nothing detects it. That zero is a property of the ruler.

So the threshold is **derived from the oracle**: both placements are run under a roomy SLO, and the limit is put at the midpoint of the two TTFTs that come back.

| placement | p99 TTFT (ms) |
| --- | --- |
| `pd-nodeX-Z@bd1c59407606` | 527.6249 |
| `pd-nodeY-Z@ba17b8accbfa` | 470.9231 |

Separating threshold: **499.274 ms**. Feasible under it: `pd-nodeY-Z@ba17b8accbfa`.

| arm | representatives | mismerged pairs |
| --- | --- | --- |
| `full` | 2 | 0 |
| `no_boundary` | 1 | 1 |

**Criterion 2 met.** Dropping the boundary folded two placements the oracle judges differently, and the boundary-aware compression on the same spec does not. The pairs:

| a | b |
| --- | --- |
| `pd-nodeX-Z@bd1c59407606` | `pd-nodeY-Z@ba17b8accbfa` |

**Deriving the threshold is not tuning to win.** Tuning to win is moving a parameter until the method looks good. This makes the instrument able to resolve the difference at all, and the claim under test is precisely that a difference exists. The control is the `full` arm on the *same* spec: if it had mis-merged too, the row above would say the finding is against us. `tests/test_oracle_agreement.py::test_dropping_the_boundary_produces_a_mismerge` derives it the same way and states the same reason.

## The corpus-wide `no_boundary` row


**Zero on graph-toy-shared-nic, graph-toy-abcde — and this row is not the place to read criterion 2.** Under the fixed tight spec these placements are all far above the TTFT limit, so they share a verdict and `mismerged_pairs` cannot see the difference even where the fold really happened (watch `compression_ratio` halve). The section above answers criterion 2 on the pair it is actually about.

**This is the only arm where a non-zero `mismerged_pairs` does not stop the run.** Its purpose is to produce one. Every other arm is bound by the common invariant, and a non-zero there is a stop-and-report under work order rule 5.

## Reading the rest

`no_compression` should show the same correctness numbers as `full` and strictly more simulations — one representative per placement means nothing is folded and everything is evaluated separately. If its simulation count matches `full`, the compression folded nothing on that fixture and the row says so rather than the ratio being read as a saving.

`no_bounds` drops the **relaxations** only. `compat` and `memory` are exact feasibility checks, not bounds, and stay on: turning them off would not be an ablation of the elimination, it would be an ablation of the feasibility test.

`contention=fluid` is the one arm that ADDS rather than removes. It changes nothing unless a candidate's own flows overlap on a resource (GS-20), so most rows match `full` — and a run where it changed everything would be a bug rather than a finding.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/scripts/e_g7_ablation.py \
    --out experiments/results/e_g7_ablation.md
```
