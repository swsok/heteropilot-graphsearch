"""`scripts/paper/tables.yaml` and what `md_to_tex.py` does with it (revision R1.1).

The tables were set whole and shrunk to fit, so the correctness columns of
Table I were in the PDF at a size nobody could read -- or past the margin. The
mapping chooses columns; these pin that every column it names reaches the
generated LaTeX, and that a column it cannot find stops the build rather than
vanishing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _md_to_tex():
    spec = importlib.util.spec_from_file_location(
        "md_to_tex", ROOT / "scripts" / "paper" / "md_to_tex.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["md_to_tex"] = module
    spec.loader.exec_module(module)
    return module


MD = _md_to_tex()
SPEC = yaml.safe_load((ROOT / "scripts" / "paper" / "tables.yaml").read_text())


def _labels(entry: dict) -> list[str]:
    labels = entry.get("labels") or {}
    names = [c if isinstance(c, str) else c["name"] for c in entry["columns"]]
    return [labels.get(n, n) for n in names]


@pytest.mark.parametrize("key", sorted(SPEC))
def test_every_mapped_column_reaches_the_tex(key: str, tmp_path: Path) -> None:
    stem = key.rsplit("_", 1)[0] if key.rsplit("_", 1)[-1].isdigit() else key
    MD.convert(ROOT / "experiments" / "results" / f"{stem}.md", tmp_path)
    tex = (tmp_path / f"{key}.tex").read_text()
    header = next(line for line in tex.splitlines() if line.strip().endswith("\\\\")
                  and "toprule" not in line)
    for label in _labels(SPEC[key]):
        assert MD.escape_tex(label) in header, (key, label)
    env = "table*" if SPEC[key].get("width") == "page" else "table"
    assert f"\\begin{{{env}}}" in tex
    assert f"\\{SPEC[key].get('size', 'small')}" in tex


def test_a_column_the_table_lacks_is_an_error() -> None:
    spec = MD.TableSpec(columns=["fixture", "renamed_away"])
    with pytest.raises(MD.TableSpecError, match="renamed_away"):
        MD.apply_spec("t", ["fixture", "x"], [["a", "1"]], spec, [])


def test_a_join_without_a_match_is_a_dash_not_a_guess() -> None:
    main = (["fixture", "x"], [["a", "1"], ["b", "2"]])
    other = (["fixture", "saving_s"], [["a", "9.5"]])
    spec = MD.TableSpec(columns=["fixture", "saving_s"],
                        joins=[{"find": ["fixture", "saving_s"], "columns": ["saving_s"]}])
    header, rows = MD.apply_spec("t", *main, spec, [main, other])
    assert header == ["fixture", "saving_s"]
    assert rows == [["a", "9.5"], ["b", "-"]]


def test_a_composite_sets_two_cells_side_by_side() -> None:
    table = (["fixture", "ours", "theirs"], [["a", "0.6", "0.1"]])
    spec = MD.TableSpec(columns=[{"name": "r", "cells": ["ours", "theirs"], "sep": " / "}],
                        labels={"r": "recall"})
    header, rows = MD.apply_spec("t", *table, spec, [table])
    assert header == ["recall"] and rows == [["0.6 / 0.1"]]


def test_where_keeps_only_the_named_rows_and_refuses_to_empty_a_table() -> None:
    main = (["devices", "ratio"], [["32", "0.08"], ["128", "0.02"]])
    spec = MD.TableSpec(columns=["devices", "ratio"], where={"devices": ["128"]})
    _, rows = MD.apply_spec("t", *main, spec, [main])
    assert rows == [["128", "0.02"]]
    with pytest.raises(MD.TableSpecError):
        MD.apply_spec("t", *main, MD.TableSpec(columns=["devices"],
                                              where={"devices": ["64"]}), [main])
