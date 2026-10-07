# E-G6 — scalability

> **MOCK — not performance numbers.** Nine synthetic clusters, every field `source: placeholder`, evaluated by a deterministic mock predictor. Nothing here is a measurement or a simulation of any hardware, and research design §12 forbids presenting a simulation at this scale as large-scale accuracy validation.

| devices | symmetry | nodes | templates | embeddings | representatives | compression_ratio | excluded_by_scope | simulations | t_enumerate_s | t_hash_s | t_vf2_s | t_bounds_s | t_search_s | t_total_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 32 | 0.0 | 8 | 2448 | 9024 | 744 | 0.082447 | 0 | 8 | 6.04 | 4.078 | 2.842 | 2.268 | 0.09 | 15.5 |
| 32 | 0.5 | 8 | 2448 | 9024 | 342 | 0.037899 | 0 | 8 | 6.08 | 4.099 | 2.95 | 1.023 | 0.08 | 14.44 |
| 32 | 1.0 | 8 | 2448 | 9024 | 42 | 0.004654 | 0 | 8 | 5.94 | 4.094 | 3.327 | 0.082 | 0.08 | 13.73 |
| 64 | 0.0 | 16 | 9504 | 36480 | 2640 | 0.072368 | 0 | 8 | 25.68 | 17.99 | 12.853 | 16.249 | 0.11 | 74.08 |
| 64 | 0.5 | 16 | 9504 | 36480 | 930 | 0.025493 | 0 | 8 | 26.36 | 17.828 | 12.563 | 5.659 | 0.09 | 63.53 |
| 64 | 1.0 | 16 | 9504 | 36480 | 42 | 0.001151 | 0 | 8 | 26.36 | 17.87 | 13.189 | 0.134 | 0.09 | 58.68 |
| 128 | 0.0 | 32 | 37440 | 146688 | 9888 | 0.067408 | 0 | 8 | 111.07 | 81.495 | 49.159 | 140.455 | 0.27 | 388.52 |
| 128 | 0.5 | 32 | 37440 | 146688 | 2970 | 0.020247 | 0 | 8 | 109.91 | 81.338 | 54.011 | 38.057 | 0.12 | 287.66 |
| 128 | 1.0 | 32 | 37440 | 146688 | 42 | 0.000286 | 0 | 8 | 112.09 | 82.23 | 54.162 | 0.238 | 0.08 | 255.84 |

## What is registered, and what is not

`docs/preregistration.md` registers **no success criterion** for E-G6. Every column above is report-only: an absolute wall-time target would be a statement about the machine this ran on, not about the search. The curve is the result; a line drawn across it would be decoration.

One failure condition **is** registered: `saving < 0` at `symmetry = 1`. Symmetry 1 is the most favourable case the generator can produce — every node identical, so the compression has the most to fold — and a compression that cannot pay for itself there cannot pay for itself anywhere. It fires research design §12's first named failure condition, and the registered response is E-G3's: demote exact compression to a cache key and narrow the paper.

## `t_enumerate` before and after GS-25/GS-26

This grid was first measured on 2026-09-28 and re-measured on 2026-09-29 after the enumerator changed. **Every structural column is identical** -- templates, embeddings, representatives, compression ratio, `false_infeasible` and `mismerged_pairs` -- and only the seconds moved:

| devices | `t_enumerate` before | after | |
| --- | --- | --- | --- |
| 32 | 18.2 s | 6.04 s | 3.0x |
| 64 | 128.65 s | 25.68 s | 5.0x |
| 128 | 868.99 s | 111.07 s | 7.8x |

GS-25 stopped enumerating the `prod_a R_a!` replica orderings and computes the folded count in closed form; GS-26 stopped recomputing one graph's paths once per placement. Neither changes which embeddings exist, which is why only this column moved -- and the 1-minute load figures below moved too, because the 2026-09-28 grid carried a neighbour that has since gone.

## The machine these timings were taken on

1-minute load average across the cells: min 2.01, median 2.12, max 2.36.

**The median is not near zero, and that is a standing condition rather than a fault.** This box carries a neighbour that holds roughly six cores continuously. It affects every cell about equally, so it shifts the curve rather than bending it — but a reader comparing these seconds against a quiet machine's should know, and the banner does not say it.

A cell is marked as taken under contention when its peak load exceeds the run's own median by more than 2.0 (so, above 4.12). Relative, because an absolute threshold on this box would mark every row, and a check that always fires is as useless as one that never does. What bends the curve is a TRANSIENT hitting some cells and not others.

## Why there is no `saving` column here

E-G6's registered failure condition is `saving < 0` at `symmetry = 1`, and **this table cannot evaluate it.** `saving` is `t_sim_oracle - (t_sim_proposed + t_hash + t_vf2 + t_bounds)`, and these cells run the MOCK, where a simulation costs microseconds. Against a predictor that free, any compression whatsoever loses: the column would be negative everywhere and would say nothing about the contribution.

**That question is E-G3's, and E-G3 answered it** under the real simulator: `saving` +2475 s, +1220 s and +269 s on the three fixtures, against a compression that cost about half a second in total. What E-G6 adds is the other half — how the compression's OWN cost and the ratio behave as the cluster grows — and the two are read together.

**The condition itself was then run under the real simulator**, on this grid's 32-device, symmetry-1 cell, both arms end to end (preregistration change-log row 10): `e_g6_real_sim.md`. It does not fire there.

## The compression's cost, and what it is not

`t_hash_s` and `t_vf2_s` are the compression's whole cost and are kept apart because they scale differently — hashing is linear in embeddings, VF2 is quadratic inside a bucket, and a lumped number could not say which one ate the budget.

**`t_compress_s` is not charged to the compression, and the difference used to be most of it.** `compress` also built a conflict matrix — O(n²) over embeddings — that the search pipeline discards. On the 32-device cell that was 32.3 s of 52.1 s. Charging it here would not have made this table slow, it would have made it **wrong**, and wrong in the direction of failing our own contribution (GS-21).

## Reading `compression_ratio`

A ratio near 1.0 at `symmetry = 0` is **not** a failure. It is the designed behaviour of an asymmetric cluster — no two placements can be isomorphic — and it is in the grid so the number gets reported rather than avoided, exactly as `graph-toy-asym` does at toy scale. The boundary of where the contribution applies is a result about the contribution.

`excluded_by_scope` counts representatives the enumeration cap (`--max-embeddings-per-template 64`) or the scope rules put out of reach. **They are not infeasible** — they were not judged, and the five states never merge.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/scripts/e_g6_traces.py   # the three load levels
bash experiments/scripts/e_g6_run.sh
```

The nine clusters are **not committed**. They are regenerated from `graphsearch/synth/cluster_gen.py` with seed 20260928 and the arguments in the `cluster` column's path, byte for byte — which is what `tests/test_cluster_gen.py` pins. Committing them would be committing a derived artefact that can drift from its generator.
