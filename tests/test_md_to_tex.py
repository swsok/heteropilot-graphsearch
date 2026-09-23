"""P0.5: the results-to-LaTeX converter, and the one thing it must refuse.

The script's job is not conversion -- it is that a number cannot reach the paper
without the provenance banner it was published under. Conversion is how it gets
there. So the tests that matter are the refusal and the classification, and they
are here rather than in the script's docstring because a docstring is not a
mechanism.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from graphsearch import paths_root

_SCRIPT = paths_root.GRAPHSEARCH_ROOT / "scripts" / "paper" / "md_to_tex.py"


def _module():
    """Load the script by path: `scripts/` is not a package and must not become one."""
    spec = importlib.util.spec_from_file_location("md_to_tex", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["md_to_tex"] = module
    spec.loader.exec_module(module)
    return module


MD = _module()


def test_a_file_without_a_banner_is_refused() -> None:
    """The whole point. An untraceable number stops the build."""
    with pytest.raises(MD.BannerError):
        MD.classify_banner("# a title\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("# t\n\n> **MockPredictor results. Not performance numbers.**\n", "mock"),
        ("# t\n\n> REAL SIM -- LLMServingSim, cache outputs/cache-eg3\n", "real-sim"),
        ("# t\n\n> REAL HARDWARE -- node serials RNG26040100105Q\n", "hardware"),
    ],
)
def test_each_banner_is_classified(text: str, expected: str) -> None:
    kind, _line = MD.classify_banner(text)
    assert kind == expected


def test_real_sim_is_tested_before_mock() -> None:
    """A REAL SIM file that also says "mock" somewhere is a simulation, not a mock.

    The ordering in `BANNERS` is load-bearing: matched the other way round, a
    result file explaining that it is NOT the mock would be filed as one.
    """
    text = "# t\n\n> REAL SIM -- LLMServingSim, not the MOCK predictor\n"
    assert MD.classify_banner(text)[0] == "real-sim"


def test_a_banner_deep_in_the_prose_does_not_count() -> None:
    """Mentioning hardware is not claiming to be it."""
    body = "\n".join(f"line {i}" for i in range(30))
    with pytest.raises(MD.BannerError):
        MD.classify_banner(f"# t\n\n{body}\n\n> REAL HARDWARE -- serial 1\n")


def test_tex_specials_are_escaped_and_markdown_is_unwrapped() -> None:
    assert MD.escape_tex("compression_ratio") == "compression\\_ratio"
    assert MD.escape_tex("**bold**") == "bold"
    assert MD.escape_tex("`--bounds none`") == "--bounds none"
    assert MD.escape_tex("50%") == "50\\%"
    assert MD.escape_tex("a & b") == "a \\& b"


def test_every_committed_results_file_converts() -> None:
    """The gate, applied to the corpus as it stands.

    If an experiment script ever writes a results file without its banner, this
    fails here rather than in a paper build nobody ran.
    """
    results = sorted((paths_root.GRAPHSEARCH_ROOT / "experiments" / "results").glob("*.md"))
    assert results, "no results files found"
    for path in results:
        kind, _ = MD.classify_banner(path.read_text(encoding="utf-8"))
        assert kind in MD.NOTES
        assert MD.find_tables(path.read_text(encoding="utf-8")), f"{path} has no table"


def test_conversion_is_deterministic(tmp_path: Path) -> None:
    source = paths_root.GRAPHSEARCH_ROOT / "experiments" / "results" / "e_g1_toy_pilot.md"
    first = [p.read_text(encoding="utf-8") for p in MD.convert(source, tmp_path / "a")]
    second = [p.read_text(encoding="utf-8") for p in MD.convert(source, tmp_path / "b")]
    assert first == second
    assert "false\\_infeasible" in first[0]
    assert "not performance numbers" in first[0]


def test_a_numeric_column_is_right_aligned_and_a_text_one_is_not() -> None:
    header = ["fixture", "embeddings", "correct"]
    rows = [["abcde", "528", "True"], ["asym", "840", "True"]]
    assert MD.column_spec(header, rows) == "lrl"
