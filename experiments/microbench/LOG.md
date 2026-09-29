# E-G4 microbenchmark — run log

> **REAL HARDWARE.** The rows below are runs that happened, on the node whose
> serials they carry. `occupancy stable` is computed by `run_pair.py` and
> written into each raw file; it is not a recollection.

One row per invocation of `run_pair.py`. Fill it **as you run**, not afterwards
— the columns that matter most are the ones nobody remembers an hour later.

`experiments/microbench/PLAN.md` says what to run and why. This says what was
actually run, which is not the same document and must not be merged with it: a
plan edited to match what happened is not a plan.

## Before the first row

- [ ] `bash vendor/heteropilot/scripts/whichnode.sh` — paste the `accel serials`
      line into the *Node* column of every row. The `detected node` line above
      it is a node **kind** and identifies nothing.
- [ ] A torch-with-CUDA interpreter exists (`cd vendor/heteropilot && bash
      scripts/install-vllm.sh`). `vendor/heteropilot/.venv` is the *simulator's*
      and has no torch.
- [ ] `git -C vendor/heteropilot status --porcelain` prints nothing.

## The log

| # | date | node (accel serials, first 16) | condition | pairs | share | bg util | iters | others on GPUs | occupancy stable | raw file | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | `GPU-11e5c5fd-9e9` | single | 0-2 | independent | 0.0 | 20 | 0 (none) | yes | `raw/2026-09-28-GPU-11e5c5fd-9e9/a-cond1-single-bridge-0-2.json` | load 0.53; mempolicy `bind:0` |
| 2 | 2026-09-28 | `GPU-11e5c5fd-9e9` | single | 0-1 | independent | 0.0 | 20 | 0 (none) | yes | `raw/2026-09-28-GPU-11e5c5fd-9e9/a-cond1-single-nvlink-0-1.json` | load 0.49; mempolicy `bind:0` |
| 3 | 2026-09-28 | `GPU-11e5c5fd-9e9` | two-same | 0-2 | same | 0.598 | 20 | 0 (none) | yes | `raw/2026-09-28-GPU-11e5c5fd-9e9/a-cond2-bg60-same-bridge.json` | load 0.16; mempolicy `bind:0` |
| 4 | 2026-09-28 | `GPU-11e5c5fd-9e9` | two-same | 0-2,1-3 | same | 0.0 | 20 | 0 (none) | yes | `raw/2026-09-28-GPU-11e5c5fd-9e9/a-cond2-two-same-bridge.json` | load 0.57; mempolicy `bind:0` |
| 5 | 2026-09-28 | `GPU-11e5c5fd-9e9` | two-independent | 0-2 | independent | 0.598 | 20 | 0 (none) | yes | `raw/2026-09-28-GPU-11e5c5fd-9e9/a-cond3-bg60-independent.json` | load 0.21; mempolicy `bind:0` |
| 6 | 2026-09-28 | `GPU-11e5c5fd-9e9` | two-independent | 0-2,4-6 | independent | 0.0 | 20 | 0 (none) | yes | `raw/2026-09-28-GPU-11e5c5fd-9e9/a-cond3-two-independent.json` | load 0.61; mempolicy `bind:0` |
| 7 | 2026-09-28 | `GPU-11e5c5fd-9e9` | bidirectional | 0-2,2-0 | same | 0.598 | 20 | 0 (none) | yes | `raw/2026-09-28-GPU-11e5c5fd-9e9/a-cond4-bidi-bg60-same.json` | load 0.33; mempolicy `bind:0` |
| 8 | 2026-09-28 | `GPU-11e5c5fd-9e9` | bidirectional | 0-2,2-0 | same | 0.0 | 20 | 0 (none) | yes | `raw/2026-09-28-GPU-11e5c5fd-9e9/a-cond4-bidirectional-0-2.json` | load 0.72; mempolicy `bind:0` |
| 9 | 2026-09-28 | `GPU-11e5c5fd-9e9` | collective | ranks 0,1 | n/a | 0.0 | - | 0 (none) | yes | `raw/collective-2026-09-28/c-world2-bridge-0-2.json` | world 2; **ranks 0,1 here are GPU0 and GPU2** -- `CUDA_VISIBLE_DEVICES=0,2` remaps them, so rank ids are not device ids in this row |
| 10 | 2026-09-28 | `GPU-11e5c5fd-9e9` | collective | ranks 0,1 | n/a | 0.0 | - | 0 (none) | yes | `raw/collective-2026-09-28/c-world2-nvlink-0-1.json` | world 2; link_probe.py, busbw |
| 11 | 2026-09-28 | `GPU-11e5c5fd-9e9` | collective | ranks 0,1,2,3 | n/a | 0.0 | - | 0 (none) | yes | `raw/collective-2026-09-28/c-world4-numa0.json` | world 4; link_probe.py, busbw |

### Columns that decide whether a row is usable

**others on GPUs** — `run_pair.py` records every compute process and its owner
into the raw file automatically; this column is so a reader of the log alone
can see it. A figure measured while another tenant drives half the machine is
not wrong, it holds under a condition the `REAL HARDWARE` banner does not
state. On 2026-09-28 GPUs 4–7 were held by `root` running Megatron-DeepSpeed and
GPUs 0–3 were idle; prefer 0–3 while that is true.

**occupancy stable** — `no` means the set of GPU processes changed mid-run.
`analyze.py` refuses those rows: a tenant that started or stopped halfway makes
the p50 and the p90 answers to two different questions. Re-run when the node is
quiet rather than arguing with the number.

**share** — what *you* believe the pairs do, `same` or `independent`. It is
recorded, never inferred. On this node `0-2` and `1-3` cross the same PCIe host
bridge within NUMA 0; `0-1` is an NVLink pair and is a control, not a
contention case. PLAN.md §1 has the table.

**bg util** — the *target*. The raw file also carries `achieved_duty_cycle`, and
the analysis uses that one. A generator that missed its target and a model that
missed its prediction are different failures and must not cancel.

## After each run

- [ ] commit the raw JSON under `experiments/microbench/raw/<date>-<serial>/`
- [ ] add the row here
- [ ] if anything was odd — a thermal event, a competing job appearing, a
      cable moved — write it in **notes**, in words, now. A number with an
      unrecorded anomaly is worse than a missing number, because it will be
      averaged in.

## When the matrix is complete

Say so, and commit. `analyze.py` (P2.4) starts then and not before — it reads
the raw files, compares them against both contention models, and writes
`experiments/results/e_g4_microbench.md`. **No number is filled in from the
Claude Code side**; an empty cell stays empty and the result says which inputs
were missing.
