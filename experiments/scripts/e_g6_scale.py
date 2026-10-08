"""E-G6: how the search's cost grows with size, and with how alike the nodes are.

**MOCK unless the banner says otherwise.** The nine grid cells run against the
deterministic mock predictor; no number here is a measurement or a simulation
of any hardware, and the clusters are synthetic with every field
`source: placeholder`. Research design §12 forbids presenting a simulation at
this scale as large-scale accuracy validation, and this file makes no such
claim.

**What the pre-registration asks of this, and does not.** E-G6 registers **no
success criterion**: wall time, VF2 seconds, compression ratio and the
`excluded_by_scope` count are all report-only. An absolute wall-time target
would be a statement about the machine it ran on. One failure condition *is*
registered -- `saving < 0` at `symmetry = 1`, the most favourable case the
generator can produce -- and it fires §12's first named failure condition.

The grid: {32, 64, 128} devices x symmetry {0, 0.5, 1}, seeds recorded.

    bash experiments/scripts/e_g6_run.sh          # the wrapper, with a ceiling
    python experiments/scripts/e_g6_scale.py --devices 32 --only-symmetry 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
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

from graphsearch.adaptive import (  # noqa: E402
    AdaptiveConfig,
    AdaptiveSearch,
    build_ranker,
)
from graphsearch.bounds import BoundPolicy, CandidateStatus, prune  # noqa: E402
from graphsearch.embeddings import EmbeddingPolicy, enumerate_embeddings  # noqa: E402
from graphsearch.equivalence import CompressionPolicy, compress  # noqa: E402
from graphsearch.schema import build_resource_graph  # noqa: E402
from graphsearch.synth.cluster_gen import build_parser as gen_parser  # noqa: E402
from graphsearch.synth.cluster_gen import resolve as gen_resolve  # noqa: E402
from graphsearch.synth.cluster_gen import write as gen_write  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"

BANNER = (
    "> **MOCK — not performance numbers.** Nine synthetic clusters, every "
    "field `source: placeholder`, evaluated by a deterministic mock predictor. "
    "Nothing here is a measurement or a simulation of any hardware, and "
    "research design §12 forbids presenting a simulation at this scale as "
    "large-scale accuracy validation."
)

#: Devices per node. Four, so a 32-device cluster is eight nodes -- enough
#: distinct nodes for symmetry to mean something, which it cannot on two.
DEVICES_PER_NODE = 4

SYMMETRIES = (0.0, 0.5, 1.0)
DEVICE_COUNTS = (32, 64, 128)


def service_spec():
    """The same roomy-TTFT spec E-G1 and E-G3 use, for the same reason.

    E-G6 measures the SEARCH's cost, not whether a toy SLO is reachable. A
    spec that made everything infeasible would still enumerate, compress and
    bound exactly the same way -- but the simulation count would collapse and
    the wall-time curve would stop being about the search.
    """
    spec = load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")
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


def _say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def machine_load() -> dict:
    """What else was running while this cell was timed.

    The wall-time columns are E-G6's product, and a cell timed beside a busy
    machine is timed under a condition the table does not otherwise state.
    This is the same guard `experiments/microbench/run_pair.py` puts on GPU
    occupancy, applied to the resource this experiment actually competes for.

    It is recorded rather than enforced: a run is not refused for being busy,
    it is labelled, and `analysed_as_quiet` in the report is what a reader
    checks before quoting a time.
    """
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:                                  # pragma: no cover
        return {"available": False}
    return {
        "available": True,
        "load_1min": round(one, 2),
        "load_5min": round(five, 2),
        "load_15min": round(fifteen, 2),
        "cpus": os.cpu_count(),
    }


def generate(devices: int, symmetry: float, seed: int, out_root: Path) -> Path:
    nodes = devices // DEVICES_PER_NODE
    out = out_root / f"d{devices}-s{str(symmetry).replace('.', '')}"
    args = gen_resolve(
        gen_parser().parse_args(
            [
                "--nodes", str(nodes),
                "--devices-per-node", str(DEVICES_PER_NODE),
                "--symmetry", str(symmetry),
                "--seed", str(seed),
                # Three uplink capacities so asymmetry has something to differ
                # in. With one kind, `symmetry 0` would still produce nodes
                # that differ only in price, and price is not in the candidate
                # graph -- the compression would fold them and the x-axis
                # would be measuring nothing.
                "--uplink-kinds", "3",
                "--out", str(out),
            ]
        )
    )
    return gen_write(args)


def _cell_star(packed) -> dict:
    """`ProcessPoolExecutor.map` takes one argument; `one_cell` takes three."""
    return one_cell(*packed)


def one_cell(args, devices: int, symmetry: float) -> dict:
    load_before = machine_load()
    _say(f"d={devices} s={symmetry}: generating")
    path = generate(devices, symmetry, args.seed, Path(args.synth_root))
    cluster = load_cluster_spec(path)
    profiles = load_profiles_for(cluster, ROOT)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)
    spec = service_spec()

    started = time.perf_counter()
    generated = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=args.enable_pd,
    ).generate()
    templates = [
        c for c in generated.candidates if c.total_devices <= args.max_devices
    ]
    t_templates = time.perf_counter() - started

    _say(f"d={devices} s={symmetry}: {len(templates)} templates; enumerating")
    started = time.perf_counter()
    embeddings, stats = enumerate_embeddings(
        templates, by_id, graph, spec,
        EmbeddingPolicy(max_embeddings_per_template=args.max_embeddings_per_template),
    )
    t_enumerate = time.perf_counter() - started

    _say(f"d={devices} s={symmetry}: {len(embeddings)} embeddings; compressing")
    started = time.perf_counter()
    representatives, _, report = compress(
        embeddings, graph, CompressionPolicy(conflicts=False)
    )
    t_compress = time.perf_counter() - started

    started = time.perf_counter()
    verdicts, rejections = prune(
        representatives, spec, graph, by_id, profiles, stats, policy=BoundPolicy()
    )
    t_bounds = time.perf_counter() - started

    scope = sum(
        1
        for v in verdicts.values()
        if v.status is CandidateStatus.EXCLUDED_BY_SCOPE
    )

    simulations = None
    t_search = None
    if not args.no_search:
        _say(f"d={devices} s={symmetry}: {len(representatives)} reps; searching")
        sys.path.insert(0, str(ROOT))
        from tests.graph_fixtures import GraphAwareMockPredictor

        predictor = GraphAwareMockPredictor()
        search = AdaptiveSearch(
            spec, cluster, by_id, profiles, predictor,
            graph=graph, representatives=representatives, verdicts=verdicts,
            ranker=build_ranker(representatives, spec, graph, by_id, profiles),
            config=AdaptiveConfig(k_schedule=(args.k,)),
            embedding_stats=stats, compression=report,
            bound_rejections=rejections,
        )
        started = time.perf_counter()
        _, audit = search.run()
        t_search = time.perf_counter() - started
        simulations = audit.simulations_run

    load_after = machine_load()

    ratio = len(representatives) / len(embeddings) if embeddings else None
    return {
        "load_before": load_before,
        "load_after": load_after,
        "devices": devices,
        "symmetry": symmetry,
        "nodes": devices // DEVICES_PER_NODE,
        "seed": args.seed,
        "cluster": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "templates": len(templates),
        "embeddings": len(embeddings),
        "representatives": len(representatives),
        "compression_ratio": None if ratio is None else round(ratio, 6),
        "excluded_by_scope": scope,
        "truncated_templates": getattr(stats, "truncated", None),
        "simulations": simulations,
        "t_templates_s": round(t_templates, 2),
        "t_enumerate_s": round(t_enumerate, 2),
        "t_compress_s": round(t_compress, 2),
        "t_hash_s": round(report.hash_seconds, 3),
        "t_vf2_s": round(report.vf2_seconds, 3),
        "t_bounds_s": round(t_bounds, 3),
        "t_search_s": None if t_search is None else round(t_search, 2),
        "t_total_s": round(
            t_templates + t_enumerate + t_compress + t_bounds + (t_search or 0.0), 2
        ),
    }


COLUMNS = [
    "devices", "symmetry", "nodes", "templates", "embeddings",
    "representatives", "compression_ratio", "excluded_by_scope",
    "simulations", "t_enumerate_s", "t_hash_s", "t_vf2_s", "t_bounds_s",
    "t_search_s", "t_total_s",
]


def classify_load(rows: list[dict], outlier: float) -> dict:
    """Mark the cells whose load sat materially above this run's own median.

    Relative because the baseline belongs to the machine, not to the
    experiment. This box runs a constant ~6-core neighbour, so an absolute
    threshold marks everything; what distorts the curve is a TRANSIENT that
    hits some cells and not others -- a parallel test run, a second grid, a
    holdout script someone started without thinking.

    Done here rather than in `one_cell` so the whole run's distribution is
    available: the first cell cannot know what normal looks like.
    """
    loads = []
    for row in rows:
        samples = [
            snapshot.get("load_1min")
            for snapshot in (row.get("load_before"), row.get("load_after"))
            if snapshot and snapshot.get("available")
        ]
        row["_load_peak"] = max(samples) if samples else None
        if row["_load_peak"] is not None:
            loads.append(row["_load_peak"])

    if not loads:
        for row in rows:
            row["timed_on_a_quiet_machine"] = None
        return {"available": False}

    ordered = sorted(loads)
    median = ordered[len(ordered) // 2]
    for row in rows:
        peak = row["_load_peak"]
        row["timed_on_a_quiet_machine"] = (
            None if peak is None else peak <= median + outlier
        )
    return {
        "available": True,
        "median": round(median, 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
        "threshold": round(median + outlier, 2),
    }


def markdown(rows: list[dict], args) -> str:
    load = classify_load(rows, args.load_outlier)
    out = ["# E-G6 — scalability", "", BANNER, ""]
    out.append("| " + " | ".join(COLUMNS) + " |")
    out.append("| " + " | ".join("---" for _ in COLUMNS) + " |")
    for row in sorted(rows, key=lambda r: (r["devices"], r["symmetry"])):
        out.append(
            "| "
            + " | ".join(
                "-" if row.get(c) is None else str(row.get(c)) for c in COLUMNS
            )
            + " |"
        )

    out += ["", "## What is registered, and what is not", ""]
    out.append(
        "`docs/preregistration.md` registers **no success criterion** for "
        "E-G6. Every column above is report-only: an absolute wall-time "
        "target would be a statement about the machine this ran on, not about "
        "the search. The curve is the result; a line drawn across it would be "
        "decoration."
    )
    out.append("")
    out.append(
        "One failure condition **is** registered: `saving < 0` at "
        "`symmetry = 1`. Symmetry 1 is the most favourable case the generator "
        "can produce — every node identical, so the compression has the most "
        "to fold — and a compression that cannot pay for itself there cannot "
        "pay for itself anywhere. It fires research design §12's first named "
        "failure condition, and the registered response is E-G3's: demote "
        "exact compression to a cache key and narrow the paper."
    )

    out += ["", "## `t_enumerate` before and after GS-25/GS-26", ""]
    out.append(
        "This grid was first measured on 2026-09-28 and re-measured on "
        "2026-09-29 after the enumerator changed. **Every structural column "
        "is identical** -- templates, embeddings, representatives, "
        "compression ratio, `false_infeasible` and `mismerged_pairs` -- and "
        "only the seconds moved:"
    )
    out.append("")
    out.append(
        "| devices | `t_enumerate` before | after | |\n"
        "| --- | --- | --- | --- |\n"
        "| 32 | 18.2 s | 6.04 s | 3.0x |\n"
        "| 64 | 128.65 s | 25.68 s | 5.0x |\n"
        "| 128 | 868.99 s | 111.07 s | 7.8x |"
    )
    out.append("")
    out.append(
        "GS-25 stopped enumerating the `prod_a R_a!` replica orderings and "
        "computes the folded count in closed form; GS-26 stopped recomputing "
        "one graph's paths once per placement. Neither changes which "
        "embeddings exist, which is why only this column moved -- and the "
        "1-minute load figures below moved too, because the 2026-09-28 grid "
        "carried a neighbour that has since gone."
    )

    if load.get("available"):
        out += ["", "## The machine these timings were taken on", ""]
        out.append(
            f"1-minute load average across the cells: min {load['min']}, "
            f"median {load['median']}, max {load['max']}."
        )
        out.append("")
        out.append(
            "**The median is not near zero, and that is a standing condition "
            "rather than a fault.** This box carries a neighbour that holds "
            "roughly six cores continuously. It affects every cell about "
            "equally, so it shifts the curve rather than bending it — but a "
            "reader comparing these seconds against a quiet machine's should "
            "know, and the banner does not say it."
        )
        out.append("")
        out.append(
            f"A cell is marked as taken under contention when its peak load "
            f"exceeds the run's own median by more than {args.load_outlier} "
            f"(so, above {load['threshold']}). Relative, because an absolute "
            f"threshold on this box would mark every row, and a check that "
            f"always fires is as useless as one that never does. What bends "
            f"the curve is a TRANSIENT hitting some cells and not others."
        )

    busy = [
        f"{r['devices']}/{r['symmetry']:g}"
        for r in rows
        if r.get("timed_on_a_quiet_machine") is False
    ]
    if busy:
        out += ["", "## Cells timed under contention", ""]
        out.append(
            f"**{', '.join(busy)}** ran with a 1-minute load average above "
            "the quiet threshold, so something else had the memory bandwidth "
            "at the same time. Their wall-time columns are not comparable "
            "with the other rows. The counts are unaffected — they are "
            "properties of the graph, not of the machine — and re-running "
            "those cells on a quiet box is the fix, not a footnote."
        )
        out.append("")
        out.append(
            "Recorded from `os.getloadavg()` at the start and end of each "
            "cell rather than remembered. It has caught two real "
            "contaminations already: a 16-worker test run that overlapped two "
            "64-device cells, and a holdout script started while the "
            "128-device cells were being timed. Neither showed up anywhere "
            "else in the output."
        )

    if not all(row.get("timings_are_serial", True) for row in rows):
        out += ["", "## These timings were taken under contention", ""]
        out.append(
            f"**Run with `--jobs {rows[0].get('jobs')}`, so the wall-time "
            "columns are not comparable with a serial run and not comparable "
            "with each other.** Cells sharing a machine contend for memory "
            "bandwidth unevenly: the 128-device cell takes more of it than the "
            "32-device one, so the curve distorts rather than merely shifting. "
            "The counts — embeddings, representatives, `compression_ratio`, "
            "`excluded_by_scope` — are unaffected, because they are properties "
            "of the graph and not of the machine. Re-run with `--jobs 1` "
            "before quoting any time."
        )

    out += ["", "## Why there is no `saving` column here", ""]
    out.append(
        "E-G6's registered failure condition is `saving < 0` at "
        "`symmetry = 1`, and **this table cannot evaluate it.** `saving` is "
        "`t_sim_oracle - (t_sim_proposed + t_hash + t_vf2 + t_bounds)`, and "
        "these cells run the MOCK, where a simulation costs microseconds. "
        "Against a predictor that free, any compression whatsoever loses: the "
        "column would be negative everywhere and would say nothing about the "
        "contribution."
    )
    out.append("")
    out.append(
        "**That question is E-G3's, and E-G3 answered it** under the real "
        "simulator: `saving` +2475 s, +1220 s and +269 s on the three "
        "fixtures, against a compression that cost about half a second in "
        "total. What E-G6 adds is the other half — how the compression's OWN "
        "cost and the ratio behave as the cluster grows — and the two are read "
        "together."
    )
    out.append("")
    out.append(
        "**The condition itself was then run under the real simulator**, on "
        "this grid's 32-device, symmetry-1 cell, both arms end to end "
        "(preregistration change-log row 10): `e_g6_real_sim.md`. It does not "
        "fire there."
    )

    out += ["", "## The compression's cost, and what it is not", ""]
    out.append(
        "`t_hash_s` and `t_vf2_s` are the compression's whole cost and are "
        "kept apart because they scale differently — hashing is linear in "
        "embeddings, VF2 is quadratic inside a bucket, and a lumped number "
        "could not say which one ate the budget."
    )
    out.append("")
    out.append(
        "**`t_compress_s` is not charged to the compression, and the "
        "difference used to be most of it.** `compress` also built a conflict "
        "matrix — O(n²) over embeddings — that the search pipeline discards. "
        "On the 32-device cell that was 32.3 s of 52.1 s. Charging it here "
        "would not have made this table slow, it would have made it **wrong**, "
        "and wrong in the direction of failing our own contribution (GS-21)."
    )

    out += ["", "## Reading `compression_ratio`", ""]
    out.append(
        "A ratio near 1.0 at `symmetry = 0` is **not** a failure. It is the "
        "designed behaviour of an asymmetric cluster — no two placements can "
        "be isomorphic — and it is in the grid so the number gets reported "
        "rather than avoided, exactly as `graph-toy-asym` does at toy scale. "
        "The boundary of where the contribution applies is a result about the "
        "contribution."
    )
    out.append("")
    out.append(
        "`excluded_by_scope` counts representatives the enumeration cap "
        f"(`--max-embeddings-per-template {args.max_embeddings_per_template}`) "
        "or the scope rules put out of reach. **They are not infeasible** — "
        "they were not judged, and the five states never merge."
    )

    out += ["", "## Reproducing", ""]
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("python experiments/scripts/e_g6_traces.py   # the three load levels")
    out.append("bash experiments/scripts/e_g6_run.sh")
    out.append("```")
    out.append("")
    out.append(
        "The nine clusters are **not committed**. They are regenerated from "
        f"`graphsearch/synth/cluster_gen.py` with seed {args.seed} and the "
        "arguments in the `cluster` column's path, byte for byte — which is "
        "what `tests/test_cluster_gen.py` pins. Committing them would be "
        "committing a derived artefact that can drift from its generator."
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g6_scale.md")
    parser.add_argument("--json-out", default="outputs/e_g6/scale.json")
    parser.add_argument("--synth-root", default="outputs/e_g6/clusters")
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--devices", type=int, nargs="+", default=list(DEVICE_COUNTS))
    parser.add_argument(
        "--only-symmetry", type=float, nargs="+", default=list(SYMMETRIES)
    )
    parser.add_argument("--max-devices", type=int, default=2)
    parser.add_argument("--max-embeddings-per-template", type=int, default=64)
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--no-search", action="store_true")
    parser.add_argument(
        "--load-outlier", type=float, default=2.0,
        help=(
            "how far above the run's OWN median load a cell may sit before "
            "its timings are marked as taken under contention. Relative, not "
            "absolute, because the baseline is a property of the box: this "
            "one carries a constant ~6-core neighbour, so an absolute "
            "threshold would mark every cell and a threshold that always "
            "fires is as useless as one that never does. What distorts the "
            "CURVE is a transient that hits some cells and not others."
        ),
    )
    parser.add_argument(
        "--jobs", type=int, default=1,
        help=(
            "run this many cells concurrently. DEFAULT 1, and that is not "
            "laziness: the wall-time columns are E-G6's product, and cells "
            "sharing a machine contend for memory bandwidth unevenly -- the "
            "128-device cell takes more than the 32-device one, so the CURVE "
            "distorts rather than merely shifting. Raise it to fill a box "
            "when you want the counts (embeddings, representatives, ratio, "
            "excluded_by_scope) and not the times; every row then records "
            "`timings_are_serial: false` and the report says so."
        ),
    )
    parser.add_argument("--no-enable-pd", dest="enable_pd", action="store_false")
    parser.add_argument(
        "--from-json", default=None,
        help=(
            "re-render the report from a previous run's --json-out and "
            "measure nothing. The load classification happens at report time, "
            "so a change to it costs seconds rather than another grid."
        ),
    )
    args = parser.parse_args(argv)

    if args.from_json:
        rows = json.loads(Path(args.from_json).read_text())
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        report = markdown(rows, args)
        out.write_text(report + "\n")
        _say(f"re-rendered {len(rows)} cell(s) from {args.from_json}; nothing ran")
        return 0

    cells = [
        (devices, symmetry)
        for devices in sorted(args.devices)
        for symmetry in sorted(args.only_symmetry)
    ]
    if args.jobs > 1:
        # Every cell is independent, so this is a straight win in throughput
        # and a loss in what the timings MEAN -- see `--jobs`' help. The
        # condition is recorded in every row rather than left for a reader to
        # infer from a suspiciously flat curve.
        _say(
            f"running {len(cells)} cells on {args.jobs} processes; the timing "
            f"columns are NOT comparable with a serial run"
        )
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            rows = list(pool.map(_cell_star, [(args, d, s) for d, s in cells]))
    else:
        rows = [one_cell(args, devices, symmetry) for devices, symmetry in cells]

    for row in rows:
        row["jobs"] = args.jobs
        row["timings_are_serial"] = args.jobs == 1

    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = markdown(rows, args)
    out.write_text(report + "\n")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
