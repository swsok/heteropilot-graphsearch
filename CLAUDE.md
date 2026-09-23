# CLAUDE.md — heteropilot-graphsearch

Guidance for Claude Code in this repository. Read `README.md` first for what it
is; this file is about how to work in it.

## Read these, in this order

| Document | Why |
| --- | --- |
| `docs/HeteroPilot_그래프기반_배치탐색_연구설계.md` | The research design. §9's worked example is where G6 and G7's expected numbers come from — 28 embeddings, 5 representatives, `[2,2,4,4,16]`; then 3 after the 50 ms filter. |
| `docs/graph_search_design.md` | The same thing as code structure: module by module, with the API each one exposes. |
| `WORK_ORDER_graph_search.md` | What to build, in what order, with the test for each step. Each STEP is self-contained on purpose. |
| `docs/decisions.md` | GS-1, GS-2 … decisions made here. |
| `vendor/heteropilot/CLAUDE.md` | The planner's absolute rules. **They apply here too.** |
| `vendor/heteropilot/AGENTS.md` | Upstream simulator internals. |

## The boundary, which is the thing to get right

**`vendor/heteropilot` is read-only.** Do not edit a file under it, ever. A
change there is a PR in that repository followed by a submodule bump here. The
check is `git -C vendor/heteropilot status --porcelain` printing nothing, and
the quality gate runs it.

**Imports go one way**: `graphsearch` imports `planner.*`; nothing in heteropilot
knows this package exists. The precedent is ScenarioLab (heteropilot D24).

**Do not monkeypatch heteropilot.** Its golden tests are what prove the default
path is byte-identical, and a patch from here bypasses that proof. If something
in `planner/` needs to change, it needs a hook — H1–H3 added four, and a fifth
would be a new PR there.

## Rules inherited from heteropilot

1. Never invent hardware numbers. Anything unmeasured is `source: placeholder`.
   **Every fixture in this repo is fictional** and says so in its header; a
   result computed from one is not a measurement of anything.
2. Never mix backends in one TP group.
3. **A pruning stage must be a relaxation of the feasibility test.** It may
   reject only when the most optimistic arithmetic already misses a constraint
   §5.6 declares. This binds `graphsearch/bounds.py` exactly as it binds
   `planner/candidate_generator.py`, and the throughput bound is the one to
   watch: it exists only because H1 added `slo.min_goodput_rps`, and with that
   field unset it must not run at all.
4. **Unevaluated is not infeasible.** The five states —
   `impossible_proven`, `excluded_by_scope`, `deferred_heuristic`,
   `unknown_measurement`, `evaluated` — never merge. A budget is not a property
   of the hardware.
5. Code comments, docstrings and log messages in English. The work order is
   Korean; the code it produces is not.
6. One STEP = one branch = one PR (`feat/g<N>-<name>`).
7. Determinism: sorted iteration, `json.dumps(sort_keys=True)`, sorted insertion
   into networkx graphs. The same input twice must give byte-identical output.

## The pipeline, module by module

```
ClusterSpecV2 -> schema.py        normalised graph: bytes/s, directed, res: vertices
              -> paths.py         allowed paths, cut capacity, the boundary
              -> demand.py        CommFlow: what a candidate sends
              -> embeddings.py    templates -> placements on named devices
              -> equivalence.py   fold by VF2, never by hash alone
              -> bounds.py        eliminate only on arithmetic that cannot be beaten
              -> ranker.py        order what is left; never produce metrics
              -> adaptive.py      spend the budget; report what it did not reach
              -> adapter.py       compile, and name what the simulator was not told
              -> restore.py       bind back to devices; multiplicity != max_concurrent
              -> oracle.py        did the search lose the answer?
```

`cost.py` and `contention.py` sit beside these: an incomplete cost is None, and
the contention model is named in every record so two results computed under
different ones cannot be compared by accident.

## Recording a decision

Here: `docs/decisions.md`, next free `GS-n` (number · date · decision · why ·
what it affects). In heteropilot: `docs/deviations.md`, and **only** from the
`D120–D129` block that work order claimed. Numbers are not interchangeable and
neither log renumbers the other.

Experiments here are tagged `E-G*` (claimed in heteropilot's `CLAUDE.md`).

## Quality gate

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
pytest -q && ruff check . && mypy graphsearch/
git -C vendor/heteropilot status --porcelain     # must be empty
```

CI also runs a subset of heteropilot's own tests against the pinned sha, to
catch a submodule that was bumped to something broken.

## When the work order and the code disagree

The real code wins — heteropilot's rule, and it has already bitten twice in the
hook PRs (the CLAUDE.md block row had to move from H3 to H1; H2's documentation
target was a page describing a different schema). Record the difference where
the change lands: `docs/decisions.md` here, `docs/deviations.md` there.
