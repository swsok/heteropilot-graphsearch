# Decisions (GS-n)

This repository's own decisions. Anything that changes heteropilot is recorded
there instead, in `docs/deviations.md`, under the `D120–D129` block this work
order claimed — the two logs do not overlap and neither renumbers the other.

Format: number · date · decision · why · what it affects.

---

## GS-1 — two repositories, heteropilot pinned as a submodule · 2026-09-23

**Decision.** The graph search lives here; heteropilot takes only the hook PRs
H1–H3 and is vendored at `vendor/heteropilot`, pinned to
`675ea66fb4954ad3325ec4874a6cae9496c87e7d` (H3, plus the removal of this repo's
staged document copies from there). Imports go one way,
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

---

## GS-3 — replica symmetry is folded by the canonical key, not by construction · 2026-09-23

**Decision.** `_ordered_groupings` enumerates replica orderings and lets
`canonical_only` collapse them, rather than emitting each partition once by
fixing the lowest device into the first group.

**Why.** Collapsing by construction makes `EmbeddingStats.skipped_symmetric`
structurally zero. A counter that cannot move is not evidence that symmetry was
removed — it is a claim with nothing behind it, and the compression numbers this
work reports are exactly the kind of claim that needs evidence. Enumerating the
orderings makes the count real, and `canonical_only=False` then measures how
much symmetry a cluster had.

The cost is a factor of `replicas!`, paid in building lists rather than in
simulation, which is the cheap side of this pipeline by orders of magnitude.

**Affects.** `graphsearch/embeddings.py`; the `skipped_symmetric` column of
every compression table.

---

## GS-4 — the work order's `dp=2 tp=1 -> 3` reads as `tp=2 dp=2` · 2026-09-23

**Decision.** G5's test asserts 3 for `tp=2 dp=2` and 6 for `tp=1 dp=2`, and
says in its docstring that the work order's example names the other one.

**Why.** For an island of n devices, R replicas of D each, the count is
`C(n, RD) x (RD)! / (D!^R R!)`. On four devices that is 3 for (R=2, D=2) —
partitioning four labelled devices into two unordered pairs — and 6 for
(R=2, D=1). The work order's STEP G5 test (iv) pairs the number 3 with the
parameters `dp=2 tp=1`, which the arithmetic does not support.

Rather than pick one, the test asserts both readings and states the formula, so
a future change to enumeration cannot quietly move the denominator of every
compression ratio.

**Affects.** `tests/test_embeddings.py`. No code change; the enumeration was
already correct.
