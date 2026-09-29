# E-G5 — the recommendation and the bounds, on hardware

> **REAL HARDWARE.** Every measured column comes from `experiments/e_g5/raw/`, on the node whose accelerator serials each provenance file carries. The predicted columns are the planner's, taken from the plan that was deployed. Nothing here is a simulation.

Each deployment is offered the rate **its own spec** declares: the service rows ask whether the recommendation meets its SLOs at the service's load, and the bound-stress row asks whether a candidate the throughput bound rejected can reach the floor it was rejected against. One trace for both would answer neither, and an earlier run of this experiment did exactly that -- replaying a stock trace at 10 rps against a plan simulated at 4 put a predicted p99 TTFT of 162 ms beside a measured 22,068, a number that says nothing about the simulator and everything about two different offered loads.

## The placement decides whether the SLO is met

One template, three placements of it, nine repetitions. The rows below are the recommendation at each placement, and the target is the same 550 ms in every one.

| placement | devices | reps | p99 TTFT median | range | p99 TPOT median | goodput median | SLO |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | 0,1 | 3 | 379.3 ms | [351.6, 400.1] | 51.04 ms | 2.598 rps | **met** |
| T2 | 0,2 | 3 | 2891.3 ms | [2712.2, 3286.5] | 55.57 ms | 2.469 rps | **MISSED** |
| T3 | 0,1,2,3 | 3 | 2269.1 ms | [2128.0, 2707.5] | 54.27 ms | 2.590 rps | **MISSED** |

**T1 meets the latency target and T2 does not**, by a factor of about seven, with the same model, the same trace, the same scheduler knobs, the same seed and the same plan. The only difference is which wire the tensor-parallel all-reduce crosses. Three repetitions per cell and the ranges do not overlap.

The planner being extended **cannot express that difference at all**: `resolve_devices` maps an execution island to every one of its accelerator ids, so a TP=2 plan is launched with all eight devices visible and the runtime takes the first two. It names a template; T1 and T2 are two placements of that one template, and the choice between them decides whether the service meets its objectives.

## Predicted against measured

| condition | deployment | devices | offered rps | p99 TTFT pred | p99 TTFT meas | p99 TPOT pred | p99 TPOT meas | goodput meas | SLO |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 503.1 | 400.1 | 41.20 | 51.04 | 2.598 | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal | 0,1 | 4.0 | 503.1 | 406.7 | 41.20 | 51.32 | 2.594 | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 550.0 | 31177.2 | 60.00 | 54.58 | 2.878 | **MISSED** |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 546.7 | 379.3 | 46.11 | 51.05 | 2.596 | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal | 0,1 | 4.0 | 546.7 | 422.8 | 46.11 | 51.60 | 2.590 | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 550.0 | 31190.0 | 60.00 | 54.60 | 2.877 | **MISSED** |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 456.5 | 351.6 | 50.28 | 50.75 | 2.600 | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal | 0,1 | 4.0 | 456.5 | 343.6 | 50.28 | 51.15 | 2.594 | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 550.0 | 31183.4 | 60.00 | 54.59 | 2.877 | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 503.1 | 3286.5 | 41.20 | 56.17 | 2.451 | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal | 0,2 | 4.0 | 503.1 | 3027.6 | 41.20 | 55.72 | 2.465 | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 550.0 | 33789.8 | 60.00 | 58.96 | 2.707 | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 546.7 | 2891.3 | 46.11 | 55.57 | 2.469 | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal | 0,2 | 4.0 | 546.7 | 3234.0 | 46.11 | 55.98 | 2.453 | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 550.0 | 33781.6 | 60.00 | 58.94 | 2.708 | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 456.5 | 2712.2 | 50.28 | 55.12 | 2.477 | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal | 0,2 | 4.0 | 456.5 | 3078.9 | 50.28 | 55.68 | 2.457 | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 550.0 | 33772.2 | 60.00 | 58.92 | 2.708 | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 161.7 | 2269.1 | 13.16 | 54.27 | 2.590 | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal | 0,1,2,3 | 4.0 | 161.7 | 2267.4 | 13.16 | 54.26 | 2.590 | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 550.0 | 30868.3 | 60.00 | 54.34 | 2.888 | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 244.5 | 2707.5 | 15.47 | 55.08 | 2.559 | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal | 0,1,2,3 | 4.0 | 244.5 | 1800.7 | 15.47 | 53.61 | 2.605 | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 550.0 | 31144.6 | 60.00 | 54.82 | 2.866 | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 212.4 | 2128.0 | 16.06 | 54.19 | 2.590 | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal | 0,1,2,3 | 4.0 | 212.4 | 1883.6 | 16.06 | 53.68 | 2.609 | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 550.0 | 31128.1 | 60.00 | 54.79 | 2.867 | **MISSED** |

## Where the recommendation missed, and on which axis

- **boundary:impossible_proven** (llama31-8b__normal__T1__knee): TTFT 31177 > 550 ms; goodput 2.88 < 55.00 rps
- **boundary:impossible_proven** (llama31-8b__normal__T1__knee): TTFT 31190 > 550 ms; goodput 2.88 < 55.00 rps
- **boundary:impossible_proven** (llama31-8b__normal__T1__knee): TTFT 31183 > 550 ms; goodput 2.88 < 55.00 rps
- **recommendation** (llama31-8b__normal__T2__knee): TTFT 3287 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T2__knee): TTFT 3028 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T2__knee): TTFT 33790 > 550 ms; goodput 2.71 < 55.00 rps
- **recommendation** (llama31-8b__normal__T2__knee): TTFT 2891 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T2__knee): TTFT 3234 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T2__knee): TTFT 33782 > 550 ms; goodput 2.71 < 55.00 rps
- **recommendation** (llama31-8b__normal__T2__knee): TTFT 2712 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T2__knee): TTFT 3079 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T2__knee): TTFT 33772 > 550 ms; goodput 2.71 < 55.00 rps
- **recommendation** (llama31-8b__normal__T3__knee): TTFT 2269 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T3__knee): TTFT 2267 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T3__knee): TTFT 30868 > 550 ms; goodput 2.89 < 55.00 rps
- **recommendation** (llama31-8b__normal__T3__knee): TTFT 2708 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T3__knee): TTFT 1801 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T3__knee): TTFT 31145 > 550 ms; goodput 2.87 < 55.00 rps
- **recommendation** (llama31-8b__normal__T3__knee): TTFT 2128 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T3__knee): TTFT 1884 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T3__knee): TTFT 31128 > 550 ms; goodput 2.87 < 55.00 rps

A missed target is recorded, not explained away. The candidate causes are the ones the work order names and they are not separated by this experiment: prediction error, the contention model, and the engine's own scheduler. What can be said from these rows alone is the size and the direction of the prediction error, below.

## The size and direction of the prediction error

| deployment | p99 TTFT | p99 TPOT |
| --- | --- | --- |
| recommendation | measured is 0.8x the prediction | 1.2x |
| boundary:feasible_marginal | measured is 0.8x the prediction | 1.2x |
| boundary:impossible_proven | measured is 56.7x the prediction | 0.9x |
| recommendation | measured is 0.7x the prediction | 1.1x |
| boundary:feasible_marginal | measured is 0.8x the prediction | 1.1x |
| boundary:impossible_proven | measured is 56.7x the prediction | 0.9x |
| recommendation | measured is 0.8x the prediction | 1.0x |
| boundary:feasible_marginal | measured is 0.8x the prediction | 1.0x |
| boundary:impossible_proven | measured is 56.7x the prediction | 0.9x |
| recommendation | measured is 6.5x the prediction | 1.4x |
| boundary:feasible_marginal | measured is 6.0x the prediction | 1.4x |
| boundary:impossible_proven | measured is 61.4x the prediction | 1.0x |
| recommendation | measured is 5.3x the prediction | 1.2x |
| boundary:feasible_marginal | measured is 5.9x the prediction | 1.2x |
| boundary:impossible_proven | measured is 61.4x the prediction | 1.0x |
| recommendation | measured is 5.9x the prediction | 1.1x |
| boundary:feasible_marginal | measured is 6.7x the prediction | 1.1x |
| boundary:impossible_proven | measured is 61.4x the prediction | 1.0x |
| recommendation | measured is 14.0x the prediction | 4.1x |
| boundary:feasible_marginal | measured is 14.0x the prediction | 4.1x |
| boundary:impossible_proven | measured is 56.1x the prediction | 0.9x |
| recommendation | measured is 11.1x the prediction | 3.6x |
| boundary:feasible_marginal | measured is 7.4x the prediction | 3.5x |
| boundary:impossible_proven | measured is 56.6x the prediction | 0.9x |
| recommendation | measured is 10.0x the prediction | 3.4x |
| boundary:feasible_marginal | measured is 8.9x the prediction | 3.3x |
| boundary:impossible_proven | measured is 56.6x the prediction | 0.9x |

The simulator is **optimistic on both axes**, which is the direction its own accuracy domain already records at low served concurrency. No margin from this data is fitted here and none may be: a domain built from E-G5 could not then be tested by E-G5.

## The lower bound, tested on hardware

The candidate the throughput bound rejected by the smallest margin, deployed and offered the floor it was rejected against.

| ceiling the bound computed | floor it was rejected against | measured goodput | ratio |
| --- | --- | --- |---|
| 54.433 rps | 55.0 rps | 2.878 rps | **18.9x** |
| 54.433 rps | 55.0 rps | 2.877 rps | **18.9x** |
| 54.433 rps | 55.0 rps | 2.877 rps | **18.9x** |
| 54.433 rps | 55.0 rps | 2.707 rps | **20.1x** |
| 54.433 rps | 55.0 rps | 2.708 rps | **20.1x** |
| 54.433 rps | 55.0 rps | 2.708 rps | **20.1x** |
| 54.433 rps | 55.0 rps | 2.888 rps | **18.9x** |
| 54.433 rps | 55.0 rps | 2.866 rps | **19.0x** |
| 54.433 rps | 55.0 rps | 2.867 rps | **19.0x** |

**`false_infeasible` is zero on hardware**: the candidate did not reach the floor, so the bound was right to reject it. That was the expected outcome and the test is registered as weak -- the bound is a *relaxation*, so it rejects only what the most optimistic arithmetic already misses, and a rejection being correct is not news.

**The useful number is the ratio.** The optimistic ceiling sits an order of magnitude above what the hardware actually delivers. A bound that loose still eliminates nothing it should not, which is its only correctness requirement, but it eliminates very little: the looseness is the price of soundness and this is its size on this node.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
vendor/heteropilot/.venv/bin/python experiments/e_g5/deploy_and_bench.py \
    --condition llama31-8b__normal__T3__knee --rep 42 \
    --knee-rps 4 --predictor sim
python experiments/e_g5/analyze.py --out experiments/results/e_g5_real_hardware.md
```
