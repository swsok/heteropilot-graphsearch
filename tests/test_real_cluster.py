"""P3.2: the real A40 fixture regenerates, loads, and says what it measured.

This is the first cluster file in the repository that is **not fictional**, so
the things worth pinning are different from the toy fixtures'. There, the test
is that the physics is self-consistent. Here it is that the provenance is
honest: that no `source: measured` number appeared without a raw file behind
it, and that the shared-resource model still reproduces what the wire did.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.inventory import (  # noqa: E402
    Source,
    detect_islands,
    load_cluster_spec,
    load_profiles_for,
)

from graphsearch.contention import contention_model  # noqa: E402
from graphsearch.demand import CommFlow  # noqa: E402
from graphsearch.paths import path_set  # noqa: E402
from graphsearch.schema import build_resource_graph  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURE = ROOT / "fixtures" / "clusters" / "real-a40x8.v2.yaml"
BUILDER = ROOT / "experiments" / "e_g5" / "build_cluster.py"
GB = 1e9


@pytest.fixture(scope="module")
def cluster():
    return load_cluster_spec(FIXTURE)


@pytest.fixture(scope="module")
def graph(cluster):
    return build_resource_graph(cluster, load_profiles_for(cluster, ROOT))


def test_it_regenerates_byte_identically() -> None:
    """A generated fixture that has drifted from its generator is a hand-edit.

    Run with `--check`, which compares rather than writes: a test that
    regenerated the file would pass by overwriting the evidence.
    """
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        capture_output=True, text=True, cwd=ROOT,
        env={"PYTHONPATH": f"{ROOT}:{ROOT / 'vendor' / 'heteropilot'}",
             "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_heteropilots_own_loader_accepts_it(cluster) -> None:
    assert cluster.schema_version == 2
    assert len(cluster.nodes) == 1
    assert len(cluster.nodes[0].accelerators) == 8


def test_every_measured_number_names_a_raw_file_that_exists(cluster) -> None:
    """`source: measured` with no traceable artefact is not a measurement.

    heteropilot's own `LinkMeasurement` already refuses a measured figure with
    no `method`. This goes one step further and checks the `raw:` path resolves
    -- a method nobody can re-run and a file nobody can open are the same
    problem.
    """
    seen = 0
    for link in cluster.links:
        for m in link.measurements:
            assert m.source is Source.MEASURED
            assert m.method.strip(), f"{link.id}: measured figure with no method"
            assert m.raw, f"{link.id}: measured figure with no raw artefact"
            assert (ROOT / m.raw).exists(), f"{link.id}: {m.raw} does not exist"
            assert m.date, f"{link.id}: measured figure with no date"
            seen += 1
    assert seen >= 8, "the E-G4 measurements are missing from the fixture"


def test_the_measured_bandwidth_matches_the_raw_file_it_points_at(cluster) -> None:
    """The one check that catches a transcription error, which is why it exists."""
    checked = 0
    for link in cluster.links:
        for m in link.measurements:
            if m.collective != "p2p":
                continue
            raw = json.loads((ROOT / m.raw).read_text())
            pair = next(iter(raw["sizes"]["256MiB"]["pairs"]))
            measured = raw["sizes"]["256MiB"]["pairs"][pair]["bandwidth_gbps"]
            assert abs(m.bus_bw_gbps - measured) < 0.01, (
                f"{link.id}: fixture says {m.bus_bw_gbps}, "
                f"{m.raw} says {measured}"
            )
            checked += 1
    assert checked >= 4


def test_world_size_is_part_of_the_key_and_the_figures_differ(cluster) -> None:
    """8.71 against 19.34 over the same wires. If these ever collide, one of
    them silently answers for the other, which is the substitution the key
    exists to stop."""
    by_world: dict[int, set[float]] = {}
    for link in cluster.links:
        for m in link.measurements:
            if m.collective == "all_reduce":
                by_world.setdefault(m.world_size, set()).add(m.bus_bw_gbps)
    assert 2 in by_world and 4 in by_world
    assert max(by_world[4]) < min(by_world[2]), (
        "a four-rank all-reduce should be slower than a two-rank one over the "
        "same path; if not, the two measurements have been swapped"
    )


def test_nothing_is_priced_so_no_cost_objective_can_be_computed(cluster) -> None:
    """Unpriced is a deliberate state, not an oversight.

    Nobody has given this lab machine an hourly price. A partial sum would rank
    the under-priced plan cheapest, so every device is explicitly `None` and
    E-G5 reports cost as uncomputed rather than as zero.
    """
    for accel in cluster.nodes[0].accelerators:
        assert accel.price_per_hour_usd is None


# --- the model, against what the wire did (GS-22) --------------------------

def _flow(graph, fid: str, src: int, dst: int, mib: int = 64) -> CommFlow:
    return CommFlow(
        flow_id=fid, kind="pd_kv_transfer",
        participants=(f"a40x8/gpu{src}", f"a40x8/gpu{dst}"),
        bytes_per_event=float(mib << 20), events_per_request=1.0,
        on_critical_path="none",
        allowed_paths=(path_set(graph, f"a40x8/gpu{src}", f"a40x8/gpu{dst}"),),
    )


def _rates(graph, pairs, mib: int = 64) -> dict[str, float]:
    flows = [_flow(graph, fid, a, b, mib) for fid, a, b in pairs]
    times = contention_model("fluid").transfer_times_ns(flows, graph)
    size = (mib << 20) / GB
    return {k: size / (v / 1e9) for k, v in times.items()}


@pytest.mark.parametrize(
    "name,pairs,expected",
    [
        # E-G4, 256 MiB plateau: 25.12 alone, 25.11 each concurrently.
        ("disjoint ports do not contend",
         [("a", 0, 2), ("b", 1, 3)], {"a": 25.12, "b": 25.12}),
        # Different NUMA halves, different ports. Also measured: 25.11 each.
        ("different NUMA halves do not contend",
         [("a", 0, 2), ("b", 4, 6)], {"a": 25.12, "b": 25.12}),
        # The one case that DOES contend, and processor sharing gets it right:
        # measured 12.5 GB/s each from 16 to 64 MiB.
        ("both directions of one link share a port",
         [("a", 0, 2), ("b", 2, 0)], {"a": 12.56, "b": 12.56}),
    ],
)
def test_the_shared_resource_model_reproduces_the_measurements(
    graph, name, pairs, expected
) -> None:
    rates = _rates(graph, pairs)
    for fid, want in expected.items():
        assert abs(rates[fid] - want) < 0.1, f"{name}: {fid} got {rates[fid]:.2f}"


def test_a_background_reservation_lands_on_one_port_not_the_whole_bridge(
    cluster, graph
) -> None:
    """The measurement that killed the per-bridge model.

    A generator holding gpu1-gpu3 at a measured 0.60 duty cycle left gpu0-gpu2
    at its unloaded rate to three digits. Under a per-bridge resource both
    models predicted a 2.5x slowdown (146 % error). Reserving `port-gpu1` here
    must leave `port-gpu0` untouched.
    """
    import dataclasses

    resources = dict(graph.shared_resources)
    resources["port-gpu1"] = dataclasses.replace(
        resources["port-gpu1"], reserved_bytes_per_s=15.0 * GB
    )
    loaded = dataclasses.replace(graph, shared_resources=resources)
    assert abs(_rates(loaded, [("a", 0, 2)])["a"] - 25.12) < 0.1, (
        "a reservation on gpu1's port changed gpu0->gpu2; the resource model "
        "has gone back to a shared bridge"
    )
    assert _rates(loaded, [("b", 1, 3)])["b"] < 25.12, (
        "the reservation did not affect the port it was placed on"
    )


def test_the_node_is_one_peer_capable_island_and_that_is_recorded(
    cluster, graph
) -> None:
    """Deliberately unlike heteropilot's own a40 fixtures, which model two
    size-4 islands. Measured: `can_device_access_peer(0, 4)` is True and the
    cross-NUMA copy sustains 22.58 GB/s. The divergence is in the file header;
    this pins that it is still true."""
    islands = detect_islands(cluster, load_profiles_for(cluster, ROOT))
    assert len(islands) == 1
    assert len(islands[0].accelerator_ids) == 8
    assert 8 in islands[0].max_tp_candidates
    assert "one island of 8" in Path(FIXTURE).read_text()
