"""E-G1b: top-K against a spec that binds -- heteropilot's surrogate vs this search.

**MockPredictor results. Not performance numbers.** Every figure below comes
from a deterministic mock that respects the same physics as the bounds -- which
is what makes an oracle disagreement mean something -- but no number here is a
measurement or a simulation of any hardware.

E-G1 runs with a roomy TTFT so its rows measure the search rather than the toy
SLO, and that makes it useless for a top-K comparison: when everything is
feasible, a ranker that picks four at random has perfect recall. This runs the
same corpus against `graph-toy-llama31-8b-tight.yaml`, where a quarter of the
placements meet the TTFT and the TPOT splits the rest on a second axis.

Arms, one predictor, one oracle:

    oracle                    every placement evaluated. No compression, no
                              bounds, no top-K. The denominator.
    heteropilot               `planner.optimizer.exhaustive.search` with its
                              own `BinnedRooflineRanker` and `top_k in {4,8,16}`.
    graphsearch               `AdaptiveSearch` with the `service_margin` ranker
                              (corrected in G15) and `k_schedule` truncated to
                              the same K.
    graphsearch (v1)          the same search with `service_margin_v1`, the
                              pre-G15 estimate, kept as the baseline. The
                              "before G15" section at the bottom is this arm,
                              recomputed rather than pasted so it stays true.

`first_feasible_at_sim` is the ordinal of the simulation that first produced a
candidate the run ended up calling feasible: 1 means the ranker's first pick
was an answer, and `-` means the run never found one. It is recorded by the
same counting predictor in both arms, so the two columns are comparable even
though the arms disagree about what a candidate is.

**The recall column is generous to heteropilot, deliberately.** heteropilot
ranks and judges TEMPLATES; it has no way to say which devices a candidate
runs on, so one verdict has to stand for every placement of that template.
Crediting it with all of them is the most favourable reading available, and it
is the reading used here -- the point of the comparison is not to win it on a
technicality. Where that credit is unearned is exactly what E-G1's shared-NIC
row now shows separately.

The table-building functions are imported by `e_g2_topk_holdout.py`, which runs
the same comparison on fixtures the G15 diagnosis never saw.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import (  # noqa: E402
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)
from planner.optimizer.exhaustive import search  # noqa: E402
from planner.optimizer.surrogate import BinnedRooflineRanker  # noqa: E402
from planner.spec import load_service_spec  # noqa: E402

from graphsearch.adaptive import (  # noqa: E402
    AdaptiveConfig,
    AdaptiveSearch,
    build_ranker,
)
from graphsearch.bounds import BoundPolicy, prune  # noqa: E402
from graphsearch.cost import cost_of_devices  # noqa: E402
from graphsearch.embeddings import enumerate_embeddings  # noqa: E402
from graphsearch.equivalence import CompressionPolicy, compress  # noqa: E402
from graphsearch.oracle import bind_predictor, run_oracle  # noqa: E402
from graphsearch.ranker import DEFAULT_RANKER_VARIANT, RANKER_V1  # noqa: E402
from graphsearch.schema import build_resource_graph  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"
SPEC = FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml"

BANNER = (
    "> **MockPredictor results. Not performance numbers.** Every figure here "
    "comes from a deterministic mock that respects the same physics as the "
    "bounds; none of it is a measurement or a simulation of any hardware."
)

CLUSTERS: dict[str, Path] = {
    "graph-toy-abcde": FIXTURES / "clusters/graph-toy-abcde.v2.yaml",
    "graph-toy-shared-nic": FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml",
}

K_VALUES = (4, 8, 16)


class CountingPredictor:
    """Wraps the mock and records the ordinal of each candidate's simulation.

    A proxy rather than a subclass because both arms have to be measured by
    the same instrument, and `search()` and `AdaptiveSearch` reach for
    different parts of the predictor's surface.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.order: dict[str, int] = {}
        self.calls = 0

    def predict(self, candidate, *args, **kw):
        self.calls += 1
        self.order.setdefault(candidate.id, self.calls)
        return self._inner.predict(candidate, *args, **kw)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def mock():
    from tests.graph_fixtures import GraphAwareMockPredictor

    return CountingPredictor(GraphAwareMockPredictor())


def first_feasible(predictor: CountingPredictor, ids) -> int | None:
    ordinals = [predictor.order[i] for i in ids if i in predictor.order]
    return min(ordinals) if ordinals else None


def world(path: Path, spec_path: Path, profiles_root: Path | None = None):
    spec = load_service_spec(spec_path)
    cluster = load_cluster_spec(path)
    profiles = load_profiles_for(cluster, profiles_root or ROOT)
    islands = detect_islands(cluster, profiles)
    graph = build_resource_graph(cluster, profiles)
    return spec, cluster, profiles, islands, graph


def templates_of(spec, cluster, islands, profiles, limit: int):
    generated = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=True,
    ).generate()
    return [c for c in generated.candidates if c.total_devices <= limit]


def oracle_arm(spec, cluster, profiles, islands, graph, templates):
    predictor = mock()
    result = run_oracle(
        spec, cluster, {i.id: i for i in islands}, profiles, predictor,
        graph=graph, templates=templates,
    )
    # A fixture with an unpriced device yields `None` costs (heterogeneous-lab
    # carries no `price_per_hour_usd`); regret is then uncomputed, not zero.
    costs = [
        result.cost[i] for i in result.feasible_ids
        if result.cost.get(i) is not None
    ]
    return result, predictor, (min(costs) if costs else None)


def _template_cost(output, oracle, graph) -> float | None:
    """What heteropilot's recommendation would cost, read most favourably.

    Its recommendation names a TEMPLATE, not devices, so it is priced as the
    cheapest placement of that template -- the best case available to an arm
    that cannot choose one. Both arms are priced by the same function, because
    a regret computed from two different cost models is not a regret.
    """
    if output.recommended is None:
        return None
    template_id = output.recommended.plan.candidate.id
    costs = [
        cost_of_devices(e.devices, graph).total_usd_per_hour
        for e in oracle.embeddings
        if e.template.id == template_id
    ]
    priced = [c for c in costs if c is not None]
    return min(priced) if priced else None


def _embedding_cost(output, oracle, graph) -> float | None:
    """What this search's recommendation costs: it named the devices."""
    if output.recommended is None:
        return None
    chosen = output.recommended.plan.candidate.id
    for embedding in oracle.embeddings:
        if embedding.id == chosen:
            return cost_of_devices(embedding.devices, graph).total_usd_per_hour
    return None


def heteropilot_arm(spec, cluster, profiles, islands, graph, oracle, k: int):
    """heteropilot's own surrogate and top-K, judging templates."""
    predictor = mock()
    captured: dict = {}

    def on_evaluation(result, candidates) -> None:
        captured["feasible"] = [p.candidate.id for p in result.feasible_plans]

    output = search(
        spec, cluster, islands, profiles, predictor,
        enable_bound_pruning=False, enable_pd=True,
        surrogate=BinnedRooflineRanker(), top_k=k,
        on_evaluation=on_evaluation,
    )
    feasible_templates = set(captured.get("feasible", []))

    # One template verdict credited to every placement of it -- the most
    # favourable reading available to an arm that cannot name a placement.
    reached = {
        e.id
        for e in oracle.embeddings
        if e.template.id in feasible_templates
    }
    return {
        "reached": reached,
        "simulations": predictor.calls,
        "best_cost": _template_cost(output, oracle, graph),
        "first_feasible_at_sim": first_feasible(predictor, feasible_templates),
    }


def graphsearch_arm(
    spec, cluster, profiles, islands, graph, oracle, k: int, *, variant: str
):
    predictor = mock()
    by_id = {i.id: i for i in islands}
    templates = list({e.template.id: e.template for e in oracle.embeddings}.values())
    embeddings, stats = enumerate_embeddings(templates, by_id, graph, spec)
    representatives, _, report = compress(embeddings, graph, CompressionPolicy())
    verdicts, rejections = prune(
        representatives, spec, graph, by_id, profiles, stats, policy=BoundPolicy()
    )
    search_ = AdaptiveSearch(
        spec, cluster, by_id, profiles, predictor,
        graph=graph, representatives=representatives, verdicts=verdicts,
        ranker=build_ranker(
            representatives, spec, graph, by_id, profiles, variant=variant
        ),
        config=AdaptiveConfig(k_schedule=(k,)),
        embedding_stats=stats, compression=report, bound_rejections=rejections,
        bind_embeddings=lambda batch: bind_predictor(
            predictor, list(batch.values()), graph,
            spec=spec, cluster=cluster, islands=by_id, profiles=profiles,
        ),
        embedded_pd_cost=True,
    )
    output, audit = search_.run()

    feasible_exemplars = set(audit.feasible_ids)
    reached: set[str] = set()
    for representative in representatives:
        if representative.exemplar.id in feasible_exemplars:
            reached |= {e.id for e in representative.embeddings}
    return {
        "reached": reached,
        "simulations": audit.simulations_run,
        "best_cost": _embedding_cost(output, oracle, graph),
        "first_feasible_at_sim": first_feasible(predictor, feasible_exemplars),
    }


def row(fixture: str, arm: str, k: int, result: dict, oracle, oracle_best) -> dict:
    feasible = oracle.feasible_ids
    recall = (
        1.0 if not feasible else len(result["reached"] & feasible) / len(feasible)
    )
    regret = None
    if oracle_best not in (None, 0) and result["best_cost"] is not None:
        regret = (result["best_cost"] - oracle_best) / abs(oracle_best)
    return {
        "fixture": fixture,
        "arm": arm,
        "k": k,
        "simulations": result["simulations"],
        "feasible_recall": round(recall, 4),
        "cost_regret": None if regret is None else round(regret, 6),
        "first_feasible_at_sim": result["first_feasible_at_sim"],
    }


ARM_LABEL = {DEFAULT_RANKER_VARIANT: "graphsearch", RANKER_V1: "graphsearch (v1)"}


def run(
    fixture: str,
    path: Path,
    spec_path: Path,
    limit: int,
    *,
    variants: Sequence[str] = (DEFAULT_RANKER_VARIANT,),
    profiles_root: Path | None = None,
) -> tuple[list[dict], tuple[int, int]]:
    """Every arm on one fixture. Returns the rows and (feasible, total)."""
    spec, cluster, profiles, islands, graph = world(path, spec_path, profiles_root)
    templates = templates_of(spec, cluster, islands, profiles, limit)
    oracle, oracle_predictor, oracle_best = oracle_arm(
        spec, cluster, profiles, islands, graph, templates
    )
    rows = [
        {
            "fixture": fixture,
            "arm": "oracle",
            "k": len(oracle.embeddings),
            "simulations": oracle.simulations,
            "feasible_recall": 1.0,
            "cost_regret": 0.0 if oracle_best is not None else None,
            "first_feasible_at_sim": first_feasible(
                oracle_predictor, oracle.feasible_ids
            ),
        }
    ]
    for k in K_VALUES:
        rows.append(
            row(
                fixture, "heteropilot", k,
                heteropilot_arm(spec, cluster, profiles, islands, graph, oracle, k),
                oracle, oracle_best,
            )
        )
        for variant in variants:
            rows.append(
                row(
                    fixture, ARM_LABEL[variant], k,
                    graphsearch_arm(
                        spec, cluster, profiles, islands, graph, oracle, k,
                        variant=variant,
                    ),
                    oracle, oracle_best,
                )
            )
    return rows, (len(oracle.feasible_ids), len(oracle.embeddings))


COLUMNS = [
    "fixture", "arm", "k", "simulations", "feasible_recall",
    "cost_regret", "first_feasible_at_sim",
]


def table(rows: Sequence[Mapping]) -> list[str]:
    def cell(value) -> str:
        return "-" if value is None else str(value)

    out = ["| " + " | ".join(COLUMNS) + " |"]
    out.append("| " + " | ".join("---" for _ in COLUMNS) + " |")
    for r in rows:
        out.append("| " + " | ".join(cell(r.get(c)) for c in COLUMNS) + " |")
    return out


def corpus_notes(feasible_counts: Mapping[str, tuple[int, int]]) -> list[str]:
    out = ["## The corpus", ""]
    for fixture, (feasible, total) in sorted(feasible_counts.items()):
        share = 0.0 if not total else feasible / total
        out.append(
            f"- **{fixture}**: {feasible} of {total} placements meet both SLOs "
            f"({share:.1%}). A top-K row is worth reading only because this is "
            f"not 100%."
        )
    return out


def reading_notes() -> list[str]:
    return [
        "## Reading the table",
        "",
        "`feasible_recall` is over PLACEMENTS in both arms, and the "
        "heteropilot rows are credited generously: that arm ranks and judges "
        "templates, so one verdict is allowed to stand for every placement of "
        "the template. It cannot name a placement, so there is no stricter "
        "reading that would be fair to it.",
        "",
        "`first_feasible_at_sim` is the ordinal of the simulation that first "
        "produced a candidate the run ended up calling feasible. `1` means the "
        "ranker's first pick was an answer; `-` means the run never found one. "
        "The same counting predictor records it in both arms.",
        "",
        "A `cost_regret` of `-` means the run recommended nothing, or the "
        "fixture priced nothing the objective could score. It is not a zero -- "
        "a regret that cannot be computed is reported as uncomputed.",
        "",
        "`simulations` is not comparable to `k` directly: heteropilot "
        "simulates at most `top_k` TEMPLATES, this search simulates at most "
        "`k` REPRESENTATIVES, and a representative stands for a class of "
        "placements whose size is in E-G1's compression column.",
    ]


def markdown(rows: list[dict], feasible_counts: dict[str, tuple[int, int]]) -> str:
    current = [r for r in rows if r["arm"] != ARM_LABEL[RANKER_V1]]
    before = [r for r in rows if r["arm"] in ("oracle", "heteropilot", ARM_LABEL[RANKER_V1])]

    out = ["# E-G1b — top-K, against a spec that binds", "", BANNER, ""]
    out += table(current)
    out.append("")
    out += corpus_notes(feasible_counts)
    out.append("")
    out.append("## Reproducing")
    out.append("")
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("python experiments/scripts/e_g1b_topk.py \\")
    out.append("    --out experiments/results/e_g1b_topk.md")
    out.append("```")
    out.append("")
    out.append("## What the columns say")
    out.append("")
    out.append(
        "**The heteropilot arm plateaus.** Its recall stops at 0.5 on both "
        "fixtures and does not move between k=8 and k=16. The reason is "
        "structural rather than a matter of ranking: the arm judges templates, "
        "and half the feasible placements here belong to templates whose other "
        "placements are not feasible. One verdict cannot be right about both, "
        "and the generous credit this table already gives it is what keeps the "
        "number as high as 0.5."
    )
    out.append("")
    out.append(
        "**The graphsearch rows are the corrected ranker** (`service_margin`, "
        "G15). Before the correction this search recommended nothing at k=4 on "
        "both fixtures; the diagnosis is `e_g2_ranker_diagnosis.md`, the "
        "holdout check is `e_g2_topk_holdout.md`, and the pre-correction table "
        "is kept below -- recomputed on every run with `service_margin_v1` "
        "rather than pasted, so it cannot drift from what that ranker does."
    )
    out.append("")
    out += reading_notes()
    out.append("")
    out.append("## Before G15 — `service_margin_v1`")
    out.append("")
    out.append(
        "The same oracle and heteropilot rows, with the pre-G15 estimate in "
        "the graphsearch arm. This is the table E-G1b first shipped with, "
        "recomputed."
    )
    out.append("")
    out += table(before)
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g1b_topk.md")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    rows: list[dict] = []
    counts: dict[str, tuple[int, int]] = {}
    for name, path in CLUSTERS.items():
        if args.only and args.only != name:
            continue
        fixture_rows, counts[name] = run(
            name, path, SPEC, args.limit,
            variants=(DEFAULT_RANKER_VARIANT, RANKER_V1),
        )
        rows.extend(fixture_rows)

    text = markdown(rows, counts)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
