# E-G5 — the recommendation and the bounds, on hardware

> **REAL HARDWARE.** Every measured column comes from `experiments/e_g5/raw/`, on the node whose accelerator serials each provenance file carries. The predicted columns are the planner's, taken from the plan that was deployed. Nothing here is a simulation.

Each deployment is offered the rate **its own spec** declares: the service rows ask whether the recommendation meets its SLOs at the service's load, and the bound-stress row asks whether a candidate the throughput bound rejected can reach the floor it was rejected against. One trace for both would answer neither, and an earlier run of this experiment did exactly that -- replaying a stock trace at 10 rps against a plan simulated at 4 put a predicted p99 TTFT of 162 ms beside a measured 22,068, a number that says nothing about the simulator and everything about two different offered loads.

## Predicted against measured

| condition | deployment | devices | offered rps | p99 TTFT pred | p99 TTFT meas | p99 TPOT pred | p99 TPOT meas | goodput meas | SLO |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 161.7 | 2278.1 | 13.16 | 54.27 | 2.588 | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal | 0,1,2,3 | 4.0 | 161.7 | 1803.4 | 13.16 | 53.61 | 2.611 | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 550.0 | 31137.0 | 60.00 | 54.81 | 2.866 | **MISSED** |

## Where the recommendation missed, and on which axis

- **recommendation** (llama31-8b__normal__T3__knee): TTFT 2278 > 550 ms
- **boundary:feasible_marginal** (llama31-8b__normal__T3__knee): TTFT 1803 > 550 ms
- **boundary:impossible_proven** (llama31-8b__normal__T3__knee): TTFT 31137 > 550 ms; goodput 2.87 < 55.00 rps

A missed target is recorded, not explained away. The candidate causes are the ones the work order names and they are not separated by this experiment: prediction error, the contention model, and the engine's own scheduler. What can be said from these rows alone is the size and the direction of the prediction error, below.

## The size and direction of the prediction error

| deployment | p99 TTFT | p99 TPOT |
| --- | --- | --- |
| recommendation | measured is 14.1x the prediction | 4.1x |
| boundary:feasible_marginal | measured is 11.2x the prediction | 4.1x |
| boundary:impossible_proven | measured is 56.6x the prediction | 0.9x |

The simulator is **optimistic on both axes**, which is the direction its own accuracy domain already records at low served concurrency. No margin from this data is fitted here and none may be: a domain built from E-G5 could not then be tested by E-G5.

## The lower bound, tested on hardware

The candidate the throughput bound rejected by the smallest margin, deployed and offered the floor it was rejected against.

| ceiling the bound computed | floor it was rejected against | measured goodput | ratio |
| --- | --- | --- |---|
| 54.433 rps | 55.0 rps | 2.866 rps | **19.0x** |

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
