"""E-G1: what the compression and the adaptive search buy, on the toy fixtures.

**MockPredictor results. Not performance numbers.** Every figure below is
produced by a deterministic mock that respects the same physics as the bounds
-- which is what makes an oracle disagreement mean something -- but no number
here is a measurement or a simulation of any hardware. This is why the run
writes its own banner into the report and why heteropilot's `docs/CLAIMS.md`
does not carry these.

What the table is for: `correct` must be True on every row, and it is the
column to read first. `representatives / embeddings` is the compression, and
`proposed / oracle simulations` is what that compression saved.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import (  # noqa: E402
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)
from planner.optimizer.surrogate import BinnedRooflineRanker  # noqa: E402
from planner.spec import Objective, load_service_spec  # noqa: E402

from graphsearch.oracle import compare, run_oracle, run_proposed, table_row  # noqa: E402
from graphsearch.schema import build_resource_graph  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"

BANNER = (
    "> **MockPredictor results. Not performance numbers.** Every figure here "
    "comes from a deterministic mock that respects the same physics as the "
    "bounds; none of it is a measurement or a simulation of any hardware. "
    "`correct` is the column to read first."
)

CLUSTERS = {
    "graph-toy-abcde": FIXTURES / "clusters/graph-toy-abcde.v2.yaml",
    "graph-toy-shared-nic": FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml",
    "graph-toy-asym": FIXTURES / "clusters/graph-toy-asym.v2.yaml",
    "heterogeneous-lab": paths_root.HETEROPILOT_ROOT
    / "examples/clusters/heterogeneous-lab.yaml",
}


def predictor():
    from tests.graph_fixtures import GraphAwareMockPredictor

    return GraphAwareMockPredictor()


def service_spec(name: str):
    if name == "heterogeneous-lab":
        path = paths_root.HETEROPILOT_ROOT / "examples/service_specs/llama31-8b.yaml"
    else:
        path = FIXTURES / "service_specs/graph-toy-llama31-8b.yaml"
    spec = load_service_spec(path)
    # A roomy TTFT so the row measures the SEARCH, not whether the toy SLO is
    # reachable -- an all-infeasible corpus makes recall and regret vacuous.
    return spec.model_copy(
        update={
            "slo": spec.slo.model_copy(
                update={"ttft": spec.slo.ttft.model_copy(update={"max_ms": 1e6})}
            ),
            "objective": spec.objective.model_copy(
                update={
                    "primary": Objective.MINIMIZE_COST_PER_HOUR, "secondary": None
                }
            ),
        }
    )


def one(name: str, path: Path, limit: int) -> dict:
    spec = service_spec(name)
    cluster = load_cluster_spec(path)
    root = paths_root.HETEROPILOT_ROOT if name == "heterogeneous-lab" else ROOT
    profiles = load_profiles_for(cluster, root)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)
    generated = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=True,
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= limit]

    oracle = run_oracle(
        spec, cluster, by_id, profiles, predictor(),
        graph=graph, templates=templates,
    )
    proposed = run_proposed(
        spec, cluster, by_id, profiles, predictor(),
        graph=graph, templates=templates,
    )
    comparison = compare(oracle, proposed)
    ratio = (
        len(proposed.representatives) / len(oracle.embeddings)
        if oracle.embeddings
        else None
    )
    return table_row(
        name,
        comparison,
        {
            "templates": len(templates),
            "embeddings": len(oracle.embeddings),
            "representatives": len(proposed.representatives),
            "compression_ratio": None if ratio is None else round(ratio, 4),
        },
    )


def markdown(rows: list[dict]) -> str:
    columns = [
        "fixture", "templates", "embeddings", "representatives",
        "compression_ratio", "oracle_simulations", "proposed_simulations",
        "feasible_recall", "cost_regret", "false_infeasible",
        "mismerged_pairs", "correct",
    ]

    def cell(row: dict, key: str) -> str:
        value = row.get(key)
        if isinstance(value, list):
            return str(len(value))
        return "-" if value is None else str(value)

    out = ["# E-G1 — toy pilot", "", BANNER, ""]
    out.append("| " + " | ".join(columns) + " |")
    out.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        out.append("| " + " | ".join(cell(row, c) for c in columns) + " |")
    out.append("")
    out.append("## Reproducing")
    out.append("")
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("python experiments/scripts/e_g1_toy_pilot.py \\")
    out.append("    --out experiments/results/e_g1_toy_pilot.md")
    out.append("```")
    out.append("")
    out.append("## Reading the table")
    out.append("")
    out.append(
        "`correct` first: it is `false_infeasible == 0 and mismerged_pairs == 0`, "
        "and a False there is a bound or an equivalence being wrong, never a "
        "tuning issue."
    )
    out.append("")
    out.append(
        "A `compression_ratio` of 1.0 means exact equivalence folded nothing, "
        "and each row has its own reason:"
    )
    out.append("")
    out.append(
        "- **graph-toy-asym** is the designed failure condition. Five nodes, no "
        "two alike in price, uplink capacity or reservation, so no two "
        "placements can be isomorphic. It is in the corpus precisely so this "
        "number gets reported rather than avoided."
    )
    out.append(
        "- **graph-toy-shared-nic** is the counterexample fixture, and its row "
        "is the one that changed. It used to read `ratio 1.0, mismerged 0` and "
        "that was the result of an input with no counterexample in it: the "
        "fixture had two nodes and `enable_pd` was never set, so no flow a "
        "latency target charges for ever crossed an uplink. It now has three "
        "nodes -- X with 6 of its 10 GB/s held, Y and Z free -- and both GPUs "
        "wired to the NIC, so `P on X -> D on Z` and `P on Y -> D on Z` differ "
        "in nothing but the boundary they cross. Exact equivalence keeps them "
        "apart and folds Y with Z; `include_boundary=False` folds all three "
        "and the oracle reports the mis-merge (GS-9, retracted and replaced)."
    )
    out.append("")
    out.append(
        "`feasible_recall` is 1.0 and `cost_regret` 0.0 on every row because "
        "the K schedule defaults to every representative here. A budget makes "
        "recall fall and correctness hold -- that separation is what "
        "`tests/test_oracle_agreement.py` pins."
    )
    out.append("")
    out.append(
        "`BinnedRooflineRanker` is heteropilot's own surrogate and is run as a "
        "baseline in **E-G1b** (`experiments/results/e_g1b_topk.md`), against "
        "a copy of the toy spec whose TTFT and TPOT limits actually bind. It "
        "is not run here because a top-K comparison against a corpus where "
        "everything is feasible measures nothing."
    )
    out.append("")
    out.append(
        "A `cost_regret` of `-` is not a zero. It means the fixture priced "
        "nothing the objective could score, so the planner declined to guess "
        "rather than inventing a number -- `heterogeneous-lab` carries no "
        "`price_per_hour_usd`. A regret that cannot be computed is reported as "
        "uncomputed."
    )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g1_toy_pilot.md")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    assert BinnedRooflineRanker is not None      # the baseline exists
    rows = [
        one(name, path, args.limit)
        for name, path in CLUSTERS.items()
        if args.only is None or args.only == name
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(rows) + "\n")
    print(markdown(rows))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2) + "\n")
    return 0 if all(r["correct"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
