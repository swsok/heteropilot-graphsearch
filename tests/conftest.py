"""Test setup: make `planner.*` importable, and share heteropilot's own mock.

`vendor/heteropilot/tests/conftest.py` cannot be imported as `tests.conftest` -
this repo has a `tests` package of its own and the names collide - so it is
loaded by path under a different module name.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphsearch import paths_root

HETEROPILOT_ROOT = paths_root.ensure_importable()
GRAPHSEARCH_ROOT = paths_root.GRAPHSEARCH_ROOT


hp_conftest = paths_root.load_heteropilot_conftest()

MockPredictor = hp_conftest.MockPredictor
MOCK_ROOFLINE_SLACK = hp_conftest.MOCK_ROOFLINE_SLACK


@pytest.fixture
def hp_root() -> Path:
    return HETEROPILOT_ROOT


@pytest.fixture
def gs_root() -> Path:
    return GRAPHSEARCH_ROOT
