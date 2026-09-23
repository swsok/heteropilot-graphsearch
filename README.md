# heteropilot-graphsearch

Graph-based placement search over [HeteroPilot](https://github.com/swsok/heteropilot)'s
planner: equivalence compression that preserves shared communication resources,
provable elimination, and an adaptive Top-K that reports what it never evaluated.

**This repository holds no measurements.** Every number it prints is either
computed from a vendored heteropilot profile or produced by a mock predictor,
and it propagates heteropilot's provenance labels unchanged. Nothing here
measures hardware, and no result from here may be labelled as measured.

## Layout

```
graphsearch/         the package (13 modules when complete; G1-G13)
fixtures/            toy clusters, profiles and a service spec - all fictional
tests/               pytest; reuses heteropilot's MockPredictor
experiments/         scripts and their results
docs/                the research design, the software design, the decision log
vendor/heteropilot/  submodule, pinned; READ-ONLY
WORK_ORDER_graph_search.md
```

## Setup

```bash
git clone https://github.com/swsok/heteropilot-graphsearch.git
cd heteropilot-graphsearch
git submodule update --init                  # planner/ only -- enough for everything below
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

**`--recursive` is only for the simulator.** Everything in this repository runs
against `--predictor mock`, which imports `planner/` and nothing under it, so
the plain `--init` above is enough and skips ASTRA-Sim's own submodules. Add
`--recursive` when you intend to run `--predictor sim`, which additionally
needs heteropilot's built environment (see *Running the real simulator* below).
CI checks out with `submodules: true`, which is the non-recursive form, for the
same reason.

heteropilot is **not** pip-installable — its `pyproject.toml` has no `[project]`
table — so it is reached by path:

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
pytest -q && ruff check . && mypy graphsearch/
```

## Running it

```bash
python -m graphsearch plan \
    --service fixtures/service_specs/graph-toy-llama31-8b.yaml \
    --cluster fixtures/clusters/graph-toy-abcde.v2.yaml \
    --k-schedule 4,8,16 --output outputs/plan.yaml

python -m graphsearch compare \
    --service fixtures/service_specs/graph-toy-llama31-8b.yaml \
    --cluster fixtures/clusters/graph-toy-shared-nic.v2.yaml
```

`plan` prints heteropilot's own render output unchanged, then a `Graph search:`
block underneath. `compare` runs the oracle against the search and prints the
four numbers, exiting non-zero when either correctness number is not zero.

| flag | |
| --- | --- |
| `--k-schedule 4,8,16` | evaluate in batches of increasing size |
| `--search-mode budget\|certify` | stop on budget, or only when nothing unevaluated could win |
| `--budget-sims N`, `--budget-seconds S` | hard caps; what they cut is reported, never hidden |
| `--epsilon E` | slack on the certificate |
| `--max-embeddings-per-template N` | enumeration cap; truncation is charged to `excluded_by_scope` |
| `--compression exact\|off` | `off` measures what the compression was worth |
| `--bounds all\|none\|<list>` | `none` drops the *relaxations*; compat and memory are exact checks and stay |
| `--diversity` | reserve part of each batch for distinct structures |
| `--oracle` | evaluate every embedding: no compression, no bounds, no top-K |
| `--predictor mock\|sim` | `mock` is the default and prints a banner on every run |

**`--predictor mock` numbers are fictional.** The mock respects the same physics
as the bounds -- which is what makes an oracle disagreement mean something --
but nothing it prints is a measurement or a simulation of any hardware. The
banner says so on every run, and `experiments/results/` repeats it in every
report.

`HETEROPILOT_ROOT` overrides where `planner.*` is imported from, if you would
rather use an existing checkout than the submodule.

**The submodule is private.** CI and any agent need a read token or an SSH key
to clone it; there is no public fallback.

### Running against the real simulator

`--predictor sim` needs LLMServingSim and ASTRA-Sim built, which is a much
larger install (protobuf toolchain, a compiled ASTRA-Sim, a Chakra matching
`protobuf>=7.35.1`). Reuse the submodule's own environment rather than building
a second one:

```bash
vendor/heteropilot/.venv/bin/python -m graphsearch plan ...
```

Read `vendor/heteropilot/CLAUDE.md` § Environment before attempting it. Every
step of the current work order runs on CPU with `--predictor mock`.

## The boundary

| | `vendor/heteropilot` | here |
| --- | --- | --- |
| Changes | hook PRs H1–H3 only, made **in that repo** | everything else |
| Imports | knows nothing about this package | imports `planner.*` |
| Decisions | `docs/deviations.md`, block `D120–D129` | `docs/decisions.md`, `GS-n` |
| Experiments | — | tag `E-G*` |

`vendor/heteropilot` is read-only. Changing it means opening a PR there and then
bumping the submodule here; `git -C vendor/heteropilot status --porcelain` must
print nothing.

## Where to start reading

1. `docs/HeteroPilot_그래프기반_배치탐색_연구설계.md` — why this approach (§9 has the worked compression example)
2. `docs/graph_search_design.md` — that design as code structure
3. `WORK_ORDER_graph_search.md` — the implementation order and the test for each step
4. `docs/decisions.md` — what was decided here, and why
