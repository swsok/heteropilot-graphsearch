"""Turn a recommended representative back into devices you can actually take.

A plan that names a representative is not deployable. The search simulated one
exemplar and the class may stand for sixteen placements; something has to pick
which of them to run, check that the hardware is still free, and check that the
shared capacity the plan assumed has not been taken since.

**`multiplicity` is not `max_concurrent`, and this module exists to stop the
two being confused.** A representative covering sixteen placements does not mean
sixteen deployments fit: they overlap on devices, and they contend for the same
uplinks. Multiplying one representative's predicted throughput by its
multiplicity is the mistake that makes a paper number look sixteen times better
than the hardware, and `restore_many` refuses to hand out more sets than
actually coexist.

**The snapshot is re-checked, not assumed.** The graph was read once, before the
search. `recheck_snapshot` compares the plan against a later reading and reports
every difference rather than the first, because a deployer wants the whole list.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field

from graphsearch import paths_root
from graphsearch.cost import cost_of_devices
from graphsearch.embeddings import EmbeddedCandidate
from graphsearch.equivalence import ConflictMatrix, Representative
from graphsearch.schema import ResourceGraph, VertexKind

paths_root.ensure_importable()

from planner.inventory import AcceleratorState  # noqa: E402
from planner.plan import DeploymentPlan  # noqa: E402


class RestoreError(ValueError):
    """The representative cannot be placed as asked."""


@dataclass(frozen=True)
class RestoredPlan:
    """A plan bound to named devices, with what it will hold on the way out."""

    plan: DeploymentPlan
    embedding: EmbeddedCandidate
    device_ids: tuple[str, ...]
    #: shared resource id -> bytes/s this deployment will put through it.
    shared_resource_reservations: Mapping[str, float] = field(default_factory=dict)
    #: The graph reading this was chosen against.
    snapshot_version: str = ""

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(sorted({d.split("/")[0] for d in self.device_ids}))


def _free(graph: ResourceGraph, device_id: str, occupied: Collection[str]) -> bool:
    if device_id in occupied:
        return False
    vertex = graph.vertices.get(device_id)
    if vertex is None or vertex.kind is not VertexKind.ACCELERATOR:
        return False
    return vertex.attrs.get("state") == AcceleratorState.FREE.value


def _default_preference(
    graph: ResourceGraph,
) -> Callable[[EmbeddedCandidate], tuple]:
    """Cheapest first, then the lowest node id.

    A deterministic tie-break matters more than the criterion: two runs of the
    same plan must pick the same devices, or a "reproducible" plan is not one.
    """

    def key(embedding: EmbeddedCandidate) -> tuple:
        breakdown = cost_of_devices(embedding.devices, graph)
        cost = (
            float("inf")
            if breakdown.total_usd_per_hour is None
            else breakdown.total_usd_per_hour
        )
        return (cost, min(embedding.nodes, default=""), embedding.id)

    return key


def restore(
    representative: Representative,
    plan: DeploymentPlan,
    graph: ResourceGraph,
    *,
    occupied: Collection[str] = frozenset(),
    prefer: Callable[[EmbeddedCandidate], tuple] | None = None,
) -> RestoredPlan:
    """Pick one of this representative's placements and bind the plan to it.

    Every member is equivalent by construction -- G6 merged them only after VF2
    confirmed the candidate graphs isomorphic -- so any of them serves the
    prediction. Which one is a deployment decision, and `prefer` is where it
    lives.
    """
    key = prefer or _default_preference(graph)
    for embedding in sorted(representative.embeddings, key=key):
        if all(_free(graph, device, occupied) for device in sorted(embedding.devices)):
            return RestoredPlan(
                plan=plan,
                embedding=embedding,
                device_ids=tuple(sorted(embedding.devices)),
                shared_resource_reservations=dict(embedding.resource_demand),
                snapshot_version=graph.snapshot_version,
            )
    raise RestoreError(
        f"representative {representative.rep_id} stands for "
        f"{representative.multiplicity} placement(s), none of which is free "
        f"(occupied: {sorted(occupied)})"
    )


def restore_many(
    pairs: Sequence[tuple[Representative, DeploymentPlan]],
    graph: ResourceGraph,
    conflicts: ConflictMatrix,
    *,
    count: int = 1,
    prefer: Callable[[EmbeddedCandidate], tuple] | None = None,
) -> list[RestoredPlan]:
    """Bind `count` non-overlapping deployments, or say why it cannot.

    Refuses rather than over-promising. A representative's multiplicity counts
    placements, not simultaneous deployments -- they share devices and they
    share uplinks -- and returning fewer than asked without saying so is how a
    throughput figure ends up multiplied by a number the hardware never
    supported.
    """
    out: list[RestoredPlan] = []
    occupied: set[str] = set()
    chosen_ids: list[str] = []

    for representative, plan in pairs:
        while len(out) < count:
            try:
                restored = restore(
                    representative, plan, graph, occupied=occupied, prefer=prefer
                )
            except RestoreError:
                break
            if any(
                frozenset({restored.embedding.id, picked}) in conflicts.conflicts
                for picked in chosen_ids
            ):
                occupied |= set(restored.device_ids)
                continue
            over = check_capacity([*out, restored], graph)
            if over:
                occupied |= set(restored.device_ids)
                continue
            out.append(restored)
            chosen_ids.append(restored.embedding.id)
            occupied |= set(restored.device_ids)
        if len(out) >= count:
            break

    if len(out) < count:
        available = sum(r.multiplicity for r, _ in pairs)
        raise RestoreError(
            f"asked for {count} concurrent deployment(s) and only {len(out)} "
            f"coexist; the representative(s) cover {available} placement(s), "
            f"but multiplicity counts placements, not deployments -- they "
            f"overlap on devices and on shared capacity"
        )
    return out


def check_capacity(
    restored: Sequence[RestoredPlan], graph: ResourceGraph
) -> list[str]:
    """Shared resources these deployments would together over-subscribe."""
    totals: dict[str, float] = {}
    for plan in restored:
        for resource_id, demand in plan.shared_resource_reservations.items():
            totals[resource_id] = totals.get(resource_id, 0.0) + demand

    out: list[str] = []
    for resource_id in sorted(totals):
        resource = graph.shared_resources.get(resource_id)
        if resource is None:
            out.append(f"{resource_id}: not in this graph")
            continue
        if totals[resource_id] > resource.available_bytes_per_s:
            out.append(
                f"{resource_id}: {totals[resource_id]:.6g} B/s demanded against "
                f"{resource.available_bytes_per_s:.6g} B/s available "
                f"(capacity {resource.capacity_bytes_per_s:.6g}, reserved "
                f"{resource.reserved_bytes_per_s:.6g})"
            )
    return out


def recheck_snapshot(
    restored: RestoredPlan, current: ResourceGraph
) -> list[str]:
    """Every way the cluster moved since this plan was chosen.

    All of them, not the first: a deployer deciding whether to proceed wants
    the list, and stopping at the first difference hides the rest behind one
    fix.
    """
    out: list[str] = []
    if restored.snapshot_version and restored.snapshot_version != current.snapshot_version:
        out.append(
            f"snapshot moved: plan chose against {restored.snapshot_version[:12]}, "
            f"cluster now reads {current.snapshot_version[:12]}"
        )

    for device in restored.device_ids:
        vertex = current.vertices.get(device)
        if vertex is None:
            out.append(f"{device}: no longer in the inventory")
        elif vertex.attrs.get("state") != AcceleratorState.FREE.value:
            out.append(f"{device}: now {vertex.attrs.get('state')}, not FREE")

    for resource_id, demand in sorted(restored.shared_resource_reservations.items()):
        resource = current.shared_resources.get(resource_id)
        if resource is None:
            out.append(f"{resource_id}: no longer in the inventory")
        elif demand > resource.available_bytes_per_s:
            out.append(
                f"{resource_id}: {demand:.6g} B/s was planned for, only "
                f"{resource.available_bytes_per_s:.6g} B/s is now available"
            )
    return out


def describe(restored: RestoredPlan) -> str:
    devices = ", ".join(restored.device_ids)
    holds = (
        ", ".join(
            f"{k} {v:.3g} B/s"
            for k, v in sorted(restored.shared_resource_reservations.items())
        )
        or "nothing shared"
    )
    return f"{restored.plan.plan_id} -> [{devices}] holding [{holds}]"
