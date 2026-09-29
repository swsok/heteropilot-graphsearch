"""E-G7 P5.3: the baselines, on the same candidate space, predictor and cache.

**MockPredictor results. Not performance numbers.** Every figure comes from a
deterministic mock; none of it is a measurement or a simulation of any hardware.

A comparison is only worth reading if the arms were asked the same question. So
all four run over the same generated candidates, through the same predictor
instance type, with the same spec:

    oracle          heteropilot's `exhaustive.oracle()` -- every candidate
                    simulated, bound pruning off. The denominator.
    surrogate_topk  `exhaustive.search(surrogate=BinnedRooflineRanker,
                    top_k=K)`. heteropilot's own top-K, its own ranker.
    greedy          `optimizer.greedy.greedy()` -- the single candidate a
                    greedy planner picks, then simulates. One simulation.
    graphsearch     `AdaptiveSearch` at the same K.

**Two things are said out loud rather than buried, and both favour the
baseline.**

1. **heteropilot ranks and judges TEMPLATES.** It cannot name which devices a
   candidate runs on, so one verdict has to stand for every placement of that
   template. Crediting it with all of them is the most favourable reading
   available and it is the reading used here. There is no stricter reading that
   would be fair to it, and winning on that technicality would not be winning.

2. **`greedy` gets one simulation and is not being beaten for it.** It is in
   the table as the floor -- what you get without any search at all -- not as a
   contender. A method that needs 16 simulations to beat a method that needs 1
   has to say so.

The last section reproduces heteropilot's own documented top-K failures rather
than citing them: `docs/surrogate_topk_regret.md` records cases false-infeasible
all the way to K=50. A baseline's weakness quoted from its own repository is not
evidence; run here, on this corpus, it is.

    python experiments/scripts/e_g7_baseline_fairness.py \\
        --out experiments/results/e_g7_baseline_fairness.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

import e_g1b_topk as base  # noqa: E402  (same directory as this script)
from planner.optimizer.greedy import greedy  # noqa: E402
from planner.optimizer.surrogate import BinnedRooflineRanker  # noqa: E402

from graphsearch.oracle import run_oracle  # noqa: E402
from graphsearch.ranker import DEFAULT_RANKER_VARIANT  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"

BANNER = base.BANNER

CLUSTERS = {
    "graph-toy-abcde": FIXTURES / "clusters/graph-toy-abcde.v2.yaml",
    "graph-toy-shared-nic": FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml",
}

#: heteropilot's own documented ceiling. `docs/surrogate_topk_regret.md`
#: records efficiency-ordered rankers false-infeasible "to K=50" at 20 rps on
#: both of its fixtures, so the sweep has to reach that far to reproduce the
#: shape rather than stopping where the baseline still looks fine.
K_VALUES = (4, 8, 16, 30, 50)


def _say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def greedy_arm(spec, cluster, profiles, islands, graph, templates, oracle) -> dict:
    """What a greedy planner picks, and whether the oracle agrees it works.

    One simulation, by construction. It is the floor the whole exercise is
    measured against: if a search that costs sixteen simulations cannot beat
    the one that costs one, the search is not worth its budget.
    """
    # No predictor: `greedy` only RANKS, and every metric its pick needs is
    # already in the oracle. Instantiating one would be a prop suggesting a
    # simulation that never happens.
    #
    # `base.world` hands islands back as a LIST (that is what
    # `CandidateGenerator` wants); `greedy.estimate` subscripts them by id.
    by_id = {island.id: island for island in islands}
    choice = greedy(list(templates), spec, by_id, profiles)
    if choice is None:
        return {"reached": set(), "simulations": 0, "best_cost": None,
                "first_feasible_at_sim": None}

    # `greedy` names a TEMPLATE, so it is credited with every placement of it,
    # the same generosity the surrogate arm gets.
    reached = {
        embedding.id
        for embedding in oracle.embeddings
        if embedding.template.id == choice.id
    }
    feasible = reached & oracle.feasible_ids
    priced = [
        oracle.cost[i] for i in feasible if oracle.cost.get(i) is not None
    ]
    return {
        "reached": reached,
        "simulations": 1,
        "best_cost": min(priced) if priced else None,
        "first_feasible_at_sim": 1 if feasible else None,
        "picked": choice.id,
    }


def run_fixture(fixture: str, path: Path, spec_path: Path, args) -> list[dict]:
    spec, cluster, profiles, islands, graph = base.world(path, spec_path, None)
    templates = base.templates_of(spec, cluster, islands, profiles, args.limit)
    oracle, _oracle_predictor, oracle_best = base.oracle_arm(
        spec, cluster, profiles, islands, graph, templates
    )

    rows = [
        base.row(
            fixture, "oracle", len(oracle.embeddings),
            {
                "reached": set(oracle.feasible_ids),
                "simulations": oracle.simulations,
                "best_cost": oracle_best,
                "first_feasible_at_sim": None,
            },
            oracle, oracle_best,
        )
    ]

    _say(f"{fixture}: greedy")
    rows.append(
        base.row(
            fixture, "greedy", 1,
            greedy_arm(
                spec, cluster, profiles, islands, graph, templates, oracle
            ),
            oracle, oracle_best,
        )
    )

    for k in args.k_values:
        _say(f"{fixture}: surrogate_topk k={k}")
        rows.append(
            base.row(
                fixture, "surrogate_topk", k,
                base.heteropilot_arm(
                    spec, cluster, profiles, islands, graph, oracle, k
                ),
                oracle, oracle_best,
            )
        )
        _say(f"{fixture}: graphsearch k={k}")
        rows.append(
            base.row(
                fixture, "graphsearch", k,
                base.graphsearch_arm(
                    spec, cluster, profiles, islands, graph, oracle, k,
                    variant=DEFAULT_RANKER_VARIANT,
                ),
                oracle, oracle_best,
            )
        )
    return rows


def missed_at_k50(rows: list[dict]) -> list[str]:
    """heteropilot's documented failure, reproduced on this corpus.

    `docs/surrogate_topk_regret.md` records efficiency-ordered rankers
    false-infeasible to K=50. Reproducing it here rather than citing it is the
    point: a baseline's weakness quoted from its own repository is not
    evidence, because nobody can check whether it survives a different corpus.
    """
    out: list[str] = []
    for fixture in sorted({r["fixture"] for r in rows}):
        at50 = [
            r
            for r in rows
            if r["fixture"] == fixture
            and r["arm"] == "surrogate_topk"
            and r["k"] == 50
        ]
        if not at50:
            continue
        row = at50[0]
        ours = [
            r
            for r in rows
            if r["fixture"] == fixture and r["arm"] == "graphsearch" and r["k"] == 50
        ]
        mine = ours[0] if ours else None
        out.append(
            f"- **{fixture}** — at K=50 the surrogate reaches recall "
            f"{row['feasible_recall']}"
            + (
                f", this search {mine['feasible_recall']}."
                if mine
                else "."
            )
        )
        if row["feasible_recall"] < 1.0:
            out.append(
                "  Still short of the oracle at K=50, which is the shape "
                "`surrogate_topk_regret.md` describes -- reproduced here "
                "rather than cited."
            )
    return out


def markdown(rows: list[dict], args) -> str:
    out = ["# E-G7 — baseline fairness", "", BANNER, ""]
    out.append(
        "All arms run over the same generated candidates, the same predictor "
        "and the same spec. A comparison is only worth reading if the arms "
        "were asked the same question."
    )
    out.append("")
    out += base.table(rows)

    out += ["", "## Where the scoring favours the baseline, deliberately", ""]
    out.append(
        "**heteropilot ranks and judges TEMPLATES.** It cannot name which "
        "devices a candidate runs on, so one verdict stands for every "
        "placement of that template, and every one of them is credited to it. "
        "That is the most favourable reading available and it is the one used "
        "here. There is no stricter reading that would be fair to it, and "
        "winning on that technicality would not be winning."
    )
    out.append("")
    out.append(
        "`greedy` gets **one** simulation and is not being beaten for it. It "
        "is the floor — what a planner gets without any search at all — not a "
        "contender. A method that needs sixteen simulations to beat a method "
        "that needs one has to say so, and this table does."
    )

    reproduced = missed_at_k50(rows)
    if reproduced:
        out += ["", "## heteropilot's own K=50 gap, reproduced", ""]
        out.append(
            "`vendor/heteropilot/docs/surrogate_topk_regret.md` records "
            "efficiency-ordered rankers false-infeasible all the way to K=50 "
            "on both of its fixtures. Run here, on this corpus:"
        )
        out.append("")
        out += reproduced
        out.append("")
        out.append(
            "Reproduced rather than cited on purpose. A baseline's weakness "
            "quoted from its own repository is not evidence — nobody can "
            "check whether it survives a different corpus, and the obvious "
            "suspicion is that it was quoted because it was convenient."
        )

    out += ["", "## Reproducing", ""]
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("python experiments/scripts/e_g7_baseline_fairness.py \\")
    out.append(f"    --out {args.out}")
    out.append("```")
    out.append("")
    out += base.reading_notes()
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default="experiments/results/e_g7_baseline_fairness.md"
    )
    parser.add_argument("--json-out", default="outputs/e_g7/baseline.json")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--only", default=None)
    parser.add_argument(
        "--k-values", type=int, nargs="+", default=list(K_VALUES)
    )
    args = parser.parse_args(argv)

    assert BinnedRooflineRanker is not None and run_oracle is not None
    spec_path = FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml"
    rows: list[dict] = []
    for fixture, path in CLUSTERS.items():
        if args.only and args.only != fixture:
            continue
        rows.extend(run_fixture(fixture, path, spec_path, args))

    text = markdown(rows, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(rows, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
