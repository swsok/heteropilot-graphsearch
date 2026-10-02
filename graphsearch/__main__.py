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
import tempfile
from dataclasses import dataclass, field
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
from planner.plan import PlannerOutput  # noqa: E402
from planner.render import render  # noqa: E402
from planner.spec import SpecError, load_service_spec  # noqa: E402

from graphsearch.adaptive import (  # noqa: E402
    AdaptiveConfig,
    AdaptiveSearch,
    SearchAudit,
    SearchMode,
    build_ranker,
)
from graphsearch.bounds import ALL_CHECKS, BoundPolicy, prune  # noqa: E402
from graphsearch.contention import (  # noqa: E402
    CONTENTION_MODELS,
    contention_model,
)
from graphsearch.embeddings import EmbeddingPolicy, enumerate_embeddings  # noqa: E402
from graphsearch.equivalence import (  # noqa: E402
    CompressionPolicy,
    CompressionReport,
    compress,
)
from graphsearch.oracle import (  # noqa: E402
    binder_for,
    compare,
    prices_pd_on_the_path,
    run_oracle,
    run_proposed,
)
from graphsearch.paths import DEFAULT_POLICY, PathPolicy  # noqa: E402
from graphsearch.ranker import (  # noqa: E402
    DEFAULT_RANKER_VARIANT,
    RANKER_VARIANTS,
    DiversityQuota,
)
from graphsearch.render import render_graph_block  # noqa: E402
from graphsearch.restore import (  # noqa: E402
    RestoredPlan,
    RestoreError,
    restore,
)
from graphsearch.schema import build_resource_graph  # noqa: E402

#: heteropilot's own defaults, repeated rather than imported: `planner.__main__`
#: is a script, and importing it to read a constant would run its argparse
#: setup. Pinned by a test so a drift in either is caught.
DEFAULT_TRACE_REQUESTS = 300
DEFAULT_TRACE_SEED = 42

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


#: What a `--predictor sim` run needs beyond the predictor itself. The trace
#: and the cache key are built exactly the way heteropilot's own `plan` builds
#: them, so a cache directory is shared between the two rather than silently
#: forked -- `EnvelopeKey` is heteropilot's and a second convention here would
#: make the two disagree about what a hit is.
@dataclass
class SimEnvironment:
    predictor: object
    cache: object | None
    trace_path: Path
    work_root: Path


def _require_the_simulator_venv() -> Path:
    """The one interpreter `--predictor sim` may run under, or a refusal.

    Two separate failures, said separately because the fix differs: the venv
    does not exist (build it), or it exists and is not the one running this
    process (relaunch through it). The second is not pedantry -- since
    heteropilot D27 the Chakra converter runs IN-PROCESS, so which venv started
    the run decides which protobuf converts the trace, and a venv without
    `protobuf>=7.35.1` raises at the first conversion instead of converting
    wrongly (D26/D27).
    """
    venv = paths_root.HETEROPILOT_ROOT / ".venv"
    if not venv.exists():
        raise SystemExit(
            f"--predictor sim needs a built simulator, and {venv} does not "
            f"exist. Read vendor/heteropilot/CLAUDE.md § Environment, then run "
            f"this through that interpreter."
        )
    if Path(sys.prefix).resolve() != venv.resolve():
        raise SystemExit(
            f"--predictor sim must be launched through {venv}/bin/python, not "
            f"{sys.executable}. The Chakra converter runs in-process, so the "
            f"interpreter decides which protobuf converts the trace "
            f"(heteropilot D26/D27)."
        )
    return venv


def sim_environment(
    spec,
    cluster,
    islands,
    *,
    num_requests: int = DEFAULT_TRACE_REQUESTS,
    seed: int = DEFAULT_TRACE_SEED,
    cache_dir: str | Path | None = None,
    work_dir: str | Path | None = None,
    timeout_s: float = 900.0,
) -> SimEnvironment:
    """Trace, envelope cache and simulator predictor, in heteropilot's own shape.

    Public, and taking values rather than an argparse namespace, because the
    E-G3 harness needs exactly this environment and a second copy of it would
    be a second convention: the trace digest and the `EnvelopeKey` it feeds are
    what decide whether a cache entry answers, and two builders that drifted
    apart would turn every hit into a miss without saying so.
    """
    _require_the_simulator_venv()

    from planner.envelope import EnvelopeCache
    from planner.predictor.llmservingsim import LLMServingSimPredictor
    from planner.topology import TopologyGraph
    from planner.util import provenance as prov
    from planner.util.workload import generate_trace

    # Under `outputs/`, which is gitignored, and not under the repository root:
    # a default that scatters `gs-sim-*` directories through a working tree
    # makes `git status` noise out of every simulator run, and one of them
    # eventually gets committed. heteropilot's own predictor stages into
    # `outputs/` for the same reason.
    default_root = paths_root.GRAPHSEARCH_ROOT / "outputs"
    default_root.mkdir(parents=True, exist_ok=True)
    work_root = (
        Path(work_dir)
        if work_dir
        else Path(tempfile.mkdtemp(prefix="gs-sim-", dir=default_root))
    )
    work_root.mkdir(parents=True, exist_ok=True)
    trace = generate_trace(
        spec, work_root / "workload.jsonl",
        num_requests=num_requests, seed=seed,
    )

    cache = None
    if cache_dir:
        reduction = TopologyGraph(cluster).reduce_for_simulator(list(islands.values()))
        cache = EnvelopeCache(
            Path(cache_dir),
            spec,
            accelerator_of={i.id: i.accelerator_model for i in islands.values()},
            link_bw_gbps=reduction.link_bw_gbps,
            trace_digest=prov.hash_file(trace.path),
            topology_level=1,
        )

    predictor = LLMServingSimPredictor(
        trace,
        work_dir=work_root / "sims",
        timeout_s=timeout_s,
    )
    return SimEnvironment(
        predictor=predictor, cache=cache,
        trace_path=Path(trace.path), work_root=work_root,
    )


def _sim_environment(args, spec, cluster, islands) -> SimEnvironment:
    """`sim_environment` with the CLI's flags unpacked."""
    return sim_environment(
        spec, cluster, islands,
        num_requests=args.num_requests, seed=args.seed,
        cache_dir=args.cache_dir, work_dir=args.work_dir,
        timeout_s=args.timeout,
    )


def _mock_predictor():
    sys.path.insert(0, str(paths_root.GRAPHSEARCH_ROOT))
    from tests.graph_fixtures import GraphAwareMockPredictor

    return GraphAwareMockPredictor()


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


def _templates(
    spec, cluster, islands, profiles, enable_pd: bool = True,
    max_devices: int | None = None,
):
    """P/D generation is ON by default here, unlike heteropilot's CLI (GS-11).

    The research counterexample -- two placements alike in everything except
    which contended uplink they cross -- only becomes visible through a
    `PD_KV_TRANSFER` flow, because that is the only traffic a latency target
    charges for that can cross a node boundary. With P/D off the pipeline
    generates none, and the compression has nothing to demonstrate.
    """
    templates = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=enable_pd,
    ).generate().candidates
    if max_devices is not None:
        # A SCOPE cut, not a feasibility judgement. What it removes is
        # `excluded_by_scope`: the caller asked "what is the best plan using at
        # most N devices", and templates above N were never considered rather
        # than considered and rejected. The two do not merge (work order rule
        # 4), and every caller that passes this records the number.
        templates = [t for t in templates if t.total_devices <= max_devices]
    return templates


@dataclass(frozen=True)
class PlanObjects:
    """Everything `cmd_plan` computes, before any of it is printed.

    `plan --output` writes a YAML summary, and a summary cannot be launched:
    `VllmCudaBackend.launch` wants a `DeploymentPlan`. E-G5's harness needs the
    objects, and re-deriving them by parsing the summary would be a second,
    quietly different code path -- the first time the two disagreed, the
    deployment would not match the plan it claims to be.
    """

    output: PlannerOutput
    audit: SearchAudit
    report: CompressionReport
    restored: list[RestoredPlan]
    representatives: list
    verdicts: object
    rejections: object
    graph: object
    islands_by_id: dict
    profiles: object
    cluster: object
    spec: object


def cmd_plan(args) -> int:
    if args.oracle:
        # Handled here rather than in `cmd_plan_objects`, which has no way to
        # say "there is no plan": the oracle mode simulates everything and
        # recommends nothing, so there are no objects to return. An earlier
        # version signalled it with `raise SystemExit(0)` from inside the
        # pipeline, which `cmd_plan` then could not turn back into its
        # documented int return -- tests/test_cli.py caught it.
        return _cmd_plan_oracle(args)
    objects = cmd_plan_objects(args)
    if args.predictor == "mock":
        print(MOCK_BANNER)
    print(render(objects.output))
    print()
    print(render_graph_block(objects.audit, objects.report, objects.restored))

    if args.output:
        _write(objects.output, objects.audit, objects.report,
               objects.restored, Path(args.output))
        print(f"\nwritten to {args.output}")
    return 0


def _cmd_plan_oracle(args) -> int:
    """`--oracle`: simulate every embedding, recommend nothing, say so."""
    spec, cluster, profiles, islands, graph = _load(args)
    by_id = {i.id: i for i in islands}
    templates = _templates(spec, cluster, islands, profiles, not args.no_enable_pd)
    predictor, _cache = _predictor_for(args, spec, cluster, by_id)
    result = run_oracle(
        spec, cluster, by_id, profiles, predictor,
        graph=graph, templates=templates,
        policy=EmbeddingPolicy(
            max_embeddings_per_template=args.max_embeddings_per_template
        ),
    )
    print(MOCK_BANNER if args.predictor == "mock" else "")
    print(
        f"Oracle: {len(result.embeddings)} embeddings simulated, "
        f"{len(result.feasible_ids)} feasible. No compression, no bounds, "
        f"no top-K."
    )
    return 0


def _predictor_for(args, spec, cluster, by_id):
    """The predictor and its cache. One definition, three callers."""
    if args.predictor == "mock":
        return _mock_predictor(), None
    environment = _sim_environment(args, spec, cluster, by_id)
    print(
        f"sim: trace {environment.trace_path} "
        f"({args.num_requests} requests, seed {args.seed}); "
        f"work {environment.work_root}; "
        f"cache {args.cache_dir or 'none'}",
        file=sys.stderr,
    )
    return environment.predictor, environment.cache


def cmd_plan_objects(args) -> PlanObjects:
    """The whole planning pipeline, returning objects instead of printing.

    `cmd_plan` is this plus the rendering, so the CLI's output is unchanged and
    the two cannot drift: there is one pipeline, not two.
    """
    spec, cluster, profiles, islands, graph = _load(args)
    by_id = {i.id: i for i in islands}
    templates = _templates(
        spec, cluster, islands, profiles, not args.no_enable_pd,
        max_devices=getattr(args, "max_devices", None),
    )
    predictor, cache = _predictor_for(args, spec, cluster, by_id)

    embedding_policy = EmbeddingPolicy(
        max_embeddings_per_template=args.max_embeddings_per_template
    )
    # `conflicts=False` for the same reason `run_proposed` does it: the
    # matrix is discarded here and is O(n^2) over embeddings (GS-21).
    compression_policy = CompressionPolicy(
        enabled=args.compression == "exact", conflicts=False
    )

    path_policy = (
        PathPolicy(max_hops=args.max_hops)
        if getattr(args, "max_hops", None) is not None else DEFAULT_POLICY
    )
    embeddings, stats = enumerate_embeddings(
        templates, by_id, graph, spec, embedding_policy, path_policy=path_policy
    )
    representatives, _, report = compress(embeddings, graph, compression_policy)
    verdicts, rejections = prune(
        representatives, spec, graph, by_id, profiles, stats,
        policy=_bound_policy(args.bounds), path_policy=path_policy,
    )
    contention = contention_model(args.contention)
    quota = DiversityQuota() if args.diversity else None
    search = AdaptiveSearch(
        spec, cluster, by_id, profiles, predictor,
        graph=graph, representatives=representatives, verdicts=verdicts,
        ranker=build_ranker(
            representatives, spec, graph, by_id, profiles, quota=quota,
            k_hint=args.k_schedule[-1] if quota else None, variant=args.ranker,
            contention=contention,
        ),
        config=AdaptiveConfig(
            k_schedule=args.k_schedule,
            mode=SearchMode(args.search_mode),
            max_simulations=args.budget_sims,
            max_wall_seconds=args.budget_seconds,
            epsilon=args.epsilon,
        ),
        embedding_stats=stats, compression=report, bound_rejections=rejections,
        cache=cache,
        # Without these the predictor never learns WHICH devices a candidate
        # runs on, so it answers per template and two placements differing only
        # in the uplink they cross come back identical -- the distinction this
        # whole search exists to keep. `compare` bound them from the start;
        # `plan` did not, and the audit's `hook_calls` is now the evidence
        # either way (GS-13).
        bind_embeddings=binder_for(
            predictor, graph, spec, cluster, by_id, profiles, contention
        ),
        embedded_pd_cost=prices_pd_on_the_path(predictor),
        max_workers=args.max_workers,
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

    return PlanObjects(
        output=output, audit=audit, report=report, restored=restored,
        representatives=representatives, verdicts=verdicts,
        rejections=rejections, graph=graph, islands_by_id=by_id,
        profiles=profiles, cluster=cluster, spec=spec,
    )



@dataclass
class PlacementVerdict:
    """What the search says about ONE placement, asked about that placement.

    E-G5 deploys a template at a placement the condition names. The search's
    recommendation is the best placement it reached, which is not necessarily
    that one, and printing the recommendation's metrics beside a measurement
    taken somewhere else is the defect GS-30 records. This is the verdict for
    the placement actually deployed.
    """

    embedding_id: str
    devices: tuple[str, ...]
    #: How the search's own run treated this placement's representative, in
    #: the five-state vocabulary: whether the bound judged it, and whether the
    #: budget reached it. Never merged with `state` below.
    search_state: str
    #: The verdict of simulating THIS placement: `evaluated` or
    #: `unknown_measurement`. Only `evaluated` carries metrics.
    state: str
    feasible: bool | None
    plan: object | None
    detail: str
    #: The violated axes as the feasibility check judged them: metric, target,
    #: predicted, overshoot ratio. Empty when the placement was feasible.
    violations: list = field(default_factory=list)


def evaluate_placement(args, objects: PlanObjects, template_id: str,
                       devices) -> PlacementVerdict:
    """Simulate one placement of one template, through the search's own parts.

    Same predictor, same compile hook, same per-candidate cache signature as
    `cmd_plan_objects` uses, so a placement the search already evaluated is a
    cache hit with its own metrics, and one it did not reach is simulated now
    rather than reported as something it is not.
    """
    from typing import cast

    from planner.optimizer.exhaustive import evaluate_candidates

    from graphsearch.adaptive import _graph_signature
    from graphsearch.schema import ResourceGraph

    wanted = frozenset(devices)
    rep = embedding = None
    for r in objects.representatives:
        if r.template_id != template_id:
            continue
        for e in [r.exemplar, *r.embeddings]:
            if e.devices == wanted:
                rep, embedding = r, e
                break
        if embedding is not None:
            break
    if embedding is None:
        return PlacementVerdict(
            embedding_id="", devices=tuple(sorted(wanted)),
            search_state="excluded_by_scope", state="excluded_by_scope",
            feasible=None, plan=None,
            detail=f"no embedding of {template_id} occupies exactly these devices",
        )

    assert rep is not None
    graph = cast(ResourceGraph, objects.graph)
    bound = cast(dict, objects.verdicts).get(rep.rep_id)
    reached = rep.exemplar.id not in set(objects.audit.unevaluated_ids or [])
    feasible_ids = {p.candidate.id for p in objects.audit.feasible_plans}
    if bound is not None and bound.eliminated:
        search_state = "impossible_proven (by a bound; never simulated)"
    elif not reached:
        search_state = "unevaluated (the budget did not reach it)"
    elif rep.exemplar.id in feasible_ids:
        search_state = "evaluated: feasible"
    else:
        search_state = "evaluated: not feasible"

    spec, cluster = objects.spec, objects.cluster
    by_id, profiles = objects.islands_by_id, objects.profiles
    predictor, cache = _predictor_for(args, spec, cluster, by_id)
    bind = binder_for(predictor, graph, spec, cluster, by_id, profiles,
                      contention_model(args.contention))
    if bind is not None:
        bind({embedding.id: embedding})
    if cache is not None:
        signature = _graph_signature(rep, graph)
        cache = cache.with_signature_of(lambda c: signature)
    candidate = embedding.template.model_copy(update={"id": embedding.id})
    result = evaluate_candidates(
        [candidate], spec, cluster, by_id, profiles, predictor,
        cache=cache, pd_transfer=not prices_pd_on_the_path(predictor),
    )
    ranks = tuple(v for p in embedding.placements for v in p.ranks)
    if result.feasible_plans:
        return PlacementVerdict(embedding.id, ranks, search_state, "evaluated",
                                True, result.feasible_plans[0], "")
    if result.infeasible_plans:
        plan, report = result.infeasible_plans[0]
        violations = [
            {"metric": v.metric, "target": v.target, "predicted": v.predicted,
             "overshoot_ratio": v.overshoot_ratio}
            for v in getattr(report, "violations", [])
        ]
        return PlacementVerdict(embedding.id, ranks, search_state, "evaluated",
                                False, plan, str(getattr(report, "reasons", report)),
                                violations)
    why = "; ".join(str(r) for r in result.rejections) or "; ".join(result.notes)
    return PlacementVerdict(
        embedding.id, ranks, search_state, "unknown_measurement", None, None,
        why or "the simulator returned no verdict for this placement",
    )

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
    predictor = (
        _mock_predictor()
        if args.predictor == "mock"
        else _sim_environment(args, spec, cluster, by_id).predictor
    )

    oracle = run_oracle(
        spec, cluster, by_id, profiles, predictor, graph=graph, templates=templates
    )
    proposed = run_proposed(
        spec, cluster, by_id, profiles, predictor, graph=graph, templates=templates,
        ranker_variant=args.ranker, contention=contention_model(args.contention),
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
        p.add_argument(
            "--ranker", choices=RANKER_VARIANTS, default=DEFAULT_RANKER_VARIANT,
            help="service_margin_v1 is the pre-G15 estimate, kept as the baseline",
        )
        # --predictor sim only. Named the same as heteropilot's own `plan`
        # flags, and defaulting to the same values, so a cache directory is
        # shared between the two rather than forked.
        p.add_argument("--num-requests", type=int, default=DEFAULT_TRACE_REQUESTS)
        p.add_argument("--seed", type=int, default=DEFAULT_TRACE_SEED)
        p.add_argument("--cache-dir", default=None,
                       help="PerformanceEnvelope cache directory (--predictor sim)")
        p.add_argument("--work-dir", default=None,
                       help="where the trace and the simulator inputs are staged")
        p.add_argument("--timeout", type=float, default=900.0,
                       help="seconds per simulation before it is abandoned")
        p.add_argument("--max-workers", type=int, default=None,
                       help="concurrent simulations; assembly stays sequential")
        # `null` stays the default, so the path every result up to E-G3 was
        # computed under is the one you get without asking. The BOUNDS use
        # null whatever this says: a pruning stage may reject only on the most
        # optimistic arithmetic, and fluid is never the faster of the two.
        p.add_argument(
            "--contention", choices=sorted(CONTENTION_MODELS), default="null",
            help="how flows sharing a resource are priced (default null)",
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
    plan.add_argument(
        "--max-hops", type=int, default=None,
        help="cap on a path's hop count (default: the library's, 8). Every "
             "simple path up to the cap is enumerated, so on a cluster whose "
             "nodes are full PCIe meshes an inter-node pair has tens of "
             "thousands of them; the cap is then a declared modelling choice, "
             "recorded by the caller (GS-32).",
    )
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
