# E-G8 -- prefill/decode across two different accelerators

> **REAL HARDWARE** -- two nodes, `s8` (A40) and `a5k2` (`a5000-2` GPU 0); deployed by this experiment's harness, not by heteropilot's `planner/deploy/` (GS-28).

SLO (spec S): p99 TTFT <= 550.0 ms, p99 TPOT <= 60.0 ms. 150 requests per run.

## D1: prefill `s8` (A40) -> decode `a5k2` (RTX A5000)

Template, fixed for every run: `pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s32-t8192`, the mirror image of D2's `pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s32-t8192`. Row 5's rule **could not be applied**: at the selection rate no template has a simulator verdict, so the selection is `unknown_measurement` -- the simulator's memory model exhausts the decode instance's KV and raises instead of returning a verdict -- the same cause as E-G3's C14 (e_g3_sim_error_causes.md). At the run rate the deployed placement *is* simulated, and metric 1 is judged against that prediction (row 11 (e)).
Simulator error: `RuntimeError: [MemoryModel] [node_id=1,inst=1] NPU: tried to load <n>MB but only <n>MB is available.`

| template | state | predicted p99 TTFT | predicted p99 TPOT | feasible |
| --- | --- | --- | --- | --- |
| `pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s128-t2048` | unknown_measurement | - | - | unknown |
| `pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s128-t8192` | unknown_measurement | - | - | unknown |
| `pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s256-t2048` | unknown_measurement | - | - | unknown |
| `pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s256-t8192` | unknown_measurement | - | - | unknown |
| `pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s32-t2048` | unknown_measurement | - | - | unknown |
| `pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s32-t8192` | unknown_measurement | - | - | unknown |

### Simulator ceiling (report-only, not a criterion)

The highest rate on the pilot ladder at which the simulator returns a verdict for `pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s32-t8192`, descending: **2 rps** 4 rps unknown_measurement, 3 rps unknown_measurement, 2 rps evaluated. Read beside the measured onset of preemption in the knee pilot.

### Knee pilot (excluded from validation)

| offered rps | drain-corrected goodput / offered | goodput (E-G5) | p99 TTFT | mean interval | interval p99 / mean | decode preemptions | load rule |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.045 | 0.904 | 647 ms | 174.6 ms | 1.33 | 0 | passes |
| 1.5 | 1.030 | 1.236 | 8451 ms | 3652.3 ms | 2.29 | 17 | fails: no_preemption, interval_ratio |
| 2 | 0.784 | 1.244 | 26552 ms | 14225.9 ms | 1.86 | 30 | fails: goodput, no_preemption |
| 3 | 0.525 | 1.237 | 51126 ms | 24578.9 ms | 2.08 | 28 | fails: goodput, no_preemption, interval_ratio |

Decode preemption starts at **1.5 rps** (metric 3).

### Pilot pairs (excluded from validation)

| rep | requests paired | interval change (mean) | per-request SD |
| --- | --- | --- | --- |
| 1 | 150 | +8.25 ms | 25.45 ms |
| 2 | 150 | +10.34 ms | 23.11 ms |
| 3 | 150 | +6.28 ms | 24.18 ms |

### 1. Judgement agreement, 1 rps

Three axes: p99 TTFT <= 550 ms, p99 TPOT <= 60 ms, goodput >= 0.8 rps (row 4's rule at this rate, row 11). The latency-only columns are auxiliary.

| condition | rep | predicted | measured p99 TTFT | measured p99 TPOT | measured goodput | measured | agree | predicted (latency) | measured (latency) | agree (latency) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| independent | 42 | MISSED | 637.2 ms | 32.2 ms | 0.905 rps | MISSED | yes | met | MISSED | no |
| independent | 43 | MISSED | 661.7 ms | 32.5 ms | 0.904 rps | MISSED | yes | met | MISSED | no |
| independent | 44 | MISSED | 629.5 ms | 32.6 ms | 0.904 rps | MISSED | yes | met | MISSED | no |
| shared | 42 | MISSED | 664.5 ms | 32.5 ms | 0.905 rps | MISSED | yes | met | MISSED | no |
| shared | 43 | MISSED | 669.5 ms | 32.6 ms | 0.904 rps | MISSED | yes | met | MISSED | no |
| shared | 44 | MISSED | 705.8 ms | 32.6 ms | 0.904 rps | MISSED | yes | met | MISSED | no |

Agreement: **6 of 6**; false met (counted as a miss): **0**. Auxiliary, latency only: 0 of 6.

Floor sensitivity (analysis only; row 11 (e), as row 9 (c)):

| condition | rep | predicted goodput | floor 0.75: predicted / measured / agree | floor 0.7: predicted / measured / agree |
| --- | --- | --- | --- | --- |
| independent | 42 | 0.785266 | met / MISSED / no | met / MISSED / no |
| independent | 43 | 0.785266 | met / MISSED / no | met / MISSED / no |
| independent | 44 | 0.785266 | met / MISSED / no | met / MISSED / no |
| shared | 42 | 0.785161 | met / MISSED / no | met / MISSED / no |
| shared | 43 | 0.785161 | met / MISSED / no | met / MISSED / no |
| shared | 44 | 0.785161 | met / MISSED / no | met / MISSED / no |

### 2. The contention effect on the KV interval

| pair | requests paired | independent mean | shared mean | change | background duty (shared) |
| --- | --- | --- | --- | --- | --- |
| 42 | 150 | 176.11 ms | 184.17 ms | +8.06 ms | 0.6 |
| 43 | 150 | 178.08 ms | 183.73 ms | +5.65 ms | 0.6 |
| 44 | 150 | 176.24 ms | 184.77 ms | +8.53 ms | 0.6 |

Mean of the pair changes **+7.41 ms** against a predicted **+22.23 ms**: ratio **0.33**, same sign. Same sign and 0.5-2x: **NOT met**.

### 3. Preemptions (report-only)

| condition | rep | decode engine | prefill engine | failed requests |
| --- | --- | --- | --- | --- |
| independent | 42 | 0 | 0 | 0 |
| independent | 43 | 0 | 0 | 0 |
| independent | 44 | 0 | 0 | 0 |
| shared | 42 | 0 | 0 | 0 |
| shared | 43 | 0 | 0 | 0 |
| shared | 44 | 0 | 0 | 0 |

## D2: prefill `a5k2` (RTX A5000) -> decode `s8` (A40)

Template, fixed for every run: `pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s32-t8192`, chosen once at seed 42 by row 5's rule (predictor `sim`).

| template | state | predicted p99 TTFT | predicted p99 TPOT | feasible |
| --- | --- | --- | --- | --- |
| `pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s128-t2048` | evaluated | 979.3 ms | 61.8 ms | False |
| `pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s128-t8192` | evaluated | 509.7 ms | 61.8 ms | False |
| `pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s256-t2048` | evaluated | 979.3 ms | 61.8 ms | False |
| `pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s256-t8192` | evaluated | 509.7 ms | 61.8 ms | False |
| `pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s32-t2048` | evaluated | 979.4 ms | 160.6 ms | False |
| `pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s32-t8192` | evaluated | 509.6 ms | 160.7 ms | False |

### Knee pilot (excluded from validation)

| offered rps | drain-corrected goodput / offered | goodput (E-G5) | p99 TTFT | mean interval | interval p99 / mean | decode preemptions | load rule |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.045 | 0.875 | 852 ms | 221.1 ms | 1.25 | 0 | passes |
| 1.5 | 0.872 | 1.049 | 20388 ms | 10970.3 ms | 1.85 | 0 | fails: goodput |
| 2 | 0.668 | 1.062 | 42518 ms | 21029.8 ms | 2.01 | 0 | fails: goodput, interval_ratio |
| 3 | 0.452 | 1.071 | 65265 ms | 30144.9 ms | 1.89 | 0 | fails: goodput |

Decode preemption starts at **no rate on the sweep** (metric 3).

### Pilot pairs (excluded from validation)

| rep | requests paired | interval change (mean) | per-request SD |
| --- | --- | --- | --- |
| 1 | 150 | +1.12 ms | 19.39 ms |
| 2 | 150 | +4.24 ms | 17.98 ms |
| 3 | 150 | +1.82 ms | 20.30 ms |

### 1. Judgement agreement, 1 rps

Three axes: p99 TTFT <= 550 ms, p99 TPOT <= 60 ms, goodput >= 0.8 rps (row 4's rule at this rate, row 11). The latency-only columns are auxiliary.

| condition | rep | predicted | measured p99 TTFT | measured p99 TPOT | measured goodput | measured | agree | predicted (latency) | measured (latency) | agree (latency) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| independent | 42 | MISSED | 766.3 ms | 40.3 ms | 0.875 rps | MISSED | yes | met | MISSED | no |
| independent | 43 | MISSED | 774.7 ms | 40.3 ms | 0.875 rps | MISSED | yes | met | MISSED | no |
| independent | 44 | MISSED | 784.8 ms | 40.3 ms | 0.875 rps | MISSED | yes | met | MISSED | no |
| shared | 42 | MISSED | 793.8 ms | 40.3 ms | 0.875 rps | MISSED | yes | met | MISSED | no |
| shared | 43 | MISSED | 790.3 ms | 40.3 ms | 0.875 rps | MISSED | yes | met | MISSED | no |
| shared | 44 | MISSED | 801.9 ms | 40.3 ms | 0.875 rps | MISSED | yes | met | MISSED | no |

Agreement: **6 of 6**; false met (counted as a miss): **0**. Auxiliary, latency only: 0 of 6.

`shared`'s predicted p99 TTFT has a 0.3 % margin, so its latency-only verdict is **not counted as evidence of prediction accuracy**, whichever way it went (row 11 (e)).

Floor sensitivity (analysis only; row 11 (e), as row 9 (c)):

| condition | rep | predicted goodput | floor 0.75: predicted / measured / agree | floor 0.7: predicted / measured / agree |
| --- | --- | --- | --- | --- |
| independent | 42 | 0.766471 | met / MISSED / no | met / MISSED / no |
| independent | 43 | 0.766471 | met / MISSED / no | met / MISSED / no |
| independent | 44 | 0.766471 | met / MISSED / no | met / MISSED / no |
| shared | 42 | 0.766476 | met / MISSED / no | met / MISSED / no |
| shared | 43 | 0.766476 | met / MISSED / no | met / MISSED / no |
| shared | 44 | 0.766476 | met / MISSED / no | met / MISSED / no |

### 2. The contention effect on the KV interval

| pair | requests paired | independent mean | shared mean | change | background duty (shared) |
| --- | --- | --- | --- | --- | --- |
| 42 | 150 | 221.06 ms | 222.51 ms | +1.45 ms | 0.595 |
| 43 | 150 | 221.07 ms | 222.34 ms | +1.27 ms | 0.595 |
| 44 | 150 | 221.67 ms | 222.34 ms | +0.67 ms | 0.598 |

Mean of the pair changes **+1.13 ms** against a predicted **+24.49 ms**: ratio **0.05**, same sign. Same sign and 0.5-2x: **NOT met**.

### 3. Preemptions (report-only)

| condition | rep | decode engine | prefill engine | failed requests |
| --- | --- | --- | --- | --- |
| independent | 42 | 0 | 0 | 0 |
| independent | 43 | 0 | 0 | 0 |
| independent | 44 | 0 | 0 | 0 |
| shared | 42 | 0 | 0 | 0 |
| shared | 43 | 0 | 0 | 0 |
| shared | 44 | 0 | 0 | 0 |

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/e_g8/analyze.py
```
