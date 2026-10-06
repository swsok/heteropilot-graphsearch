"""E-G6 under the real simulator: one condition, the registered failure condition's.

**REAL SIM.** E-G6's grid runs against the mock, under which simulation costs
microseconds and no compression can pay for itself -- so the one failure
condition E-G6 registers, `saving < 0` on a fully symmetric cluster, could not
be judged by it. This runs that one condition (32 devices, symmetry 1.0, the
grid's own seed) with LLMServingSim as the evaluator, both arms:

- **oracle**: every embedding simulated, nothing folded, nothing bounded;
- **proposed**: compression, bounds and the adaptive search, end to end.

`saving = t_oracle - t_proposed`, with the proposed arm's own hashing,
isomorphism checks and bounds charged against it -- E-G3's definition, so the
two are comparable. The cell is built exactly as `e_g6_scale.py` builds it:
same generator and seed, same template filter, same embedding cap, same
compression policy. Correctness (`false_infeasible`, `mismerged_pairs`) and
the unjudged placements are reported with it, never folded into the saving.

**It needs the A5000 tp=2 profile.** The synthetic devices borrow the A5000's
perf bundle (`sim_hardware: A5000`) and the cell allows tp=2; until heteropilot
ships that profile every tp=2 placement fails to simulate and the run is
incomplete. `--smoke` runs a few tp=1 templates to rehearse the harness.

    vendor/heteropilot/.venv/bin/python experiments/scripts/e_g6_real_sim.py \\
        --max-workers 60
    .venv/bin/python experiments/scripts/e_g6_real_sim.py --predictor mock   # rehearsal
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import (  # noqa: E402
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)

from graphsearch.embeddings import EmbeddingPolicy  # noqa: E402
from graphsearch.equivalence import CompressionPolicy  # noqa: E402
from graphsearch.oracle import compare, run_oracle, run_proposed  # noqa: E402
from graphsearch.schema import build_resource_graph  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
HERE = Path(__file__).resolve().parent

BANNER = (
    "> **REAL SIM — LLMServingSim, cache `{cache}`, not real hardware.** The "
    "cluster is E-G6's synthetic one: every field `source: placeholder`, its "
    "devices borrowing the A5000's perf bundle without being A5000s. Nothing here "
    "is a measurement of any machine, and one condition at 32 devices is not "
    "accuracy validation at scale."
)
MOCK_BANNER = (
    "> **MOCK — not performance numbers.** A rehearsal of the harness with the "
    "mock predictor; this file must not be cited as E-G6's real-simulator result."
)


def _e_g6():
    spec = importlib.util.spec_from_file_location("e_g6_scale", HERE / "e_g6_scale.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["e_g6_scale"] = module
    spec.loader.exec_module(module)
    return module


def _say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def build(args):
    """The E-G6 cell, built the way `e_g6_scale.one_cell` builds it."""
    g6 = _e_g6()
    path = g6.generate(args.devices, args.symmetry, args.seed, Path(args.synth_root))
    cluster = load_cluster_spec(path)
    profiles = load_profiles_for(cluster, ROOT)
    islands = detect_islands(cluster, profiles)
    graph = build_resource_graph(cluster, profiles)
    spec = g6.service_spec()
    generated = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=True,
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= args.max_devices]
    if args.smoke:
        templates = [c for c in templates
                     if all(a.tp_size == 1 for a in c.assignments)][: args.smoke]
    return path, spec, cluster, profiles, {i.id: i for i in islands}, graph, templates


def predictor_for(args, spec, cluster, islands, arm: str):
    if args.predictor == "mock":
        sys.path.insert(0, str(ROOT))
        from tests.graph_fixtures import GraphAwareMockPredictor

        return GraphAwareMockPredictor(), None
    from graphsearch.__main__ import sim_environment

    environment = sim_environment(
        spec, cluster, islands,
        num_requests=args.num_requests, seed=args.sim_seed,
        cache_dir=Path(args.cache_dir) / arm,
        work_dir=Path(args.work_dir) / arm,
        timeout_s=args.timeout,
    )
    return environment.predictor, environment.cache


def run(args) -> dict:
    path, spec, cluster, profiles, islands, graph, templates = build(args)
    embedding_policy = EmbeddingPolicy(
        max_embeddings_per_template=args.max_embeddings_per_template)
    compression_policy = CompressionPolicy(conflicts=False)
    _say(f"{path.name}: {len(templates)} templates; proposed arm starting")

    predictor, cache = predictor_for(args, spec, cluster, islands, "proposed")
    started = time.perf_counter()
    proposed = run_proposed(
        spec, cluster, islands, profiles, predictor, graph=graph, templates=templates,
        embedding_policy=embedding_policy, compression_policy=compression_policy,
        cache=cache, max_workers=args.max_workers,
    )
    t_proposed = time.perf_counter() - started
    proposed_cache = dict(cache.stats()) if cache is not None else {}
    _say(f"proposed: {t_proposed:.0f}s, {proposed.simulations} simulations; oracle starting")

    predictor, cache = predictor_for(args, spec, cluster, islands, "oracle")
    started = time.perf_counter()
    oracle = run_oracle(
        spec, cluster, islands, profiles, predictor, graph=graph, templates=templates,
        policy=embedding_policy, cache=cache, max_workers=args.max_workers,
    )
    t_oracle = time.perf_counter() - started
    oracle_cache = dict(cache.stats()) if cache is not None else {}
    _say(f"oracle: {t_oracle:.0f}s, {oracle.simulations} placements, "
         f"{len(oracle.unjudged)} unjudged")

    comparison = compare(oracle, proposed)
    return {
        "condition": f"d{args.devices}-s{args.symmetry}",
        "cluster": str(path.relative_to(ROOT) if ROOT in path.parents else path),
        "predictor": args.predictor,
        "smoke": bool(args.smoke),
        "templates": len(templates),
        "embeddings": len(oracle.embeddings),
        "representatives": len(proposed.representatives),
        "oracle_simulations": oracle.simulations,
        "proposed_simulations": proposed.simulations,
        "t_oracle_s": round(t_oracle, 1),
        "t_proposed_s": round(t_proposed, 1),
        "saving_s": round(t_oracle - t_proposed, 1),
        "proposed_timings": dict(getattr(proposed.audit, "timings", {}) or {}),
        "oracle_cache": oracle_cache,
        "proposed_cache": proposed_cache,
        "unjudged_reasons": dict(sorted(Counter(oracle.unjudged.values()).items())),
        **comparison.as_dict(),
    }


def markdown(row: dict, args) -> str:
    banner = MOCK_BANNER if row["predictor"] == "mock" else BANNER.format(cache=args.cache_dir)
    head = ["condition", "embeddings", "representatives", "oracle_simulations",
            "proposed_simulations", "t_oracle_s", "t_proposed_s", "saving_s",
            "false_infeasible", "mismerged_pairs", "unjudged", "complete"]
    def count(value):
        return len(value) if isinstance(value, (list, tuple, dict)) else value

    cells = {**row, "false_infeasible": count(row.get("false_infeasible")),
             "mismerged_pairs": count(row.get("mismerged_pairs")),
             "unjudged": count(row.get("unjudged"))}
    verdict = ("**not judged**: a smoke run rehearses the harness on a few "
               "templates" if row["smoke"] else
               "**not judged**: the run is incomplete, so the registered failure "
               "condition is not evaluated by it" if not row.get("complete") else
               ("**fires**: `saving < 0` on the fully symmetric cell" if row["saving_s"] < 0
                else "**does not fire**: the compression saved more than it cost"))
    out = ["# E-G6 — the registered failure condition, under the real simulator", "",
           banner, "",
           "| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |",
           "| " + " | ".join(str(cells.get(h, "-")) for h in head) + " |", "",
           f"The registered failure condition (`saving < 0` at symmetry 1, preregistration "
           f"E-G6): {verdict}.", ""]
    if row.get("unjudged_reasons"):
        out += [f"Unjudged placements by reason: {row['unjudged_reasons']}.", ""]
    if row["smoke"]:
        out += ["**Smoke run** (`--smoke`): a few tp=1 templates only. It rehearses the "
                "harness and judges nothing.", ""]
    out += ["## Reproducing", "", "```bash", "export PYTHONPATH=$PWD:$PWD/vendor/heteropilot",
            "vendor/heteropilot/.venv/bin/python experiments/scripts/e_g6_real_sim.py \\",
            f"    --max-workers {args.max_workers} --out {args.out}", "```"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--predictor", choices=("sim", "mock"), default="sim")
    parser.add_argument("--devices", type=int, default=32)
    parser.add_argument("--symmetry", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260928, help="the grid's generator seed")
    parser.add_argument("--sim-seed", type=int, default=42)
    parser.add_argument("--num-requests", type=int, default=300)
    parser.add_argument("--max-devices", type=int, default=2)
    parser.add_argument("--max-embeddings-per-template", type=int, default=64)
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--smoke", type=int, default=0,
                        help="only this many tp=1 templates: a harness rehearsal")
    parser.add_argument("--synth-root", default="outputs/e_g6/clusters")
    parser.add_argument("--cache-dir", default="outputs/cache-eg6-real")
    parser.add_argument("--work-dir", default="outputs/e_g6-real")
    parser.add_argument("--out", default="experiments/results/e_g6_real_sim.md")
    parser.add_argument("--json-out", default="outputs/e_g6/real-sim.json")
    args = parser.parse_args(argv)

    row = run(args)
    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(markdown(row, args))
    _say(f"wrote {args.out} and {args.json_out}")
    return 0 if row.get("correct", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
