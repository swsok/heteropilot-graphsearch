# E-G1 — toy pilot

> **MockPredictor results. Not performance numbers.** Every figure here comes from a deterministic mock that respects the same physics as the bounds; none of it is a measurement or a simulation of any hardware. `correct` is the column to read first.

| fixture | templates | embeddings | representatives | compression_ratio | oracle_simulations | proposed_simulations | feasible_recall | cost_regret | false_infeasible | mismerged_pairs | correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| graph-toy-abcde | 180 | 528 | 78 | 0.1477 | 528 | 78 | 1.0 | 0.0 | 0 | 0 | True |
| graph-toy-shared-nic | 108 | 288 | 60 | 0.2083 | 288 | 60 | 1.0 | 0.0 | 0 | 0 | True |
| graph-toy-asym | 270 | 840 | 840 | 1.0 | 840 | 840 | 1.0 | 0.0 | 0 | 0 | True |
| heterogeneous-lab | 48 | 114 | 72 | 0.6316 | 114 | 48 | 1.0 | - | 0 | 0 | True |

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/scripts/e_g1_toy_pilot.py \
    --out experiments/results/e_g1_toy_pilot.md
```

## Reading the table

`correct` first: it is `false_infeasible == 0 and mismerged_pairs == 0`, and a False there is a bound or an equivalence being wrong, never a tuning issue.

A `compression_ratio` of 1.0 means exact equivalence folded nothing, and each row has its own reason:

- **graph-toy-asym** is the designed failure condition. Five nodes, no two alike in price, uplink capacity or reservation, so no two placements can be isomorphic. It is in the corpus precisely so this number gets reported rather than avoided.
- **graph-toy-shared-nic** is the counterexample fixture, and its row is the one that changed. It used to read `ratio 1.0, mismerged 0` and that was the result of an input with no counterexample in it: the fixture had two nodes and `enable_pd` was never set, so no flow a latency target charges for ever crossed an uplink. It now has three nodes -- X with 6 of its 10 GB/s held, Y and Z free -- and both GPUs wired to the NIC, so `P on X -> D on Z` and `P on Y -> D on Z` differ in nothing but the boundary they cross. Exact equivalence keeps them apart and folds Y with Z; `include_boundary=False` folds all three and the oracle reports the mis-merge (GS-9, retracted and replaced).

`feasible_recall` is 1.0 and `cost_regret` 0.0 on every row because the K schedule defaults to every representative here. A budget makes recall fall and correctness hold -- that separation is what `tests/test_oracle_agreement.py` pins.

`BinnedRooflineRanker` is heteropilot's own surrogate and is run as a baseline in **E-G1b** (`experiments/results/e_g1b_topk.md`), against a copy of the toy spec whose TTFT and TPOT limits actually bind. It is not run here because a top-K comparison against a corpus where everything is feasible measures nothing.

A `cost_regret` of `-` is not a zero. It means the fixture priced nothing the objective could score, so the planner declined to guess rather than inventing a number -- `heterogeneous-lab` carries no `price_per_hour_usd`. A regret that cannot be computed is reported as uncomputed.
