# E-G1 — toy pilot

> **MockPredictor results. Not performance numbers.** Every figure here comes from a deterministic mock that respects the same physics as the bounds; none of it is a measurement or a simulation of any hardware. `correct` is the column to read first.

| fixture | templates | embeddings | representatives | compression_ratio | oracle_simulations | proposed_simulations | feasible_recall | cost_regret | false_infeasible | mismerged_pairs | correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| graph-toy-abcde | 108 | 240 | 54 | 0.225 | 240 | 54 | 1.0 | 0.0 | 0 | 0 | True |
| graph-toy-shared-nic | 42 | 72 | 72 | 1.0 | 72 | 72 | 1.0 | 0.0 | 0 | 0 | True |
| graph-toy-asym | 150 | 360 | 360 | 1.0 | 360 | 360 | 1.0 | 0.0 | 0 | 0 | True |
| heterogeneous-lab | 36 | 66 | 48 | 0.7273 | 66 | 48 | 1.0 | - | 0 | 0 | True |

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
- **graph-toy-shared-nic** wires only `gpu0` to the NIC, so the two GPUs in a node are not interchangeable and even an intra-node pair has no symmetry to fold. `graph-toy-abcde` gives both GPUs uplink access (the research design's §9 says they have it), which is most of why it reaches 0.225.

`feasible_recall` is 1.0 and `cost_regret` 0.0 on every row because the K schedule defaults to every representative here. A budget makes recall fall and correctness hold -- that separation is what `tests/test_oracle_agreement.py` pins.

`BinnedRooflineRanker` is heteropilot's own surrogate and is available as a baseline through the same ABC; it is not run here because a top-K comparison needs a corpus where the SLO actually binds, which the toy fixtures do not provide.
