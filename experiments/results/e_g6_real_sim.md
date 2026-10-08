# E-G6 — the registered failure condition, under the real simulator

> **REAL SIM — LLMServingSim, cache `outputs/cache-eg6-real`, not real hardware.** The cluster is E-G6's synthetic one: every field `source: placeholder`, its devices borrowing the A5000's perf bundle without being A5000s. Nothing here is a measurement of any machine, and one condition at 32 devices is not accuracy validation at scale.

| condition | embeddings | representatives | oracle_simulations | proposed_simulations | t_oracle_s | t_proposed_s | saving_s | false_infeasible | mismerged_pairs | unjudged | complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| d32-s1.0 | 9024 | 42 | 9024 | 42 | 38701.8 | 168.6 | 38533.2 | 0 | 0 | 0 | True |

The registered failure condition (`saving < 0` at symmetry 1, preregistration E-G6): **does not fire**: the compression saved more than it cost.

## What the proposed arm's time was spent on

| t_enumerate_s | t_hash_s | t_vf2_s | t_bounds_s | t_sim_s | t_proposed_s |
| --- | --- | --- | --- | --- | --- |
| 5.94 | 4.03 | 3.06 | 0.08 | 155.06 | 168.60 |

`t_proposed_s` is the whole arm's wall clock, so enumeration, hashing, VF2 and the bounds are all charged to it, once. `t_oracle_s` is the oracle arm's wall clock likewise, its own enumeration included. Both arms ran with 60 concurrent simulations, each from a cold cache (oracle 0 hits / 9024 misses, proposed 0 hits / 42 misses).

Feasible placements: oracle 1088, proposed 1088; `feasible_recall` 1.0, `cost_regret` 0.0 (report-only, as in E-G3).

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
vendor/heteropilot/.venv/bin/python experiments/scripts/e_g6_real_sim.py \
    --max-workers 60 --out experiments/results/e_g6_real_sim.md
```
