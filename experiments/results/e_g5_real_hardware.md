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

## Above the knee: the exhaustive scope, and what it decided

At `high` the verdict is decided once, by evaluating every representative of GS-27's scope at seed 42 without a budget; the three repetitions repeat the deployment and the measurement of what that decided (row 8). A recommendation that saturates here is a false positive of the 6 rps prediction; a closest miss that also misses is agreement with the infeasibility verdict. They are different claims.

| condition | representatives | evaluated | feasible of size | branch | deployed | K=16 recall | hardware (seeds 42 / 43 / 44) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__burst__T1__high | 210 | 210 | 0 | closest_miss | `…1-dp2-s128-t8192` | - (none feasible) | MISSED / MISSED / MISSED |
| llama31-8b__burst__T2__high | 210 | 210 | 0 | closest_miss | `…1-dp2-s128-t8192` | - (none feasible) | MISSED / MISSED / MISSED |
| llama31-8b__burst__T3__high | 1302 | 1302 | 172 | recommendation | `…4-dp1-s128-t8192` | 0/172 | MISSED / MISSED / MISSED |
| llama31-8b__normal__T1__high | 210 | 210 | 4 | recommendation | `…2-dp1-s256-t8192` | 4/4 | met / met / met |
| llama31-8b__normal__T2__high | 210 | 210 | 4 | recommendation | `…2-dp1-s256-t8192` | 4/4 | MISSED / MISSED / MISSED |
| llama31-8b__normal__T3__high | 1302 | 1302 | 676 | recommendation | `…4-dp1-s128-t8192` | 16/676 | MISSED / MISSED / MISSED |

**The registered adaptive search on a real-hardware spec (row 8 c).** K = 16 against the exhaustive feasible set of the condition's size, seed 42: `burst T3` 0/172; `normal T1` 4/4; `normal T2` 4/4; `normal T3` 16/676. This sits beside GS-31: there the ranker's recall failed a registered criterion on the real-lab holdout; here it is measured on the specs the hardware campaign actually deployed. The ranker is not changed.

## Above the knee: is there really no feasible plan of this size?

At `high` the search returns no feasible plan of the condition's size, so the recommendation's slot is filled by the **closest miss** -- heteropilot's `closest_plan` rule, the infeasible plan with the smallest worst normalised overshoot, restricted to the size (row 8). What is tested is the verdict "no feasible plan of this size", within GS-27's scope cut, not a recommendation's SLO.

| condition | devices | offered rps | p99 TTFT pred | p99 TTFT meas | p99 TPOT pred | p99 TPOT meas | goodput meas | predicted violated axes | measured violated axes | (i) hardware missed | (ii) same axes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__burst__T1__high | 0,1 | 6.0 | 709.6 | 1009.1 | 59.40 | 66.61 | 2.555 | ttft +29 %, goodput +12 % | tpot, ttft | yes | **no** |
| llama31-8b__burst__T1__high | 0,1 | 6.0 | 907.4 | 1009.9 | 61.56 | 65.62 | 2.557 | tpot +3 %, ttft +65 %, goodput +28 % | tpot, ttft | yes | **no** |
| llama31-8b__burst__T1__high | 0,1 | 6.0 | 685.4 | 1010.6 | 66.49 | 66.06 | 2.554 | tpot +11 %, ttft +25 %, goodput +65 % | tpot, ttft | yes | **no** |
| llama31-8b__burst__T2__high | 0,2 | 6.0 | 709.6 | 1009.9 | 59.40 | 66.32 | 2.556 | ttft +29 %, goodput +12 % | tpot, ttft | yes | **no** |
| llama31-8b__burst__T2__high | 0,2 | 6.0 | 907.4 | 1006.6 | 61.56 | 66.17 | 2.552 | tpot +3 %, ttft +65 %, goodput +28 % | tpot, ttft | yes | **no** |
| llama31-8b__burst__T2__high | 0,2 | 6.0 | 685.4 | 1007.0 | 66.49 | 65.66 | 2.556 | tpot +11 %, ttft +25 %, goodput +65 % | tpot, ttft | yes | **no** |

(i) the hardware also missed: **6 of 6**. (ii) and on the predicted axes: **0 of 6**.

## The widened matrix, by pattern and level (row 8)

The recommendation (or, at `high` without a feasible plan, the closest miss) per placement; medians over the three repetitions. `n/a` means the search offered no candidate of the condition's size to deploy.

| pattern | level | placement | deployed | predicted (42/43/44) | measured (42/43/44) | median p99 TTFT | ratio to T1 at this level |
| --- | --- | --- | --- | --- | --- | --- | --- |
| normal | low | T1 | recommendation | n/a / met / n/a | n/a / met / n/a | 301 ms | 1.0x |
| normal | low | T2 | recommendation | n/a / met / n/a | n/a / met / n/a | 343 ms | 1.1x |
| normal | low | T3 | recommendation | met / met / met | met / met / met | 394 ms | 1.3x |
| normal | knee | T1 | recommendation | met / met / met | met / met / met | 405 ms | 1.0x |
| normal | knee | T2 | recommendation | MISSED / MISSED / MISSED | MISSED / MISSED / MISSED | 3341 ms | 8.3x |
| normal | knee | T3 | recommendation | met / met / met | MISSED / MISSED / MISSED | 1948 ms | 4.8x |
| normal | high | T1 | recommendation | met / MISSED / MISSED | met / met / met | 498 ms | 1.0x |
| normal | high | T2 | recommendation | MISSED / MISSED / MISSED | MISSED / MISSED / MISSED | 691 ms | 1.4x |
| normal | high | T3 | recommendation | met / met / met | MISSED / MISSED / MISSED | 13341 ms | 26.8x |
| burst | low | T1 | recommendation | n/a / n/a / n/a | n/a / n/a / n/a | - | - |
| burst | low | T2 | recommendation | n/a / n/a / n/a | n/a / n/a / n/a | - | - |
| burst | low | T3 | recommendation | met / met / met | MISSED / MISSED / MISSED | 1276 ms | - |
| burst | knee | T1 | recommendation | n/a / n/a / n/a | n/a / n/a / n/a | - | - |
| burst | knee | T2 | recommendation | n/a / n/a / n/a | n/a / n/a / n/a | - | - |
| burst | knee | T3 | recommendation | met / met / met | MISSED / MISSED / MISSED | 8488 ms | - |
| burst | high | T1 | closest_miss | MISSED / MISSED / MISSED | MISSED / MISSED / MISSED | 1010 ms | 1.0x |
| burst | high | T2 | closest_miss | MISSED / MISSED / MISSED | MISSED / MISSED / MISSED | 1007 ms | 1.0x |
| burst | high | T3 | recommendation | met / met / met | MISSED / MISSED / MISSED | 17060 ms | 16.9x |

| pattern | level | rows judged | verdicts agreeing |
| --- | --- | --- | --- |
| normal | low | 19 | 19 |
| normal | knee | 27 | 21 |
| normal | high | 27 | 20 |
| burst | low | 15 | 9 |
| burst | knee | 15 | 9 |
| burst | high | 21 | 15 |

## Post-hoc re-prediction after the adapter fix (GS-38, no deployment)

`compile_embedded` gave the simulator the bandwidth of the TP group's **first rank pair** only, and that pair's nominal capacity: a four-rank group on two NVLink pairs bridged by PCIe (T3) was simulated at 112.5 GB/s instead of the 8.71 GB/s busbw measured at world 4. Every deployed row is simulated again below, at its own placement, seed and spec, with the corrected adapter and a fresh cache. **Nothing was redeployed; the hardware column is unchanged.** Link figure given to the simulator, before -> after: T1 112.5 -> 39.24 GB/s, T2 25.12 -> 19.34 GB/s, T3 112.5 -> 8.71 GB/s.

| condition | rep | deployment | p99 TTFT pred | p99 TTFT re-pred | p99 TPOT pred | p99 TPOT re-pred | goodput pred | goodput re-pred | predicted | post-hoc re-prediction (adapter corrected, no deployment) | measured |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__burst__T1__high | 42 | closest_miss | 710 | 710 | 59.4 | 59.4 | 2.12 | 2.12 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__high | 42 | boundary:impossible_proven | 29198 | 30777 | 53.6 | 56.2 | 0.23 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__high | 43 | closest_miss | 907 | 907 | 61.6 | 61.6 | 1.72 | 1.72 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__high | 43 | boundary:impossible_proven | 29383 | 30906 | 53.4 | 55.9 | 0.24 | 0.23 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__high | 44 | closest_miss | 685 | 685 | 66.5 | 66.5 | 0.84 | 0.84 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__high | 44 | boundary:impossible_proven | 32643 | 34450 | 59.8 | 62.7 | 0.17 | 0.07 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__knee | 42 | boundary:impossible_proven | 29198 | 30777 | 53.6 | 56.2 | 0.23 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__knee | 43 | boundary:impossible_proven | 29383 | 30906 | 53.4 | 55.9 | 0.24 | 0.23 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__knee | 44 | boundary:impossible_proven | 32643 | 34450 | 59.8 | 62.7 | 0.17 | 0.07 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__low | 42 | boundary:impossible_proven | 29198 | 30777 | 53.6 | 56.2 | 0.23 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__low | 43 | boundary:impossible_proven | 29383 | 30906 | 53.4 | 55.9 | 0.24 | 0.23 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T1__low | 44 | boundary:impossible_proven | 32643 | 34450 | 59.8 | 62.7 | 0.17 | 0.07 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__high | 42 | closest_miss | 710 | 710 | 59.4 | 59.4 | 2.12 | 2.12 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__high | 42 | boundary:impossible_proven | 32140 | 33271 | 58.5 | 60.4 | 0.19 | 0.09 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__high | 43 | closest_miss | 907 | 907 | 61.6 | 61.6 | 1.72 | 1.72 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__high | 43 | boundary:impossible_proven | 32340 | 33492 | 58.3 | 60.1 | 0.21 | 0.15 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__high | 44 | closest_miss | 685 | 685 | 66.5 | 66.5 | 0.84 | 0.84 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__high | 44 | boundary:impossible_proven | 36009 | 37303 | 65.3 | 67.4 | 0.00 | 0.00 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__knee | 42 | boundary:impossible_proven | 32140 | 33271 | 58.5 | 60.4 | 0.19 | 0.09 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__knee | 43 | boundary:impossible_proven | 32340 | 33492 | 58.3 | 60.1 | 0.21 | 0.15 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__knee | 44 | boundary:impossible_proven | 36009 | 37303 | 65.3 | 67.4 | 0.00 | 0.00 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__low | 42 | boundary:impossible_proven | 32140 | 33271 | 58.5 | 60.4 | 0.19 | 0.09 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__low | 43 | boundary:impossible_proven | 32340 | 33492 | 58.3 | 60.1 | 0.21 | 0.15 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T2__low | 44 | boundary:impossible_proven | 36009 | 37303 | 65.3 | 67.4 | 0.00 | 0.00 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__high | 42 | recommendation | 305 | 10581 | 20.7 | 45.6 | 4.72 | 1.38 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__high | 42 | boundary:feasible_marginal | 601 | 601 | 31.9 | 31.9 | 3.60 | 3.60 | MISSED | **MISSED** | met |
| llama31-8b__burst__T3__high | 42 | boundary:impossible_proven | 29198 | 30777 | 53.6 | 56.2 | 0.23 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__high | 43 | recommendation | 280 | 9688 | 23.4 | 47.5 | 4.37 | 1.54 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__high | 43 | boundary:feasible_marginal | 632 | 632 | 35.2 | 35.2 | 3.40 | 3.40 | MISSED | **MISSED** | met |
| llama31-8b__burst__T3__high | 43 | boundary:impossible_proven | 29383 | 30906 | 53.4 | 55.9 | 0.24 | 0.23 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__high | 44 | recommendation | 300 | 12210 | 23.3 | 53.2 | 4.00 | 0.98 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__high | 44 | boundary:feasible_marginal | 782 | 782 | 37.0 | 37.0 | 3.14 | 3.14 | MISSED | **MISSED** | met |
| llama31-8b__burst__T3__high | 44 | boundary:impossible_proven | 32643 | 34450 | 59.8 | 62.7 | 0.17 | 0.07 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 42 | recommendation | 500 | 1580 | 16.9 | 42.1 | 3.69 | 1.84 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 42 | boundary:feasible_marginal (dup.) | 500 | 1580 | 16.9 | 42.1 | 3.69 | 1.84 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 42 | boundary:impossible_proven | 29198 | 30777 | 53.6 | 56.2 | 0.23 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 43 | recommendation | 466 | 2805 | 20.0 | 46.3 | 3.32 | 1.65 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 43 | boundary:feasible_marginal (dup.) | 466 | 2805 | 20.0 | 46.3 | 3.32 | 1.65 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 43 | boundary:impossible_proven | 29383 | 30906 | 53.4 | 55.9 | 0.24 | 0.23 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 44 | recommendation | 455 | 1901 | 19.7 | 50.6 | 3.10 | 1.34 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 44 | boundary:feasible_marginal (dup.) | 455 | 1901 | 19.7 | 50.6 | 3.10 | 1.34 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__knee | 44 | boundary:impossible_proven | 32643 | 34450 | 59.8 | 62.7 | 0.17 | 0.07 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 42 | recommendation | 418 | 1250 | 13.8 | 22.9 | 2.14 | 1.59 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 42 | boundary:feasible_marginal (dup.) | 418 | 1250 | 13.8 | 22.9 | 2.14 | 1.59 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 42 | boundary:impossible_proven | 29198 | 30777 | 53.6 | 56.2 | 0.23 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 43 | recommendation | 312 | 1208 | 15.0 | 28.4 | 1.84 | 1.40 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 43 | boundary:feasible_marginal (dup.) | 312 | 1208 | 15.0 | 28.4 | 1.84 | 1.40 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 43 | boundary:impossible_proven | 29383 | 30906 | 53.4 | 55.9 | 0.24 | 0.23 | MISSED | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 44 | recommendation | 344 | 1130 | 13.1 | 23.6 | 1.77 | 1.31 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 44 | boundary:feasible_marginal (dup.) | 344 | 1130 | 13.1 | 23.6 | 1.77 | 1.31 | met | **MISSED** | MISSED |
| llama31-8b__burst__T3__low | 44 | boundary:impossible_proven | 32643 | 34450 | 59.8 | 62.7 | 0.17 | 0.07 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__high | 42 | recommendation | 446 | 496 | 48.9 | 51.1 | 2.92 | 2.87 | met | **met** | met |
| llama31-8b__normal__T1__high | 42 | boundary:feasible_marginal (dup.) | 446 | 496 | 48.9 | 51.1 | 2.92 | 2.87 | met | **met** | met |
| llama31-8b__normal__T1__high | 42 | boundary:impossible_proven | 28334 | 29913 | 53.6 | 56.2 | 0.21 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__high | 43 | recommendation | 554 | 655 | 49.6 | 52.0 | 2.91 | 2.71 | MISSED | **MISSED** | met |
| llama31-8b__normal__T1__high | 43 | boundary:feasible_marginal (dup.) | 554 | 655 | 49.6 | 52.0 | 2.91 | 2.71 | MISSED | **MISSED** | met |
| llama31-8b__normal__T1__high | 43 | boundary:impossible_proven | 29339 | 30944 | 53.5 | 56.1 | 0.20 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__high | 44 | recommendation | 841 | 1049 | 56.4 | 59.1 | 2.56 | 2.33 | MISSED | **MISSED** | met |
| llama31-8b__normal__T1__high | 44 | boundary:feasible_marginal (dup.) | 841 | 1049 | 56.4 | 59.1 | 2.56 | 2.33 | MISSED | **MISSED** | met |
| llama31-8b__normal__T1__high | 44 | boundary:impossible_proven | 32582 | 34388 | 59.8 | 62.7 | 0.07 | 0.05 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__knee | 42 | recommendation | 503 | 597 | 41.2 | 43.6 | 2.46 | 2.43 | met | **MISSED** | met |
| llama31-8b__normal__T1__knee | 42 | boundary:feasible_marginal (dup.) | 503 | 597 | 41.2 | 43.6 | 2.46 | 2.43 | met | **MISSED** | met |
| llama31-8b__normal__T1__knee | 42 | boundary:impossible_proven | 28334 | 29913 | 53.6 | 56.2 | 0.21 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__knee | 43 | recommendation | 547 | 572 | 46.1 | 48.5 | 2.52 | 2.42 | met | **MISSED** | met |
| llama31-8b__normal__T1__knee | 43 | boundary:feasible_marginal (dup.) | 547 | 572 | 46.1 | 48.5 | 2.52 | 2.42 | met | **MISSED** | met |
| llama31-8b__normal__T1__knee | 43 | boundary:impossible_proven | 29339 | 30944 | 53.5 | 56.1 | 0.20 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__knee | 44 | recommendation | 457 | 537 | 50.3 | 53.2 | 2.37 | 2.34 | met | **met** | met |
| llama31-8b__normal__T1__knee | 44 | boundary:feasible_marginal (dup.) | 457 | 537 | 50.3 | 53.2 | 2.37 | 2.34 | met | **met** | met |
| llama31-8b__normal__T1__knee | 44 | boundary:impossible_proven | 32582 | 34388 | 59.8 | 62.7 | 0.07 | 0.05 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__low | 42 | boundary:impossible_proven | 28334 | 29913 | 53.6 | 56.2 | 0.21 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__low | 43 | recommendation | 372 | 410 | 25.1 | 26.2 | 1.67 | 1.67 | met | **met** | met |
| llama31-8b__normal__T1__low | 43 | boundary:feasible_marginal (dup.) | 372 | 410 | 25.1 | 26.2 | 1.67 | 1.67 | met | **met** | met |
| llama31-8b__normal__T1__low | 43 | boundary:impossible_proven | 29339 | 30944 | 53.5 | 56.1 | 0.20 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T1__low | 44 | boundary:impossible_proven | 32582 | 34388 | 59.8 | 62.7 | 0.07 | 0.05 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 42 | recommendation | 586 | 621 | 53.3 | 55.5 | 2.78 | 2.71 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 42 | boundary:feasible_marginal (dup.) | 586 | 621 | 53.3 | 55.5 | 2.78 | 2.71 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 42 | boundary:impossible_proven | 31276 | 32407 | 58.5 | 60.4 | 0.14 | 0.08 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 43 | recommendation | 731 | 762 | 54.4 | 56.4 | 2.62 | 2.48 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 43 | boundary:feasible_marginal (dup.) | 731 | 762 | 54.4 | 56.4 | 2.62 | 2.48 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 43 | boundary:impossible_proven | 32329 | 33480 | 58.3 | 60.1 | 0.17 | 0.13 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 44 | recommendation | 1225 | 1360 | 62.0 | 64.3 | 1.99 | 1.57 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 44 | boundary:feasible_marginal (dup.) | 1225 | 1360 | 62.0 | 64.3 | 1.99 | 1.57 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__high | 44 | boundary:impossible_proven | 35947 | 37242 | 65.3 | 67.4 | 0.00 | 0.00 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 42 | recommendation | 631 | 734 | 46.0 | 48.1 | 2.40 | 2.35 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 42 | boundary:feasible_marginal (dup.) | 631 | 734 | 46.0 | 48.1 | 2.40 | 2.35 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 42 | boundary:impossible_proven | 31276 | 32407 | 58.5 | 60.4 | 0.14 | 0.08 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 43 | recommendation | 658 | 668 | 50.6 | 52.3 | 2.34 | 2.31 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 43 | boundary:feasible_marginal (dup.) | 658 | 668 | 50.6 | 52.3 | 2.34 | 2.31 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 43 | boundary:impossible_proven | 32329 | 33480 | 58.3 | 60.1 | 0.17 | 0.13 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 44 | recommendation | 628 | 780 | 55.7 | 57.7 | 2.17 | 2.10 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 44 | boundary:feasible_marginal (dup.) | 628 | 780 | 55.7 | 57.7 | 2.17 | 2.10 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__knee | 44 | boundary:impossible_proven | 35947 | 37242 | 65.3 | 67.4 | 0.00 | 0.00 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__low | 42 | boundary:impossible_proven | 31276 | 32407 | 58.5 | 60.4 | 0.14 | 0.08 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__low | 43 | recommendation | 457 | 490 | 27.4 | 28.7 | 1.66 | 1.65 | met | **met** | met |
| llama31-8b__normal__T2__low | 43 | boundary:feasible_marginal (dup.) | 457 | 490 | 27.4 | 28.7 | 1.66 | 1.65 | met | **met** | met |
| llama31-8b__normal__T2__low | 43 | boundary:impossible_proven | 32329 | 33480 | 58.3 | 60.1 | 0.17 | 0.13 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T2__low | 44 | boundary:impossible_proven | 35947 | 37242 | 65.3 | 67.4 | 0.00 | 0.00 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__high | 42 | recommendation | 172 | 2180 | 17.7 | 46.1 | 4.10 | 3.00 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__high | 42 | boundary:feasible_marginal | 444 | 444 | 43.3 | 43.3 | 2.73 | 2.73 | met | **met** | met |
| llama31-8b__normal__T3__high | 42 | boundary:impossible_proven | 28334 | 29913 | 53.6 | 56.2 | 0.21 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__high | 43 | recommendation | 205 | 7692 | 21.0 | 47.0 | 4.27 | 2.30 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__high | 43 | boundary:feasible_marginal | 463 | 463 | 45.0 | 45.0 | 2.78 | 2.78 | met | **met** | met |
| llama31-8b__normal__T3__high | 43 | boundary:impossible_proven | 29339 | 30944 | 53.5 | 56.1 | 0.20 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__high | 44 | recommendation | 209 | 9032 | 22.2 | 53.8 | 4.03 | 2.06 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__high | 44 | boundary:feasible_marginal | 478 | 478 | 47.8 | 47.8 | 2.66 | 2.66 | met | **met** | met |
| llama31-8b__normal__T3__high | 44 | boundary:impossible_proven | 32582 | 34388 | 59.8 | 62.7 | 0.07 | 0.05 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 42 | recommendation | 162 | 742 | 13.2 | 29.9 | 2.99 | 2.73 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 42 | boundary:feasible_marginal (dup.) | 162 | 742 | 13.2 | 29.9 | 2.99 | 2.73 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 42 | boundary:impossible_proven | 28334 | 29913 | 53.6 | 56.2 | 0.21 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 43 | recommendation | 244 | 758 | 15.5 | 39.9 | 3.26 | 2.62 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 43 | boundary:feasible_marginal (dup.) | 244 | 758 | 15.5 | 39.9 | 3.26 | 2.62 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 43 | boundary:impossible_proven | 29339 | 30944 | 53.5 | 56.1 | 0.20 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 44 | recommendation | 212 | 1339 | 16.1 | 42.4 | 3.10 | 2.31 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 44 | boundary:feasible_marginal (dup.) | 212 | 1339 | 16.1 | 42.4 | 3.10 | 2.31 | met | **MISSED** | MISSED |
| llama31-8b__normal__T3__knee | 44 | boundary:impossible_proven | 32582 | 34388 | 59.8 | 62.7 | 0.07 | 0.05 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__low | 42 | recommendation | 155 | 422 | 11.1 | 14.9 | 1.61 | 1.60 | met | **met** | met |
| llama31-8b__normal__T3__low | 42 | boundary:feasible_marginal (dup.) | 155 | 422 | 11.1 | 14.9 | 1.61 | 1.60 | met | **met** | met |
| llama31-8b__normal__T3__low | 42 | boundary:impossible_proven | 28334 | 29913 | 53.6 | 56.2 | 0.21 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__low | 43 | recommendation | 211 | 597 | 11.3 | 16.5 | 1.82 | 1.74 | met | **MISSED** | met |
| llama31-8b__normal__T3__low | 43 | boundary:feasible_marginal (dup.) | 211 | 597 | 11.3 | 16.5 | 1.82 | 1.74 | met | **MISSED** | met |
| llama31-8b__normal__T3__low | 43 | boundary:impossible_proven | 29339 | 30944 | 53.5 | 56.1 | 0.20 | 0.20 | MISSED | **MISSED** | MISSED |
| llama31-8b__normal__T3__low | 44 | recommendation | 169 | 509 | 12.7 | 19.7 | 1.76 | 1.71 | met | **met** | met |
| llama31-8b__normal__T3__low | 44 | boundary:feasible_marginal (dup.) | 169 | 509 | 12.7 | 19.7 | 1.76 | 1.71 | met | **met** | met |
| llama31-8b__normal__T3__low | 44 | boundary:impossible_proven | 32582 | 34388 | 59.8 | 62.7 | 0.07 | 0.05 | MISSED | **MISSED** | MISSED |

The deployed recommendation (or closest miss) only, every pattern and level, by placement:

| placement | rows | original agrees | re-prediction agrees | original false positives | re-prediction false positives |
| --- | --- | --- | --- | --- | --- |
| T1 | 10 | 8 | 6 | 0 | 0 |
| T2 | 10 | 10 | 10 | 0 | 0 |
| T3 | 18 | 3 | 17 | 15 | 0 |

Verdict agreement with the hardware, original against post-hoc (duplicate marginal rows not counted twice):

| pattern | level | placement | rows | original agrees | re-prediction agrees |
| --- | --- | --- | --- | --- | --- |
| burst | high | T1 | 6 | 6 | 6 |
| burst | high | T2 | 6 | 6 | 6 |
| burst | high | T3 | 9 | 3 | 6 |
| burst | knee | T1 | 3 | 3 | 3 |
| burst | knee | T2 | 3 | 3 | 3 |
| burst | knee | T3 | 6 | 3 | 6 |
| burst | low | T1 | 3 | 3 | 3 |
| burst | low | T2 | 3 | 3 | 3 |
| burst | low | T3 | 6 | 3 | 6 |
| normal | high | T1 | 6 | 4 | 4 |
| normal | high | T2 | 6 | 6 | 6 |
| normal | high | T3 | 9 | 6 | 9 |
| normal | knee | T1 | 6 | 6 | 4 |
| normal | knee | T2 | 6 | 6 | 6 |
| normal | knee | T3 | 6 | 3 | 6 |
| normal | low | T1 | 4 | 4 | 4 |
| normal | low | T2 | 4 | 4 | 4 |
| normal | low | T3 | 6 | 6 | 5 |

## Why burst T1/T2 at low and knee recommended nothing (GS-38)

From the registered runs' cached predictions only (no new simulation; cache misses: 0). Counts are over the evaluated candidates of the condition's size; a candidate can violate more than one axis.

| condition | rep | floor | evaluated of size | TTFT | TPOT | goodput | goodput only | best goodput | best goodput, latency met |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__burst__T1__knee | 42 | 2.3 | 16 | 16 | 0 | 16 | 0 | 2.273 | - |
| llama31-8b__burst__T1__knee | 43 | 2.3 | 16 | 16 | 0 | 16 | 0 | 2.184 | - |
| llama31-8b__burst__T1__knee | 44 | 2.3 | 16 | 16 | 0 | 16 | 0 | 2.059 | - |
| llama31-8b__burst__T1__low | 42 | 1.6 | 16 | 16 | 0 | 0 | 0 | 1.742 | - |
| llama31-8b__burst__T1__low | 43 | 1.6 | 16 | 16 | 0 | 0 | 0 | 1.659 | - |
| llama31-8b__burst__T1__low | 44 | 1.6 | 16 | 16 | 0 | 16 | 0 | 1.527 | - |
| llama31-8b__burst__T2__knee | 42 | 2.3 | 16 | 16 | 0 | 16 | 0 | 2.273 | - |
| llama31-8b__burst__T2__knee | 43 | 2.3 | 16 | 16 | 0 | 16 | 0 | 2.184 | - |
| llama31-8b__burst__T2__knee | 44 | 2.3 | 16 | 16 | 0 | 16 | 0 | 2.059 | - |
| llama31-8b__burst__T2__low | 42 | 1.6 | 16 | 16 | 0 | 0 | 0 | 1.742 | - |
| llama31-8b__burst__T2__low | 43 | 1.6 | 16 | 16 | 0 | 0 | 0 | 1.659 | - |
| llama31-8b__burst__T2__low | 44 | 1.6 | 16 | 16 | 0 | 16 | 0 | 1.527 | - |

**TTFT eliminated every evaluated candidate in every row**; 0 candidate(s) failed on goodput alone, and the lowest predicted p99 TTFT of any evaluated candidate in these rows is 607 ms against 550. So this is not the normal-low goodput-floor artifact: relaxing the floor recovers nothing (next section). T1 and T2 rows are identical because the search is the same for both -- the condition's placement applies only at deployment. These are the pre-GS-38 adapter's predictions, the ones the run acted on.

## A hardware-derived floor applied to pessimistic simulator predictions (GS-38, analysis only, no deployment)

Row 4's rule derives each level's goodput floor from the *hardware's* measured goodput. The simulator predicts lower goodput than the hardware delivers, so a floor that the hardware clears by construction can sit above every prediction. Below, each condition's cached predictions are re-judged at other floors: latency verdicts exactly as the run's own feasibility reports gave them (with their accuracy margins), goodput re-tested against the floor. **The evaluated set is the registered floor's**: a run made at another floor would reorder the ranker's budget (GS-36) and could reach other candidates, which this cannot show. Each cell: feasible candidates of the condition's size / whether the recommendation's template is the deployed one (`same`, `other`, or `-` for none).

| condition | rep | registered floor | at registered | at 1.4 | at 1.5 | at 1.6 |
| --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__burst__T1__high | 42 | 2.4 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T1__knee | 42 | 2.3 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T1__knee | 43 | 2.3 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T1__knee | 44 | 2.3 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T1__low | 42 | 1.6 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T1__low | 43 | 1.6 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T1__low | 44 | 1.6 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T2__high | 42 | 2.4 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T2__knee | 42 | 2.3 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T2__knee | 43 | 2.3 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T2__knee | 44 | 2.3 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T2__low | 42 | 1.6 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T2__low | 43 | 1.6 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T2__low | 44 | 1.6 | 0 / - | 0 / - | 0 / - | 0 / - |
| llama31-8b__burst__T3__high | 42 | 2.4 | 172 / same | 172 / same | 172 / same | 172 / same |
| llama31-8b__burst__T3__knee | 42 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__burst__T3__knee | 43 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__burst__T3__knee | 44 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__burst__T3__low | 42 | 1.6 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__burst__T3__low | 43 | 1.6 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__burst__T3__low | 44 | 1.6 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T1__high | 42 | 2.4 | 4 / same | 4 / same | 4 / same | 4 / same |
| llama31-8b__normal__T1__knee | 42 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T1__knee | 43 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T1__knee | 44 | 2.3 | 8 / same | 8 / same | 8 / same | 8 / same |
| llama31-8b__normal__T1__low | 42 | 1.6 | 0 / - | 16 / same as rep 43's | 16 / same as rep 43's | 0 / - |
| llama31-8b__normal__T1__low | 43 | 1.6 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T1__low | 44 | 1.6 | 0 / - | 16 / same as rep 43's | 16 / same as rep 43's | 0 / - |
| llama31-8b__normal__T2__high | 42 | 2.4 | 4 / same | 4 / same | 4 / same | 4 / same |
| llama31-8b__normal__T2__knee | 42 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T2__knee | 43 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T2__knee | 44 | 2.3 | 8 / same | 8 / same | 8 / same | 8 / same |
| llama31-8b__normal__T2__low | 42 | 1.6 | 0 / - | 16 / same as rep 43's | 16 / same as rep 43's | 0 / - |
| llama31-8b__normal__T2__low | 43 | 1.6 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T2__low | 44 | 1.6 | 0 / - | 16 / same as rep 43's | 16 / same as rep 43's | 0 / - |
| llama31-8b__normal__T3__high | 42 | 2.4 | 676 / same | 676 / same | 676 / same | 676 / same |
| llama31-8b__normal__T3__knee | 42 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T3__knee | 43 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T3__knee | 44 | 2.3 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T3__low | 42 | 1.6 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T3__low | 43 | 1.6 | 16 / same | 16 / same | 16 / same | 16 / same |
| llama31-8b__normal__T3__low | 44 | 1.6 | 16 / same | 16 / same | 16 / same | 16 / same |

Conditions whose recommendation appears or vanishes across these floors: normal__T1__low seed 42, normal__T1__low seed 44, normal__T2__low seed 42, normal__T2__low seed 44. Everywhere else the answer, and the template, is the same at every floor tried.

## Predicted against measured (normal x knee)

| condition | deployment | devices | offered rps | p99 TTFT pred | p99 TTFT meas | p99 TPOT pred | p99 TPOT meas | goodput meas | predicted | measured |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 503.1 | 404.5 | 41.20 | 51.49 | 2.582 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,1 | 4.0 | 503.1 | 422.6 | 41.20 | 52.16 | 2.571 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 28334.3 | 31557.8 | 53.61 | 55.24 | 2.849 | MISSED | **MISSED** |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 546.7 | 421.3 | 46.11 | 51.93 | 2.576 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,1 | 4.0 | 546.7 | 424.1 | 46.11 | 52.25 | 2.569 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 29338.7 | 31416.3 | 53.48 | 55.14 | 2.852 | MISSED | **MISSED** |
| llama31-8b__normal__T1__knee | recommendation | 0,1 | 4.0 | 456.5 | 352.2 | 50.28 | 50.99 | 2.596 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,1 | 4.0 | 456.5 | 380.9 | 50.28 | 51.54 | 2.591 | met | **met** |
| llama31-8b__normal__T1__knee | boundary:impossible_proven | 0,1 | 55.0 | 32582.2 | 31297.6 | 59.78 | 55.01 | 2.859 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 630.8 | 3341.1 | 46.01 | 56.20 | 2.445 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,2 | 4.0 | 630.8 | 3381.8 | 46.01 | 56.36 | 2.444 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 31275.5 | 34070.0 | 58.50 | 59.44 | 2.687 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 658.2 | 3400.1 | 50.61 | 56.29 | 2.443 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,2 | 4.0 | 658.2 | 3332.0 | 50.61 | 56.17 | 2.449 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 32329.3 | 34074.6 | 58.29 | 59.45 | 2.687 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | recommendation | 0,2 | 4.0 | 628.0 | 3056.0 | 55.71 | 55.68 | 2.458 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,2 | 4.0 | 628.0 | 3044.1 | 55.71 | 55.76 | 2.458 | MISSED | **MISSED** |
| llama31-8b__normal__T2__knee | boundary:impossible_proven | 0,2 | 55.0 | 35947.3 | 34049.1 | 65.27 | 59.39 | 2.688 | MISSED | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 161.7 | 1948.3 | 13.16 | 53.76 | 2.607 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,1,2,3 | 4.0 | 161.7 | 2117.0 | 13.16 | 54.18 | 2.592 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 28334.3 | 30858.8 | 53.61 | 54.32 | 2.888 | MISSED | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 244.5 | 1827.7 | 15.47 | 53.63 | 2.611 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,1,2,3 | 4.0 | 244.5 | 2938.5 | 15.47 | 55.32 | 2.552 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:impossible_proven | 0,1 | 55.0 | 29338.7 | 31220.4 | 53.48 | 54.95 | 2.860 | MISSED | **MISSED** |
| llama31-8b__normal__T3__knee | recommendation | 0,1,2,3 | 4.0 | 212.4 | 2051.8 | 16.06 | 54.01 | 2.598 | met | **MISSED** |
| llama31-8b__normal__T3__knee | boundary:feasible_marginal (duplicate of recommendation) | 0,1,2,3 | 4.0 | 212.4 | 2395.6 | 16.06 | 54.56 | 2.579 | met | **MISSED** |
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

**This arm's question is the size of the contention effect and whether the model's prediction of it agrees, not whether a P/D deployment meets its SLO** (preregistration row 7 f). Prefill on `s8` GPU 0, decode on `s6` GPU 0, `NixlConnector`. The primary metric is the per-request **interval** from the prefill response to the decode stream's first token -- the KV pull plus the decode instance's first step -- as a paired mean difference; p99 TTFT is secondary. A constant added to every request shows in a mean and is buried in a p99.[^pdtokens]

Template, fixed for every run (row 7 a): `pd(cuda-a40-s8-tp1-dp1 P + cuda-a40-s6-tp1-dp1 D)-s32-t8192`, chosen once at seed 42. **Every P/D template was predicted infeasible on TPOT** before selection, which is reported as a separate fact and is not this arm's question:

| template | predicted p99 TTFT | predicted p99 TPOT | feasible |
| --- | --- | --- | --- |
| `…)-s128-t2048` | 727.1 ms | 61.8 ms | False |
| `…)-s128-t8192` | 472.2 ms | 61.9 ms | False |
| `…)-s256-t2048` | 727.1 ms | 61.8 ms | False |
| `…)-s256-t8192` | 472.2 ms | 61.9 ms | False |
| `…D)-s32-t2048` | 726.6 ms | 160.7 ms | False |
| `…D)-s32-t8192` | 471.9 ms | 160.7 ms | False |

### The knee pilot (excluded from validation)

| offered rps | goodput / offered | drain-corrected | p50 TTFT | p99 TTFT | mean interval |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.875 | 1.045 | 336 ms | 668 ms | 217.1 ms |
| 1.5 | 0.700 | 0.873 | 13404 ms | 20375 ms | 10979.9 ms |
| 2 | 0.531 | 0.665 | 24121 ms | 42369 ms | 20970.8 ms |
| 3 | 0.358 | 0.452 | 34064 ms | 64783 ms | 31085.6 ms |

The rerun rate is the highest pilot rate whose drain-corrected goodput is at least 0.9 of offered: **1 rps**. E-G5's own goodput divides by the span to the last completion, so an unqueued run of this trace scores 0.845 at 1 rps; the corrected figure removes one unqueued request's service time from the span (row 7 b).

### Pilot pairs (excluded from validation)

| rep | requests paired | interval change (mean) | per-request SD |
| --- | --- | --- | --- |
| 42 | 150 | +3.87 ms | 15.24 ms |
| 43 | 150 | +1.79 ms | 17.84 ms |
| 44 | 150 | +1.77 ms | 14.03 ms |

SD of the pair-mean change across pilot pairs: **1.20 ms**.

### The validation pairs, 1 rps

| pair | requests paired | interval mean independent | shared | change | predicted change | p99 TTFT independent | shared | change | predicted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 42 | 150 | 216.40 ms | 219.36 ms | +2.96 ms | +14.45 ms | 669.2 ms | 667.8 ms | -1.4 ms | +50.9 ms |
| 43 | 150 | 218.22 ms | 220.26 ms | +2.05 ms | +14.45 ms | 658.9 ms | 668.5 ms | +9.6 ms | +50.9 ms |
| 44 | 150 | 217.77 ms | 217.48 ms | -0.28 ms | +14.45 ms | 657.0 ms | 647.4 ms | -9.5 ms | +50.9 ms |

#### The registered criterion (row 7 e)

| quantity | value |
| --- | --- |
| measured change | +1.57 |
| SD across pairs | 1.67 |
| predicted change | +14.45 |
| ratio | 0.11 |
| verdict | NOT met |

Mean of the pair changes **+1.57 ms** against a predicted **+14.45 ms**: ratio **0.11**, same sign. Registered: same sign and a ratio between 0.5 and 2. Verdict: **NOT met**.

### The row-5 runs (GS-33), kept and not validated

Registered by row 5 and run before row 7 existed. Each repetition chose its own template and the configuration saturated; they are kept as the record of why row 7 was needed, and no verdict is drawn from them.

| condition | rep | completed | failed | p50 TTFT | p99 TTFT | p99 TPOT | goodput | SLO attainment | background duty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pd-independent | 42 | 150 | 0 | 38640.5 | 76859.3 | 41.21 | 1.081 | 0.080 | none |
| pd-independent | 43 | 150 | 0 | 1257.1 | 24795.0 | 96.22 | 1.563 | 0.167 | none |
| pd-independent | 44 | 150 | 0 | 38592.9 | 76812.6 | 41.21 | 1.079 | 0.080 | none |
| pd-shared | 42 | 150 | 0 | 39230.5 | 76485.0 | 41.20 | 1.080 | 0.080 | 0.600 |
| pd-shared | 43 | 150 | 0 | 1239.6 | 24799.9 | 97.57 | 1.560 | 0.147 | 0.600 |
| pd-shared | 44 | 150 | 0 | 38633.5 | 76717.8 | 41.22 | 1.081 | 0.080 | 0.600 |

#### Paired by repetition

| rep | template | independent p99 TTFT | shared p99 TTFT | change | predicted change | goodput / offered |
| --- | --- | --- | --- | --- | --- | --- |
| 42 | `…D)-s32-t8192` | 76859.3 ms | 76485.0 ms | -374.3 ms | +51.5 ms | 0.27 |
| 43 | `…)-s128-t8192` | 24795.0 ms | 24799.9 ms | +4.8 ms | +50.9 ms | 0.39 |
| 44 | `…D)-s32-t8192` | 76812.6 ms | 76717.8 ms | -94.8 ms | +50.9 ms | 0.27 |

**Saturated in repetitions 42, 43, 44.** Goodput is below 90 % of the offered rate, so requests queue for the whole trace and p99 TTFT is set by that queue, not by the path the KV takes. In that regime a change in the NIC's load is not observable, and this arm cannot answer its question.

#### Row 5's criterion

**Not computable as registered.** The criterion reads the spread of the three independent repetitions as noise, which assumes they are replicates. They are not: each repetition re-ran the search and deployed the template it chose, and the repetitions chose 2 different ones (`…)-s128-t8192`, `…D)-s32-t8192`). The spread is therefore a configuration difference, and a verdict computed from it would be met by construction. It is not reported as met.

[^pdtokens]: This arm compares **latency** between two P/D conditions, not outputs. A disaggregated greedy token stream is not the aggregated one: across these two nodes two of three probe prompts diverged, reproducibly (GS-29). No statement about output identity is made from these rows.

## Reproducing

The measured columns are hardware and are not reproducible from this repository; their raw files are committed under `experiments/e_g5/raw/` and this file is rebuilt from them in under a second by the last command. `REPRODUCE.md` says what each step needs.

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
# hardware: the registered matrix (row 8) and, with WITH_PD=1, the P/D arm (row 7)
bash experiments/e_g5/run_grid.sh
# GS-38: post-hoc re-prediction (corrected adapter, fresh cache; CPU only)
vendor/heteropilot/.venv/bin/python experiments/e_g5/repredict.py
# GS-38: cache-only floor diagnosis, under the pre-GS-38 adapter
bash experiments/e_g5/run_floor_diagnosis.sh
.venv/bin/python experiments/e_g5/analyze.py --out experiments/results/e_g5_real_hardware.md
```
