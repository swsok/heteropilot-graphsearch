# E-G6 — scalability

> **MOCK — not performance numbers.** Nine synthetic clusters, every field `source: placeholder`, evaluated by a deterministic mock predictor. Nothing here is a measurement or a simulation of any hardware, and research design §12 forbids presenting a simulation at this scale as large-scale accuracy validation.

| devices | symmetry | nodes | templates | embeddings | representatives | compression_ratio | excluded_by_scope | simulations | t_enumerate_s | t_hash_s | t_vf2_s | t_bounds_s | t_search_s | t_total_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 32 | 0.0 | 8 | 2448 | 9024 | 744 | 0.082447 | 0 | 8 | 18.2 | 4.084 | 2.869 | 1.935 | 0.09 | 27.36 |
| 32 | 0.5 | 8 | 2448 | 9024 | 342 | 0.037899 | 0 | 8 | 18.21 | 4.067 | 3.049 | 0.821 | 0.08 | 26.39 |
| 32 | 1.0 | 8 | 2448 | 9024 | 42 | 0.004654 | 0 | 8 | 18.1 | 4.053 | 3.32 | 0.081 | 0.08 | 25.86 |
| 64 | 0.0 | 16 | 9504 | 36480 | 2640 | 0.072368 | 0 | 8 | 128.65 | 17.846 | 12.108 | 16.717 | 0.11 | 176.48 |
| 64 | 0.5 | 16 | 9504 | 36480 | 930 | 0.025493 | 0 | 8 | 128.59 | 17.837 | 13.474 | 5.515 | 0.09 | 166.51 |
| 64 | 1.0 | 16 | 9504 | 36480 | 42 | 0.001151 | 0 | 8 | 130.88 | 17.974 | 13.849 | 0.136 | 0.08 | 163.62 |
| 128 | 0.0 | 32 | 37440 | 146688 | 9888 | 0.067408 | 0 | 8 | 868.99 | 81.044 | 50.016 | 142.447 | 0.27 | 1148.43 |
| 128 | 0.5 | 32 | 37440 | 146688 | 2970 | 0.020247 | 0 | 8 | 891.23 | 83.601 | 53.203 | 37.165 | 0.12 | 1069.52 |
| 128 | 1.0 | 32 | 37440 | 146688 | 42 | 0.000286 | 0 | 8 | 889.26 | 83.206 | 56.556 | 0.238 | 0.08 | 1036.58 |

## What is registered, and what is not

`docs/preregistration.md` registers **no success criterion** for E-G6. Every column above is report-only: an absolute wall-time target would be a statement about the machine this ran on, not about the search. The curve is the result; a line drawn across it would be decoration.

One failure condition **is** registered: `saving < 0` at `symmetry = 1`. Symmetry 1 is the most favourable case the generator can produce — every node identical, so the compression has the most to fold — and a compression that cannot pay for itself there cannot pay for itself anywhere. It fires research design §12's first named failure condition, and the registered response is E-G3's: demote exact compression to a cache key and narrow the paper.

## The machine these timings were taken on

1-minute load average across the cells: min 1.02, median 1.16, max 8.19.

**The median is not near zero, and that is a standing condition rather than a fault.** This box carries a neighbour that holds roughly six cores continuously. It affects every cell about equally, so it shifts the curve rather than bending it — but a reader comparing these seconds against a quiet machine's should know, and the banner does not say it.

A cell is marked as taken under contention when its peak load exceeds the run's own median by more than 2.0 (so, above 3.16). Relative, because an absolute threshold on this box would mark every row, and a check that always fires is as useless as one that never does. What bends the curve is a TRANSIENT hitting some cells and not others.

## Cells timed under contention

**128/0, 128/0.5** ran with a 1-minute load average above the quiet threshold, so something else had the memory bandwidth at the same time. Their wall-time columns are not comparable with the other rows. The counts are unaffected — they are properties of the graph, not of the machine — and re-running those cells on a quiet box is the fix, not a footnote.

Recorded from `os.getloadavg()` at the start and end of each cell rather than remembered. It has caught two real contaminations already: a 16-worker test run that overlapped two 64-device cells, and a holdout script started while the 128-device cells were being timed. Neither showed up anywhere else in the output.

## Why there is no `saving` column here

E-G6's registered failure condition is `saving < 0` at `symmetry = 1`, and **this table cannot evaluate it.** `saving` is `t_sim_oracle - (t_sim_proposed + t_hash + t_vf2 + t_bounds)`, and these cells run the MOCK, where a simulation costs microseconds. Against a predictor that free, any compression whatsoever loses: the column would be negative everywhere and would say nothing about the contribution.

**That question is E-G3's, and E-G3 answered it** under the real simulator: `saving` +2475 s, +1220 s and +269 s on the three fixtures, against a compression that cost about half a second in total. What E-G6 adds is the other half — how the compression's OWN cost and the ratio behave as the cluster grows — and the two are read together.

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
