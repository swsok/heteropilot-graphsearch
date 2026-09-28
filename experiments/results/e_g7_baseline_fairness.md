# E-G7 — baseline fairness

> **MockPredictor results. Not performance numbers.** Every figure here comes from a deterministic mock that respects the same physics as the bounds; none of it is a measurement or a simulation of any hardware.

All arms run over the same generated candidates, the same predictor and the same spec. A comparison is only worth reading if the arms were asked the same question.

| fixture | arm | k | simulations | feasible_recall | cost_regret | first_feasible_at_sim |
| --- | --- | --- | --- | --- | --- | --- |
| graph-toy-abcde | oracle | 528 | 528 | 1.0 | 0.0 | - |
| graph-toy-abcde | greedy | 1 | 1 | 0.0625 | 0.0 | 1 |
| graph-toy-abcde | surrogate_topk | 4 | 4 | 0.25 | 0.0 | 1 |
| graph-toy-abcde | graphsearch | 4 | 4 | 0.5 | 0.0 | 1 |
| graph-toy-abcde | surrogate_topk | 8 | 8 | 0.5 | 0.0 | 1 |
| graph-toy-abcde | graphsearch | 8 | 8 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | surrogate_topk | 16 | 16 | 0.5 | 0.0 | 1 |
| graph-toy-abcde | graphsearch | 16 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | surrogate_topk | 30 | 30 | 0.5 | 0.0 | 5 |
| graph-toy-abcde | graphsearch | 30 | 30 | 1.0 | 0.0 | 1 |
| graph-toy-abcde | surrogate_topk | 50 | 50 | 0.5 | 0.0 | 5 |
| graph-toy-abcde | graphsearch | 50 | 50 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | oracle | 288 | 288 | 1.0 | 0.0 | - |
| graph-toy-shared-nic | greedy | 1 | 1 | 0.0833 | 0.0 | 1 |
| graph-toy-shared-nic | surrogate_topk | 4 | 4 | 0.3333 | 0.0 | 1 |
| graph-toy-shared-nic | graphsearch | 4 | 4 | 0.5 | 0.0 | 1 |
| graph-toy-shared-nic | surrogate_topk | 8 | 8 | 0.5 | 0.0 | 1 |
| graph-toy-shared-nic | graphsearch | 8 | 8 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | surrogate_topk | 16 | 16 | 0.5 | 0.0 | 5 |
| graph-toy-shared-nic | graphsearch | 16 | 16 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | surrogate_topk | 30 | 30 | 0.5 | 0.0 | 5 |
| graph-toy-shared-nic | graphsearch | 30 | 30 | 1.0 | 0.0 | 1 |
| graph-toy-shared-nic | surrogate_topk | 50 | 50 | 0.5 | 0.0 | 5 |
| graph-toy-shared-nic | graphsearch | 50 | 50 | 1.0 | 0.0 | 1 |

## Where the scoring favours the baseline, deliberately

**heteropilot ranks and judges TEMPLATES.** It cannot name which devices a candidate runs on, so one verdict stands for every placement of that template, and every one of them is credited to it. That is the most favourable reading available and it is the one used here. There is no stricter reading that would be fair to it, and winning on that technicality would not be winning.

`greedy` gets **one** simulation and is not being beaten for it. It is the floor — what a planner gets without any search at all — not a contender. A method that needs sixteen simulations to beat a method that needs one has to say so, and this table does.

## heteropilot's own K=50 gap, reproduced

`vendor/heteropilot/docs/surrogate_topk_regret.md` records efficiency-ordered rankers false-infeasible all the way to K=50 on both of its fixtures. Run here, on this corpus:

- **graph-toy-abcde** — at K=50 the surrogate reaches recall 0.5, this search 1.0.
  Still short of the oracle at K=50, which is the shape `surrogate_topk_regret.md` describes -- reproduced here rather than cited.
- **graph-toy-shared-nic** — at K=50 the surrogate reaches recall 0.5, this search 1.0.
  Still short of the oracle at K=50, which is the shape `surrogate_topk_regret.md` describes -- reproduced here rather than cited.

Reproduced rather than cited on purpose. A baseline's weakness quoted from its own repository is not evidence — nobody can check whether it survives a different corpus, and the obvious suspicion is that it was quoted because it was convenient.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/scripts/e_g7_baseline_fairness.py \
    --out experiments/results/e_g7_baseline_fairness.md
```

## Reading the table

`feasible_recall` is over PLACEMENTS in both arms, and the heteropilot rows are credited generously: that arm ranks and judges templates, so one verdict is allowed to stand for every placement of the template. It cannot name a placement, so there is no stricter reading that would be fair to it.

`first_feasible_at_sim` is the ordinal of the simulation that first produced a candidate the run ended up calling feasible. `1` means the ranker's first pick was an answer; `-` means the run never found one. The same counting predictor records it in both arms.

A `cost_regret` of `-` means the run recommended nothing, or the fixture priced nothing the objective could score. It is not a zero -- a regret that cannot be computed is reported as uncomputed.

`simulations` is not comparable to `k` directly: heteropilot simulates at most `top_k` TEMPLATES, this search simulates at most `k` REPRESENTATIVES, and a representative stands for a class of placements whose size is in E-G1's compression column.
