"""G10: bind a representative back to devices, and refuse to over-promise.

`test_multiplicity_is_not_max_concurrent` is the whole file in one line. A
representative covering sixteen placements does not mean sixteen deployments
fit -- they overlap on devices and contend for the same uplinks. Multiplying
one representative's predicted throughput by its multiplicity is how a paper
number ends up sixteen times better than the hardware.
"""

from __future__ import annotations

import pytest

from graphsearch import paths_root
from graphsearch.embeddings import enumerate_embeddings
from graphsearch.equivalence import compress
from graphsearch.restore import (
    RestoreError,
    check_capacity,
    describe,
    recheck_snapshot,
    restore,
    restore_many,
)
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import FIXTURES, load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import AcceleratorState, detect_islands  # noqa: E402
from planner.plan import DeploymentPlan, PredictedMetrics  # noqa: E402
from planner.spec import load_service_spec  # noqa: E402

MODEL = "meta-llama/Llama-3.1-8B"


def spec():
    return load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")


def world(name: str = "abcde_v2", *, limit: int = 2):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)
    service_spec = spec()
    generated = CandidateGenerator(
        service_spec, cluster, islands, profiles, enable_bound_pruning=False
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= limit]
    found, _ = enumerate_embeddings(templates, by_id, graph, service_spec)
    representatives, conflicts, _ = compress(found, graph)
    return graph, representatives, conflicts


def a_plan(representative) -> DeploymentPlan:
    return DeploymentPlan(
        plan_id="hp-00000",
        model=MODEL,
        candidate=representative.exemplar.template,
        predicted=PredictedMetrics(
            p50_ttft_ms=1.0, p95_ttft_ms=1.0, p99_ttft_ms=1.0,
            p50_tpot_ms=1.0, p95_tpot_ms=1.0, p99_tpot_ms=1.0,
            throughput_tps=1.0, slo_goodput_rps=1.0, slo_attainment=1.0,
            completed_requests=1, completed_tokens=1,
        ),
    )


def biggest(representatives):
    return max(representatives, key=lambda r: r.multiplicity)


# --- the point of the module ---------------------------------------------

def test_multiplicity_is_not_max_concurrent() -> None:
    _, representatives, conflicts = world()
    representative = biggest(representatives)
    assert representative.multiplicity == 16
    assert conflicts.max_concurrent(representative) < representative.multiplicity


def test_asking_for_more_than_coexist_is_refused_not_trimmed() -> None:
    """Returning fewer without saying so is how a throughput figure ends up
    multiplied by a number the hardware never supported."""
    graph, representatives, conflicts = world()
    representative = biggest(representatives)
    plan = a_plan(representative)
    concurrent = conflicts.max_concurrent(representative)

    assert len(restore_many([(representative, plan)], graph, conflicts,
                            count=concurrent)) == concurrent
    with pytest.raises(RestoreError, match="multiplicity counts placements"):
        restore_many(
            [(representative, plan)], graph, conflicts,
            count=representative.multiplicity,
        )


def test_the_refusal_says_what_the_numbers_mean() -> None:
    graph, representatives, conflicts = world()
    representative = biggest(representatives)
    with pytest.raises(RestoreError) as excinfo:
        restore_many(
            [(representative, a_plan(representative))], graph, conflicts, count=99
        )
    message = str(excinfo.value)
    assert "coexist" in message
    assert "overlap on devices" in message


# --- restore --------------------------------------------------------------

def test_restore_binds_the_plan_to_real_devices() -> None:
    graph, representatives, _ = world()
    representative = biggest(representatives)
    restored = restore(representative, a_plan(representative), graph)
    assert set(restored.device_ids) == set(restored.embedding.devices)
    assert all(d in graph.vertices for d in restored.device_ids)
    assert restored.snapshot_version == graph.snapshot_version


def test_restore_is_deterministic() -> None:
    """Two runs of a reproducible plan must pick the same devices."""
    graph, representatives, _ = world()
    representative = biggest(representatives)
    plan = a_plan(representative)
    assert (
        restore(representative, plan, graph).device_ids
        == restore(representative, plan, graph).device_ids
    )


def test_restore_avoids_devices_already_taken() -> None:
    graph, representatives, _ = world()
    representative = biggest(representatives)
    first = restore(representative, a_plan(representative), graph)
    second = restore(
        representative, a_plan(representative), graph,
        occupied=set(first.device_ids),
    )
    assert not set(second.device_ids) & set(first.device_ids)


def test_restore_refuses_when_nothing_is_free() -> None:
    graph, representatives, _ = world()
    representative = biggest(representatives)
    everything = {d for e in representative.embeddings for d in e.devices}
    with pytest.raises(RestoreError, match="none of which is free"):
        restore(representative, a_plan(representative), graph, occupied=everything)


def test_a_busy_device_is_not_offered() -> None:
    from dataclasses import replace

    graph, representatives, _ = world()
    representative = biggest(representatives)
    free = restore(representative, a_plan(representative), graph)

    busy = graph
    for device in free.device_ids:
        vertex = busy.vertices[device]
        attrs = dict(vertex.attrs)
        attrs["state"] = AcceleratorState.ALLOCATED.value
        busy = replace(
            busy,
            vertices={**busy.vertices, device: replace(vertex, attrs=attrs)},
        )
    after = restore(representative, a_plan(representative), busy)
    assert set(after.device_ids) != set(free.device_ids)


def test_the_plan_is_carried_by_reference_not_copied() -> None:
    """The metrics came from a simulation; re-deriving them here would be a
    second opinion nobody asked for."""
    graph, representatives, _ = world()
    representative = biggest(representatives)
    plan = a_plan(representative)
    assert restore(representative, plan, graph).plan is plan


def test_a_preference_can_be_supplied() -> None:
    graph, representatives, _ = world()
    representative = biggest(representatives)
    last = sorted(representative.embeddings, key=lambda e: e.id)[-1]
    restored = restore(
        representative, a_plan(representative), graph,
        prefer=lambda e: (0 if e.id == last.id else 1, e.id),
    )
    assert restored.embedding.id == last.id


# --- capacity -------------------------------------------------------------

def test_capacity_is_checked_across_deployments_not_one_at_a_time() -> None:
    from dataclasses import replace

    graph, representatives, _ = world()
    representative = biggest(representatives)
    restored = restore(representative, a_plan(representative), graph)

    resource_id = next(iter(restored.shared_resource_reservations), None)
    assert resource_id is not None
    available = graph.shared_resources[resource_id].available_bytes_per_s

    fits = replace(restored, shared_resource_reservations={resource_id: available * 0.4})
    assert check_capacity([fits], graph) == []
    assert check_capacity([fits, fits], graph) == []          # 0.8 of it

    third = replace(restored, shared_resource_reservations={resource_id: available * 0.4})
    over = check_capacity([fits, fits, third], graph)         # 1.2 of it
    assert over
    assert resource_id in over[0]
    assert "available" in over[0]


def test_an_unknown_resource_is_reported_not_ignored() -> None:
    from dataclasses import replace

    graph, representatives, _ = world()
    representative = biggest(representatives)
    restored = replace(
        restore(representative, a_plan(representative), graph),
        shared_resource_reservations={"ghost": 1.0},
    )
    assert any("ghost" in line for line in check_capacity([restored], graph))


# --- the snapshot ---------------------------------------------------------

def test_a_moved_snapshot_is_reported() -> None:
    graph, representatives, _ = world()
    representative = biggest(representatives)
    restored = restore(representative, a_plan(representative), graph)
    assert recheck_snapshot(restored, graph) == []

    from dataclasses import replace

    moved = replace(graph, snapshot_version="deadbeefdeadbeef")
    problems = recheck_snapshot(restored, moved)
    assert problems
    assert "snapshot moved" in problems[0]


def test_every_difference_is_reported_not_just_the_first() -> None:
    """A deployer deciding whether to proceed wants the list."""
    from dataclasses import replace

    graph, representatives, _ = world()
    representative = biggest(representatives)
    restored = restore(representative, a_plan(representative), graph)

    changed = replace(graph, snapshot_version="deadbeefdeadbeef")
    for device in restored.device_ids:
        vertex = changed.vertices[device]
        attrs = dict(vertex.attrs)
        attrs["state"] = AcceleratorState.ALLOCATED.value
        changed = replace(
            changed,
            vertices={**changed.vertices, device: replace(vertex, attrs=attrs)},
        )
    problems = recheck_snapshot(restored, changed)
    assert len(problems) == 1 + len(restored.device_ids)
    assert any("not FREE" in p for p in problems)


def test_a_reservation_taken_since_is_reported() -> None:
    from dataclasses import replace

    graph, representatives, _ = world()
    representative = biggest(representatives)
    restored = restore(representative, a_plan(representative), graph)
    resource_id = next(iter(restored.shared_resource_reservations))

    resource = graph.shared_resources[resource_id]
    squeezed = replace(
        graph,
        shared_resources={
            **graph.shared_resources,
            resource_id: replace(
                resource, reserved_bytes_per_s=resource.capacity_bytes_per_s
            ),
        },
    )
    problems = recheck_snapshot(restored, squeezed)
    assert any(resource_id in p and "now available" in p for p in problems)


# --- restore_many ---------------------------------------------------------

def test_restore_many_returns_disjoint_device_sets() -> None:
    graph, representatives, conflicts = world()
    representative = biggest(representatives)
    concurrent = conflicts.max_concurrent(representative)
    if concurrent < 2:
        pytest.skip("this representative admits only one deployment")
    restored = restore_many(
        [(representative, a_plan(representative))], graph, conflicts,
        count=min(2, concurrent),
    )
    seen: set[str] = set()
    for plan in restored:
        assert not seen & set(plan.device_ids)
        seen |= set(plan.device_ids)


def test_restore_many_of_one_is_restore() -> None:
    graph, representatives, conflicts = world()
    representative = biggest(representatives)
    plan = a_plan(representative)
    assert restore_many([(representative, plan)], graph, conflicts)[0].device_ids == (
        restore(representative, plan, graph).device_ids
    )


def test_describe_names_the_devices_and_what_they_hold() -> None:
    graph, representatives, _ = world()
    representative = biggest(representatives)
    restored = restore(representative, a_plan(representative), graph)
    text = describe(restored)
    assert restored.plan.plan_id in text
    assert restored.device_ids[0] in text
