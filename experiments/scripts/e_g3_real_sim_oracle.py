"""E-G3: the correctness check again, with LLMServingSim in place of the mock.

**REAL SIM. Simulated, not measured.** Every figure here is LLMServingSim's
output under the cache directory named below. No hardware was run, and nothing
here is a measurement of any.

E-G1 asked whether exact compression and the bounds lose the oracle's answer.
It asked the *mock*, which respects the same physics as the bounds -- which is
what made a disagreement meaningful, and also what made it the weaker test: the
bounds got to define the thing they were being checked against. This asks the
simulator, whose behaviour they do not define.

Two arms per fixture:

  oracle     every embedding simulated. No compression, no bounds, no top-K.
  proposed   exact compression + bounds + adaptive, K = every representative,
             so the comparison isolates the compression and the bounds rather
             than the budget.

**The arms do not share a cache directory.** They get `<cache-dir>/oracle` and
`<cache-dir>/proposed`, and the reason is the `saving` column: an exemplar
simulated by whichever arm ran first would be a cache hit for the other, and
the arm that ran second would report a wall time that measures the filesystem.
Each arm is independently cold, independently rerunnable, and independently
cache-verifiable (P1.4). What they lose is roughly a compression-ratio's worth
of duplicated simulation, which is the price of the number meaning anything.

Registered in `docs/preregistration.md` before this ran. The success criterion
is the invariant plus `saving >= 0`; the compression ratio, recall and regret
are report-only.

Run it through the simulator's own venv, under the livelock watchdog -- see
`experiments/scripts/e_g3_oracle_run.sh`, which does both.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import (  # noqa: E402
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)
from planner.spec import Objective, load_service_spec  # noqa: E402

from graphsearch.__main__ import sim_environment  # noqa: E402
from graphsearch.oracle import (  # noqa: E402
    compare,
    run_oracle,
    run_proposed,
    table_row,
)
from graphsearch.schema import build_resource_graph  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"

BANNER_TEMPLATE = (
    "> **REAL SIM — LLMServingSim, cache `{cache}`, not real hardware.** Every "
    "figure here is the simulator's output under that cache directory. No "
    "hardware was run and nothing here is a measurement of any. `correct` is "
    "the column to read first."
)

MOCK_BANNER = (
    "> **MOCK — not performance numbers.** This run used the mock predictor, "
    "which means it is a rehearsal of the harness and NOT E-G3. The real run "
    "is `--predictor sim`; this file must not be cited as E-G3's result."
)

CLUSTERS = {
    "graph-toy-abcde": FIXTURES / "clusters/graph-toy-abcde.v2.yaml",
    "graph-toy-shared-nic": FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml",
    "heterogeneous-lab": paths_root.HETEROPILOT_ROOT
    / "examples/clusters/heterogeneous-lab.yaml",
}


@dataclass
class Loaded:
    """Everything one fixture needs, loaded once and shared by both arms."""

    spec: object
    cluster: object
    profiles: dict
    islands: dict
    graph: object
    templates: list


def service_spec(name: str):
    """The same spec E-G1 used, for the same reason.

    A roomy TTFT so the row measures the SEARCH rather than whether the toy SLO
    is reachable at all -- an all-infeasible corpus makes recall and regret
    vacuous. Changing it here would make E-G3's rows incomparable with E-G1's,
    which is the whole point of running them on the same corpus.
    """
    if name == "heterogeneous-lab":
        path = paths_root.HETEROPILOT_ROOT / "examples/service_specs/llama31-8b.yaml"
    else:
        path = FIXTURES / "service_specs/graph-toy-llama31-8b.yaml"
    spec = load_service_spec(path)
    return spec.model_copy(
        update={
            "slo": spec.slo.model_copy(
                update={"ttft": spec.slo.ttft.model_copy(update={"max_ms": 1e6})}
            ),
            "objective": spec.objective.model_copy(
                update={"primary": Objective.MINIMIZE_COST_PER_HOUR, "secondary": None}
            ),
        }
    )


def load(name: str, path: Path, limit: int) -> Loaded:
    spec = service_spec(name)
    cluster = load_cluster_spec(path)
    root = paths_root.HETEROPILOT_ROOT if name == "heterogeneous-lab" else ROOT
    profiles = load_profiles_for(cluster, root)
    islands = detect_islands(cluster, profiles)
    graph = build_resource_graph(cluster, profiles)
    generated = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=True,
    ).generate()
    return Loaded(
        spec=spec, cluster=cluster, profiles=profiles,
        islands={i.id: i for i in islands}, graph=graph,
        templates=[c for c in generated.candidates if c.total_devices <= limit],
    )


def predictor_for(args, loaded: Loaded, arm: str):
    """One predictor and one cache per arm. Returns (predictor, cache)."""
    if args.predictor == "mock":
        import sys

        sys.path.insert(0, str(ROOT))
        from tests.graph_fixtures import GraphAwareMockPredictor

        return GraphAwareMockPredictor(), None

    environment = sim_environment(
        loaded.spec, loaded.cluster, loaded.islands,
        num_requests=args.num_requests, seed=args.seed,
        cache_dir=Path(args.cache_dir) / arm if args.cache_dir else None,
        work_dir=Path(args.work_dir) / arm if args.work_dir else None,
        timeout_s=args.timeout,
    )
    return environment.predictor, environment.cache


def _stats(cache) -> dict[str, int]:
    return dict(cache.stats()) if cache is not None else {"hits": 0, "misses": 0}


def _say(message: str) -> None:
    """Progress, on stderr, flushed.

    A three-fixture cold run is an hour of silence otherwise, and silence is
    indistinguishable from a hang to the person watching it -- which is exactly
    the judgement `livelock_watch` cannot make for this harness (see
    `e_g3_oracle_run.sh`'s header). This is what a human uses instead.
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def one(args, name: str, path: Path) -> dict:
    _say(f"{name}: loading")
    loaded = load(name, path, args.limit)
    _say(
        f"{name}: {len(loaded.templates)} templates; proposed arm starting"
    )

    # The proposed arm first, deliberately. It is the cheaper one, so a fixture
    # that is going to fail fails before the expensive arm has been paid for.
    proposed_predictor, proposed_cache = predictor_for(args, loaded, "proposed")
    started = time.perf_counter()
    proposed = run_proposed(
        loaded.spec, loaded.cluster, loaded.islands, loaded.profiles,
        proposed_predictor, graph=loaded.graph, templates=loaded.templates,
        cache=proposed_cache, max_workers=args.max_workers,
    )
    t_proposed = time.perf_counter() - started
    _say(
        f"{name}: proposed arm done in {t_proposed:.0f}s "
        f"({proposed.simulations} simulations); oracle arm starting"
    )

    oracle_predictor, oracle_cache = predictor_for(args, loaded, "oracle")
    started = time.perf_counter()
    oracle = run_oracle(
        loaded.spec, loaded.cluster, loaded.islands, loaded.profiles,
        oracle_predictor, graph=loaded.graph, templates=loaded.templates,
        cache=oracle_cache, max_workers=args.max_workers,
    )
    t_oracle = time.perf_counter() - started
    _say(
        f"{name}: oracle arm done in {t_oracle:.0f}s "
        f"({oracle.simulations} placements, {len(oracle.unjudged)} unjudged)"
    )

    comparison = compare(oracle, proposed)
    _say(
        f"{name}: correct={comparison.correct} complete={comparison.complete} "
        f"false_infeasible={len(comparison.false_infeasible)} "
        f"mismerged={len(comparison.mismerged_pairs)}"
    )
    ratio = (
        len(proposed.representatives) / len(oracle.embeddings)
        if oracle.embeddings
        else None
    )
    audit = proposed.audit
    return table_row(
        name,
        comparison,
        {
            "embeddings": len(oracle.embeddings),
            "representatives": len(proposed.representatives),
            "compression_ratio": None if ratio is None else round(ratio, 4),
            "t_oracle_s": round(t_oracle, 1),
            "t_proposed_s": round(t_proposed, 1),
            "oracle_timings": dict(oracle.timings),
            "oracle_cache": _stats(oracle_cache),
            "proposed_cache": _stats(proposed_cache),
            # "18 unjudged" is a count; "18 SIM_ERROR" is a lead. The reason
            # comes from the evaluator's own rejection stage, not from a guess
            # here about what went wrong.
            "unjudged_reasons": dict(
                sorted(Counter(oracle.unjudged.values()).items())
            ),
            "timings": dict(getattr(audit, "timings", {}) or {}),
        },
    )


# --- the diagnosis --------------------------------------------------------

def diagnose_pair(args, first: str, second: str) -> str:
    """Is a mis-merge the simulator being non-deterministic, or us being wrong?

    A `mismerged_pairs` entry says two placements in one equivalence class came
    back with different metrics. That has two possible causes and they call for
    opposite responses:

      * **the simulator is non-deterministic** for a logically identical input
        -- instance numbering, `config_builder` ordering, the D40 family of
        problems. Then the finding is about the harness and the equivalence
        relation is innocent.
      * **the equivalence relation is wrong** -- the signature dropped a
        property the metrics depend on. Then the finding is the contribution
        failing, and no amount of re-running fixes it.

    The discriminator is to simulate the SAME placement twice, under the same
    node ordering, and see whether it agrees with itself. If it does not, the
    pair proves nothing about the equivalence. This prints both numbers.
    """
    name = args.diagnose_fixture
    loaded = load(name, CLUSTERS[name], args.limit)
    predictor, _ = predictor_for(args, loaded, "diagnose")

    from planner.optimizer.exhaustive import evaluate_candidates

    from graphsearch.embeddings import enumerate_embeddings
    from graphsearch.oracle import _candidate_for, bind_predictor

    embeddings, _ = enumerate_embeddings(
        loaded.templates, loaded.islands, loaded.graph, loaded.spec
    )
    by_id = {e.id: e for e in embeddings}
    missing = [i for i in (first, second) if i not in by_id]
    if missing:
        return f"diagnose: no such embedding id: {', '.join(missing)}"

    lines = [f"### Diagnosis of `{first}` vs `{second}` ({name})", ""]
    lines.append(
        "| run | embedding | p99 TTFT ms | p99 TPOT ms | throughput tok/s |"
    )
    lines.append("| --- | --- | --- | --- | --- |")

    seen: dict[str, list[tuple[float, float, float]]] = {first: [], second: []}
    for attempt in (1, 2):
        for embedding_id in (first, second):
            embedding = by_id[embedding_id]
            embedded_pd = bind_predictor(
                predictor, [embedding], loaded.graph,
                spec=loaded.spec, cluster=loaded.cluster,
                islands=loaded.islands, profiles=loaded.profiles,
            )
            evaluation = evaluate_candidates(
                [_candidate_for(embedding)],
                loaded.spec, loaded.cluster, dict(loaded.islands),
                dict(loaded.profiles), predictor,
                # No cache: a cached second run would agree with the first by
                # construction and would answer nothing.
                cache=None, pd_transfer=not embedded_pd,
            )
            plans = list(evaluation.feasible_plans) + [
                p for p, _ in evaluation.infeasible_plans
            ]
            # `DeploymentPlan.predicted`, not `.metrics`: the latter does not
            # exist and a `getattr` fallback would report NaN for every run and
            # then conclude "no disagreement reproduced".
            metrics = plans[0].predicted if plans else None
            row = (
                (
                    metrics.p99_ttft_ms,
                    metrics.p99_tpot_ms,
                    metrics.throughput_tps,
                )
                if metrics is not None
                else (float("nan"),) * 3
            )
            seen[embedding_id].append(row)
            lines.append(
                f"| {attempt} | {embedding_id} | {row[0]:.4f} | {row[1]:.4f} "
                f"| {row[2]:.1f} |"
            )

    lines.append("")
    if any(any(x != x for x in row) for rows_ in seen.values() for row in rows_):
        lines.append(
            "**Verdict: no metrics.** At least one run produced no plan at "
            "all -- the simulation errored or was refused before simulating. "
            "That is `unknown_measurement`, not a disagreement, and this pair "
            "cannot be diagnosed until the simulation completes."
        )
        return "\n".join(lines)

    self_consistent = all(len(set(v)) == 1 for v in seen.values())
    across = seen[first][0] != seen[second][0]
    if not self_consistent:
        lines.append(
            "**Verdict: simulator non-determinism.** At least one placement "
            "disagreed with ITSELF across two runs of the same input, so the "
            "pair says nothing about the equivalence relation. The finding is "
            "about the harness -- instance numbering or `config_builder` "
            "ordering -- and the equivalence is not implicated."
        )
    elif across:
        lines.append(
            "**Verdict: the equivalence relation is wrong.** Each placement "
            "reproduces itself exactly, and the two still differ. The "
            "signature dropped a property these metrics depend on. This is a "
            "correctness defect in the contribution and is not fixed by "
            "re-running or by relaxing the test."
        )
    else:
        lines.append(
            "**Verdict: no disagreement reproduced.** Both placements are "
            "self-consistent and agree with each other here, so whatever "
            "produced the reported mis-merge is not reproducible under this "
            "path. Reported as unexplained rather than as resolved."
        )
    return "\n".join(lines)


# --- the report -----------------------------------------------------------

COLUMNS = [
    "fixture", "embeddings", "representatives", "compression_ratio",
    "oracle_simulations", "proposed_simulations", "feasible_recall",
    "cost_regret", "false_infeasible", "mismerged_pairs", "correct",
    "unjudged", "unjudged_pairs", "complete",
]

TIME_COLUMNS = [
    "fixture", "t_sim_oracle_s", "t_sim_proposed_s", "t_hash_s", "t_vf2_s",
    "t_bounds_s", "saving_s", "arm_wall_oracle_s", "arm_wall_proposed_s",
    "cold",
]


def _cell(row: dict, key: str) -> str:
    value = row.get(key)
    if isinstance(value, list):
        return str(len(value))
    return "-" if value is None else str(value)


def _cold(row: dict) -> bool:
    """Whether BOTH arms simulated everything rather than reading a cache.

    A warm run's wall time measures the filesystem. `saving` is only a
    measurement when this is True, and the report says so rather than leaving
    a reader to infer it from a suspiciously small number.
    """
    return not (
        (row.get("oracle_cache") or {}).get("hits")
        or (row.get("proposed_cache") or {}).get("hits")
    )


def _saving(row: dict) -> dict:
    """`saving = t_sim_oracle - (t_sim_proposed + t_hash + t_vf2 + t_bounds)`.

    **Both `t_sim` terms are SIMULATION time, not whole-arm wall time.** Using
    the arm's wall clock for `t_sim_proposed` would subtract hashing, VF2 and
    the bounds twice -- once inside that wall clock and once as their own terms
    -- which understates the saving by the compression's entire cost. It is the
    conservative direction, which is no excuse: it is not the quantity the
    pre-registration names.

    The compression's own cost IS charged, once. A saving computed without it
    would be measuring how many simulations were skipped, which is the
    compression ratio wearing a stopwatch.
    """
    timings = row.get("timings") or {}
    oracle_timings = row.get("oracle_timings") or {}
    hashing = timings.get("hash", 0.0)
    vf2 = timings.get("vf2", 0.0)
    bounds = timings.get("bounds", 0.0)
    sim_oracle = oracle_timings.get("sim", 0.0)
    sim_proposed = timings.get("sim", 0.0)
    return {
        "fixture": row["fixture"],
        "t_sim_oracle_s": round(sim_oracle, 1),
        "t_sim_proposed_s": round(sim_proposed, 1),
        "t_hash_s": round(hashing, 3),
        "t_vf2_s": round(vf2, 3),
        "t_bounds_s": round(bounds, 3),
        "saving_s": round(sim_oracle - (sim_proposed + hashing + vf2 + bounds), 1),
        "arm_wall_oracle_s": row.get("t_oracle_s"),
        "arm_wall_proposed_s": row.get("t_proposed_s"),
        "cold": _cold(row),
    }


def markdown(rows: list[dict], args, diagnosis: str | None) -> str:
    banner = (
        MOCK_BANNER
        if args.predictor == "mock"
        else BANNER_TEMPLATE.format(cache=args.cache_dir or "none")
    )
    out = ["# E-G3 — the oracle, against the real simulator", "", banner, ""]
    out.append("| " + " | ".join(COLUMNS) + " |")
    out.append("| " + " | ".join("---" for _ in COLUMNS) + " |")
    for row in rows:
        out.append("| " + " | ".join(_cell(row, c) for c in COLUMNS) + " |")

    out += ["", "## Wall time, and what the compression cost", ""]
    out.append("| " + " | ".join(TIME_COLUMNS) + " |")
    out.append("| " + " | ".join("---" for _ in TIME_COLUMNS) + " |")
    savings = [_saving(row) for row in rows]
    for saving in savings:
        out.append("| " + " | ".join(_cell(saving, c) for c in TIME_COLUMNS) + " |")
    out.append("")
    out.append(
        "`saving_s = t_sim_oracle - (t_sim_proposed + t_hash + t_vf2 + "
        "t_bounds)`, the formula `docs/preregistration.md` registers."
    )
    out.append("")
    out.append(
        "**Both `t_sim` terms are simulation time**, measured around the "
        "evaluation and not around the arm. `arm_wall_*` is the whole arm and "
        "is shown beside them for context only: using it as `t_sim_proposed` "
        "would subtract hashing, VF2 and the bounds twice -- once inside that "
        "wall clock and once as their own terms -- which understates the "
        "saving by the compression's entire cost."
    )
    out.append("")
    out.append(
        "The compression's own cost is charged, once. A saving that counted "
        "only the skipped simulations would be the compression ratio wearing "
        "a stopwatch."
    )
    warm = [s["fixture"] for s in savings if not s["cold"]]
    if warm:
        out.append("")
        out.append(
            f"**`cold` is False on {', '.join(warm)}: those wall times are not "
            "a measurement.** An arm that read its answers from the envelope "
            "cache timed the filesystem, and `saving_s` for that row means "
            "nothing. Delete the cache directory and re-run before quoting any "
            "number in this table's second half. The correctness columns above "
            "are unaffected -- a cached metric is the same metric."
        )

    negative = [s["fixture"] for s in savings if (s["saving_s"] or 0) < 0]
    if args.predictor == "mock":
        out.append("")
        out.append(
            "**Under `--predictor mock` the `saving` column means nothing and "
            "is expected to be negative.** The mock answers in microseconds, "
            "so there is no simulation time for the compression to buy back "
            "and the column measures only what the compression cost. §12's "
            "failure condition is about the real simulator and is NOT "
            "triggered by anything on this page."
        )
    elif negative and not warm:
        out.append("")
        out.append(
            f"**`saving < 0` on {', '.join(negative)}.** This is research "
            "design §12's second named failure condition — the isomorphism "
            "check costing more than the simulation it saves — and the "
            "response was registered before this ran "
            "(`docs/preregistration.md`, E-G3): exact compression is demoted "
            "from a contribution to a **cache key**, and the paper's focus "
            "moves to the contention model and the adaptive budget. Recorded "
            "as a GS-n rather than absorbed here."
        )

    unjudged = [r["fixture"] for r in rows if r.get("unjudged")]
    if unjudged:
        out += ["", "## Placements the simulator did not judge", ""]
        out.append(
            "`unjudged` counts placements the oracle could not reach a verdict "
            "on -- a `SIM_ERROR`, a timeout. They are `unknown_measurement`, "
            "the fourth of the five states, and they are **not** infeasible: "
            "a crash is a property of the run and never of the placement "
            "(work order rule 4)."
        )
        out.append("")
        out.append(
            "`unjudged_pairs` counts pairs inside one equivalence class that "
            "could not be compared because a member was unjudged. They are "
            "excluded from `mismerged_pairs` on purpose: comparing "
            "\"feasible\" against \"no answer\" measures the simulator's "
            "reliability, not the equivalence relation. A run with unjudged "
            "placements has proved LESS than a complete one -- `complete` is "
            "False -- but it has not proved anything wrong."
        )
        out.append("")
        out.append("")
        out.append("| fixture | unjudged | reasons |")
        out.append("| --- | --- | --- |")
        for row in rows:
            if not row.get("unjudged"):
                continue
            reasons = row.get("unjudged_reasons") or {}
            rendered = ", ".join(f"{k} x{v}" for k, v in sorted(reasons.items()))
            out.append(f"| {row['fixture']} | {row['unjudged']} | {rendered} |")
        out.append("")
        out.append(
            "Until `complete` is True on every row, E-G3's correctness claim "
            "covers only the placements that were judged, and the row says how "
            "many that was. **The failures are reported, not explained**: "
            "nothing here claims to know why the simulator refused them."
        )

    out += ["", "## The two arms did not share a cache", ""]
    out.append(
        "`--cache-dir` is a root; the arms run under `<root>/oracle` and "
        "`<root>/proposed`. An exemplar simulated by whichever arm ran first "
        "would otherwise be a cache hit for the other, and the second arm's "
        "wall time would measure the filesystem. The work order names one "
        "directory; this splits it, and the `saving` column is the reason."
    )

    if diagnosis:
        out += ["", diagnosis]

    out += ["", "## Reproducing", ""]
    out.append("```bash")
    out.append("bash experiments/scripts/e_g3_oracle_run.sh")
    out.append("```")
    out.append("")
    out.append(
        "That wrapper sets `PYTHONPATH` and launches through "
        "`vendor/heteropilot/.venv/bin/python` — mandatory, because the Chakra "
        "converter runs in-process and the interpreter decides which protobuf "
        "converts the trace (heteropilot D26/D27)."
    )
    out.append("")
    out.append(
        "It wraps the run in `livelock_watch.sh` with `-g 0 -s 0 -t`, which "
        "asks for a wall-clock ceiling and a process-group kill and **turns "
        "its progress detection off**. That detector reads the simulator's "
        "own tick lines from the wrapped command's stdout; this harness starts "
        "each simulation as a subprocess whose output goes to its own log, so "
        "the watchdog sees a driver that never speaks and kills it. It did "
        "exactly that to a healthy run at 901 s, with 66 simulations already "
        "finished (GS-18). One hung simulation is abandoned by the "
        "predictor's own per-simulation `--timeout` instead, which is the "
        "right layer: the other placements continue."
    )

    out += ["", "## Reading the table", ""]
    out.append(
        "`correct` first: it is `false_infeasible == 0 and mismerged_pairs == "
        "0`. A False there is a bound or an equivalence being wrong, never a "
        "tuning issue, and the registered response is to stop and report — not "
        "to relax the test."
    )
    out.append("")
    out.append(
        "`compression_ratio`, `feasible_recall` and `cost_regret` are "
        "**report-only** under the pre-registration: they are tabulated and "
        "discussed and no pass or fail is claimed from them. The registered "
        "criteria are the invariant and `saving >= 0`."
    )
    out.append("")
    out.append(
        "A non-zero `mismerged_pairs` is diagnosed, not explained: "
        "`--diagnose-pair a b` re-simulates each placement twice under the "
        "same node ordering and says whether the pair is simulator "
        "non-determinism or an equivalence defect. The verdict goes in this "
        "file, in those words."
    )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g3_real_sim_oracle.md")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--predictor", choices=("sim", "mock"), default="sim")
    parser.add_argument("--cache-dir", default="outputs/cache-eg3")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--num-requests", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--only", default=None)
    parser.add_argument(
        "--diagnose-pair", nargs=2, metavar=("A", "B"), default=None,
        help="two embedding ids: is their disagreement the simulator or us?",
    )
    parser.add_argument("--diagnose-fixture", default="graph-toy-shared-nic")
    parser.add_argument(
        "--from-json", default=None,
        help=(
            "re-render the report from a previous run's --json-out and "
            "simulate nothing. For fixing the prose without disturbing the "
            "numbers, and for rebuilding the table from the archived results "
            "in the reproduction package."
        ),
    )
    args = parser.parse_args()

    if args.from_json:
        rows = json.loads(Path(args.from_json).read_text())
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        report = markdown(rows, args, None)
        out.write_text(report + "\n")
        _say(f"re-rendered {len(rows)} row(s) from {args.from_json}; nothing ran")
        return 0 if all(r["correct"] for r in rows) else 1

    rows = [
        one(args, name, path)
        for name, path in CLUSTERS.items()
        if args.only is None or args.only == name
    ]
    diagnosis = (
        diagnose_pair(args, *args.diagnose_pair) if args.diagnose_pair else None
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = markdown(rows, args, diagnosis)
    out.write_text(report + "\n")
    print(report)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2) + "\n")
    return 0 if all(r["correct"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
