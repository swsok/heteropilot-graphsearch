"""E-G7 P5.2: take one piece out at a time and see what breaks.

**MockPredictor results. Not performance numbers.** Every figure comes from a
deterministic mock that respects the same physics as the bounds; none of it is
a measurement or a simulation of any hardware.

The arm that matters is **`no_boundary`**. Contribution A is that the
equivalence relation must carry the shared communication boundary, and the only
way to show a property is load-bearing is to remove it and watch the thing fall
over. So `docs/preregistration.md` registered, before this ran:

> `no_boundary` produces `mismerged_pairs > 0` where `full` shows 0. A zero
> does **not** vindicate the contribution -- it means the corpus contains no
> structure in which the counterexample is reachable, and the response is to
> re-examine the fixture selection and report contribution A as unsupported by
> these fixtures.

**This is the one arm where a non-zero `mismerged_pairs` does not stop the
run.** Its whole purpose is to produce one, by removing the property that
prevents it. Every other arm is bound by the common invariant, and a non-zero
there is a stop-and-report.

    python experiments/scripts/e_g7_ablation.py \\
        --out experiments/results/e_g7_ablation.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
from planner.plan import (  # noqa: E402
    CandidateConfig,
    IslandAssignment,
    Role,
    ServingArch,
)
from planner.spec import load_service_spec  # noqa: E402

from graphsearch.adaptive import AdaptiveConfig  # noqa: E402
from graphsearch.bounds import BoundPolicy  # noqa: E402
from graphsearch.contention import CONTENTION_MODELS  # noqa: E402
from graphsearch.equivalence import CompressionPolicy  # noqa: E402
from graphsearch.oracle import compare, run_oracle, run_proposed  # noqa: E402
from graphsearch.ranker import DEFAULT_RANKER_VARIANT, RANKER_V1  # noqa: E402
from graphsearch.schema import build_resource_graph  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"

BANNER = (
    "> **MockPredictor results. Not performance numbers.** Every figure here "
    "comes from a deterministic mock that respects the same physics as the "
    "bounds; none of it is a measurement or a simulation of any hardware."
)

CLUSTERS = {
    "graph-toy-shared-nic": FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml",
    "graph-toy-abcde": FIXTURES / "clusters/graph-toy-abcde.v2.yaml",
}


@dataclass(frozen=True)
class Arm:
    """One thing removed, and what removing it is supposed to show."""

    name: str
    what_it_removes: str
    compression: CompressionPolicy | None = None
    bounds: BoundPolicy | None = None
    ranker: str = DEFAULT_RANKER_VARIANT
    contention: str = "null"
    #: True only for `no_boundary`: the arm exists to produce a mis-merge, so
    #: one is the expected result rather than a stop-and-report.
    mismerge_expected: bool = False


ARMS = (
    Arm("full", "nothing -- the search as it ships"),
    Arm(
        "no_boundary",
        "the shared-resource boundary, from the signature",
        compression=CompressionPolicy(include_boundary=False, conflicts=False),
        mismerge_expected=True,
    ),
    Arm(
        "no_compression",
        "the folding entirely; one representative per placement",
        compression=CompressionPolicy(enabled=False, conflicts=False),
    ),
    Arm(
        "no_bounds",
        "the RELAXATIONS. compat and memory are exact checks and stay",
        bounds=BoundPolicy(comm_latency=False, throughput_capacity=False),
    ),
    Arm("ranker=service_margin_v1", "the G15 correction", ranker=RANKER_V1),
    Arm("contention=fluid", "nothing; it ADDS the fluid model", contention="fluid"),
)


MODEL = "meta-llama/Llama-3.1-8B"


def counterexample_templates(cluster, profiles, islands, graph):
    """The research design's §5 pair: `P on X -> D on Z` and `P on Y -> D on Z`.

    Two prefill pairs talking to the SAME third decode partner, so they differ
    in nothing but which uplink the KV handoff crosses -- X's has 6 of its 10
    GB/s held, Y's is free. With only X and Y a P/D candidate crosses BOTH
    uplinks whichever way it runs and there is nothing to compare, which is why
    the fixture has a nodeZ.
    """
    def island_of(node: str) -> str:
        return next(i.id for i in islands.values() if i.node_id == node)

    def pd(prefill: str) -> CandidateConfig:
        return CandidateConfig(
            id=f"pd-{prefill}-Z", model=MODEL, dtype="bfloat16",
            serving_arch=ServingArch.PD_SPLIT,
            assignments=[
                IslandAssignment(
                    island_id=island_of(prefill), role=Role.PREFILL, tp_size=2
                ),
                IslandAssignment(
                    island_id=island_of("nodeZ"), role=Role.DECODE, tp_size=2
                ),
            ],
        )

    return [pd("nodeX"), pd("nodeY")]


def contribution_a_probe(args) -> dict:
    """Does dropping the boundary fold two placements the oracle prices apart?

    **The corpus-wide arms cannot answer this, and the first version of this
    script wrongly reported that they had.** `mismerged_pairs` compares
    feasibility VERDICTS and costs, not metrics. Under the fixed tight spec
    (TTFT 50 ms) both X->Z and Y->Z are far above it, both infeasible, same
    verdict -- so `no_boundary` folded them (60 representatives became 30) and
    nothing detected it. A zero there is an artefact of the ruler, not a
    finding about the contribution, and reporting it as "contribution A
    unsupported" would have been the worst kind of wrong: an honest-looking
    negative.

    So the threshold is **derived from the oracle rather than written down**:
    run both placements under a roomy SLO, read the two TTFTs, and put the
    limit at their midpoint. That is not tuning to win. Tuning to win is moving
    a parameter until the method looks good; this is making the instrument able
    to resolve the difference at all, and the claim under test is precisely
    that a difference exists. `tests/test_oracle_agreement.py` derives it the
    same way and for the same stated reason.

    The control that makes it a test rather than a demonstration is the `full`
    arm on the SAME spec: it must show `mismerged_pairs == 0`. If the
    boundary-aware compression also mis-merged there, the finding would be
    against us and this would say so.
    """
    spec_path = FIXTURES / "service_specs/graph-toy-llama31-8b.yaml"
    roomy = load_service_spec(spec_path)
    roomy = roomy.model_copy(
        update={
            "slo": roomy.slo.model_copy(
                update={"ttft": roomy.slo.ttft.model_copy(update={"max_ms": 1e6})}
            )
        }
    )
    cluster = load_cluster_spec(CLUSTERS["graph-toy-shared-nic"])
    profiles = load_profiles_for(cluster, ROOT)
    islands = {i.id: i for i in detect_islands(cluster, profiles)}
    graph = build_resource_graph(cluster, profiles)
    templates = counterexample_templates(cluster, profiles, islands, graph)

    survey = run_oracle(
        roomy, cluster, islands, profiles, mock(),
        graph=graph, templates=templates,
    )
    ttfts = {
        plan.candidate.id: plan.predicted.p99_ttft_ms
        for plan in survey.plans.values()
    }
    if len(ttfts) != 2:
        return {"reachable": False, "why": f"expected 2 placements, got {len(ttfts)}"}
    ordered = sorted(ttfts.values())
    if ordered[0] >= ordered[1]:
        return {
            "reachable": False,
            "why": (
                f"the contended uplink cost nothing: both TTFTs are {ordered}. "
                f"The result hook that prices the handoff over its own path is "
                f"not bound, so there is no difference for the boundary to keep."
            ),
        }

    separating = (ordered[0] + ordered[1]) / 2
    tight = roomy.model_copy(
        update={
            "slo": roomy.slo.model_copy(
                update={
                    "ttft": roomy.slo.ttft.model_copy(update={"max_ms": separating})
                }
            )
        }
    )
    oracle = run_oracle(
        tight, cluster, islands, profiles, mock(),
        graph=graph, templates=templates,
    )
    sighted = run_proposed(
        tight, cluster, islands, profiles, mock(),
        graph=graph, templates=templates,
        compression_policy=CompressionPolicy(conflicts=False),
    )
    blind = run_proposed(
        tight, cluster, islands, profiles, mock(),
        graph=graph, templates=templates,
        compression_policy=CompressionPolicy(
            include_boundary=False, conflicts=False
        ),
    )
    return {
        "reachable": True,
        "ttft_ms": {k: round(v, 4) for k, v in sorted(ttfts.items())},
        "separating_ttft_ms": round(separating, 4),
        "representatives_full": len(sighted.representatives),
        "representatives_no_boundary": len(blind.representatives),
        "mismerged_full": [
            list(p) for p in sorted(compare(oracle, sighted).mismerged_pairs)
        ],
        "mismerged_no_boundary": [
            list(p) for p in sorted(compare(oracle, blind).mismerged_pairs)
        ],
        "feasible_ids": sorted(oracle.feasible_ids),
    }


def _say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def mock():
    sys.path.insert(0, str(ROOT))
    from tests.graph_fixtures import GraphAwareMockPredictor

    return GraphAwareMockPredictor()


def world(path: Path, spec_path: Path, limit: int):
    spec = load_service_spec(spec_path)
    cluster = load_cluster_spec(path)
    profiles = load_profiles_for(cluster, ROOT)
    islands = detect_islands(cluster, profiles)
    graph = build_resource_graph(cluster, profiles)
    generated = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=True,
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= limit]
    return spec, cluster, profiles, {i.id: i for i in islands}, graph, templates


def run_arm(arm: Arm, fixture: str, path: Path, spec_path: Path, args) -> dict:
    _say(f"{fixture} / {arm.name}")
    spec, cluster, profiles, islands, graph, templates = world(
        path, spec_path, args.limit
    )

    # The oracle is the SAME in every arm: it has no compression, no bounds and
    # no ranker to ablate. Re-running it per arm would only add noise, but it
    # must be re-run per FIXTURE because the corpus differs.
    oracle = run_oracle(
        spec, cluster, islands, profiles, mock(), graph=graph, templates=templates
    )
    proposed = run_proposed(
        spec, cluster, islands, profiles, mock(),
        graph=graph, templates=templates,
        compression_policy=arm.compression,
        bound_policy=arm.bounds,
        ranker_variant=arm.ranker,
        contention=CONTENTION_MODELS[arm.contention],
        config=AdaptiveConfig(k_schedule=(args.k,)),
    )
    comparison = compare(oracle, proposed)
    audit = proposed.audit
    ratio = (
        len(proposed.representatives) / len(oracle.embeddings)
        if oracle.embeddings
        else None
    )
    first = None
    for index, plan in enumerate(proposed.output.alternatives or [], start=1):
        if plan is not None:
            first = index
            break

    return {
        "fixture": fixture,
        "arm": arm.name,
        "removes": arm.what_it_removes,
        "embeddings": len(oracle.embeddings),
        "representatives": len(proposed.representatives),
        "compression_ratio": None if ratio is None else round(ratio, 4),
        "simulations": audit.simulations_run,
        "feasible_recall": comparison.feasible_recall,
        "cost_regret": comparison.cost_regret,
        "false_infeasible": len(comparison.false_infeasible),
        "mismerged_pairs": len(comparison.mismerged_pairs),
        "mismerged_ids": [list(p) for p in sorted(comparison.mismerged_pairs)][:8],
        "correct": comparison.correct,
        "first_feasible_at_sim": first,
        "mismerge_expected": arm.mismerge_expected,
    }


COLUMNS = [
    "fixture", "arm", "false_infeasible", "mismerged_pairs", "correct",
    "compression_ratio", "representatives", "simulations", "feasible_recall",
    "cost_regret", "first_feasible_at_sim",
]


def appendix(rows: list[dict], args) -> list[str]:
    """The mis-merged pairs `no_boundary` produced, with their metrics.

    P5.2 asks for this by name: the arm's non-zero `mismerged_pairs` is the
    direct evidence for contribution A, and a count alone is not evidence --
    a reader has to be able to see WHICH two placements were folded and that
    the oracle really priced them differently.
    """
    out: list[str] = []
    for row in rows:
        if row["arm"] != "no_boundary" or not row["mismerged_ids"]:
            continue
        out.append("")
        out.append(f"### `no_boundary` on {row['fixture']}")
        out.append("")
        out.append(
            f"{row['mismerged_pairs']} pair(s) folded into one class that the "
            f"oracle judged differently. The first few:"
        )
        out.append("")
        out.append("| a | b |")
        out.append("| --- | --- |")
        for first, second in row["mismerged_ids"]:
            out.append(f"| `{first}` | `{second}` |")
    return out


def probe_section(probe: dict) -> list[str]:
    out = ["", "## Criterion 2 — contribution A, on the pair it is about", ""]
    if not probe.get("reachable"):
        out.append(f"**Not reachable: {probe.get('why')}**")
        out.append("")
        out.append(
            "A zero here would not vindicate the contribution. The registered "
            "response is to re-examine the fixture selection and report "
            "contribution A as unsupported by these fixtures."
        )
        return out

    out.append(
        "The corpus-wide `no_boundary` row above **cannot** answer this, and "
        "reading it as if it could was the first version's mistake. "
        "`mismerged_pairs` compares feasibility verdicts and costs, not "
        "metrics: under the fixed tight spec both placements sit far above the "
        "50 ms TTFT, both are infeasible, the verdicts agree — so the fold "
        "happens and nothing detects it. That zero is a property of the ruler."
    )
    out.append("")
    out.append(
        "So the threshold is **derived from the oracle**: both placements are "
        "run under a roomy SLO, and the limit is put at the midpoint of the "
        "two TTFTs that come back."
    )
    out.append("")
    out.append("| placement | p99 TTFT (ms) |")
    out.append("| --- | --- |")
    for candidate_id, ttft in probe["ttft_ms"].items():
        out.append(f"| `{candidate_id}` | {ttft} |")
    out.append("")
    out.append(
        f"Separating threshold: **{probe['separating_ttft_ms']} ms**. "
        f"Feasible under it: {', '.join(f'`{i}`' for i in probe['feasible_ids']) or 'none'}."
    )
    out.append("")
    out.append("| arm | representatives | mismerged pairs |")
    out.append("| --- | --- | --- |")
    out.append(
        f"| `full` | {probe['representatives_full']} | "
        f"{len(probe['mismerged_full'])} |"
    )
    out.append(
        f"| `no_boundary` | {probe['representatives_no_boundary']} | "
        f"{len(probe['mismerged_no_boundary'])} |"
    )
    out.append("")

    if probe["mismerged_no_boundary"] and not probe["mismerged_full"]:
        out.append(
            "**Criterion 2 met.** Dropping the boundary folded two placements "
            "the oracle judges differently, and the boundary-aware compression "
            "on the same spec does not. The pairs:"
        )
        out.append("")
        out.append("| a | b |")
        out.append("| --- | --- |")
        for first, second in probe["mismerged_no_boundary"]:
            out.append(f"| `{first}` | `{second}` |")
    elif probe["mismerged_full"]:
        out.append(
            "**The control failed.** The boundary-aware `full` arm mis-merged "
            "on this spec too, so this says nothing in the contribution's "
            "favour — it says the equivalence relation is wrong. Stop and "
            "report."
        )
    else:
        out.append(
            "**Criterion 2 NOT met.** The boundary was dropped, the "
            "placements folded, and the oracle still judged them the same. "
            "The registered response is to re-examine the fixture selection "
            "and report contribution A as unsupported by these fixtures — "
            "never to declare it safe because nothing broke."
        )

    out.append("")
    out.append(
        "**Deriving the threshold is not tuning to win.** Tuning to win is "
        "moving a parameter until the method looks good. This makes the "
        "instrument able to resolve the difference at all, and the claim under "
        "test is precisely that a difference exists. The control is the `full` "
        "arm on the *same* spec: if it had mis-merged too, the row above would "
        "say the finding is against us. "
        "`tests/test_oracle_agreement.py::test_dropping_the_boundary_produces_a_mismerge` "
        "derives it the same way and states the same reason."
    )
    return out


def markdown(rows: list[dict], args, probe: dict | None = None) -> str:
    out = ["# E-G7 — ablation", "", BANNER, ""]
    out.append("| " + " | ".join(COLUMNS) + " |")
    out.append("| " + " | ".join("---" for _ in COLUMNS) + " |")
    for row in rows:
        out.append(
            "| "
            + " | ".join(
                "-" if row.get(c) is None else str(row.get(c)) for c in COLUMNS
            )
            + " |"
        )

    out += ["", "## What each arm removes", ""]
    out.append("| arm | removes |")
    out.append("| --- | --- |")
    for arm in ARMS:
        out.append(f"| `{arm.name}` | {arm.what_it_removes} |")

    if probe is not None:
        out += probe_section(probe)

    out += ["", "## The corpus-wide `no_boundary` row", ""]
    boundary = [r for r in rows if r["arm"] == "no_boundary"]
    produced = [r["fixture"] for r in boundary if r["mismerged_pairs"] > 0]
    silent = [r["fixture"] for r in boundary if r["mismerged_pairs"] == 0]

    if produced:
        out.append(
            f"**Mis-merges on {', '.join(produced)}.** Removing the shared boundary "
            "from the signature folded placements the oracle prices "
            "differently, which is the existence proof for contribution A: the "
            "property is load-bearing, and the way to show that is to take it "
            "out and watch the thing fall over."
        )
    if silent:
        out.append("")
        out.append(
            f"**Zero on {', '.join(silent)} — and this row is not the place to "
            "read criterion 2.** Under the fixed tight spec these placements "
            "are all far above the TTFT limit, so they share a verdict and "
            "`mismerged_pairs` cannot see the difference even where the fold "
            "really happened (watch `compression_ratio` halve). The section "
            "above answers criterion 2 on the pair it is actually about."
        )

    out.append("")
    out.append(
        "**This is the only arm where a non-zero `mismerged_pairs` does not "
        "stop the run.** Its purpose is to produce one. Every other arm is "
        "bound by the common invariant, and a non-zero there is a "
        "stop-and-report under work order rule 5."
    )

    violations = [
        f"{r['fixture']}/{r['arm']}"
        for r in rows
        if not r["correct"] and not r["mismerge_expected"]
    ]
    if violations:
        out += ["", "## The invariant was broken where it should not be", ""]
        out.append(
            f"**{', '.join(violations)}.** These arms are bound by the common "
            "invariant and are not. This is a stop-and-report: the test is not "
            "relaxed and the labelling is not loosened."
        )

    out += appendix(rows, args)

    out += ["", "## Reading the rest", ""]
    out.append(
        "`no_compression` should show the same correctness numbers as `full` "
        "and strictly more simulations — one representative per placement "
        "means nothing is folded and everything is evaluated separately. If "
        "its simulation count matches `full`, the compression folded nothing "
        "on that fixture and the row says so rather than the ratio being read "
        "as a saving."
    )
    out.append("")
    out.append(
        "`no_bounds` drops the **relaxations** only. `compat` and `memory` are "
        "exact feasibility checks, not bounds, and stay on: turning them off "
        "would not be an ablation of the elimination, it would be an ablation "
        "of the feasibility test."
    )
    out.append("")
    out.append(
        "`contention=fluid` is the one arm that ADDS rather than removes. It "
        "changes nothing unless a candidate's own flows overlap on a resource "
        "(GS-20), so most rows match `full` — and a run where it changed "
        "everything would be a bug rather than a finding."
    )

    out += ["", "## Reproducing", ""]
    out.append("```bash")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append("python experiments/scripts/e_g7_ablation.py \\")
    out.append(f"    --out {args.out}")
    out.append("```")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g7_ablation.md")
    parser.add_argument("--json-out", default="outputs/e_g7/ablation.json")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--k", type=int, default=16)
    parser.add_argument("--only", default=None)
    parser.add_argument("--only-arm", default=None)
    parser.add_argument("--no-probe", action="store_true")
    args = parser.parse_args(argv)

    spec_path = FIXTURES / "service_specs/graph-toy-llama31-8b-tight.yaml"
    rows = [
        run_arm(arm, fixture, path, spec_path, args)
        for fixture, path in CLUSTERS.items()
        if args.only is None or args.only == fixture
        for arm in ARMS
        if args.only_arm is None or args.only_arm == arm.name
    ]

    probe = None if args.no_probe else contribution_a_probe(args)
    text = markdown(rows, args, probe)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps({"arms": rows, "contribution_a": probe}, indent=2) + "\n"
        )

    broken = [r for r in rows if not r["correct"] and not r["mismerge_expected"]]
    if broken:
        print(
            f"\nE-G7 ablation: the invariant broke in "
            f"{', '.join(r['arm'] for r in broken)}, which is not the arm "
            f"allowed to break it. Stop and report (work order rule 5)."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
