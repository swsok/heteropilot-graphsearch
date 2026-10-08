# E-G3 — the oracle, against the real simulator

> **REAL SIM — LLMServingSim, cache `outputs/cache-eg3`, not real hardware.** Every figure here is the simulator's output under that cache directory. No hardware was run and nothing here is a measurement of any. `correct` is the column to read first.

| fixture | embeddings | representatives | compression_ratio | oracle_simulations | proposed_simulations | feasible_recall | cost_regret | false_infeasible | mismerged_pairs | correct | unjudged | unjudged_pairs | complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| graph-toy-abcde | 528 | 78 | 0.1477 | 528 | 78 | 1.0 | 0.0 | 0 | 0 | True | 24 | 12 | False |
| graph-toy-shared-nic | 288 | 60 | 0.2083 | 288 | 60 | 1.0 | 0.0 | 0 | 0 | True | 18 | 6 | False |
| heterogeneous-lab | 114 | 72 | 0.6316 | 114 | 48 | 1.0 | - | 0 | 0 | True | 24 | 12 | False |

## Wall time, and what the compression cost

| fixture | t_sim_oracle_s | t_sim_proposed_s | t_hash_s | t_vf2_s | t_bounds_s | saving_s | arm_wall_oracle_s | arm_wall_proposed_s | cold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| graph-toy-abcde | 2789.7 | 314.1 | 0.255 | 0.149 | 0.108 | 2475.1 | 2790.5 | 316.1 | True |
| graph-toy-shared-nic | 1498.9 | 278.4 | 0.115 | 0.08 | 0.056 | 1220.3 | 1499.2 | 279.5 | True |
| heterogeneous-lab | 534.5 | 265.7 | 0.023 | 0.007 | 0.053 | 268.7 | 534.6 | 266.6 | True |

`saving_s = t_sim_oracle - (t_sim_proposed + t_hash + t_vf2 + t_bounds)`, the formula `docs/preregistration.md` registers.

**Both `t_sim` terms are simulation time**, measured around the evaluation and not around the arm. `arm_wall_*` is the whole arm and is shown beside them for context only: using it as `t_sim_proposed` would subtract hashing, VF2 and the bounds twice -- once inside that wall clock and once as their own terms -- which understates the saving by the compression's entire cost.

The compression's own cost is charged, once. A saving that counted only the skipped simulations would be the compression ratio wearing a stopwatch.

## Placements the simulator did not judge

`unjudged` counts placements the oracle could not reach a verdict on -- a `SIM_ERROR`, a timeout. They are `unknown_measurement`, the fourth of the five states, and they are **not** infeasible: a crash is a property of the run and never of the placement (work order rule 4).

`unjudged_pairs` counts pairs inside one equivalence class that could not be compared because a member was unjudged. They are excluded from `mismerged_pairs` on purpose: comparing "feasible" against "no answer" measures the simulator's reliability, not the equivalence relation. A run with unjudged placements has proved LESS than a complete one -- `complete` is False -- but it has not proved anything wrong.


| fixture | unjudged | reasons |
| --- | --- | --- |
| graph-toy-abcde | 24 | RejectionStage.SIM_ERROR x24 |
| graph-toy-shared-nic | 18 | RejectionStage.SIM_ERROR x18 |
| heterogeneous-lab | 24 | RejectionStage.SIM_ERROR x24 |

Until `complete` is True on every row, E-G3's correctness claim covers only the placements that were judged, and the row says how many that was. **The failures are reported, not explained**: nothing here claims to know why the simulator refused them.

## The two arms did not share a cache

`--cache-dir` is a root; the arms run under `<root>/oracle` and `<root>/proposed`. An exemplar simulated by whichever arm ran first would otherwise be a cache hit for the other, and the second arm's wall time would measure the filesystem. The work order names one directory; this splits it, and the `saving` column is the reason.

## Reproducing

```bash
bash experiments/scripts/e_g3_oracle_run.sh
```

That wrapper sets `PYTHONPATH` and launches through `vendor/heteropilot/.venv/bin/python` — mandatory, because the Chakra converter runs in-process and the interpreter decides which protobuf converts the trace (heteropilot D26/D27).

It wraps the run in `livelock_watch.sh` with `-g 0 -s 0 -t`, which asks for a wall-clock ceiling and a process-group kill and **turns its progress detection off**. That detector reads the simulator's own tick lines from the wrapped command's stdout; this harness starts each simulation as a subprocess whose output goes to its own log, so the watchdog sees a driver that never speaks and kills it. It did exactly that to a healthy run at 901 s, with 66 simulations already finished (GS-18). One hung simulation is abandoned by the predictor's own per-simulation `--timeout` instead, which is the right layer: the other placements continue.

## Reading the table

`correct` first: it is `false_infeasible == 0 and mismerged_pairs == 0`. A False there is a bound or an equivalence being wrong, never a tuning issue, and the registered response is to stop and report — not to relax the test.

`compression_ratio`, `feasible_recall` and `cost_regret` are **report-only** under the pre-registration: they are tabulated and discussed and no pass or fail is claimed from them. The registered criteria are the invariant and `saving >= 0`.

A non-zero `mismerged_pairs` is diagnosed, not explained: `--diagnose-pair a b` re-simulates each placement twice under the same node ordering and says whether the pair is simulator non-determinism or an equivalence defect. The verdict goes in this file, in those words.

## The cache, verified (P1.4)

The cold run above filled the cache; this is the same command run a second time against it.

| fixture | simulations | cache_hits | re-simulated | wall s |
| --- | --- | --- | --- | --- |
| graph-toy-abcde | 78 | 66 | 12 | 6.1 |
| graph-toy-shared-nic | 60 | 48 | 12 | 6.7 |
| heterogeneous-lab | 48 | 48 | 0 | 0.9 |

**`cache_hits == simulations_run` is not the identity to expect, and the difference is not a defect.** `EnvelopeCache.put` skips a result that is not `ok`, so a placement whose simulation errored is never written and misses again on every re-run. A corpus containing `SIM_ERROR`s can never be fully warm. `re-simulated` is that set, and the identity that must hold is `cache_hits == simulations_run - failures_in_that_arm`. A shortfall beyond it is a cache that is not answering.

Both arms reconcile exactly, which is the check:

```
proposed  186 simulated - 24 never cached (failed) = 162 cached  ->  162 files
oracle    930 placements - 66 unjudged = 864 judged  ->  864 files
```

The `unjudged` column in the correctness table is the ORACLE arm's, which is why it does not match `re-simulated` row by row: the two arms simulate different populations and fail independently.

### One file, one placement

The arms share one directory each across all three fixtures, so these are totals for the corpus and not per-fixture figures.

| directory | files | distinct owners | files claimed twice |
| --- | --- | --- | --- |
| `oracle/` | 864 | 864 | 0 |
| `proposed/` | 162 | 162 | — |

Every cache file records the `candidate_id` that wrote it. `distinct owners` below `files` would mean a file was overwritten by a second placement -- and a shared file is a shared verdict, which is the mis-merge the compression exists to prevent reappearing one layer down in the cache (GS-16).

### Two placements that differ only in their boundary

| fixture | pair | verdict |
| --- | --- | --- |
| graph-toy-abcde | `cuda-toygpu-nodeA-tp1-dp1-s128-t2048@5b5d48e8d6b6`<br>`cuda-toygpu-nodeC-tp1-dp1-s128-t2048@693a423f1a60` | distinct files |
| graph-toy-shared-nic | `cuda-toygpu-nodeX-tp1-dp1-s128-t2048@7d36012c2000`<br>`cuda-toygpu-nodeY-tp1-dp1-s128-t2048@8a5235922f1b` | distinct files |
| heterogeneous-lab | `cuda-rtxpro6000-node1-tp1-dp1-s128-t2048@b5df10418062`<br>`cuda-rtxpro6000-node1-tp1-dp1-s128-t2048@bc6c20ff1980` | distinct files |

This is D126 and the reason the search exists. On `graph-toy-shared-nic`, `P on X -> D on Z` and `P on Y -> D on Z` are identical in every local attribute and differ only in that X's uplink already has 6 of its 10 GB/s held. `EnvelopeKey` describes parallelism and hardware and cannot express that; without the graph signature extending the key the two would collide on one file and the second would silently read the first's TTFT.

The pair is **found**, not hard-coded: a fixture edit that removed the counterexample would otherwise leave this check passing against a pair that no longer has the property.

## Re-run after the A5000 tp=2 profile, 2026-10-07

Revision R4.3. Everything above this heading is the original run and is left as it was. The submodule now pins heteropilot `60df943` (#62), whose A5000 Llama-3.1-8B bf16 bundle gained `tp2/` and `tp4/` (heteropilot D129); `tp1/` is byte-identical. The two toy fixtures, whose every failure was `No profile data for tp=[2]` (`e_g3_sim_error_causes.md`), were re-run with the same command and the same settings as the original: the A40 node, 8 workers, cold caches, one fixture per invocation. `heterogeneous-lab` was **not** re-run: its 24 failures are a decode instance exhausting KV, a different cause that a profile does not touch.

| re-run fixture | embeddings | representatives | compression_ratio | oracle_simulations | proposed_simulations | oracle_feasible | proposed_feasible | false_infeasible | mismerged_pairs | correct | unjudged | unjudged_pairs | complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| graph-toy-abcde | 528 | 78 | 0.1477 | 528 | 78 | 80 | 80 | 0 | 0 | True | 0 | 0 | True |
| graph-toy-shared-nic | 288 | 60 | 0.2083 | 288 | 60 | 48 | 48 | 0 | 0 | True | 0 | 0 | True |

| re-run fixture | t_sim_oracle_s | t_sim_proposed_s | t_hash_s | t_vf2_s | t_bounds_s | saving_s | cold |
| --- | --- | --- | --- | --- | --- | --- | --- |
| graph-toy-abcde | 3023.4 | 420.6 | 0.221 | 0.177 | 0.102 | 2602.4 | True |
| graph-toy-shared-nic | 1587.1 | 342.5 | 0.114 | 0.079 | 0.055 | 1244.4 | True |

**Both rows are complete, and both correctness counts are still zero.** The 42 `FileNotFoundError`s are gone: no placement on either fixture is unjudged, so the invariant now holds over every placement and not only over the judged ones. The compression ratios match the original run's to four decimals, as they must: the profile changes what the simulator can answer, not which placements exist or how they fold.

**The placements that used to fail are now judged, and some of them are feasible.** Feasible placements rose from 72 to 80 on `graph-toy-abcde` and from 42 to 48 on `graph-toy-shared-nic`, in both arms alike: 8 of the 24 and 6 of the 18 formerly unjudged placements. That attribution was checked rather than assumed. The original run's cache files (`outputs/cache-eg3/oracle`) and this run's share a key for every placement both runs judged: 504 on `graph-toy-abcde`, 270 on `graph-toy-shared-nic`. In every pair, every metric is identical except `sim_wall_seconds`, the simulator's own run time. The files only this run has are exactly the 24 and 18 placements, every one of them at tp=2. That is the reason `unknown_measurement` never merges with infeasible: had the failures been counted as rejections, those would have been false eliminations that nothing would have caught.

**The seconds are a second cold run, not a correction of the first.** Simulation time is higher than in the original run on both fixtures. Two things contribute, and neither was separated from the other. The 42 placements that used to fail early now simulate to the end. And one simulation's own wall time varies from run to run: for the 504 shared placements on `graph-toy-abcde`, `sim_wall_seconds` differs between the two runs by a median of 10 % and at most 66 %. `saving_s` keeps its sign and its size, with the same formula and the compression's own cost charged once. The paper's timing figures stay the original run's (table 1 above); this section adds completeness, not a new timing result.

Reproducing (the outputs go to `outputs/r43/`, so the original table is never overwritten):

```bash
for f in graph-toy-abcde graph-toy-shared-nic; do
  MAX_WORKERS=8 CACHE_DIR=outputs/cache-eg3-r43/$f \
  OUT=outputs/r43/$f.md JSON_OUT=outputs/r43/$f.json LOG=outputs/r43/$f.log \
    bash experiments/scripts/e_g3_oracle_run.sh --only $f
done
```
