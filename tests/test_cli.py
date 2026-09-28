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


# --- (vii) P1.1: the plan path binds the predictor, and says that it did ---

def test_plan_binds_the_predictor_to_the_placements(tmp_path, capsys) -> None:
    """GS-13. `compare` bound the predictor from the start and `plan` did not.

    Without the binder the predictor never learns which devices a candidate
    runs on, so it answers per TEMPLATE -- and two placements differing only in
    which contended uplink they cross come back identical, which is the one
    distinction this whole search exists to keep. The bug was invisible because
    nothing printed it; `hook_calls` is what makes it visible.
    """
    path = tmp_path / "plan.yaml"
    _, out = run(
        [
            "plan", "--service", SERVICE, "--cluster", SHARED,
            "--k-schedule", "2", "--output", str(path),
        ],
        capsys,
    )
    calls = yaml.safe_load(path.read_text())["provenance"]["graph_search"]["hook_calls"]
    assert calls["bound"] >= 2, calls
    assert calls["batches"] >= 1, calls
    assert "hooks: bound" in out


def test_the_audit_carries_what_the_simulator_was_not_told(tmp_path, capsys) -> None:
    """`topology_loss` is a key of the provenance, present even when empty.

    Empty is a real answer -- the mock compiles no simulator config, so there
    is nothing it could fail to express -- and an absent key would be
    indistinguishable from a run that dropped a shared resource silently.
    """
    path = tmp_path / "plan.yaml"
    run(
        [
            "plan", "--service", SERVICE, "--cluster", SHARED,
            "--k-schedule", "2", "--output", str(path),
        ],
        capsys,
    )
    search = yaml.safe_load(path.read_text())["provenance"]["graph_search"]
    assert "topology_loss" in search
    assert "timings" in search


def test_the_trace_defaults_match_heteropilots_own(tmp_path) -> None:
    """A cache directory is shared with heteropilot's `plan`, so the trace that
    keys it must be generated the same way. Two defaults that drifted apart
    would produce two trace digests and every cache hit would be a miss."""
    import re

    from graphsearch.__main__ import DEFAULT_TRACE_REQUESTS, DEFAULT_TRACE_SEED

    source = (paths_root.HETEROPILOT_ROOT / "planner" / "__main__.py").read_text()
    requests = re.search(r"^DEFAULT_TRACE_REQUESTS = (\d+)", source, re.M)
    assert requests is not None, "heteropilot no longer defines DEFAULT_TRACE_REQUESTS"
    assert int(requests.group(1)) == DEFAULT_TRACE_REQUESTS
    seed = re.search(r"^DEFAULT_SEED = (\d+)", source, re.M)
    assert seed is not None, "heteropilot no longer defines DEFAULT_SEED"
    assert int(seed.group(1)) == DEFAULT_TRACE_SEED


def test_the_sim_flags_parse_without_a_simulator() -> None:
    """Parsing must not need the venv: a typo should be reported before a build."""
    args = build_parser().parse_args(
        [
            "plan", "--service", SERVICE, "--cluster", CLUSTER,
            "--predictor", "sim", "--num-requests", "50",
            "--cache-dir", "outputs/cache-eg3", "--max-workers", "4",
            "--timeout", "120",
        ]
    )
    assert args.num_requests == 50
    assert args.cache_dir == "outputs/cache-eg3"
    assert args.max_workers == 4
    assert args.timeout == 120.0
