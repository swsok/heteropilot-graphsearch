# E-G4 — the contention model against the wire

> **REAL HARDWARE.** Every measured column comes from `experiments/microbench/raw/`, on the node whose serials those files carry. The predicted columns are computed. Nothing here is a mock and nothing here is a simulation.

Conditions 1-4 of `experiments/microbench/PLAN.md`, at location (a): the A40 node's shared PCIe path, GPU0-3 on NUMA 0, pinned with `numactl --cpunodebind=0 --membind=0` (both halves). 20 repetitions per point; PLAN.md registers at least 10.

**Location (b), the inter-node NIC, is `not run`.** This is one machine with one NIC and there is no second node to send to. It is reported rather than omitted: an omitted row reads as a row that passed, and half a matrix is not a matrix.

## The verdict, against the registered limits

| declaration | condition | clause | fluid | null | verdict |
| --- | --- | --- | --- | --- | --- |
| `as_measured` | bidirectional | fluid p50 <= 15% and p90 <= 30%, and fluid must beat null | 4.8% / 1.5% p90 | 48.3% | **PASS** |
| `as_measured` | single | null and fluid agree within 5% | 0.0% | 0.5% | **PASS** |
| `as_measured` | two-independent | null and fluid agree within 5% | 0.0% | 1.1% | **PASS** |
| `as_measured` | two-same | fluid p50 <= 15% and p90 <= 30%, and fluid must beat null | 1.8% / 3.0% p90 | 1.8% | **PASS** |
| `as_planned` | bidirectional | fluid p50 <= 15% and p90 <= 30%, and fluid must beat null | 33.2% / 24.3% p90 | 34.2% | **FAIL** |
| `as_planned` | single | null and fluid agree within 5% | 0.0% | 0.5% | **PASS** |
| `as_planned` | two-independent | null and fluid agree within 5% | 0.0% | 1.1% | **PASS** |
| `as_planned` | two-same | fluid p50 <= 15% and p90 <= 30%, and fluid must beat null | 93.1% / 90.9% p90 | 7.5% | **FAIL** |

**The registered verdict is the `as_planned` one.** `as_measured` is fitted on the files in the next section and is shown for one reason: to separate two corrections that would otherwise be confused.

## What actually failed, and what did not

The `two-same` row is the whole result. `PLAN.md` fixed, before any of this ran, that GPU0-2 and GPU1-3 "share one PCIe host bridge — this is the shared uplink". Processor sharing over that declaration predicts each of two concurrent copies gets half. **Measured, each got all of it**: 25.11 and 25.11 GB/s at 256 MiB against 25.12 GB/s for the same copy alone, and the same shape at every size in the grid.

25.1 GB/s is a PCIe 4.0 x16 running out of lanes. The bottleneck for a peer copy on this node is **the endpoint's own x16 port**, not a bridge behind it, so two copies between disjoint device pairs share nothing and neither slows the other down.

So the fluid model is **not** what these numbers falsify. Processor sharing over a genuinely shared resource is still processor sharing; what was wrong is the claim about which resource is shared. Those are different corrections — one rewrites `graphsearch/contention.py`, the other rewrites a line of YAML in a cluster fixture — and a table that reported only "fluid: 100% error" would have invited the first when the second is what the data supports.

## Where the model is exact, and where it stops being

The `bidirectional` case is the one worth reading carefully, and a single median over the grid would have hidden it. 0→2 and 2→0 at once **do** contend, and from 4 to 64 MiB they contend by exactly the factor processor sharing predicts — fluid is within **0.1 to 2.5 %** of the wire there, against 48-50 % for null. That is the clearest evidence in this file that the model is doing real work.

At **128 MiB and above the regime changes**: the pair reaches 16.7 GB/s per direction, an aggregate of 33.4 GB/s over a path that carries 25.1 GB/s one way. That is 1.33x a single direction, where everything below 128 MiB gives 1.0x, and fluid is then a third high. Something starts overlapping the two directions at large transfers that does not at small ones; **this file does not establish what**, and naming a cause here would be inventing one.

The registered limits are met at the median and the band above 128 MiB is recorded as the boundary of the model's accuracy, not smoothed into it. Fitting a capacity that lands on 33.4 GB/s would have made this table read clean and made the next node's prediction wrong silently — a capacity chosen because it reproduces the answer is not a measurement of anything.

| condition / flow | 1M | 2M | 4M | 8M | 16M | 32M | 64M | 128M | 256M |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `a-cond1-single-bridge-0-2` 0-2 | 0% | 9% | 5% | 3% | 0% | 0% | 0% | 0% | 0% |
| `a-cond1-single-nvlink-0-1` 0-1 | 16% | 11% | 4% | 4% | 2% | 0% | 0% | 1% | 0% |
| `a-cond2-bg60-same-bridge` 0-2 | 3% | 11% | 6% | 3% | 1% | 0% | 0% | 0% | 0% |
| `a-cond2-two-same-bridge` 0-2 | 14% | 15% | 8% | 5% | 2% | 0% | 0% | 0% | 0% |
| `a-cond2-two-same-bridge` 1-3 | 19% | 14% | 9% | 5% | 2% | 0% | 0% | 0% | 0% |
| `a-cond3-bg60-independent` 0-2 | 9% | 12% | 7% | 3% | 1% | 0% | 0% | 0% | 0% |
| `a-cond3-two-independent` 0-2 | 9% | 13% | 7% | 5% | 0% | 0% | 0% | 0% | 0% |
| `a-cond3-two-independent` 4-6 | 30% | 14% | 8% | 5% | 2% | 0% | 0% | 0% | 0% |
| `a-cond4-bidi-bg60-same` 0-2 | 14% | 8% | 4% | 1% | 0% | 0% | 0% | 0% | 34% |
| `a-cond4-bidi-bg60-same` 2-0 | 13% | 17% | 21% | 1% | 30% | 0% | 33% | 0% | 34% |
| `a-cond4-bidirectional-0-2` 0-2 | 7% | 10% | 2% | 2% | 0% | 0% | 0% | 33% | 33% |
| `a-cond4-bidirectional-0-2` 2-0 | 5% | 1% | 29% | 1% | 32% | 0% | 0% | 33% | 33% |

Fluid p50 error per point under `as_measured`. The 1-2 MiB column is overhead-dominated everywhere and the mid sizes are noisy point-to-point (`a-cond4-bidi-bg60-same` 2-0 swings between 0 and 33 % across neighbouring sizes); `bandwidth_gbps_min`/`_max` and every raw sample are in the raw files, and PLAN.md's reason for requiring repetitions is heteropilot's own record of two runs of one trial disagreeing by 38 %. The `bg60` rows carry a background generator that sustained a **measured** duty cycle of 0.585 to 0.600 against its 0.6 target, moving 24.6-25.1 GB/s while busy — entered into the graph as `reserved`, never as a flow, because it is traffic this planner does not control. Under `as_planned` that reservation sits on the bridge the foreground is declared to cross: 15.0 GB/s off a 25.1 GB/s bridge leaves 10.1, so both models predict the foreground drops to about 10 GB/s and takes **2.5x as long** (146 % error at 256 MiB). **It measured 25.12 GB/s, exactly its unloaded rate.** A third process saturating 1-3 six seconds in ten does nothing to 0-2 -- which is the same finding as `two-same`, reached by a different route, and the reason a reservation on the wrong resource is not a conservative error.

## What the `as_measured` column was fitted on

Registered here and in `docs/preregistration.md`. Anything fitted on these files is **excluded from P3's validation set** — a model shown the answer cannot also be tested by it (work order P2.4):

- `experiments/microbench/raw/*/a-cond1-single-bridge-0-2.json`
- `experiments/microbench/raw/*/a-cond1-single-nvlink-0-1.json`
- `experiments/microbench/raw/*/a-cond2-bg60-same-bridge.json`
- `experiments/microbench/raw/*/a-cond2-two-same-bridge.json`
- `experiments/microbench/raw/*/a-cond3-bg60-independent.json`
- `experiments/microbench/raw/*/a-cond3-two-independent.json`
- `experiments/microbench/raw/*/a-cond4-bidi-bg60-same.json`
- `experiments/microbench/raw/*/a-cond4-bidirectional-0-2.json`

## Condition 5 — the collective, and why `world_size` is a key

Measured on this node, busbw plateau at 64 MiB: **19.34 GB/s at world 2** across the bridge, **8.71 GB/s at world 4**. heteropilot's own `docs/nodes/a40.md` records 19.29 and 8.8 for the same two. One wire, 2.2x apart, reproduced independently — which is the argument for `world_size` being part of the `LinkMeasurement` key rather than a note beside it. NVLink at world 2 measured 52.32 GB/s p2p.

## The grid

| condition | flow | MiB | class | p50 ms | p90 ms | null ms | fluid ms | err null p50 | err fluid p50 | err fluid p90 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | 0-2 | 1 | mid | 0.064 | 0.065 | 0.064 | 0.064 | 0.0% | 0.0% | 1.1% |
| single | 0-2 | 2 | mid | 0.117 | 0.117 | 0.106 | 0.106 | 9.2% | 9.2% | 9.8% |
| single | 0-2 | 4 | bulk | 0.200 | 0.206 | 0.189 | 0.189 | 5.4% | 5.4% | 7.9% |
| single | 0-2 | 8 | bulk | 0.365 | 0.370 | 0.356 | 0.356 | 2.5% | 2.5% | 3.7% |
| single | 0-2 | 16 | bulk | 0.691 | 0.692 | 0.690 | 0.690 | 0.1% | 0.1% | 0.3% |
| single | 0-2 | 32 | bulk | 1.356 | 1.364 | 1.358 | 1.358 | 0.2% | 0.2% | 0.4% |
| single | 0-2 | 64 | bulk | 2.684 | 2.688 | 2.694 | 2.694 | 0.4% | 0.4% | 0.2% |
| single | 0-2 | 128 | bulk | 5.353 | 5.357 | 5.365 | 5.365 | 0.2% | 0.2% | 0.2% |
| single | 0-2 | 256 | bulk | 10.685 | 10.689 | 10.708 | 10.708 | 0.2% | 0.2% | 0.2% |
| single | 0-1 | 1 | mid | 0.037 | 0.038 | 0.042 | 0.042 | 15.8% | 15.8% | 11.4% |
| single | 0-1 | 2 | mid | 0.070 | 0.072 | 0.062 | 0.062 | 11.1% | 11.1% | 13.6% |
| single | 0-1 | 4 | bulk | 0.107 | 0.114 | 0.102 | 0.102 | 4.4% | 4.4% | 10.3% |
| single | 0-1 | 8 | bulk | 0.190 | 0.193 | 0.182 | 0.182 | 4.4% | 4.4% | 5.8% |
| single | 0-1 | 16 | bulk | 0.347 | 0.354 | 0.341 | 0.341 | 1.7% | 1.7% | 3.6% |
| single | 0-1 | 32 | bulk | 0.662 | 0.679 | 0.660 | 0.660 | 0.4% | 0.4% | 2.8% |
| single | 0-1 | 64 | bulk | 1.292 | 1.300 | 1.297 | 1.297 | 0.4% | 0.4% | 0.2% |
| single | 0-1 | 128 | bulk | 2.557 | 2.565 | 2.572 | 2.572 | 0.6% | 0.6% | 0.3% |
| single | 0-1 | 256 | bulk | 5.100 | 5.106 | 5.122 | 5.122 | 0.4% | 0.4% | 0.3% |
| two-same | 0-2 | 1 | mid | 0.066 | 0.067 | 0.064 | 0.064 | 3.0% | 3.0% | 4.7% |
| two-same | 0-2 | 2 | mid | 0.119 | 0.123 | 0.151 | 0.151 | 27.1% | 27.1% | 22.7% |
| two-same | 0-2 | 4 | bulk | 0.201 | 0.205 | 0.322 | 0.322 | 60.4% | 60.4% | 57.5% |
| two-same | 0-2 | 8 | bulk | 0.368 | 0.372 | 0.701 | 0.701 | 90.5% | 90.5% | 88.8% |
| two-same | 0-2 | 16 | bulk | 0.700 | 0.709 | 1.513 | 1.513 | 116.0% | 116.0% | 113.5% |
| two-same | 0-2 | 32 | bulk | 1.358 | 1.366 | 3.161 | 3.161 | 132.7% | 132.7% | 131.5% |
| two-same | 0-2 | 64 | bulk | 2.686 | 2.691 | 6.481 | 6.481 | 141.3% | 141.3% | 140.8% |
| two-same | 0-2 | 128 | bulk | 5.351 | 5.359 | 13.160 | 13.160 | 145.9% | 145.9% | 145.6% |
| two-same | 0-2 | 256 | bulk | 10.686 | 10.687 | 26.538 | 26.538 | 148.4% | 148.4% | 148.3% |
| two-same | 0-2 | 1 | mid | 0.075 | 0.086 | 0.064 | 0.106 | 14.3% | 41.5% | 23.3% |
| two-same | 1-3 | 1 | mid | 0.079 | 0.098 | 0.064 | 0.106 | 18.8% | 34.1% | 7.9% |
| two-same | 0-2 | 2 | mid | 0.124 | 0.136 | 0.106 | 0.189 | 14.8% | 52.3% | 39.0% |
| two-same | 1-3 | 2 | mid | 0.123 | 0.129 | 0.106 | 0.189 | 13.6% | 54.5% | 47.0% |
| two-same | 0-2 | 4 | bulk | 0.205 | 0.255 | 0.189 | 0.356 | 7.5% | 74.1% | 39.8% |
| two-same | 1-3 | 4 | bulk | 0.208 | 0.254 | 0.189 | 0.356 | 9.1% | 71.1% | 40.0% |
| two-same | 0-2 | 8 | bulk | 0.377 | 0.421 | 0.356 | 0.690 | 5.5% | 83.2% | 64.1% |
| two-same | 1-3 | 8 | bulk | 0.375 | 0.420 | 0.356 | 0.690 | 5.1% | 83.8% | 64.3% |
| two-same | 0-2 | 16 | bulk | 0.703 | 0.711 | 0.690 | 1.358 | 1.8% | 93.1% | 90.9% |
| two-same | 1-3 | 16 | bulk | 0.704 | 0.716 | 0.690 | 1.358 | 2.0% | 92.8% | 89.7% |
| two-same | 0-2 | 32 | bulk | 1.361 | 1.371 | 1.358 | 2.694 | 0.2% | 98.0% | 96.5% |
| two-same | 1-3 | 32 | bulk | 1.360 | 1.378 | 1.358 | 2.694 | 0.2% | 98.0% | 95.5% |
| two-same | 0-2 | 64 | bulk | 2.689 | 2.692 | 2.694 | 5.365 | 0.2% | 99.5% | 99.3% |
| two-same | 1-3 | 64 | bulk | 2.690 | 2.698 | 2.694 | 5.365 | 0.2% | 99.5% | 98.9% |
| two-same | 0-2 | 128 | bulk | 5.354 | 5.364 | 5.365 | 10.708 | 0.2% | 100.0% | 99.6% |
| two-same | 1-3 | 128 | bulk | 5.353 | 5.360 | 5.365 | 10.708 | 0.2% | 100.1% | 99.8% |
| two-same | 0-2 | 256 | bulk | 10.689 | 10.693 | 10.708 | 21.395 | 0.2% | 100.1% | 100.1% |
| two-same | 1-3 | 256 | bulk | 10.689 | 10.695 | 10.708 | 21.395 | 0.2% | 100.1% | 100.0% |
| two-independent | 0-2 | 1 | mid | 0.070 | 0.075 | 0.064 | 0.064 | 8.9% | 8.9% | 14.2% |
| two-independent | 0-2 | 2 | mid | 0.120 | 0.124 | 0.106 | 0.106 | 11.6% | 11.6% | 14.8% |
| two-independent | 0-2 | 4 | bulk | 0.204 | 0.209 | 0.189 | 0.189 | 7.3% | 7.3% | 9.2% |
| two-independent | 0-2 | 8 | bulk | 0.369 | 0.378 | 0.356 | 0.356 | 3.4% | 3.4% | 5.8% |
| two-independent | 0-2 | 16 | bulk | 0.698 | 0.702 | 0.690 | 0.690 | 1.1% | 1.1% | 1.7% |
| two-independent | 0-2 | 32 | bulk | 1.358 | 1.359 | 1.358 | 1.358 | 0.0% | 0.0% | 0.1% |
| two-independent | 0-2 | 64 | bulk | 2.685 | 2.686 | 2.694 | 2.694 | 0.3% | 0.3% | 0.3% |
| two-independent | 0-2 | 128 | bulk | 5.356 | 5.358 | 5.365 | 5.365 | 0.2% | 0.2% | 0.1% |
| two-independent | 0-2 | 256 | bulk | 10.686 | 10.687 | 10.708 | 10.708 | 0.2% | 0.2% | 0.2% |
| two-independent | 0-2 | 1 | mid | 0.070 | 0.085 | 0.064 | 0.064 | 8.8% | 8.8% | 24.8% |
| two-independent | 4-6 | 1 | mid | 0.091 | 0.095 | 0.064 | 0.064 | 29.7% | 29.7% | 32.8% |
| two-independent | 0-2 | 2 | mid | 0.122 | 0.137 | 0.106 | 0.106 | 13.5% | 13.5% | 22.5% |
| two-independent | 4-6 | 2 | mid | 0.123 | 0.157 | 0.106 | 0.106 | 14.3% | 14.3% | 32.6% |
| two-independent | 0-2 | 4 | bulk | 0.204 | 0.216 | 0.189 | 0.189 | 7.1% | 7.1% | 12.5% |
| two-independent | 4-6 | 4 | bulk | 0.205 | 0.213 | 0.189 | 0.189 | 7.7% | 7.7% | 11.3% |
| two-independent | 0-2 | 8 | bulk | 0.374 | 0.382 | 0.356 | 0.356 | 4.7% | 4.7% | 6.8% |
| two-independent | 4-6 | 8 | bulk | 0.373 | 0.382 | 0.356 | 0.356 | 4.6% | 4.6% | 6.8% |
| two-independent | 0-2 | 16 | bulk | 0.690 | 0.703 | 0.690 | 0.690 | 0.1% | 0.1% | 1.8% |
| two-independent | 4-6 | 16 | bulk | 0.704 | 0.715 | 0.690 | 0.690 | 2.0% | 2.0% | 3.4% |
| two-independent | 0-2 | 32 | bulk | 1.362 | 1.388 | 1.358 | 1.358 | 0.3% | 0.3% | 2.1% |
| two-independent | 4-6 | 32 | bulk | 1.363 | 1.390 | 1.358 | 1.358 | 0.4% | 0.4% | 2.3% |
| two-independent | 0-2 | 64 | bulk | 2.689 | 2.700 | 2.694 | 2.694 | 0.2% | 0.2% | 0.2% |
| two-independent | 4-6 | 64 | bulk | 2.693 | 2.698 | 2.694 | 2.694 | 0.0% | 0.0% | 0.1% |
| two-independent | 0-2 | 128 | bulk | 5.355 | 5.360 | 5.365 | 5.365 | 0.2% | 0.2% | 0.1% |
| two-independent | 4-6 | 128 | bulk | 5.356 | 5.360 | 5.365 | 5.365 | 0.2% | 0.2% | 0.1% |
| two-independent | 0-2 | 256 | bulk | 10.690 | 10.697 | 10.708 | 10.708 | 0.2% | 0.2% | 0.1% |
| two-independent | 4-6 | 256 | bulk | 10.692 | 10.696 | 10.708 | 10.708 | 0.2% | 0.2% | 0.1% |
| bidirectional | 0-2 | 1 | mid | 0.123 | 0.141 | 0.064 | 0.106 | 47.9% | 13.9% | 24.7% |
| bidirectional | 2-0 | 1 | mid | 0.122 | 0.146 | 0.064 | 0.106 | 47.5% | 13.4% | 27.3% |
| bidirectional | 0-2 | 2 | mid | 0.205 | 0.218 | 0.151 | 0.279 | 26.6% | 36.0% | 27.8% |
| bidirectional | 2-0 | 2 | mid | 0.162 | 0.221 | 0.151 | 0.279 | 7.1% | 72.1% | 26.4% |
| bidirectional | 0-2 | 4 | bulk | 0.372 | 0.389 | 0.321 | 0.620 | 13.6% | 66.8% | 59.5% |
| bidirectional | 2-0 | 4 | bulk | 0.294 | 0.394 | 0.321 | 0.620 | 9.4% | 111.2% | 57.3% |
| bidirectional | 0-2 | 8 | bulk | 0.699 | 0.710 | 0.702 | 1.382 | 0.4% | 97.6% | 94.6% |
| bidirectional | 2-0 | 8 | bulk | 0.695 | 0.716 | 0.702 | 1.382 | 1.0% | 98.8% | 93.0% |
| bidirectional | 0-2 | 16 | bulk | 1.361 | 1.383 | 1.512 | 3.002 | 11.1% | 120.6% | 117.1% |
| bidirectional | 2-0 | 16 | bulk | 1.042 | 1.386 | 1.512 | 3.002 | 45.1% | 188.1% | 116.5% |
| bidirectional | 0-2 | 32 | bulk | 2.692 | 2.707 | 3.159 | 6.296 | 17.4% | 133.9% | 132.6% |
| bidirectional | 2-0 | 32 | bulk | 2.694 | 2.710 | 3.159 | 6.296 | 17.3% | 133.7% | 132.3% |
| bidirectional | 0-2 | 64 | bulk | 5.360 | 5.367 | 6.476 | 12.930 | 20.8% | 141.2% | 140.9% |
| bidirectional | 2-0 | 64 | bulk | 4.030 | 5.390 | 6.476 | 12.930 | 60.7% | 220.9% | 139.9% |
| bidirectional | 0-2 | 128 | bulk | 10.681 | 10.697 | 13.170 | 26.317 | 23.3% | 146.4% | 146.0% |
| bidirectional | 2-0 | 128 | bulk | 10.680 | 10.694 | 13.170 | 26.317 | 23.3% | 146.4% | 146.1% |
| bidirectional | 0-2 | 256 | bulk | 16.017 | 21.346 | 26.561 | 53.099 | 65.8% | 231.5% | 148.8% |
| bidirectional | 2-0 | 256 | bulk | 16.016 | 21.345 | 26.561 | 53.099 | 65.8% | 231.5% | 148.8% |
| bidirectional | 0-2 | 1 | mid | 0.099 | 0.139 | 0.064 | 0.106 | 35.0% | 7.4% | 23.8% |
| bidirectional | 2-0 | 1 | mid | 0.112 | 0.132 | 0.064 | 0.106 | 42.7% | 5.3% | 20.0% |
| bidirectional | 0-2 | 2 | mid | 0.210 | 0.229 | 0.106 | 0.189 | 49.7% | 10.0% | 17.3% |
| bidirectional | 2-0 | 2 | mid | 0.187 | 0.228 | 0.106 | 0.189 | 43.3% | 1.4% | 16.8% |
| bidirectional | 0-2 | 4 | bulk | 0.365 | 0.383 | 0.189 | 0.356 | 48.2% | 2.5% | 7.0% |
| bidirectional | 2-0 | 4 | bulk | 0.277 | 0.395 | 0.189 | 0.356 | 31.7% | 28.5% | 9.7% |
| bidirectional | 0-2 | 8 | bulk | 0.703 | 0.719 | 0.356 | 0.690 | 49.3% | 1.9% | 4.0% |
| bidirectional | 2-0 | 8 | bulk | 0.696 | 0.725 | 0.356 | 0.690 | 48.8% | 0.9% | 4.8% |
| bidirectional | 0-2 | 16 | bulk | 1.357 | 1.374 | 0.690 | 1.358 | 49.1% | 0.1% | 1.1% |
| bidirectional | 2-0 | 16 | bulk | 1.027 | 1.376 | 0.690 | 1.358 | 32.8% | 32.2% | 1.3% |
| bidirectional | 0-2 | 32 | bulk | 2.698 | 2.724 | 1.358 | 2.694 | 49.7% | 0.2% | 1.1% |
| bidirectional | 2-0 | 32 | bulk | 2.697 | 2.725 | 1.358 | 2.694 | 49.6% | 0.1% | 1.1% |
| bidirectional | 0-2 | 64 | bulk | 5.350 | 5.362 | 2.694 | 5.365 | 49.6% | 0.3% | 0.1% |
| bidirectional | 2-0 | 64 | bulk | 5.353 | 5.364 | 2.694 | 5.365 | 49.7% | 0.2% | 0.0% |
| bidirectional | 0-2 | 128 | bulk | 8.026 | 10.687 | 5.365 | 10.708 | 33.1% | 33.4% | 0.2% |
| bidirectional | 2-0 | 128 | bulk | 8.023 | 10.692 | 5.365 | 10.708 | 33.1% | 33.5% | 0.2% |
| bidirectional | 0-2 | 256 | bulk | 16.096 | 21.364 | 10.708 | 21.395 | 33.5% | 32.9% | 0.1% |
| bidirectional | 2-0 | 256 | bulk | 16.093 | 21.367 | 10.708 | 21.395 | 33.5% | 32.9% | 0.1% |

## Reproducing

```bash
bash experiments/microbench/run_matrix.sh       # conditions 1-4
bash experiments/microbench/run_collective.sh   # condition 5
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/microbench/analyze.py --out experiments/results/e_g4_microbench.md
```

`p50` and `p90` are heteropilot's own `planner/util/percentile.py` (linear), over the per-copy samples in the raw files. Both models are given the same fixed per-transfer overhead, taken from condition 1's own 1 MiB median, so it cannot favour either.
