"""Test setup: make `planner.*` importable, and share heteropilot's own mock.

`vendor/heteropilot/tests/conftest.py` cannot be imported as `tests.conftest` -
this repo has a `tests` package of its own and the names collide - so it is
loaded by path under a different module name.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphsearch import paths_root

HETEROPILOT_ROOT = paths_root.ensure_importable()
GRAPHSEARCH_ROOT = paths_root.GRAPHSEARCH_ROOT


def _load_heteropilot_conftest():
    """heteropilot's conftest, under a name that cannot clash with ours."""
    path = HETEROPILOT_ROOT / "tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location("hp_conftest", path)
    if spec is None or spec.loader is None:      # pragma: no cover - packaging bug
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["hp_conftest"] = module
    spec.loader.exec_module(module)
    return module


hp_conftest = _load_heteropilot_conftest()

MockPredictor = hp_conftest.MockPredictor
MOCK_ROOFLINE_SLACK = hp_conftest.MOCK_ROOFLINE_SLACK


@pytest.fixture
def hp_root() -> Path:
    return HETEROPILOT_ROOT


@pytest.fixture
def gs_root() -> Path:
    return GRAPHSEARCH_ROOT
