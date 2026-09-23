"""`python -m graphsearch` — the graph search's own CLI.

heteropilot's `planner/__main__.py` is **not** modified and not wrapped. This
calls the same functions `planner plan` calls, in a different order, and prints
heteropilot's render output followed by a "Graph search:" block. A reader who
knows the planner's output sees it unchanged.

`--predictor mock` is the default and prints a MOCK banner on every run. The
mock respects the same physics as the bounds -- that is what makes an
oracle disagreement mean something -- but its absolute numbers are fictional
and must never be quoted as performance. `--predictor sim` needs LLMServingSim
and ASTRA-Sim built, which this repository does not carry.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import (  # noqa: E402
    InventoryError,
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)
from planner.render import render  # noqa: E402
from planner.spec import SpecError, load_service_spec  # noqa: E402

from graphsearch.adaptive import (  # noqa: E402
    AdaptiveConfig,
    AdaptiveSearch,
    SearchMode,
    build_ranker,
)
from graphsearch.bounds import ALL_CHECKS, BoundPolicy, prune  # noqa: E402
from graphsearch.embeddings import EmbeddingPolicy, enumerate_embeddings  # noqa: E402
from graphsearch.equivalence import CompressionPolicy, compress  # noqa: E402
from graphsearch.oracle import compare, run_oracle, run_proposed  # noqa: E402
from graphsearch.ranker import DiversityQuota  # noqa: E402
from graphsearch.render import render_graph_block  # noqa: E402
from graphsearch.restore import RestoreError, restore  # noqa: E402
from graphsearch.schema import build_resource_graph  # noqa: E402

MOCK_BANNER = (
    "=" * 78 + "\n"
    "MOCK PREDICTOR. These metrics are FICTIONAL. The mock respects the same\n"
    "physics as the bounds -- which is what makes an oracle disagreement mean\n"
    "something -- but no number below is a measurement or a simulation of any\n"
    "hardware. Do not quote them as performance.\n" + "=" * 78
)


def _parse_k_schedule(text: str) -> tuple[int, ...]:
    try:
        values = tuple(int(part) for part in text.split(","))
    except ValueError as exc:
        raise SystemExit(
            f"--k-schedule {text!r} is not a comma-separated int list"
        ) from exc
    if not values or any(v <= 0 for v in values):
        raise SystemExit("--k-schedule values must be positive")
    return values


def _bound_policy(text: str) -> BoundPolicy:
    if text == "all":
        return BoundPolicy()
    if text == "none":
        # compat and memory are EXACT checks, not bounds, and stay on: `none`
        # turns off the relaxations, not the feasibility test.
        return BoundPolicy(comm_latency=False, throughput_capacity=False)
    wanted = {name.strip() for name in text.split(",") if name.strip()}
    unknown = wanted - set(ALL_CHECKS)
    if unknown:
        raise SystemExit(f"--bounds: unknown check(s) {sorted(unknown)}")
    return BoundPolicy(
        compat="compat" in wanted,
        memory="memory" in wanted,
        comm_latency="comm_latency" in wanted,
        throughput_capacity="throughput_capacity" in wanted,
        cost_lower_bound="cost_lower_bound" in wanted,
    )


def _predictor(args, trace_dir: Path):
    if args.predictor == "mock":
        sys.path.insert(0, str(paths_root.GRAPHSEARCH_ROOT))
        from tests.graph_fixtures import GraphAwareMockPredictor

        return GraphAwareMockPredictor()

    venv = paths_root.HETEROPILOT_ROOT / ".venv"
    if not venv.exists():
        raise SystemExit(
            f"--predictor sim needs a built simulator, and {venv} does not "
            f"exist. Read vendor/heteropilot/CLAUDE.md § Environment, then run "
            f"this through that interpreter."
        )
    raise SystemExit(
        "--predictor sim must be launched through vendor/heteropilot/.venv, "
        "because the Chakra converter runs in-process and the wrong venv "
        "converts a trace to different bytes (heteropilot D26/D27)."
    )


def _load(args):
    try:
        spec = load_service_spec(args.service)
        cluster = load_cluster_spec(args.cluster)
    except (SpecError, InventoryError) as exc:
        raise SystemExit(str(exc)) from exc
    root = Path(args.profiles_root) if args.profiles_root else paths_root.GRAPHSEARCH_ROOT
    profiles = load_profiles_for(cluster, root)
    islands = detect_islands(cluster, profiles)
    graph = build_resource_graph(cluster, profiles)
    return spec, cluster, profiles, islands, graph


def _templates(spec, cluster, islands, profiles, enable_pd: bool = True):
    """P/D generation is ON by default here, unlike heteropilot's CLI (GS-11).

    The research counterexample -- two placements alike in everything except
    which contended uplink they cross -- only becomes visible through a
    `PD_KV_TRANSFER` flow, because that is the only traffic a latency target
    charges for that can cross a node boundary. With P/D off the pipeline
    generates none, and the compression has nothing to demonstrate.
    """
    return CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=enable_pd,
    ).generate().candidates


def cmd_plan(args) -> int:
    spec, cluster, profiles, islands, graph = _load(args)
    by_id = {i.id: i for i in islands}
    templates = _templates(spec, cluster, islands, profiles, not args.no_enable_pd)
    predictor = _predictor(args, Path(args.output or ".").parent)

    embedding_policy = EmbeddingPolicy(
        max_embeddings_per_template=args.max_embeddings_per_template
    )
    compression_policy = CompressionPolicy(enabled=args.compression == "exact")

    if args.oracle:
        result = run_oracle(
            spec, cluster, by_id, profiles, predictor,
            graph=graph, templates=templates, policy=embedding_policy,
        )
        print(MOCK_BANNER if args.predictor == "mock" else "")
        print(
            f"Oracle: {len(result.embeddings)} embeddings simulated, "
            f"{len(result.feasible_ids)} feasible. No compression, no bounds, "
            f"no top-K."
        )
        return 0

    embeddings, stats = enumerate_embeddings(
        templates, by_id, graph, spec, embedding_policy
    )
    representatives, _, report = compress(embeddings, graph, compression_policy)
    verdicts, rejections = prune(
        representatives, spec, graph, by_id, profiles, stats,
        policy=_bound_policy(args.bounds),
    )
    quota = DiversityQuota() if args.diversity else None
    search = AdaptiveSearch(
        spec, cluster, by_id, profiles, predictor,
        graph=graph, representatives=representatives, verdicts=verdicts,
        ranker=build_ranker(
            representatives, spec, graph, by_id, profiles, quota=quota,
            k_hint=args.k_schedule[-1] if quota else None,
        ),
        config=AdaptiveConfig(
            k_schedule=args.k_schedule,
            mode=SearchMode(args.search_mode),
            max_simulations=args.budget_sims,
            max_wall_seconds=args.budget_seconds,
            epsilon=args.epsilon,
        ),
        embedding_stats=stats, compression=report, bound_rejections=rejections,
    )
    output, audit = search.run()

    restored = []
    if output.recommended is not None:
        winner = next(
            (
                r
                for r in representatives
                if r.exemplar.id == output.recommended.plan.candidate.id
            ),
            None,
        )
        if winner is not None:
            try:
                restored.append(restore(winner, output.recommended.plan, graph))
            except RestoreError as exc:
                print(f"warning: could not restore the recommendation: {exc}")

    if args.predictor == "mock":
        print(MOCK_BANNER)
    print(render(output))
    print()
    print(render_graph_block(audit, report, restored))

    if args.output:
        _write(output, audit, report, restored, Path(args.output))
        print(f"\nwritten to {args.output}")
    return 0


def _write(output, audit, report, restored, path: Path) -> None:
    import yaml

    data = output.model_dump(mode="json")
    provenance = data.setdefault("provenance", {})
    provenance["graph_search"] = audit.as_provenance()
    provenance["compression"] = report.as_dict()
    provenance["restored"] = [
        {
            "plan_id": r.plan.plan_id,
            "devices": list(r.device_ids),
            "reservations": dict(r.shared_resource_reservations),
            "snapshot_version": r.snapshot_version,
        }
        for r in restored
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def cmd_compare(args) -> int:
    spec, cluster, profiles, islands, graph = _load(args)
    by_id = {i.id: i for i in islands}
    templates = _templates(spec, cluster, islands, profiles, not args.no_enable_pd)
    predictor = _predictor(args, Path("."))

    oracle = run_oracle(
        spec, cluster, by_id, profiles, predictor, graph=graph, templates=templates
    )
    proposed = run_proposed(
        spec, cluster, by_id, profiles, predictor, graph=graph, templates=templates
    )
    comparison = compare(oracle, proposed)
    if args.predictor == "mock":
        print(MOCK_BANNER)
    print(json.dumps(comparison.as_dict(), indent=2))
    return 0 if comparison.correct else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m graphsearch",
        description="Graph-based placement search over HeteroPilot's planner.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--service", required=True)
        p.add_argument("--cluster", required=True)
        p.add_argument("--profiles-root", default=None)
        p.add_argument("--predictor", choices=("mock", "sim"), default="mock")
        p.add_argument(
            "--no-enable-pd", action="store_true",
            help="do not generate P/D candidates (heteropilot's CLI default)",
        )

    plan = sub.add_parser("plan", help="search, and print what the search did")
    common(plan)
    plan.add_argument("--k-schedule", type=_parse_k_schedule, default=(4, 8, 16))
    plan.add_argument(
        "--search-mode", choices=("budget", "certify"), default="budget"
    )
    plan.add_argument("--budget-sims", type=int, default=None)
    plan.add_argument("--budget-seconds", type=float, default=None)
    plan.add_argument("--epsilon", type=float, default=0.0)
    plan.add_argument("--max-embeddings-per-template", type=int, default=None)
    plan.add_argument("--compression", choices=("exact", "off"), default="exact")
    plan.add_argument("--bounds", default="all")
    plan.add_argument("--diversity", action="store_true")
    plan.add_argument(
        "--oracle", action="store_true",
        help="evaluate every embedding: no compression, no bounds, no top-K",
    )
    plan.add_argument("--output", default=None)
    plan.set_defaults(func=cmd_plan)

    comparison = sub.add_parser(
        "compare", help="oracle vs the search: recall, regret, and correctness"
    )
    common(comparison)
    comparison.set_defaults(func=cmd_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
