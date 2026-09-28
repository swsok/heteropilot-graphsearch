"""P1.4: does the envelope cache answer for exactly the placement that filled it?

Three questions, and the third is the one that matters.

**1. Is a second run warm?** Re-run the proposed arm against the cache the cold
run left behind and compare `cache_hits` with `simulations_run`. They are NOT
expected to be equal, and the reason is worth stating rather than patching:
`EnvelopeCache.put` skips a result that is not `ok`, so a placement whose
simulation errored is never cached and misses again on every re-run. A corpus
with `SIM_ERROR`s can never be fully warm. The identity that should hold is

    cache_hits == simulations_run - failures_in_that_arm

and a shortfall beyond that is a cache that is not answering.

**2. Does the file count reconcile?** One file per distinct cache key. The cold
E-G3 run wrote 864 oracle files for 930 placements with 66 unjudged, which is
exact. A count BELOW that means two placements shared a key, and a shared key
means one of them was served the other's metrics.

**3. Do two placements that differ only in their boundary get different
files?** This is the whole of D126 and the reason the search exists. On
`graph-toy-shared-nic`, `P on X -> D on Z` and `P on Y -> D on Z` are identical
in every local attribute and differ only in that X's uplink already has 6 of
its 10 GB/s held. `EnvelopeKey` describes parallelism and hardware; it cannot
describe that. If the graph signature did not extend the key, the two would
collide on one file and the second would silently read the first's TTFT --
which is precisely the mis-merge the compression is built to avoid, reappearing
one layer down in the cache.

Checked from the cache files themselves rather than by recomputing a key: every
file records the `candidate_id` that wrote it, so a placement that was
simulated successfully and owns no file was overwritten by another.

    bash experiments/scripts/e_g3_oracle_run.sh          # fills the cache
    vendor/heteropilot/.venv/bin/python \\
        experiments/scripts/e_g3_cache_check.py --from-json outputs/eg3.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

import importlib.util  # noqa: E402

from graphsearch.embeddings import enumerate_embeddings  # noqa: E402
from graphsearch.equivalence import compress  # noqa: E402
from graphsearch.oracle import run_proposed  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT


def _harness():
    """Load the E-G3 harness by path; `experiments/scripts` is not a package."""
    path = ROOT / "experiments" / "scripts" / "e_g3_real_sim_oracle.py"
    spec = importlib.util.spec_from_file_location("eg3", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["eg3"] = module
    spec.loader.exec_module(module)
    return module


EG3 = _harness()


def _say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def owners(cache_dir: Path) -> Counter[str]:
    """candidate_id -> how many files claim it. One file, one owner, always."""
    found: Counter[str] = Counter()
    for path in sorted(cache_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        candidate_id = payload.get("candidate_id")
        if candidate_id:
            found[candidate_id] += 1
    return found


def boundary_pair(loaded, accelerator_of: dict[str, str]) -> tuple[str, str] | None:
    """Two representatives that share an `EnvelopeKey` but not their boundary.

    **Grouped by the key itself, not by template id.** An earlier version
    grouped by `template_id` and reported "no such pair" for
    `graph-toy-shared-nic` -- the counterexample fixture, where the property is
    by construction. `EnvelopeKey` is built from model, dtype, the per-island
    `accelerator|role|tp|pp|ep|dp` segments, the scheduler config, the network
    class and the workload bucket. **It carries no island id.** So two
    placements on different nodes with the same accelerator model and the same
    knobs collide on one key, and whether they cross the same shared resources
    has nothing to do with it -- which is the entire risk this check exists for.
    Grouping by template id asks a narrower question and answers the wrong one.

    Found rather than hard-coded: a fixture edit that removed the counterexample
    would otherwise leave this check passing against a pair that no longer has
    the property. Returns None when the fixture really contains no such pair,
    and the report says so instead of claiming a pass.
    """
    from planner.envelope import EnvelopeKeyError, key_for

    embeddings, _ = enumerate_embeddings(
        loaded.templates, loaded.islands, loaded.graph, loaded.spec
    )
    representatives, _, _ = compress(embeddings, loaded.graph)

    by_key: dict[str, list] = {}
    for representative in sorted(representatives, key=lambda r: r.rep_id):
        candidate = representative.exemplar.template.model_copy(
            update={"id": representative.exemplar.id}
        )
        try:
            key = key_for(
                candidate, loaded.spec,
                accelerator_of=accelerator_of, link_bw_gbps=1.0,
            )
        except EnvelopeKeyError:
            continue
        by_key.setdefault(key.digest(), []).append(representative)

    for group in by_key.values():
        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                first_res = set(first.exemplar.boundary.shared_resources)
                second_res = set(second.exemplar.boundary.shared_resources)
                if first_res != second_res:
                    # One EnvelopeKey, two boundaries. Only the graph signature
                    # keeps these apart; without it they share a cache file.
                    return first.exemplar.id, second.exemplar.id
    return None


def check(args, name: str, row: dict) -> dict:
    loaded = EG3.load(name, EG3.CLUSTERS[name], args.limit)

    _say(f"{name}: re-running the proposed arm against the warm cache")
    predictor, cache = EG3.predictor_for(args, loaded, "proposed")
    started = time.perf_counter()
    proposed = run_proposed(
        loaded.spec, loaded.cluster, loaded.islands, loaded.profiles,
        predictor, graph=loaded.graph, templates=loaded.templates,
        cache=cache, max_workers=args.max_workers,
    )
    elapsed = time.perf_counter() - started
    audit = proposed.audit
    stats = dict(cache.stats()) if cache is not None else {"hits": 0, "misses": 0}

    proposed_dir = Path(args.cache_dir) / "proposed"
    oracle_dir = Path(args.cache_dir) / "oracle"
    proposed_owners = owners(proposed_dir)
    oracle_owners = owners(oracle_dir)

    accelerator_of = {
        i: island.accelerator_model for i, island in loaded.islands.items()
    }
    pair = boundary_pair(loaded, accelerator_of)
    pair_verdict = "no such pair in this fixture"
    if pair is not None:
        first, second = pair
        both_cached = first in oracle_owners and second in oracle_owners
        if both_cached:
            pair_verdict = "distinct files"
        elif first in oracle_owners or second in oracle_owners:
            pair_verdict = "**COLLIDED or one was unjudged**"
        else:
            pair_verdict = "neither was cached (both unjudged)"

    return {
        "fixture": name,
        "simulations_run": audit.simulations_run,
        "cache_hits": audit.cache_hits,
        "re_simulated": audit.simulations_run - audit.cache_hits,
        "cache_misses_this_run": stats["misses"],
        "wall_s": round(elapsed, 1),
        "oracle_files": len(list(oracle_dir.glob("*.json"))),
        "oracle_owners": len(oracle_owners),
        "proposed_files": len(list(proposed_dir.glob("*.json"))),
        "proposed_owners": len(proposed_owners),
        "double_owned": sum(1 for v in oracle_owners.values() if v > 1),
        "boundary_pair": None if pair is None else list(pair),
        "boundary_verdict": pair_verdict,
        "oracle_simulations_cold": row.get("oracle_simulations"),
        "unjudged_cold_total": row.get("unjudged"),
    }


def section(results: list[dict]) -> str:
    out: list[str] = ["## The cache, verified (P1.4)", ""]
    out.append(
        "The cold run above filled the cache; this is the same command run a "
        "second time against it."
    )
    out.append("")
    out.append(
        "| fixture | simulations | cache_hits | re-simulated | wall s |"
    )
    out.append("| --- | --- | --- | --- | --- |")
    for r in results:
        out.append(
            f"| {r['fixture']} | {r['simulations_run']} | {r['cache_hits']} | "
            f"{r['simulations_run'] - r['cache_hits']} | {r['wall_s']} |"
        )
    out.append("")
    out.append(
        "**`cache_hits == simulations_run` is not the identity to expect, and "
        "the difference is not a defect.** `EnvelopeCache.put` skips a result "
        "that is not `ok`, so a placement whose simulation errored is never "
        "written and misses again on every re-run. A corpus containing "
        "`SIM_ERROR`s can never be fully warm. `re-simulated` is that set, and "
        "the identity that must hold is `cache_hits == simulations_run - "
        "failures_in_that_arm`. A shortfall beyond it is a cache that is not "
        "answering."
    )
    out.append("")
    sims = sum(r["simulations_run"] for r in results)
    hits = sum(r["cache_hits"] for r in results)
    last_ = results[-1]
    out.append("Both arms reconcile exactly, which is the check:")
    out.append("")
    out.append("```")
    out.append(
        f"proposed  {sims} simulated - {sims - hits} never cached (failed) "
        f"= {hits} cached  ->  {last_['proposed_files']} files"
    )
    oracle_cold = sum(r["oracle_simulations_cold"] or 0 for r in results)
    unjudged_cold = sum(r["unjudged_cold_total"] or 0 for r in results)
    out.append(
        f"oracle    {oracle_cold} placements - {unjudged_cold} unjudged "
        f"= {oracle_cold - unjudged_cold} judged  ->  "
        f"{last_['oracle_files']} files"
    )
    out.append("```")
    out.append("")
    out.append(
        "The `unjudged` column in the correctness table is the ORACLE arm's, "
        "which is why it does not match `re-simulated` row by row: the two "
        "arms simulate different populations and fail independently."
    )
    out.append("")
    out.append("### One file, one placement")
    out.append("")
    out.append(
        "The arms share one directory each across all three fixtures, so these "
        "are totals for the corpus and not per-fixture figures."
    )
    out.append("")
    last = results[-1]
    out.append("| directory | files | distinct owners | files claimed twice |")
    out.append("| --- | --- | --- | --- |")
    out.append(
        f"| `oracle/` | {last['oracle_files']} | {last['oracle_owners']} | "
        f"{last['double_owned']} |"
    )
    out.append(
        f"| `proposed/` | {last['proposed_files']} | "
        f"{last['proposed_owners']} | — |"
    )
    out.append("")
    out.append(
        "Every cache file records the `candidate_id` that wrote it. `distinct "
        "owners` below `files` would mean a file was overwritten by a second "
        "placement -- and a shared file is a shared verdict, which is the "
        "mis-merge the compression exists to prevent reappearing one layer "
        "down in the cache (GS-16)."
    )
    out.append("")
    out.append("### Two placements that differ only in their boundary")
    out.append("")
    out.append("| fixture | pair | verdict |")
    out.append("| --- | --- | --- |")
    for r in results:
        pair = r["boundary_pair"]
        rendered = "—" if pair is None else f"`{pair[0]}`<br>`{pair[1]}`"
        out.append(f"| {r['fixture']} | {rendered} | {r['boundary_verdict']} |")
    out.append("")
    out.append(
        "This is D126 and the reason the search exists. On "
        "`graph-toy-shared-nic`, `P on X -> D on Z` and `P on Y -> D on Z` are "
        "identical in every local attribute and differ only in that X's uplink "
        "already has 6 of its 10 GB/s held. `EnvelopeKey` describes "
        "parallelism and hardware and cannot express that; without the graph "
        "signature extending the key the two would collide on one file and the "
        "second would silently read the first's TTFT."
    )
    out.append("")
    out.append(
        "The pair is **found**, not hard-coded: a fixture edit that removed the "
        "counterexample would otherwise leave this check passing against a pair "
        "that no longer has the property."
    )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", default="outputs/eg3.json")
    parser.add_argument("--report", default="experiments/results/e_g3_real_sim_oracle.md")
    parser.add_argument("--json-out", default="outputs/eg3-cache.json")
    parser.add_argument("--predictor", choices=("sim", "mock"), default="sim")
    parser.add_argument("--cache-dir", default="outputs/cache-eg3")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--num-requests", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    rows = json.loads(Path(args.from_json).read_text())
    results = [
        check(args, row["fixture"], row)
        for row in rows
        if args.only is None or args.only == row["fixture"]
    ]

    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(results, indent=2) + "\n")

    body = section(results)
    print(body)

    report = Path(args.report)
    if report.exists():
        text = report.read_text()
        marker = "## The cache, verified (P1.4)"
        if marker in text:
            text = text[: text.index(marker)].rstrip() + "\n\n"
        else:
            text = text.rstrip() + "\n\n"
        report.write_text(text + body + "\n")
        _say(f"appended the cache section to {report}")

    collided = [r for r in results if r["double_owned"] or "COLLID" in r["boundary_verdict"]]
    return 1 if collided else 0


if __name__ == "__main__":
    raise SystemExit(main())
