# E-G3 — why the simulator refused

> **REAL SIM — LLMServingSim.** Every figure comes from re-running E-G3's oracle arm with the simulator's working directory preserved and reading the tracebacks it left. No hardware was run.

E-G3 records a count of placements the oracle could not judge and reports them as `unknown_measurement`. Its own result file says the failures are reported and not explained. This file explains them, and the explanation is that **one label was covering two causes with different meanings**.

## What failed, and with what

| fixture | failures | exception | distinct candidates |
| --- | --- | --- | --- |
| graph-toy-abcde | 24 | `FileNotFoundError` | 24 |
| graph-toy-shared-nic | 18 | `FileNotFoundError` | 18 |
| heterogeneous-lab | 24 | `RuntimeError` | 6 |

## What each one means

### `FileNotFoundError`

**No profile data exists** for that tensor-parallel degree on that hardware. The simulator refuses rather than extrapolating, which is the right refusal. `unknown_measurement` in its purest sense: the remedy is to run the profiler, and re-running the experiment unchanged would fail identically.

> `No profile data for tp=[2] under perf/A5000/meta-llama/Llama-3.1-8B/bf16/. Re-run the profiler with TP_DEGREES including 2.`

### `RuntimeError`

The simulator's **memory model detected a real resource exhaustion** mid-run and raised instead of returning a verdict. The placement may well be infeasible -- but nothing here proves it, and promoting a crash to `impossible_proven` would be exactly the confusion the five states exist to prevent.

> `[MemoryModel] [node_id=0,inst=0] NPU: tried to load 278.00MB but only 51.89MB is available.`

## What does not change

**Both stay `unknown_measurement`.** A missing profile is not a property of the placement, and a crash is not a verdict. Promoting either to `impossible_proven` would assert something no bound proved, which is the confusion the five states exist to prevent (work order rule 4).

**The memory bound is not at fault for the second.** `graphsearch/bounds.py::_check_memory` checks weights plus **one median request's** KV and declares that relaxation in its own proof -- "one median-length request only". It cannot reject on steady-state KV without assuming a concurrency the most optimistic arithmetic does not force, and a bound that did would no longer be a relaxation. The candidates it let through and the simulator then killed are the gap between the two, which is exactly what the simulation is for.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
for f in graph-toy-abcde graph-toy-shared-nic heterogeneous-lab; do
  vendor/heteropilot/.venv/bin/python \
      experiments/scripts/e_g3_real_sim_oracle.py --only $f \
      --work-dir outputs/eg3-diag/$f --cache-dir outputs/eg3-diag/$f/cache
done
python experiments/scripts/e_g3_sim_error_causes.py --out experiments/results/e_g3_sim_error_causes.md
```

The cache is deliberately not shared with E-G3's own: a cached success would hide the failure this file is about.
