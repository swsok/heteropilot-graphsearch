# E-G4 microbenchmark — run log

> **Template. No run has happened.** Every row below the header is an example
> showing the shape; delete them when the first real row goes in.

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
| — | 2026-09-28 | `GPU-11e5c5fd…` | *(example)* two-same | 0-2,1-3 | same | 0.0 | 10 | 4 × `root` pretrain_gpt | yes | `raw/2026-09-28-…/a40-same-bridge.json` | example row, delete |

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
