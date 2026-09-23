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
git submodule update --init --recursive     # astra-sim included; without this nothing imports
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

heteropilot is **not** pip-installable — its `pyproject.toml` has no `[project]`
table — so it is reached by path:

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
pytest -q && ruff check . && mypy graphsearch/
```

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
