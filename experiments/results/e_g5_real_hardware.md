# E-G5 — the recommendation and the bounds, on hardware

> **REAL HARDWARE.** Every measured column comes from `experiments/e_g5/raw/`, on the node whose accelerator serials each provenance file carries. The predicted columns are graph search's verdict on the placement that was deployed (GS-30): each placement simulated for itself, not the search's own pick. Only the predicted columns are simulations.

Each deployment is offered the rate **its own spec** declares: the service rows ask whether the recommendation meets its SLOs at the service's load, and the bound-stress row asks whether a candidate the throughput bound rejected can reach the floor it was rejected against. One trace for both would answer neither, and an earlier run of this experiment did exactly that -- replaying a stock trace at 10 rps against a plan simulated at 4 put a predicted p99 TTFT of 162 ms beside a measured 22,068, a number that says nothing about the simulator and everything about two different offered loads.

## The placement decides whether the SLO is met

Three placements, three repetitions each: T1 and T2 are one TP=2 template on two different pairs of devices, and T3 is the TP=4 template on four. The rows below are the recommendation at each, the target is the same 550 ms in every one, and `predicted` is the search's verdict on that placement itself (GS-30).

| placement | devices | reps | p99 TTFT pred | predicted | p99 TTFT median | vs T1 | range | p99 TPOT median | goodput median | measured |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | 0,1 | 3 | 503.1 ms | met | 404.5 ms | 1.0x | [352.2, 421.3] | 51.49 ms | 2.582 rps | **met** |
| T2 | 0,2 | 3 | 630.8 ms | MISSED | 3341.1 ms | 8.3x | [3056.0, 3400.1] | 56.20 ms | 2.445 rps | **MISSED** |
| T3 | 0,1,2,3 | 3 | 212.4 ms | met | 1948.3 ms | 4.8x | [1827.7, 2051.8] | 53.76 ms | 2.607 rps | **MISSED** |

**T1 met the latency target and T2 missed it**: median p99 TTFT 405 ms against 3341 ms, 8.3x, with the same model, trace, scheduler knobs, seed and plan. The only difference is which wire the tensor-parallel all-reduce crosses. 3 and 3 repetitions, and the ranges do not overlap.

The planner being extended **cannot express that difference at all**: `resolve_devices` maps an execution island to every one of its accelerator ids, so a TP=2 plan is launched with all eight devices visible and the runtime takes the first two. It names a template; T1 and T2 are two placements of that one template, and the choice between them decides whether the service meets its objectives.

## Does the search's verdict on a placement match the hardware's?

Before GS-30 every row carried the search's own pick, so T1 and T2 had the same prediction and this question could not be put. Each row now carries the verdict on the placement deployed, and the table counts whether it is the verdict the hardware reached.

| placement | rows | agree | disagree | disagreements |
| --- | --- | --- | --- | --- |
| T1 | 9 | 9 | 0 | - |
| T2 | 9 | 9 | 0 | - |
| T3 | 9 | 3 | 6 | predicted met, measured MISSED |
| all | 27 | 21 | 6 | - |

## Predicted against measured

| condition | deployment | devices | offered rps | p99 TTFT pred | p99 TTFT meas | p99 TPOT pred | p99 TPOT meas | goodput meas | predicted | measured |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 503.1 | 404.5 | 41.20 | 51.49 | 2.582 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal | 0,1 | 4.0 | 503.1 | 422.6 | 41.20 | 52.16 | 2.571 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 28334.3 | 31557.8 | 53.61 | 55.24 | 2.849 | MISSED | **MISSED** |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 546.7 | 421.3 | 46.11 | 51.93 | 2.576 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal | 0,1 | 4.0 | 546.7 | 424.1 | 46.11 | 52.25 | 2.569 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 29338.7 | 31416.3 | 53.48 | 55.14 | 2.852 | MISSED | **MISSED** |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 456.5 | 352.2 | 50.28 | 50.99 | 2.596 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal | 0,1 | 4.0 | 456.5 | 380.9 | 50.28 | 51.54 | 2.591 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 32582.2 | 31297.6 | 59.78 | 55.01 | 2.859 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 630.8 | 3341.1 | 46.01 | 56.20 | 2.445 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal | 0,2 | 4.0 | 630.8 | 3381.8 | 46.01 | 56.36 | 2.444 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 31275.5 | 34070.0 | 58.50 | 59.44 | 2.687 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 658.2 | 3400.1 | 50.61 | 56.29 | 2.443 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal | 0,2 | 4.0 | 658.2 | 3332.0 | 50.61 | 56.17 | 2.449 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 32329.3 | 34074.6 | 58.29 | 59.45 | 2.687 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 628.0 | 3056.0 | 55.71 | 55.68 | 2.458 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal | 0,2 | 4.0 | 628.0 | 3044.1 | 55.71 | 55.76 | 2.458 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 35947.3 | 34049.1 | 65.27 | 59.39 | 2.688 | MISSED | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 161.7 | 1948.3 | 13.16 | 53.76 | 2.607 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal | 0,1,2,3 | 4.0 | 161.7 | 2117.0 | 13.16 | 54.18 | 2.592 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 28334.3 | 30858.8 | 53.61 | 54.32 | 2.888 | MISSED | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 244.5 | 1827.7 | 15.47 | 53.63 | 2.611 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal | 0,1,2,3 | 4.0 | 244.5 | 2938.5 | 15.47 | 55.32 | 2.552 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 29338.7 | 31220.4 | 53.48 | 54.95 | 2.860 | MISSED | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 212.4 | 2051.8 | 16.06 | 54.01 | 2.598 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal | 0,1,2,3 | 4.0 | 212.4 | 2395.6 | 16.06 | 54.56 | 2.579 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 32582.2 | 31129.2 | 59.78 | 54.79 | 2.867 | MISSED | **MISSED** |

## Where the recommendation missed, and on which axis

- **boundary:impossible_proven** (llama31-8b__normal__T1__knee): TTFT 31558 > 550 ms; goodput 2.85 < 55.00 rps
- **boundary:impossible_proven** (llama31-8b__normal__T1__knee): TTFT 31416 > 550 ms; goodput 2.85 < 55.00 rps
- **boundary:impossible_proven** (llama31-8b__normal__T1__knee): TTFT 31298 > 550 ms; goodput 2.86 < 55.00 rps
- **recommendation** (llama31-8b__normal__T2__knee): TTFT 3341 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T2__knee): TTFT 3382 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T2__knee): TTFT 34070 > 550 ms; goodput 2.69 < 55.00 rps
- **recommendation** (llama31-8b__normal__T2__knee): TTFT 3400 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T2__knee): TTFT 3332 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T2__knee): TTFT 34075 > 550 ms; goodput 2.69 < 55.00 rps
- **recommendation** (llama31-8b__normal__T2__knee): TTFT 3056 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T2__knee): TTFT 3044 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T2__knee): TTFT 34049 > 550 ms; goodput 2.69 < 55.00 rps
- **recommendation** (llama31-8b__normal__T3__knee): TTFT 1948 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T3__knee): TTFT 2117 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T3__knee): TTFT 30859 > 550 ms; goodput 2.89 < 55.00 rps
- **recommendation** (llama31-8b__normal__T3__knee): TTFT 1828 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T3__knee): TTFT 2938 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T3__knee): TTFT 31220 > 550 ms; goodput 2.86 < 55.00 rps
- **recommendation** (llama31-8b__normal__T3__knee): TTFT 2052 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T3__knee): TTFT 2396 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T3__knee): TTFT 31129 > 550 ms; goodput 2.87 < 55.00 rps

A missed target is recorded, not explained away. The candidate causes are the ones the work order names and they are not separated by this experiment: prediction error, the contention model, and the engine's own scheduler. What can be said from these rows alone is the size and the direction of the prediction error, below.

## The size and direction of the prediction error

| deployment | p99 TTFT | p99 TPOT |
| --- | --- | --- |
| recommendation | measured is 0.8x the prediction | 1.2x |
| boundary:feasible_marginal | measured is 0.8x the prediction | 1.3x |
| boundary:impossible_proven | measured is 1.1x the prediction | 1.0x |
| recommendation | measured is 0.8x the prediction | 1.1x |
| boundary:feasible_marginal | measured is 0.8x the prediction | 1.1x |
| boundary:impossible_proven | measured is 1.1x the prediction | 1.0x |
| recommendation | measured is 0.8x the prediction | 1.0x |
| boundary:feasible_marginal | measured is 0.8x the prediction | 1.0x |
| boundary:impossible_proven | measured is 1.0x the prediction | 0.9x |
| recommendation | measured is 5.3x the prediction | 1.2x |
| boundary:feasible_marginal | measured is 5.4x the prediction | 1.2x |
| boundary:impossible_proven | measured is 1.1x the prediction | 1.0x |
| recommendation | measured is 5.2x the prediction | 1.1x |
| boundary:feasible_marginal | measured is 5.1x the prediction | 1.1x |
| boundary:impossible_proven | measured is 1.1x the prediction | 1.0x |
| recommendation | measured is 4.9x the prediction | 1.0x |
| boundary:feasible_marginal | measured is 4.8x the prediction | 1.0x |
| boundary:impossible_proven | measured is 0.9x the prediction | 0.9x |
| recommendation | measured is 12.1x the prediction | 4.1x |
| boundary:feasible_marginal | measured is 13.1x the prediction | 4.1x |
| boundary:impossible_proven | measured is 1.1x the prediction | 1.0x |
| recommendation | measured is 7.5x the prediction | 3.5x |
| boundary:feasible_marginal | measured is 12.0x the prediction | 3.6x |
| boundary:impossible_proven | measured is 1.1x the prediction | 1.0x |
| recommendation | measured is 9.7x the prediction | 3.4x |
| boundary:feasible_marginal | measured is 11.3x the prediction | 3.4x |
| boundary:impossible_proven | measured is 1.0x the prediction | 0.9x |

On p99 TTFT the simulator is **optimistic in 18 of 27 rows**; on p99 TPOT it is **optimistic in 23 of 27 rows**. No margin from this data is fitted here and none may be: a domain built from E-G5 could not then be tested by E-G5.

## The lower bound, tested on hardware

The candidate the throughput bound rejected by the smallest margin, deployed and offered the floor it was rejected against.

| ceiling the bound computed | floor it was rejected against | measured goodput | ratio |
| --- | --- | --- |---|
| 54.433 rps | 55.0 rps | 2.849 rps | **19.1x** |
| 54.433 rps | 55.0 rps | 2.852 rps | **19.1x** |
| 54.433 rps | 55.0 rps | 2.859 rps | **19.0x** |
| 54.433 rps | 55.0 rps | 2.687 rps | **20.3x** |
| 54.433 rps | 55.0 rps | 2.687 rps | **20.3x** |
| 54.433 rps | 55.0 rps | 2.688 rps | **20.2x** |
| 54.433 rps | 55.0 rps | 2.888 rps | **18.8x** |
| 54.433 rps | 55.0 rps | 2.860 rps | **19.0x** |
| 54.433 rps | 55.0 rps | 2.867 rps | **19.0x** |

**`false_infeasible` is zero on hardware**: the candidate did not reach the floor, so the bound was right to reject it. That was the expected outcome and the test is registered as weak -- the bound is a *relaxation*, so it rejects only what the most optimistic arithmetic already misses, and a rejection being correct is not news.

**The useful number is the ratio.** The optimistic ceiling sits an order of magnitude above what the hardware actually delivers. A bound that loose still eliminates nothing it should not, which is its only correctness requirement, but it eliminates very little: the looseness is the price of soundness and this is its size on this node.

## The inter-node P/D arm

> **REAL HARDWARE**, two nodes.

**Deployed by this experiment's harness, not by heteropilot's `planner/deploy/`**, which has no router and cannot launch a split architecture (GS-28, heteropilot D128). The router is `experiments/e_g5/pd_router.py`, an instrument for this measurement and not a serving component (GS-32).

Not run.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
vendor/heteropilot/.venv/bin/python experiments/e_g5/deploy_and_bench.py \
    --condition llama31-8b__normal__T3__knee --rep 42 \
    --knee-rps 4 --predictor sim
python experiments/e_g5/analyze.py --out experiments/results/e_g5_real_hardware.md
```
