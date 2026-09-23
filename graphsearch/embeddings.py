"""Island-level templates become placements on named physical devices.

heteropilot's `CandidateConfig` says "two accelerators of island
`cuda-toygpu-nodeA`, tensor-parallel". It does not say *which* two, because the
planner treats an island's devices as interchangeable. Inside one node that is
usually true. Across a cluster it is not: two GPUs behind a saturated uplink and
two behind a free one are the same candidate to the planner and different
candidates to the hardware.

So this layer un-folds the template into every distinct physical choice, and
G6 folds it back by *proved* equivalence rather than by assumption. Expanding
before compressing is the whole point - the compression is only meaningful
against an enumeration that did not already merge things silently.

Three things keep the expansion honest:

* **Symmetry is removed, not relied on.** Replicas are unordered and so are the
  ranks inside one, so `{a,b},{c,d}` and `{c,d},{a,b}` are one embedding.
  `canonical_only` skips the duplicates and COUNTS them, because a count of
  what was skipped is the difference between "we removed symmetry" and "we hope
  we did".
* **A cap is a scope statement, not a filter.** When
  `max_embeddings_per_template` truncates, the template's id goes into
  `EmbeddingStats.truncated_template_ids` and G7 turns that into an
  `EXCLUDED_BY_SCOPE` rejection. Dropped-for-budget is not infeasible, and the
  output has to be able to say which it was.
* **Locality survives truncation.** With `hierarchical`, groupings whose ranks
  share a PCIe switch, then a socket, then a node are enumerated first - so a
  cap keeps the placements most likely to be feasible instead of the
  alphabetically first.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from graphsearch import paths_root
from graphsearch.demand import CommFlow, FlowKind, RankGroup, flows_for
from graphsearch.paths import (
    DEFAULT_POLICY,
    BoundaryContext,
    PathPolicy,
    boundary_context,
)
from graphsearch.schema import ResourceGraph, VertexKind

paths_root.ensure_importable()

from planner.inventory import AcceleratorState, ExecutionIsland  # noqa: E402
from planner.plan import CandidateConfig  # noqa: E402
from planner.spec import ServiceSpec  # noqa: E402
from planner.util import provenance as prov  # noqa: E402


@dataclass(frozen=True)
class RankPlacement:
    """One replica's ranks, as physical vertex ids in a fixed order."""

    assignment_index: int
    replica: int
    ranks: tuple[str, ...]

    def key(self) -> tuple:
        return (self.assignment_index, self.ranks)


@dataclass(frozen=True)
class EmbeddedCandidate:
    """A template plus the devices it runs on, and what that costs in traffic."""

    template: CandidateConfig
    #: Hash of the sorted placements. Two embeddings with the same devices in
    #: the same roles are the same embedding whatever order they were built in.
    embedding_key: str
    placements: tuple[RankPlacement, ...]
    devices: frozenset[str]
    #: Non-device vertices the flows traverse - NICs, switches, resource gates.
    transit_closure: frozenset[str]
    flows: tuple[CommFlow, ...]
    boundary: BoundaryContext
    #: shared resource id -> bytes/s this candidate would put through it.
    resource_demand: Mapping[str, float] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.template.id}@{self.embedding_key[:12]}"

    @property
    def nodes(self) -> frozenset[str]:
        return frozenset(d.split("/")[0] for d in self.devices)


@dataclass(frozen=True)
class EmbeddingPolicy:
    #: None means "every one". A number is a BUDGET, and what it drops is
    #: reported as out of scope rather than silently absent.
    max_embeddings_per_template: int | None = None
    #: Enumerate the most local groupings first, so a cap keeps them.
    hierarchical: bool = True
    #: Fold re-orderings of one placement into a single embedding. Off
    #: measures how much symmetry a cluster had -- and then ids repeat, by
    #: design, because the key is over the SORTED placements.
    canonical_only: bool = True


DEFAULT_EMBEDDING_POLICY = EmbeddingPolicy()


@dataclass
class EmbeddingStats:
    templates: int = 0
    embeddings: int = 0
    #: Re-orderings of an already-emitted placement. A count, not a hope.
    skipped_symmetric: int = 0
    truncated_by_policy: int = 0
    truncated_template_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "templates": self.templates,
            "embeddings": self.embeddings,
            "skipped_symmetric": self.skipped_symmetric,
            "truncated_by_policy": self.truncated_by_policy,
            "truncated_template_ids": sorted(self.truncated_template_ids),
        }


# --- locality -------------------------------------------------------------

def _neighbours_of_kind(
    graph: ResourceGraph, device_id: str, kind: VertexKind
) -> frozenset[str]:
    out = set()
    for edge in graph.edges.values():
        for near, far in ((edge.src, edge.dst), (edge.dst, edge.src)):
            if near != device_id:
                continue
            vertex = graph.vertices.get(far)
            if vertex is not None and vertex.kind is kind:
                out.add(far)
    return frozenset(out)


def _locality_score(graph: ResourceGraph, ranks: Sequence[str]) -> tuple[int, int, int]:
    """How tightly a replica's ranks sit together: switch, socket, node.

    Counted over unordered pairs. Where a cluster declares no PCIe topology -
    every v1 file, and the toy v2 ones - the first two terms are zero for
    everything and the node term does the ordering, which is the sensible
    degradation rather than an error.
    """
    switch = socket = same_node = 0
    for a, b in itertools.combinations(sorted(ranks), 2):
        if _neighbours_of_kind(graph, a, VertexKind.PCIE_SWITCH) & _neighbours_of_kind(
            graph, b, VertexKind.PCIE_SWITCH
        ):
            switch += 1
        if _neighbours_of_kind(graph, a, VertexKind.CPU_SOCKET) & _neighbours_of_kind(
            graph, b, VertexKind.CPU_SOCKET
        ):
            socket += 1
        if a.split("/")[0] == b.split("/")[0]:
            same_node += 1
    return switch, socket, same_node


# --- enumeration ----------------------------------------------------------

def _ordered_groupings(
    devices: Sequence[str], replicas: int, per_replica: int
) -> Iterator[tuple[tuple[str, ...], ...]]:
    """Split `devices` into `replicas` ORDERED groups of `per_replica`.

    Replicas are interchangeable -- two decode replicas differ only in which
    requests a router sends them, and the planner does not model the router --
    so `({a,b},{c,d})` and `({c,d},{a,b})` are one placement. They could be
    collapsed here, by fixing the lowest device into the first group.

    They are not, on purpose. Collapsing by construction makes
    `EmbeddingStats.skipped_symmetric` structurally zero, and a counter that
    cannot move is not evidence that symmetry was removed - it is a claim with
    nothing behind it. Enumerating the orderings and letting the canonical key
    fold them makes the number real, and `canonical_only=False` then measures
    how much symmetry a cluster had. The cost is a factor of `replicas!`, paid
    in list building rather than in simulation.
    """
    if replicas == 0:
        yield ()
        return
    for group in itertools.combinations(devices, per_replica):
        remaining = [d for d in devices if d not in group]
        for tail in _ordered_groupings(remaining, replicas - 1, per_replica):
            yield (tuple(sorted(group)), *tail)


def _assignment_options(
    assignment, island: ExecutionIsland, graph: ResourceGraph, policy: EmbeddingPolicy,
    used: frozenset[str],
) -> list[tuple[tuple[str, ...], ...]]:
    """Every way this assignment could sit on its island, best-local first."""
    free = [
        f"{island.node_id}/{accel_id}"
        for accel_id in sorted(island.accelerator_ids)
        if f"{island.node_id}/{accel_id}" not in used
        and _is_free(graph, f"{island.node_id}/{accel_id}")
    ]
    need = assignment.total_devices
    if len(free) < need:
        return []

    options: list[tuple[tuple[str, ...], ...]] = []
    for chosen in itertools.combinations(free, need):
        options.extend(
            _ordered_groupings(
                list(chosen), assignment.dp_replicas, assignment.devices_per_replica
            )
        )
    if policy.hierarchical:
        options.sort(
            key=lambda groups: (
                tuple(-s for s in _locality_score(graph, sum(groups, ()))),
                groups,
            )
        )
    else:
        options.sort()
    return options


def _is_free(graph: ResourceGraph, device_id: str) -> bool:
    vertex = graph.vertices.get(device_id)
    if vertex is None:
        return False
    return vertex.attrs.get("state") == AcceleratorState.FREE.value


def _canonical_key(placements: Sequence[RankPlacement]) -> str:
    return prov.hash_object(
        sorted([p.assignment_index, list(p.ranks)] for p in placements)
    )


def _resource_demand(
    flows: Sequence[CommFlow], graph: ResourceGraph, spec: ServiceSpec
) -> dict[str, float]:
    """Bytes per second each shared resource would carry for this candidate.

    Charged to the FIRST allowed path, which is the one a caller taking
    `paths[0]` would use. A flow with several routes really spreads across them;
    charging one is pessimistic for that resource and optimistic for the others,
    so this figure is for reporting and conflict detection (G6), never for a
    bound. `cut_capacity` is what a bound reads.
    """
    rate = spec.traffic.arrival_rate_rps
    demand: dict[str, float] = {}
    for flow in flows:
        if not flow.allowed_paths:
            continue
        best = flow.allowed_paths[0].best
        if best is None:
            continue
        per_second = flow.bytes_per_request * rate
        for resource_id in sorted(best.shared_resources):
            demand[resource_id] = demand.get(resource_id, 0.0) + per_second
    return demand


def _transit_closure(
    flows: Sequence[CommFlow], graph: ResourceGraph, devices: frozenset[str]
) -> frozenset[str]:
    out: set[str] = set()
    for flow in flows:
        for path_set_ in flow.allowed_paths:
            for path in path_set_.paths:
                for edge_id in path.edges:
                    edge = graph.edges[edge_id]
                    out.update({edge.src, edge.dst} - devices)
                    if edge.shared_resource_id is not None:
                        out.add(f"res:{edge.shared_resource_id}")
    return frozenset(out)


def _build(
    template: CandidateConfig,
    placements: tuple[RankPlacement, ...],
    spec: ServiceSpec,
    graph: ResourceGraph,
    path_policy: PathPolicy,
) -> EmbeddedCandidate:
    groups = [
        RankGroup(
            assignment_index=p.assignment_index,
            replica=p.replica,
            role=template.assignments[p.assignment_index].role,
            tp_size=template.assignments[p.assignment_index].tp_size,
            pp_size=template.assignments[p.assignment_index].pp_size,
            ranks=p.ranks,
        )
        for p in placements
    ]
    flows = flows_for(template, groups, spec, graph, path_policy)
    devices = frozenset(r for p in placements for r in p.ranks)
    return EmbeddedCandidate(
        template=template,
        embedding_key=_canonical_key(placements),
        placements=placements,
        devices=devices,
        transit_closure=_transit_closure(flows, graph, devices),
        flows=flows,
        boundary=boundary_context(
            graph, devices, [ps for f in flows for ps in f.allowed_paths]
        ),
        resource_demand=_resource_demand(flows, graph, spec),
    )


def _embeddings_of(
    template: CandidateConfig,
    islands: Mapping[str, ExecutionIsland],
    graph: ResourceGraph,
    spec: ServiceSpec,
    policy: EmbeddingPolicy,
    path_policy: PathPolicy,
    stats: EmbeddingStats,
) -> list[EmbeddedCandidate]:
    out: list[EmbeddedCandidate] = []
    seen: set[str] = set()
    budget = policy.max_embeddings_per_template
    produced = 0
    truncated = False

    def walk(index: int, used: frozenset[str], acc: list[RankPlacement]) -> None:
        nonlocal produced, truncated
        if truncated:
            return
        if index == len(template.assignments):
            placements = tuple(acc)
            key = _canonical_key(placements)
            if policy.canonical_only and key in seen:
                stats.skipped_symmetric += 1
                return
            seen.add(key)
            if budget is not None and produced >= budget:
                truncated = True
                return
            out.append(_build(template, placements, spec, graph, path_policy))
            produced += 1
            return

        assignment = template.assignments[index]
        island = islands.get(assignment.island_id)
        if island is None:
            raise KeyError(
                f"template {template.id}: assignment {index} names island "
                f"{assignment.island_id!r}, which is not in this inventory"
            )
        for groups in _assignment_options(assignment, island, graph, policy, used):
            # Rule (2): two assignments on one island may not overlap devices.
            flat = frozenset(d for g in groups for d in g)
            walk(
                index + 1,
                used | flat,
                acc + [
                    RankPlacement(assignment_index=index, replica=replica, ranks=g)
                    for replica, g in enumerate(groups)
                ],
            )
            if truncated:
                return

    walk(0, frozenset(), [])

    if truncated:
        # What the cap cost, counted by re-running the enumeration without the
        # budget. Cheap next to a simulation, and the alternative is reporting
        # "some were dropped", which G7 cannot turn into a number.
        full = _count_embeddings(template, islands, graph, policy)
        stats.truncated_by_policy += max(0, full - produced)
        stats.truncated_template_ids.append(template.id)
    return out


def _count_embeddings(
    template: CandidateConfig,
    islands: Mapping[str, ExecutionIsland],
    graph: ResourceGraph,
    policy: EmbeddingPolicy,
) -> int:
    total = 0
    seen: set[str] = set()

    def walk(index: int, used: frozenset[str], acc: list[RankPlacement]) -> None:
        nonlocal total
        if index == len(template.assignments):
            key = _canonical_key(tuple(acc))
            if policy.canonical_only and key in seen:
                return
            seen.add(key)
            total += 1
            return
        assignment = template.assignments[index]
        island = islands[assignment.island_id]
        for groups in _assignment_options(assignment, island, graph, policy, used):
            flat = frozenset(d for g in groups for d in g)
            walk(
                index + 1, used | flat,
                acc + [
                    RankPlacement(assignment_index=index, replica=replica, ranks=g)
                    for replica, g in enumerate(groups)
                ],
            )

    walk(0, frozenset(), [])
    return total


def enumerate_embeddings(
    templates: Sequence[CandidateConfig],
    islands: Mapping[str, ExecutionIsland],
    graph: ResourceGraph,
    spec: ServiceSpec,
    policy: EmbeddingPolicy = DEFAULT_EMBEDDING_POLICY,
    *,
    path_policy: PathPolicy = DEFAULT_POLICY,
) -> tuple[list[EmbeddedCandidate], EmbeddingStats]:
    """Every distinct physical placement of every template, in a stable order.

    The returned list is sorted by `(template.id, embedding_key)` so two runs
    produce the same sequence and a signature built over it is reproducible.
    """
    stats = EmbeddingStats(templates=len(templates))
    out: list[EmbeddedCandidate] = []
    for template in sorted(templates, key=lambda t: t.id):
        out.extend(
            _embeddings_of(
                template, islands, graph, spec, policy, path_policy, stats
            )
        )
    out.sort(key=lambda e: (e.template.id, e.embedding_key))
    stats.embeddings = len(out)
    return out, stats


def embeddings_by_template(
    embeddings: Sequence[EmbeddedCandidate],
) -> dict[str, list[EmbeddedCandidate]]:
    out: dict[str, list[EmbeddedCandidate]] = {}
    for embedding in embeddings:
        out.setdefault(embedding.template.id, []).append(embedding)
    return out


def describe(embedding: EmbeddedCandidate) -> str:
    """One line, for a render block or a test failure message."""
    devices = ", ".join(sorted(embedding.devices))
    resources = ", ".join(sorted(embedding.boundary.shared_resources)) or "none"
    return f"{embedding.id}: [{devices}] crossing [{resources}]"


def flows_of_kind(
    embedding: EmbeddedCandidate, kind: FlowKind
) -> tuple[CommFlow, ...]:
    return tuple(f for f in embedding.flows if f.kind is kind)


def canonical_json(embedding: EmbeddedCandidate) -> str:
    """Stable rendering of the placement alone, for debugging a key mismatch."""
    return json.dumps(
        sorted([p.assignment_index, list(p.ranks)] for p in embedding.placements),
        sort_keys=True,
    )
