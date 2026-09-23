"""Where `vendor/heteropilot` is, and how to import from it.

heteropilot is not a pip-installable package -- its `pyproject.toml` has no
`[project]` table -- so it is reached by path rather than by install. One module
resolves that path so nothing else has to guess, and `HETEROPILOT_ROOT` lets a
caller point at a different checkout without editing anything.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: This repository's root.
GRAPHSEARCH_ROOT = Path(__file__).resolve().parents[1]

#: The heteropilot checkout to import `planner.*` from.
HETEROPILOT_ROOT = Path(
    os.environ.get("HETEROPILOT_ROOT", GRAPHSEARCH_ROOT / "vendor" / "heteropilot")
).resolve()


class HeteropilotMissing(RuntimeError):
    """The vendored checkout is absent or empty."""


def ensure_importable() -> Path:
    """Put `HETEROPILOT_ROOT` on `sys.path` and return it.

    Called first thing by `graphsearch.__main__` and `tests/conftest.py`. Fails
    loudly rather than letting `import planner` raise a bare ImportError two
    frames later, because the usual cause is a submodule that was never
    initialised and the fix is one documented command.
    """
    if not (HETEROPILOT_ROOT / "planner" / "__init__.py").exists():
        raise HeteropilotMissing(
            f"no planner package under {HETEROPILOT_ROOT}. If this is a fresh "
            f"clone, the submodule is empty:\n"
            f"    git submodule update --init --recursive\n"
            f"Or point HETEROPILOT_ROOT at an existing heteropilot checkout."
        )
    root = str(HETEROPILOT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return HETEROPILOT_ROOT


def examples_dir() -> Path:
    return HETEROPILOT_ROOT / "examples"


def profiles_dir() -> Path:
    return HETEROPILOT_ROOT / "profiles"


def fixtures_dir() -> Path:
    """This repo's toy fixtures. Fictional; see the header of any of them."""
    return GRAPHSEARCH_ROOT / "fixtures"


def load_heteropilot_conftest():
    """heteropilot's `tests/conftest.py`, under a name that cannot clash.

    It holds `MockPredictor`, which the graph-aware mock subclasses because
    that mock derives latency from real weight and KV sizes and therefore
    respects the same physics as the bounds. Importing it as `tests.conftest`
    is impossible -- this repository has a `tests` package of its own -- so it
    is loaded by path.

    Lives here rather than in `tests/` because `python -m graphsearch
    --predictor mock` needs it too, and a fixture module that only works under
    pytest cannot serve a CLI.
    """
    import importlib.util
    import sys

    if "hp_conftest" in sys.modules:
        return sys.modules["hp_conftest"]

    ensure_importable()
    path = HETEROPILOT_ROOT / "tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location("hp_conftest", path)
    if spec is None or spec.loader is None:      # pragma: no cover - packaging bug
        raise HeteropilotMissing(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["hp_conftest"] = module
    spec.loader.exec_module(module)
    return module
