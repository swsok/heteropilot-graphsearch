# Which machine measured the A5000 tp=1 bundle

**REAL HARDWARE.** Before E-G8 predicts with the committed A5000 bundle
(`vendor/heteropilot/profiler/perf/A5000/meta-llama/Llama-3.1-8B/bf16/tp1`), it
asks whether that bundle measures `a5000-2` GPU 0, where E-G8's A5000 engine
runs. The user said every A5000 profile was taken on `a5000-2`. The R4.2
record's GPU UUIDs point at `a5000-1` (`docs/nodes/a5000.md`). The user asked
for a re-profile wherever there was doubt, tp=1 first.

`run_tp1.sh` profiled tp=1 again on each node: R4.2's settings, GPU 0, a
separate heteropilot clone at the submodule pin `60df943`, and a separate
hardware name, so the committed bundle was never touched. Both runs ended
`EXIT=0` with nothing else on either GPU before or after (`raw/<node>/run/`).

| run | node, GPU 0 | started (UTC) |
| --- | --- | --- |
| `raw/a5k1/` | `a5000-1`, `GPU-bd2a06dc-51dd-acd4-5593-6ad96385f9d8` | 2026-10-09 14:56 |
| `raw/a5k2/` | `a5000-2`, `GPU-4e95383b-914e-325a-9f01-8b7f0abb14cd` | 2026-10-10 03:26 |

## Result

`compare_bundles.py` matches rows on every key column. All keys matched
except 3 of `skew_fit`'s 3,981. Each cell gives the relative difference as p50
/ p90, then the signed median:

| file (value) | committed -> `a5000-2` | committed -> `a5000-1` | `a5000-1` -> `a5000-2` |
| --- | --- | --- | --- |
| attention (`time_us`) | 0.26 % / 1.8 %, +0.05 % | 0.70 % / 5.0 %, -0.6 % | 0.79 % / 5.2 %, +0.6 % |
| dense (`time_us`) | 0.44 % / 1.5 %, 0.0 % | 2.4 % / 5.0 %, -2.1 % | 2.5 % / 5.2 %, +2.2 % |
| per_sequence (`time_us`) | 0.13 % / 0.6 %, 0.0 % | 4.2 % / 5.1 %, -4.1 % | 4.4 % / 5.4 %, +4.3 % |
| skew (`t_mean_us`) | 0.21 % / 2.0 %, 0.0 % | 2.2 % / 5.1 %, -1.7 % | 2.2 % / 5.3 %, +1.7 % |

`skew_fit` (`alpha`, absolute difference) is left out of the reading. Its
alphas are fitted from a handful of samples and their tails are long: a
maximum of 125.5 committed -> `a5000-2`, and 9.3 committed -> `a5000-1`. The
full figures are in each `compare-*.json`.

**What it shows.**
- **The committed tp=1 bundle is `a5000-2`'s.** Its re-profile agrees with it
  at medians of 0.1 to 0.4 % with no bias, which is re-measurement scale.
- **`a5000-1` is a different machine of the same model, 2 to 4 % faster** on
  the dense and per-sequence kernels. It is offset by the same amount and in
  the same direction from both the committed bundle and `a5000-2`.
- So the `a5000-1` run is **not** a same-machine noise baseline, though it
  was first started as one. It is a machine-to-machine comparison.

**How the two accounts fit.** R4.2 ran on `a5000-1` (its UUIDs), and it
*resumed* tp=1, re-measuring nothing ("tp=1 byte-identical"). So the bundle's
tp=1 is `a5000-2`'s and its tp=2/tp=4 are `a5000-1`'s. The user's account
holds for tp=1, and the record's for what R4.2 itself measured. That tp=2/tp=4
are `a5000-1`'s rests on the R4.2 record, and nothing here re-measured them.

**For E-G8.** Its A5000 engine runs tp=1 on `a5000-2` GPU 0, so the bundle it
predicts with is that machine's own measurement. tp=2/tp=4 are not on E-G8's
path. Whether they should be re-profiled on `a5000-2` for E-G3/E-G6 is a
separate question, and they are left as they are.
