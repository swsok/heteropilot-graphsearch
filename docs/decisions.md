# Decisions (GS-n)

This repository's own decisions. Anything that changes heteropilot is recorded
there instead, in `docs/deviations.md`, under the `D120–D129` block this work
order claimed — the two logs do not overlap and neither renumbers the other.

Format: number · date · decision · why · what it affects.

---

## GS-1 — two repositories, heteropilot pinned as a submodule · 2026-09-23

**Decision.** The graph search lives here; heteropilot takes only the hook PRs
H1–H3 and is vendored at `vendor/heteropilot`, pinned to
`ef22f11ec9f04317c43bd01057c32c161aa846b9` (H3). Imports go one way,
`graphsearch` → `planner`, never back.

**Why.** Two reasons, and the second is the one that decides it.

The physics is not reproducible outside heteropilot: `planner/util/memory.py`
calls upstream's `serving/core/memory_model.py`, and a real prediction needs
`serving/` plus the `astra-sim` submodule. Copying `planner/` alone would get as
far as a mock predictor and no further.

More importantly, heteropilot's golden tests guard the contracts this work
touches — `ServiceSpec`, the `RejectionStage` values, plan-id assignment, the
envelope cache key, the predictor's compile path. Those have to change *inside*
heteropilot, where "the default path is byte-identical" can be proved. A
monkeypatch from here would bypass that proof entirely.

**Precedent.** ScenarioLab, split out the same way on 2026-09-03 (heteropilot
`WORK_ORDER_consolidation.md` STEP 3, `docs/deviations.md` D24): submodule,
`HETEROPILOT_ROOT`, `PYTHONPATH`, one-way import.

**Affects.** Everything. heteropilot is read-only here; a change to it is a PR
there followed by a submodule bump here.

---

## GS-2 — networkx is this repo's dependency, and its version is part of a signature · 2026-09-23

**Decision.** Use networkx (`>=3.2`) for max-flow, VF2 subgraph isomorphism and
Weisfeiler–Lehman hashing. Do not add it to heteropilot (recorded there as
D123). Record the running version in `Signature.tool_version`.

**Why.** heteropilot walks its cluster with a hand-rolled BFS and says what that
does not do (`path_aware=False`, `contention_modeled=False`). The three
algorithms above are not worth reimplementing and are exactly what networkx
provides.

The version is in the signature because **a WL hash is only comparable against
itself**. The same graph hashed by two networkx releases may differ, so an
upgrade can silently re-cut every equivalence class. Without the version in the
key, a cache entry written before the upgrade would be served after it, and the
compression report would describe a partition that no longer exists.

**Affects.** `graphsearch/equivalence.py`, `graphsearch/paths.py`, the cache
signature, and the reproducibility claim.
