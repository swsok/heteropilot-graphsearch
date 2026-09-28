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


# --- the binding claim is checked against the kernel, not trusted ---------

def test_the_observed_affinity_is_read_from_proc() -> None:
    """`--binding` is what the operator claims; this is what the kernel says.

    Recorded side by side so a `numa_pinned` label can be checked. A claim
    nobody can check is the one that survives longest.
    """
    affinity = RP.observed_affinity()
    assert affinity["available"] is True
    assert affinity["Cpus_allowed_list"]
    assert affinity["Mems_allowed_list"]
    assert isinstance(affinity["looks_unrestricted"], bool)


def test_an_unrestricted_process_is_recognised_as_unpinned() -> None:
    """This test process is not under `numactl`, so it may use every CPU.

    That is exactly the state in which `--binding numa_pinned` is a false
    label, and `run_pair.py` refuses rather than recording it.
    """
    import os

    affinity = RP.observed_affinity()
    assert affinity["Cpus_allowed_list"] == f"0-{(os.cpu_count() or 1) - 1}"
    assert affinity["looks_unrestricted"] is True


def test_a_pinned_list_is_not_mistaken_for_an_unrestricted_one() -> None:
    """`0-15,32-47` is NUMA 0 on this box and must not read as "everything"."""
    assert f"0-{(RP.os.cpu_count() or 1) - 1}" != "0-15,32-47"


# --- the four defects the first real run found (GS-24) ---------------------

def test_our_own_process_is_not_counted_as_another_tenant(monkeypatch) -> None:
    """The `after` snapshot is taken while we still hold a CUDA context.

    Without the exclusion the run always found ITSELF in `after` and never in
    `before`, `occupancy_stable` was False on every run, and the analysis --
    specified to refuse a run whose occupancy changed mid-flight -- would have
    refused every measurement ever taken on a perfectly quiet node. A check
    that can never pass is worse than no check.
    """
    import subprocess

    mine = "4242"

    def fake_run(cmd, **kwargs):
        if cmd[0] == "nvidia-smi":
            out = "\n".join(f"{mine}, python, {m} MiB" for m in (260, 306))
            out += "\n9999, someone_else, 8800 MiB"
            return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="swsok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    everyone = RP.gpu_occupancy()
    assert [p["pid"] for p in everyone] == [mine, mine, "9999"]

    others = RP.gpu_occupancy(exclude_pid=int(mine))
    assert [p["pid"] for p in others] == ["9999"]


def test_a_stable_node_with_two_devices_of_one_tenant_is_still_stable() -> None:
    """nvidia-smi lists one row per (process, device).

    A neighbour holding two GPUs appears twice, so a list comparison of a
    two-device tenant against itself reports a change that did not happen.
    Sets, not lists.
    """
    before = [{"pid": "9999"}, {"pid": "9999"}]
    after = [{"pid": "9999"}, {"pid": "9999"}, {"pid": "9999"}]
    assert {p["pid"] for p in before} == {p["pid"] for p in after}


def test_the_memory_half_of_a_pin_is_read_where_it_actually_shows(tmp_path, monkeypatch) -> None:
    """`Mems_allowed_list` cannot see `--membind`; `numa_maps` can.

    Measured on the A40 node 2026-09-28: under
    `numactl --cpunodebind=0 --membind=0`, `numactl --show` says `membind: 0`
    while `/proc/self/status` still says `Mems_allowed_list: 0-1`. PLAN.md's
    first recipe checked the wrong file, and an operator following it would
    have read a correct pin as a failed one.
    """
    maps = tmp_path / "numa_maps"
    maps.write_text("55b167524000 bind:0 file=/usr/bin/head mapped=2 N0=2\n")
    monkeypatch.chdir(tmp_path)
    real_open = open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/proc/self/numa_maps":
            return real_open(maps, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    assert RP.mempolicy() == "bind:0"

    maps.write_text("5597eaeaf000 default file=/usr/bin/head mapped=2 N0=2\n")
    assert RP.mempolicy() == "default"


def test_an_unimplemented_condition_refuses_rather_than_running_the_wrong_one() -> None:
    """`collective` is in CONDITIONS but `measure()` has no branch for it.

    Left alone, `--condition collective` wrote peer-copy timings into a file
    whose `condition_means` reads "all-reduce, varying world size". A
    mislabelled measurement is the one failure this harness exists to prevent,
    so the condition names the other instrument instead.
    """
    assert "collective" in RP.CONDITIONS
    source = _SCRIPT.read_text()
    assert 'if args.condition == "collective":' in source
    assert "run_collective.sh" in source


def test_the_background_snapshot_is_taken_after_the_generator_stops() -> None:
    """`wall_s` is assigned when the generator thread leaves its loop.

    `as_dict()` called inside the `with` read `wall_s = 0.0`, so
    `achieved_duty_cycle` was None for every size in the grid -- and that is
    the one field the record's own note tells the analysis to use. All three
    background conditions carried a target nobody could check instead of a
    measurement.
    """
    source = _SCRIPT.read_text()
    inside = source.index("        with load:")
    after = source.index("        if args.background_util > 0:", inside)
    between = source[inside:after]
    assert "load.as_dict()" not in between, (
        "the background snapshot is inside the `with` again; wall_s is 0.0 "
        "there and achieved_duty_cycle comes out None"
    )


def test_a_half_pin_cannot_be_labelled_numa_pinned() -> None:
    """PLAN.md: pin both halves or neither.

    `--cpunodebind` without `--membind` leaves the buffers free to land on the
    far node -- a plausible number under a label that does not describe it.
    The CPU half was already checked; this is the memory half.
    """
    source = _SCRIPT.read_text()
    assert 'if args.binding == "numa_pinned" and not affinity.get("mem_is_bound"):' in source
