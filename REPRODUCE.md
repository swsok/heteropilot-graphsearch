# Reproducing the paper

Every table, figure and number in `paper/` comes from a file in
`experiments/results/`, and every results file says on its first line which of
three kinds of number it holds. The kind decides what "reproduce" can mean:

| class | banner | what you can reproduce | typical time |
| --- | --- | --- | --- |
| **mock** | `MockPredictor results. Not performance numbers.` | everything, byte-identically, on any machine | seconds to 16 min |
| **real sim** | `REAL SIM` | correctness columns from the archived cache in minutes; wall-time columns only by a cold run, and those are machine-dependent | minutes (cache) / hours (cold) |
| **hardware** | `REAL HARDWARE` | the analysis, byte-identically, from the committed raw files; the measurements themselves are not reproducible | under a second |

`paper/REVIEW_internal.md` (reviewer B) records the last full check: all 55
generated tables, all macros and every mock results file rebuilt
byte-identically, and E-G4/E-G5 re-analysed byte-identically from raw.

## Pins

| what | pin |
| --- | --- |
| this repository | tag **`ispass27-submission`** (`git rev-parse ispass27-submission^{commit}` names the commit; the tag, not a copied sha, is the pin) |
| `vendor/heteropilot` | `b339adfcf21d1642143c1587454d7e34fd0ada25` (submodule) |
| `vendor/heteropilot/astra-sim` | `f82fb3d` (v1.1.0, nested submodule) |
| Python | **3.10**, for both venvs (CI, heteropilot `uv venv --python 3.10`) |

`networkx` is pinned only from below (`>=3.2`, see `requirements.txt`): the
equivalence hash records its own version (`Signature.tool_version`), so a
different release fails the comparison loudly instead of re-cutting a class.

## Setup

```bash
git clone --recurse-submodules https://github.com/swsok/heteropilot-graphsearch.git
cd heteropilot-graphsearch
uv venv --python 3.10 .venv            # NOT the system python: here it is 3.8
uv pip install --python .venv/bin/python -r requirements.txt
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
```

Every command below uses `.venv/bin/python` where a results file says bare
`python`; the code needs 3.10 (`zip(strict=)`, `Path.is_relative_to`).

**The simulator** (real-sim rows only) lives in its own venv inside the
submodule. Build it with `docs/nodes/PREP.md` step B, including the two lines
after `compile.sh` (its own bare `pip3` misses the venv; Chakra needs
`protobuf>=7.35.1`). Then, because heteropilot's `.gitignore` does not cover
that venv and the quality gate requires a clean submodule:

```bash
printf '.venv/\n.venv-vllm/\n' >> .git/modules/vendor/heteropilot/info/exclude
git -C vendor/heteropilot status --porcelain     # must print nothing
```

Every `--predictor sim` run must go through
`vendor/heteropilot/.venv/bin/python` (the CLI refuses any other interpreter,
heteropilot D26/D27). Simulation is CPU-only: `--max-workers` means cores, and
no GPU is touched.

**The archive.** A few gitignored files are inputs that cannot be regenerated
without hours of simulation: the E-G3 cold-run rows and cache, the E-G6 grid
rows, and the E-G5 prediction caches -- about 18 MB (1.2 MB compressed),
listed in `scripts/reproduce/archive_outputs.sh`. It is the release asset of
the tag:

```bash
gh release download ispass27-submission -R swsok/heteropilot-graphsearch
sha256sum -c outputs-archive.tar.gz.sha256        # the archive itself
tar -xzf outputs-archive.tar.gz                   # at the repository root
bash scripts/reproduce/archive_outputs.sh --verify  # every file in it
```

(or the same two files from the release page,
`https://github.com/swsok/heteropilot-graphsearch/releases/tag/ispass27-submission`).
The repository URL is not in the paper, which is under double-blind review. The several GB of per-run simulator work
directories under `outputs/` are scratch and are not archived.

## The build

```bash
make -C paper paper     # tables + numbers + figures + PDF
make -C paper check     # no literal numbers, no forbidden claims, claim status
```

`tables` regenerates `paper/tables/*.tex` from the results files (they are
gitignored, except the hand-written `reuse.tex`); `numbers` regenerates
`paper/numbers.tex` from `scripts/paper/numbers.yaml`; `figures` regenerates
every PDF in `paper/figures/` deterministically (no embedded date) and fails
rather than skip when an input is missing. The E-G3 timing macros look up only
rows whose `cold` column is `True`, so a warm re-run cannot enter the paper.
The PDF is built with tectonic, else latexmk, else pdflatex (about a minute).

## Per artefact

Paths are relative to the repository root; "md" is the results file under
`experiments/results/`.

| paper artefact | md / raw | command | class | time | needs |
| --- | --- | --- | --- | --- | --- |
| Tab. `e_g1_toy_pilot`; C1-C4 | `e_g1_toy_pilot.md` | `.venv/bin/python experiments/scripts/e_g1_toy_pilot.py --out experiments/results/e_g1_toy_pilot.md` | mock | ~30 s | -- |
| Tab. `e_g1b_topk`; C5 | `e_g1b_topk.md` | `... e_g1b_topk.py --out experiments/results/e_g1b_topk.md` | mock | ~20 s | -- |
| C7 | `e_g2_ranker_diagnosis.md` | `... e_g2_ranker_diagnosis.py --out ...` | mock | ~10 s | -- |
| Tab. `e_g2_topk_holdout`, Fig. `topk_holdout.pdf`; C6, C8 | `e_g2_topk_holdout.md` | `... e_g2_topk_holdout.py --out ...`, then `make -C paper figures` | mock | ~1 min | -- |
| Tab. `e_g3_real_sim_oracle`; `\egthree*`; C10-C13 | `e_g3_real_sim_oracle.md` | re-render: `vendor/heteropilot/.venv/bin/python experiments/scripts/e_g3_real_sim_oracle.py --from-json outputs/eg3.json`, then `... e_g3_cache_check.py` for its P1.4 section. Rerun: `bash experiments/scripts/e_g3_oracle_run.sh` (writes `outputs/eg3.json`), then the cache check | real sim | re-render: seconds; with the cache: minutes, **timings warm**; cold: ~1.6 h at 4 workers | archive: `eg3.json`, `eg3-cache.json`, `cache-eg3` |
| C14 | `e_g3_sim_error_causes.md` | the oracle arm per fixture into a **fresh** cache, then `... e_g3_sim_error_causes.py --work-dir outputs/eg3-diag` (the md's own block) | real sim, cold by design | ~1.6 h | nothing: a cached success would hide the failure. The tracebacks were not archived, so C14 is re-derived, not re-read |
| Tab. `e_g4_microbench`; Fig. `contention_error.pdf`; `\egfour*`; C15-C17, C22, C29, C31 | `e_g4_microbench.md` <- `experiments/microbench/raw/` | `.venv/bin/python experiments/microbench/analyze.py` (measurement: `run_matrix.sh`, `run_collective.sh`, `run_nic.py`) | hardware | < 1 s | -- |
| Tab. `e_g5_real_hardware`; `\egfive*`; C18-C20, C30, C33-C35 | `e_g5_real_hardware.md` <- `experiments/e_g5/raw/` | `.venv/bin/python experiments/e_g5/analyze.py --out experiments/results/e_g5_real_hardware.md`. Behind it: `bash experiments/e_g5/run_grid.sh` (hardware), `repredict.py` (post-hoc predictions, real sim, hours at 6 jobs), `bash experiments/e_g5/run_floor_diagnosis.sh` (cache-only, pre-GS-38 adapter) | hardware + real-sim columns | analysis < 1 s | archive: `e_g5/cache`, `cache-eg5-high`, `cache-eg5-gs38` for the prediction steps |
| C21 (not established) | `experiments/e_g5/raw/pilot/` | `experiments/e_g5/pilot_placement.py` | hardware, fitted pilot | -- | not a validation result; no results file by design |
| Tab. `e_g6_scale`; `\egsix*`; C23 | `e_g6_scale.md` | re-render: `... e_g6_scale.py --from-json outputs/e_g6/scale.json`. Grid: `bash experiments/scripts/e_g6_run.sh` | mock (timings machine-dependent) | < 1 s / ~20 min serial | archive: `e_g6/scale.json` (re-render, scale figures) |
| Tab. `e_g7_ablation`; C24 | `e_g7_ablation.md` | `... e_g7_ablation.py --out ...` | mock | ~40 s | -- |
| Tab. `e_g7_baseline_fairness`; C25 | `e_g7_baseline_fairness.md` | `... e_g7_baseline_fairness.py --out ...` | mock | ~20 s | -- |
| Tab. `e_g7_holdout`; `\egseven*`; C26, C32 | `e_g7_holdout.md` | `... e_g7_holdout.py --out ...` | mock | 10-16 min | -- |
| Tab. `reuse`, Fig. `concept_sec9` | hand-written | -- | -- | -- | -- |
| C9 | `tests/test_oracle_agreement.py` | `.venv/bin/pytest -q tests/test_oracle_agreement.py` | test | seconds | -- |

Each results file also carries its own reproduce block, written by the script
that produced it, so the two cannot drift in silence: a script whose arguments
change regenerates its block on the next run.

## The clean-container check

`scripts/reproduce/clean_container.sh` takes `git archive` of the current
commit and of the pinned submodule -- nothing untracked, no venv, no `outputs/`
-- builds a fresh Python 3.10 venv from `requirements.txt` in a container, and
regenerates the E-G1 toy pilot over its own committed copy. The results file
and the LaTeX table made from it must both be byte-identical. Its last log is
`experiments/reproduce/clean-container.log`.

## Hardware

Not reproducible from this repository, by nature: the measurements depend on
the node. What is provided is every raw file (`experiments/microbench/raw/`,
`experiments/e_g5/raw/`, `experiments/pd_probe/raw/`, all committed), the
harness that produced them, the node checklist (`docs/nodes/PREP.md`), and the
rule the harness enforces: it refuses to measure beside another GPU tenant and
records occupancy and accelerator serials in every provenance file.
