# E-G7 — holdout

> **MockPredictor results. Not performance numbers.** Every figure here comes from a deterministic mock that respects the same physics as the bounds; none of it is a measurement or a simulation of any hardware.

The holdout set was fixed in `docs/preregistration.md` on 2026-09-28, before E-G6's grid ran and before anything in it was looked at. No ranker, no δ, no bound and no threshold was modified afterwards.

## Criterion 1 — the invariant, on the holdout

| fixture | embeddings | representatives | compression_ratio | false_infeasible | mismerged_pairs | correct | unjudged | complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| synth-holdout-1 | 36480 | 600 | 0.0164 | 0 | 0 | True | 0 | True |

`correct` is `false_infeasible == 0 and mismerged_pairs == 0`. It is a **condition, not a target** (pre-registration, common section): a False here is a bound or an equivalence being wrong, and the registered response is to stop and report, never to relax the test.

## Criterion 3 — recall against heteropilot's surrogate

| fixture | arm | k | simulations | feasible_recall | cost_regret | first_feasible_at_sim |
| --- | --- | --- | --- | --- | --- | --- |
| synth-holdout-1 | oracle | 36480 | 36480 | 1.0 | 0.0 | 19 |
| synth-holdout-1 | heteropilot | 4 | 4 | 0.0 | - | - |
| synth-holdout-1 | graphsearch (v1) | 4 | 4 | 0.0625 | 0.0 | 3 |
| synth-holdout-1 | graphsearch | 4 | 4 | 0.125 | 0.0 | 1 |
| synth-holdout-1 | heteropilot | 8 | 8 | 0.0 | - | - |
| synth-holdout-1 | graphsearch (v1) | 8 | 8 | 0.125 | 0.0 | 3 |
| synth-holdout-1 | graphsearch | 8 | 8 | 0.375 | 0.021407 | 1 |
| synth-holdout-1 | heteropilot | 16 | 16 | 0.0312 | 0.021407 | 13 |
| synth-holdout-1 | graphsearch (v1) | 16 | 16 | 0.4375 | 0.021407 | 3 |
| synth-holdout-1 | graphsearch | 16 | 16 | 0.625 | 0.021407 | 1 |

**Registered at k = 16**, and only there. E-G1b is where this arm reached recall 1.0, so k = 16 is the operating point the claim is about; at small K the corrected ranker is already known to tie or trail (GS-12), and registering that as a target would have been registering a result already in doubt. k = 4 and k = 8 are report-only.

## Not run

- **real-lab-holdout.v2** — the fixture does not exist yet.

`real-<lab>-holdout.v2` is the P3 hardware fixture with one uplink reservation changed, and **P3 has not run**. The row is reported as not run rather than omitted: an omitted row reads as a row that passed, and half a holdout is not a holdout. E-G7's holdout claim covers the synthetic cluster only until this exists.

## What was held out, exactly

| | value | why it is outside what was fitted |
| --- | --- | --- |
| `--symmetry` | 0.25 | E-G6's grid is {0, 0.5, 1}; this is in none of them |
| `--seed` | 20260923 | E-G6's grid uses 20260928 |
| `--nodes` x `--devices-per-node` | 8 x 8 = 64 devices | E-G6 uses 4 devices per node; this shape was never enumerated |

The cluster is **not committed**. It is regenerated from these arguments byte for byte, which `tests/test_cluster_gen.py` pins — and a committed holdout is a holdout somebody can edit.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/scripts/e_g7_holdout.py \
    --out experiments/results/e_g7_holdout.md
```

## The corpus

- **synth-holdout-1**: 128 of 36480 placements meet both SLOs (0.4%). A top-K row is worth reading only because this is not 100%.

## Reading the table

`feasible_recall` is over PLACEMENTS in both arms, and the heteropilot rows are credited generously: that arm ranks and judges templates, so one verdict is allowed to stand for every placement of the template. It cannot name a placement, so there is no stricter reading that would be fair to it.

`first_feasible_at_sim` is the ordinal of the simulation that first produced a candidate the run ended up calling feasible. `1` means the ranker's first pick was an answer; `-` means the run never found one. The same counting predictor records it in both arms.

A `cost_regret` of `-` means the run recommended nothing, or the fixture priced nothing the objective could score. It is not a zero -- a regret that cannot be computed is reported as uncomputed.

`simulations` is not comparable to `k` directly: heteropilot simulates at most `top_k` TEMPLATES, this search simulates at most `k` REPRESENTATIVES, and a representative stands for a class of placements whose size is in E-G1's compression column.
