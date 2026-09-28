"""P2.2: the parts of `run_pair.py` that can be checked without a GPU.

The timing itself needs CUDA and is the user's to run. What is checkable here
is everything that decides whether the resulting number is *filed correctly* --
and that is where a microbenchmark goes wrong quietly: a figure recorded under
the wrong message-size class answers a question it was never measured for.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

from graphsearch import paths_root

_SCRIPT = paths_root.GRAPHSEARCH_ROOT / "experiments" / "microbench" / "run_pair.py"

paths_root.ensure_importable()


def _module():
    spec = importlib.util.spec_from_file_location("run_pair", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_pair"] = module
    spec.loader.exec_module(module)
    return module


RP = _module()


def test_the_size_grid_is_the_one_the_plan_registers() -> None:
    assert RP.SIZES_MIB == [1, 2, 4, 8, 16, 32, 64, 128, 256]


def test_the_grid_crosses_the_class_boundaries_on_purpose() -> None:
    """PLAN.md says the sweep spans `mid` and `bulk`. If it stopped inside one
    band the sweep could carry a single label, and the per-figure classing
    below would be untested by the data it is meant to protect."""
    classes = {RP._class_of(mib << 20) for mib in RP.SIZES_MIB}
    assert classes == {"mid", "bulk"}, classes


def test_each_size_is_classed_by_heteropilots_own_bands() -> None:
    """Not a local copy of the boundaries. `LinkMeasurement` rejects a figure
    whose `msg_bytes` contradict its `msg_size_class`, and it uses these; a
    second definition here would drift and the rejection would fire on data
    that was correctly measured."""
    from planner.inventory import msg_size_class_of

    for mib in RP.SIZES_MIB:
        nbytes = mib << 20
        assert RP._class_of(nbytes) == msg_size_class_of(nbytes)

    assert RP._class_of(1 << 20) == "mid"       # 1 MiB: the mid floor
    assert RP._class_of(4 << 20) == "bulk"      # 4 MiB: the bulk floor


def test_every_condition_carries_a_sentence_saying_what_it_is() -> None:
    """The raw file records `condition_means`, so a reader a year later does
    not have to reconstruct what `two-same` meant."""
    assert set(RP.CONDITIONS) == {
        "single", "two-same", "two-independent", "bidirectional", "collective",
    }
    for name, description in RP.CONDITIONS.items():
        assert description and description != name


def test_pairs_parse_into_device_tuples() -> None:
    assert RP._pairs("0-2") == [(0, 2)]
    assert RP._pairs("0-2,1-3") == [(0, 2), (1, 3)]


def test_the_background_load_reports_what_it_achieved_not_what_it_targeted() -> None:
    """A generator that missed its target and a model that missed its
    prediction are different failures, and averaging them together hides
    both."""
    load = RP.BackgroundLoad(None, 4, 6, 1 << 20, 0.6)
    load.busy_s, load.wall_s = 3.0, 10.0
    recorded = load.as_dict()
    assert recorded["target_util"] == 0.6
    assert recorded["achieved_duty_cycle"] == pytest.approx(0.3)
    assert "never target_util" in recorded["note"]


def test_a_zero_length_run_does_not_divide_by_zero() -> None:
    load = RP.BackgroundLoad(None, 4, 6, 1 << 20, 0.6)
    assert load.as_dict()["achieved_duty_cycle"] is None


def test_the_probe_is_imported_from_the_submodule_and_not_copied() -> None:
    """The boundary: only hook PRs reach heteropilot, and a benchmark is not a
    hook. This asserts the file it loads is the vendored one."""
    assert RP.PROBE == (
        paths_root.HETEROPILOT_ROOT / "experiments" / "p2_evidence" / "p2p_probe.py"
    )
    assert RP.PROBE.exists()


def test_occupancy_is_recorded_as_a_list_of_processes_with_owners() -> None:
    """It must not raise on a host with no GPU, and it must name the owner --
    'someone else is on this node' is only actionable with a user attached."""
    occupancy = RP.gpu_occupancy()
    assert isinstance(occupancy, list)
    for process in occupancy:
        assert set(process) == {"pid", "process", "used_mib", "user"}
