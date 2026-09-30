# E-G7 — holdout

> **MockPredictor results. Not performance numbers.** Every figure here comes from a deterministic mock that respects the same physics as the bounds; none of it is a measurement or a simulation of any hardware.

The holdout set was fixed in `docs/preregistration.md` on 2026-09-28, before E-G6's grid ran and before anything in it was looked at. No ranker, no δ, no bound and no threshold was modified afterwards.

**What the real-lab holdout's altered field is, and is not.** E-G4 showed that this node's PCIe ports are not physically shared, so the reservation raised on `port-gpu0` is **not a physical fact**: it is a variation of the topology *assumption* the search is required to respond to. What this holdout tests is the invariant and the recall on a graph that was never touched while anything was tuned -- not whether the node behaves this way. The fixture is `real-a40x8.v2.yaml` with `shared_resources[port-gpu0].reserved` 0.0 -> 15.07 GB/s and nothing else, derived by `experiments/scripts/make_holdout_fixture.py`; 15.07 is 60 % of the measured 25.12 GB/s capacity, the fraction E-G4's background generator held. The port was chosen because the candidates under test cross it: `gpu0-gpu2` declares it and `gpu0-gpu1`, being NVLink, declares none, so the single field moves the PCIe placements from 25.12 to 10.05 GB/s and leaves the NVLink pair at 112.50. Exhaustively -- 210 representatives, none left unevaluated -- it takes the feasible set from 64 plans to 52, and the twelve that leave are the six placements containing `gpu0` over PCIe, at two templates, **evaluated and rejected rather than unevaluated**. A holdout built on a port no candidate crosses would have moved nothing, which is why this was checked rather than assumed (GS-30).

## Criterion 1 — the invariant, on the holdout

| fixture | embeddings | representatives | compression_ratio | false_infeasible | mismerged_pairs | correct | unjudged | complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| synth-holdout-1 | 36480 | 600 | 0.0164 | 0 | 0 | True | 0 | True |
| real-lab-holdout | 384 | 210 | 0.5469 | 0 | 0 | True | 0 | True |

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
| real-lab-holdout | oracle | 384 | 384 | 1.0 | - | 217 |
| real-lab-holdout | heteropilot | 4 | 4 | 0.0 | - | 1 |
| real-lab-holdout | graphsearch (v1) | 4 | 4 | 0.0 | - | - |
| real-lab-holdout | graphsearch | 4 | 4 | 0.0357 | - | 1 |
| real-lab-holdout | heteropilot | 8 | 8 | 0.5 | - | 1 |
| real-lab-holdout | graphsearch (v1) | 8 | 8 | 0.0 | - | - |
| real-lab-holdout | graphsearch | 8 | 8 | 0.0714 | - | 1 |
| real-lab-holdout | heteropilot | 16 | 16 | 0.5 | - | 3 |
| real-lab-holdout | graphsearch (v1) | 16 | 16 | 0.0714 | - | 9 |
| real-lab-holdout | graphsearch | 16 | 16 | 0.1429 | - | 1 |

### Criterion 3, judged

| fixture | `full` at k = 16 | heteropilot at k = 16 | registered criterion |
| --- | --- | --- | --- |
| real-lab-holdout | 0.1429 | 0.5 | **NOT met** |
| synth-holdout-1 | 0.625 | 0.0312 | **met** |

**The criterion is not met on every fixture, and the registered response applies rather than an explanation.** Pre-registration, failure interpretation: *"The holdout's recall is materially worse than the diagnosis fixtures' -> the ranker was fitted to the diagnosis corpus. Reported as such; the claim about the ranker narrows to those fixtures."* That is what this result does. The ranker claim covers the diagnosis corpus and `synth-holdout-1`; it does **not** cover `real-lab-holdout`, where heteropilot's template-level surrogate retrieves more feasible placements at the registered budget than this search does.

On `real-lab-holdout` the gap is 0.1429 against 0.5. The invariant still holds there --- no feasible placement was wrongly removed and nothing was mis-merged --- so what fails is the ranking, not the correctness. Those are separate claims and are reported separately.


**Registered at k = 16**, and only there. E-G1b is where this arm reached recall 1.0, so k = 16 is the operating point the claim is about; at small K the corrected ranker is already known to tie or trail (GS-12), and registering that as a target would have been registering a result already in doubt. k = 4 and k = 8 are report-only.

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

- **real-lab-holdout**: 112 of 384 placements meet both SLOs (29.2%). A top-K row is worth reading only because this is not 100%.
- **synth-holdout-1**: 128 of 36480 placements meet both SLOs (0.4%). A top-K row is worth reading only because this is not 100%.

## Reading the table

`feasible_recall` is over PLACEMENTS in both arms, and the heteropilot rows are credited generously: that arm ranks and judges templates, so one verdict is allowed to stand for every placement of the template. It cannot name a placement, so there is no stricter reading that would be fair to it.

`first_feasible_at_sim` is the ordinal of the simulation that first produced a candidate the run ended up calling feasible. `1` means the ranker's first pick was an answer; `-` means the run never found one. The same counting predictor records it in both arms.

A `cost_regret` of `-` means the run recommended nothing, or the fixture priced nothing the objective could score. It is not a zero -- a regret that cannot be computed is reported as uncomputed.

`simulations` is not comparable to `k` directly: heteropilot simulates at most `top_k` TEMPLATES, this search simulates at most `k` REPRESENTATIVES, and a representative stands for a class of placements whose size is in E-G1's compression column.
