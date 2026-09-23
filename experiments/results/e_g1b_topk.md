# E-G1b — top-K, against a spec that binds

> **MockPredictor results. Not performance numbers.** Every figure here comes from a deterministic mock that respects the same physics as the bounds; none of it is a measurement or a simulation of any hardware.

| fixture | arm | k | simulations | feasible_recall | cost_regret | first_feasible_at_sim |
| --- | --- | --- | --- | --- | --- | --- |
| graph-toy-abcde | oracle | 528 | 528 | 1.0 | 0.0 | 19 |
| graph-toy-abcde | heteropilot | 4 | 4 | 0.25 | 0.0 | 1 |
| graph-toy-abcde | graphsearch | 4 | 4 | 0.0 | - | - |
| graph-toy-abcde | heteropilot | 8 | 8 | 0.5 | 0.0 | 1 |
| graph-toy-abcde | graphsearch | 8 | 8 | 0.5 | 0.0 | 5 |
| graph-toy-abcde | heteropilot | 16 | 16 | 0.5 | 0.0 | 1 |
| graph-toy-abcde | graphsearch | 16 | 16 | 1.0 | 0.0 | 5 |
| graph-toy-shared-nic | oracle | 288 | 288 | 1.0 | 0.0 | 19 |
| graph-toy-shared-nic | heteropilot | 4 | 4 | 0.3333 | 0.0 | 1 |
| graph-toy-shared-nic | graphsearch | 4 | 4 | 0.0 | - | - |
| graph-toy-shared-nic | heteropilot | 8 | 8 | 0.5 | 0.0 | 1 |
| graph-toy-shared-nic | graphsearch | 8 | 8 | 0.5 | 0.0 | 5 |
| graph-toy-shared-nic | heteropilot | 16 | 16 | 0.5 | 0.0 | 5 |
| graph-toy-shared-nic | graphsearch | 16 | 16 | 1.0 | 0.0 | 5 |

## The corpus

- **graph-toy-abcde**: 16 of 528 placements meet both SLOs (3.0%). A top-K row is worth reading only because this is not 100%.
- **graph-toy-shared-nic**: 12 of 288 placements meet both SLOs (4.2%). A top-K row is worth reading only because this is not 100%.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/scripts/e_g1b_topk.py \
    --out experiments/results/e_g1b_topk.md
```

## What the two columns say

**The heteropilot arm plateaus.** Its recall stops at 0.5 on both fixtures and does not move between k=8 and k=16, while this search reaches 1.0 at k=16. The reason is structural rather than a matter of ranking: the arm judges templates, and half the feasible placements here belong to templates whose other placements are not feasible. One verdict cannot be right about both, and the generous credit this table already gives it is what keeps the number as high as 0.5.

**And this search loses at k=4, on both fixtures.** It recommends nothing: the service-margin ranker's first four representatives are all infeasible, while heteropilot's surrogate has an answer in its first pick. A small K is where a ranker is actually tested, and this one is worse there. The row is in the table for that reason.

## Reading the table

`feasible_recall` is over PLACEMENTS in both arms, and the heteropilot rows are credited generously: that arm ranks and judges templates, so one verdict is allowed to stand for every placement of the template. It cannot name a placement, so there is no stricter reading that would be fair to it.

`first_feasible_at_sim` is the ordinal of the simulation that first produced a candidate the run ended up calling feasible. `1` means the ranker's first pick was an answer; `-` means the run never found one. The same counting predictor records it in both arms.

A `cost_regret` of `-` means the run recommended nothing, or the fixture priced nothing the objective could score. It is not a zero -- a regret that cannot be computed is reported as uncomputed.

`simulations` is not comparable to `k` directly: heteropilot simulates at most `top_k` TEMPLATES, this search simulates at most `k` REPRESENTATIVES, and a representative stands for a class of placements whose size is in E-G1's compression column.
