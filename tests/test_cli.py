"""G13: the CLI, and the banner that stops a mock number becoming a claim.

heteropilot's `planner/__main__.py` is not modified and not wrapped. This
prints its render output unchanged and appends a block underneath, so a reader
who knows the planner's output can see exactly what the graph search added.

`test_the_mock_banner_is_unmissable` is the one that matters outside this
repository. Every figure `--predictor mock` prints is fictional, and the
distance between a fictional number and a quoted result is one copy-paste.
"""

from __future__ import annotations

import json

import pytest
import yaml

from graphsearch import paths_root
from graphsearch.__main__ import MOCK_BANNER, build_parser, main

FIXTURES = paths_root.GRAPHSEARCH_ROOT / "fixtures"
SERVICE = str(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")
CLUSTER = str(FIXTURES / "clusters/graph-toy-abcde.v2.yaml")
SHARED = str(FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml")


def run(argv, capsys) -> tuple[int, str]:
    code = main(argv)
    return code, capsys.readouterr().out


# --- the banner -----------------------------------------------------------

def test_the_mock_banner_is_unmissable(capsys) -> None:
    """The distance between a fictional number and a quoted result is one
    copy-paste."""
    code, out = run(
        ["plan", "--service", SERVICE, "--cluster", CLUSTER, "--k-schedule", "2"],
        capsys,
    )
    assert code == 0
    assert MOCK_BANNER in out
    assert "FICTIONAL" in out
    assert "Do not quote them as performance" in out


# --- (i) the block ---------------------------------------------------------

def test_plan_prints_the_graph_search_block(capsys) -> None:
    _, out = run(
        ["plan", "--service", SERVICE, "--cluster", CLUSTER, "--k-schedule", "2"],
        capsys,
    )
    assert "Graph search:" in out
    assert "representatives" in out
    assert "termination:" in out


def test_the_block_leads_with_what_was_not_judged(capsys) -> None:
    """A search that evaluated two of fifty-four and found nothing feasible has
    said something very different from a cluster that cannot serve."""
    _, out = run(
        ["plan", "--service", SERVICE, "--cluster", CLUSTER, "--k-schedule", "2"],
        capsys,
    )
    assert "NOT EVALUATED" in out
    assert "they were not judged" in out


def test_the_planner_s_own_render_is_untouched(capsys) -> None:
    """heteropilot's renderer produces what it always did; the block is added
    underneath."""
    _, out = run(
        ["plan", "--service", SERVICE, "--cluster", CLUSTER, "--k-schedule", "2"],
        capsys,
    )
    assert "Caveats" in out
    assert out.index("Caveats") < out.index("Graph search:")


# --- the YAML -------------------------------------------------------------

def test_the_output_carries_the_provenance_blocks(tmp_path, capsys) -> None:
    path = tmp_path / "plan.yaml"
    run(
        [
            "plan", "--service", SERVICE, "--cluster", CLUSTER,
            "--k-schedule", "2", "--output", str(path),
        ],
        capsys,
    )
    data = yaml.safe_load(path.read_text())
    provenance = data["provenance"]
    assert "graph_search" in provenance
    assert "compression" in provenance
    assert "restored" in provenance
    assert provenance["graph_search"]["termination"]
    assert provenance["graph_search"]["unevaluated"]["placements"] >= 0


# --- (ii) oracle mode -----------------------------------------------------

def test_oracle_mode_says_what_it_did(capsys) -> None:
    code, out = run(
        [
            "plan", "--service", SERVICE, "--cluster", CLUSTER, "--oracle",
            "--max-embeddings-per-template", "1",
        ],
        capsys,
    )
    assert code == 0
    assert "Oracle:" in out
    assert "No compression, no bounds, no top-K" in out


# --- (iii) compression off ------------------------------------------------

def test_compression_off_gives_one_representative_per_embedding(capsys) -> None:
    _, on = run(
        [
            "plan", "--service", SERVICE, "--cluster", SHARED, "--k-schedule", "1",
            "--max-embeddings-per-template", "2",
        ],
        capsys,
    )
    _, off = run(
        [
            "plan", "--service", SERVICE, "--cluster", SHARED, "--k-schedule", "1",
            "--max-embeddings-per-template", "2", "--compression", "off",
        ],
        capsys,
    )

    def reps(text: str) -> int:
        line = next(line for line in text.splitlines() if line.startswith("Graph search:"))
        return int(line.split("->")[-1].split("representatives")[0].strip())

    def embeddings(text: str) -> int:
        line = next(line for line in text.splitlines() if line.startswith("Graph search:"))
        return int(line.split("->")[1].split("embeddings")[0].strip())

    assert reps(off) == embeddings(off)
    assert reps(on) <= reps(off)


# --- (v) bounds none ------------------------------------------------------

def test_bounds_none_keeps_the_exact_checks(capsys) -> None:
    """`none` turns off the RELAXATIONS, not the feasibility test. Compat and
    memory are exact checks and a candidate that fails them is not a candidate."""
    from graphsearch.__main__ import _bound_policy

    policy = _bound_policy("none")
    assert policy.compat is True
    assert policy.memory is True
    assert policy.comm_latency is False
    assert policy.throughput_capacity is False


def test_bounds_accepts_a_named_subset() -> None:
    from graphsearch.__main__ import _bound_policy

    policy = _bound_policy("compat,memory")
    assert policy.compat and policy.memory
    assert not policy.comm_latency


def test_an_unknown_bound_is_refused() -> None:
    from graphsearch.__main__ import _bound_policy

    with pytest.raises(SystemExit, match="unknown check"):
        _bound_policy("compat,no-such-check")


# --- (vi) the sim predictor is refused clearly ---------------------------

def test_the_sim_predictor_explains_what_it_needs(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "plan", "--service", SERVICE, "--cluster", CLUSTER,
                "--predictor", "sim",
            ]
        )
    message = str(excinfo.value)
    assert "vendor/heteropilot/.venv" in message or "simulator" in message


# --- compare --------------------------------------------------------------

def test_compare_prints_the_four_numbers(capsys) -> None:
    code, out = run(["compare", "--service", SERVICE, "--cluster", SHARED], capsys)
    payload = json.loads(out[out.index("{"):])
    for key in (
        "feasible_recall", "cost_regret", "false_infeasible",
        "mismerged_pairs", "correct",
    ):
        assert key in payload
    assert code == (0 if payload["correct"] else 1)


# --- argument handling ----------------------------------------------------

def test_a_bad_k_schedule_is_refused() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["plan", "--service", SERVICE, "--cluster", CLUSTER,
             "--k-schedule", "four"]
        )


def test_a_zero_k_is_refused() -> None:
    with pytest.raises(SystemExit, match="positive"):
        build_parser().parse_args(
            ["plan", "--service", SERVICE, "--cluster", CLUSTER,
             "--k-schedule", "0,4"]
        )


def test_a_missing_spec_fails_with_the_loader_s_message() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["plan", "--service", "no-such.yaml", "--cluster", CLUSTER])
    assert "no-such.yaml" in str(excinfo.value)


def test_the_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
