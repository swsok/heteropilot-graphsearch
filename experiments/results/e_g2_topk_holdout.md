# E-G2 — holdout: the corrected ranker on fixtures it never saw

> **MockPredictor results. Not performance numbers.** Every figure here comes from a deterministic mock that respects the same physics as the bounds; none of it is a measurement or a simulation of any hardware.

Diagnosed and corrected on **graph-toy-abcde** and **graph-toy-shared-nic** only (`e_g2_ranker_diagnosis.md`). Nothing below was looked at before the correction was fixed. `graphsearch (v1)` is `service_margin_v1`, the pre-G15 estimate; `graphsearch` is the corrected `service_margin`.

| fixture | arm | k | simulations | feasible_recall | cost_regret | first_feasible_at_sim |
| --- | --- | --- | --- | --- | --- | --- |
| graph-toy-asym | oracle | 840 | 840 | 1.0 | 0.0 | 19 |
| graph-toy-asym | heteropilot | 4 | 4 | 0.2 | 0.0 | 1 |
| graph-toy-asym | graphsearch (v1) | 4 | 4 | 0.1 | 0.0 | 3 |
| graph-toy-asym | graphsearch | 4 | 4 | 0.2 | 0.0 | 1 |
| graph-toy-asym | heteropilot | 8 | 8 | 0.4 | 0.0 | 1 |
| graph-toy-asym | graphsearch (v1) | 8 | 8 | 0.2 | 0.0 | 3 |
| graph-toy-asym | graphsearch | 8 | 8 | 0.4 | 0.0 | 1 |
| graph-toy-asym | heteropilot | 16 | 16 | 0.5 | 0.0 | 1 |
| graph-toy-asym | graphsearch (v1) | 16 | 16 | 0.5 | 0.0 | 3 |
| graph-toy-asym | graphsearch | 16 | 16 | 0.8 | 0.0 | 1 |
| heterogeneous-lab | oracle | 114 | 114 | 1.0 | - | 19 |
| heterogeneous-lab | heteropilot | 4 | 4 | 0.375 | - | 1 |
| heterogeneous-lab | graphsearch (v1) | 4 | 4 | 0.125 | - | 3 |
| heterogeneous-lab | graphsearch | 4 | 4 | 0.25 | - | 1 |
| heterogeneous-lab | heteropilot | 8 | 8 | 0.5 | - | 1 |
| heterogeneous-lab | graphsearch (v1) | 8 | 8 | 0.25 | - | 3 |
| heterogeneous-lab | graphsearch | 8 | 8 | 0.5 | - | 1 |
| heterogeneous-lab | heteropilot | 16 | 16 | 0.5 | - | 1 |
| heterogeneous-lab | graphsearch (v1) | 16 | 16 | 0.5 | - | 3 |
| heterogeneous-lab | graphsearch | 16 | 16 | 1.0 | - | 1 |

## Completion condition, k=4

- **graph-toy-asym**, k=4: recall 0.1 → 0.2, first feasible at sim 3 → 1. Completion condition MET (recall rose) (found earlier).
- **heterogeneous-lab**, k=4: recall 0.125 → 0.25, first feasible at sim 3 → 1. Completion condition MET (recall rose) (found earlier).

## The corpus

- **graph-toy-asym**: 20 of 840 placements meet both SLOs (2.4%). A top-K row is worth reading only because this is not 100%.
- **heterogeneous-lab**: 16 of 114 placements meet both SLOs (14.0%). A top-K row is worth reading only because this is not 100%.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/scripts/e_g2_topk_holdout.py \
    --out experiments/results/e_g2_topk_holdout.md
```

## Reading the table

`feasible_recall` is over PLACEMENTS in both arms, and the heteropilot rows are credited generously: that arm ranks and judges templates, so one verdict is allowed to stand for every placement of the template. It cannot name a placement, so there is no stricter reading that would be fair to it.

`first_feasible_at_sim` is the ordinal of the simulation that first produced a candidate the run ended up calling feasible. `1` means the ranker's first pick was an answer; `-` means the run never found one. The same counting predictor records it in both arms.

A `cost_regret` of `-` means the run recommended nothing, or the fixture priced nothing the objective could score. It is not a zero -- a regret that cannot be computed is reported as uncomputed.

`simulations` is not comparable to `k` directly: heteropilot simulates at most `top_k` TEMPLATES, this search simulates at most `k` REPRESENTATIVES, and a representative stands for a class of placements whose size is in E-G1's compression column.
