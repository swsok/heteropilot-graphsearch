"""The normalised resource graph: the one physical representation everything reads.

`ClusterSpecV2` is a description of an inventory. It is not a graph you can run
max-flow over: its links are undirected, its bandwidth field is named for bits
and holds bytes, its shared resources are either a bare name (v1's
`contention_group`) or a capacity that no edge points back at, and in v1 there
are no CPU or switch vertices at all. Every one of those is fine for the
planner, which reasons about islands. None of it is enough to answer "what is
the cut between these four ranks, given what something else already holds".

So this module normalises once, and everything downstream - paths, demand,
equivalence, bounds - reads the result rather than the YAML. Three things are
fixed here and nowhere else:

* **Units.** Internally bytes/s and ns. `bandwidth_gbps` keeps its heteropilot
  meaning (GB/s in spite of the name) and is converted here; `bandwidth_unit`
  may select bits at `schema_version: 2`.
* **Direction.** A `bidir` link becomes two edges, each carrying the full
  capacity. That is the optimistic reading, and a bound built on it stays a
  bound. `duplex: half` is the exception: the two directions then share one
  auto-created resource, because on a half-duplex wire they genuinely do.
* **Shared capacity.** Every contended resource becomes both a `SharedResource`
  and an auxiliary `res:<id>` vertex, so a path can be said to *traverse* it and
  a cut can subtract what is already reserved.

Determinism is a property callers depend on: vertices, edges and resources are
built in sorted order and `digest()` hashes a sorted JSON rendering, so the same
cluster gives the same digest whatever order its YAML happened to list things in.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.inventory import (  # noqa: E402
    AcceleratorProfile,
    ClusterSpecV2,
    LinkMeasurement,
    LinkType,
    Source,
)
from planner.util import provenance as prov  # noqa: E402

#: Bytes per second in one "GB/s" and one "Gbit/s". heteropilot's
#: `bandwidth_gbps` is GB/s despite the name (`planner/topology.py`), and D120
#: records that v2 did not renumber it.
_UNIT_TO_BYTES_PER_S: dict[str, float] = {
    "GB/s": 1e9,
    "Gbit/s": 1e9 / 8.0,
}


class UnitError(ValueError):
    """An unrecognised bandwidth unit. Never guessed: a wrong guess is 8x."""


def bytes_per_s(value: float, unit: str) -> float:
    """`(64, "GB/s") -> 6.4e10`; `(8, "Gbit/s") -> 1e9`."""
    try:
        factor = _UNIT_TO_BYTES_PER_S[unit]
    except KeyError:
        raise UnitError(
            f"unknown bandwidth unit {unit!r}; expected one of "
            f"{sorted(_UNIT_TO_BYTES_PER_S)}"
        ) from None
    return float(value) * factor


class VertexKind(str, enum.Enum):
    ACCELERATOR = "accelerator"
    CPU_SOCKET = "cpu_socket"
    PCIE_SWITCH = "pcie_switch"
    NIC = "nic"
    NET_SWITCH = "net_switch"
    #: Not a device. An auxiliary vertex standing for a contended capacity, so
    #: that "this path crosses that uplink" is expressible as graph reachability
    #: rather than as a side table.
    SHARED_RESOURCE = "shared_resource"


@dataclass(frozen=True)
class Vertex:
    #: `<node>/<device>` for anything inside a node, the bare id for a
    #: net_switch, `res:<id>` for a shared resource.
    id: str
    kind: VertexKind
    #: None for cluster-scoped vertices (net switches, and resources that name
    #: no node).
    node_id: str | None
    attrs: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DirectedEdge:
    #: `<link_id>:fwd` / `<link_id>:rev`.
    id: str
    src: str
    dst: str
    link_type: LinkType
    capacity_bytes_per_s: float
    latency_ns: float
    rdma_capable: bool | None
    p2p_capable: bool | None
    shared_resource_id: str | None
    source: Source
    #: heteropilot's measured effective bandwidths, carried through untouched.
    #: They are NOT used to build capacity here: a measured average is not a
    #: guaranteed ceiling, so a bound computed from one would not be sound
    #: (heteropilot D112, and its §6 "실측 속도의 용도").
    measurements: tuple[LinkMeasurement, ...] = ()


@dataclass(frozen=True)
class SharedResource:
    id: str
    capacity_bytes_per_s: float
    #: Held by traffic this planner does not control. Every bound subtracts it
    #: before doing anything else.
    reserved_bytes_per_s: float
    kind: str
    node_id: str | None
    source: Source = Source.PLACEHOLDER

    @property
    def available_bytes_per_s(self) -> float:
        return max(0.0, self.capacity_bytes_per_s - self.reserved_bytes_per_s)


@dataclass(frozen=True)
class ResourceGraph:
    schema_version: int
    cluster_id: str
    vertices: Mapping[str, Vertex]
    edges: Mapping[str, DirectedEdge]
    shared_resources: Mapping[str, SharedResource]
    #: Hash over everything that can change between two readings of the same
    #: cluster - the snapshot id, every reservation, every accelerator state.
    #: A plan is re-checked against this before it is deployed.
    snapshot_version: str
    #: Where normalisation had to assume something. A v1 `contention_group` has
    #: no capacity, so one is invented and said so here.
    unit_notes: tuple[str, ...] = ()

    def out_edges(self, vertex_id: str) -> Sequence[DirectedEdge]:
        return [e for e in self.edges.values() if e.src == vertex_id]

    def in_edges(self, vertex_id: str) -> Sequence[DirectedEdge]:
        return [e for e in self.edges.values() if e.dst == vertex_id]

    def accelerators(self) -> Sequence[Vertex]:
        return [v for v in self.vertices.values() if v.kind is VertexKind.ACCELERATOR]

    def subgraph(self, vertex_ids: Collection[str]) -> ResourceGraph:
        """The graph induced on `vertex_ids`, keeping only edges with both ends in it.

        `snapshot_version` is carried over unchanged: a subgraph is a view of the
        same reading, not a new one.
        """
        keep = set(vertex_ids)
        vertices = {k: v for k, v in self.vertices.items() if k in keep}
        edges = {
            k: e for k, e in self.edges.items() if e.src in keep and e.dst in keep
        }
        used = {e.shared_resource_id for e in edges.values() if e.shared_resource_id}
        return ResourceGraph(
            schema_version=self.schema_version,
            cluster_id=self.cluster_id,
            vertices=vertices,
            edges=edges,
            shared_resources={
                k: r for k, r in self.shared_resources.items() if k in used
            },
            snapshot_version=self.snapshot_version,
            unit_notes=self.unit_notes,
        )

    def digest(self) -> str:
        """Structure and attributes, order-independent.

        Two clusters that describe the same hardware hash the same however their
        YAML was ordered; two that differ in a shared uplink do not. The second
        half is what the equivalence layer leans on, so it is asserted directly
        in the tests rather than left implied.
        """
        return prov.hash_object(_canonical(self))


def _canonical(graph: ResourceGraph) -> dict:
    return {
        "schema_version": graph.schema_version,
        "vertices": sorted(
            [v.id, v.kind.value, v.node_id, _jsonable(v.attrs)]
            for v in graph.vertices.values()
        ),
        "edges": sorted(
            [
                e.id, e.src, e.dst, e.link_type.value,
                e.capacity_bytes_per_s, e.latency_ns,
                e.rdma_capable, e.p2p_capable, e.shared_resource_id,
                e.source.value,
                sorted(str(m.key) for m in e.measurements),
            ]
            for e in graph.edges.values()
        ),
        "shared_resources": sorted(
            [r.id, r.capacity_bytes_per_s, r.reserved_bytes_per_s, r.kind, r.node_id]
            for r in graph.shared_resources.values()
        ),
    }


def _jsonable(value: object) -> object:
    """Attrs may hold enums and nested models; render them stably."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


# --- construction ---------------------------------------------------------

def _resource_vertex_id(resource_id: str) -> str:
    return f"res:{resource_id}"


def _accelerator_attrs(
    accel, node, profile: AcceleratorProfile | None
) -> dict[str, object]:
    """What a candidate graph labels an accelerator with.

    Price falls back from the device to its profile, because v2 lets a single
    machine override a model-wide figure. Power prefers the measured curve's
    active draw over a datasheet TDP for the same reason the profile does.
    Runtime capabilities are passed through as None when unstated - a checker
    must be able to tell "unsupported" from "nobody wrote it down".
    """
    price = accel.price_per_hour_usd
    if price is None and profile is not None:
        price = profile.price_per_hour_usd

    active_power_w: float | None = None
    if profile is not None:
        if profile.power is not None:
            active_power_w = profile.power.active_power
        elif profile.tdp_w is not None:
            active_power_w = profile.tdp_w

    caps = None
    if profile is not None and profile.runtime_capabilities is not None:
        caps = profile.runtime_capabilities.model_dump(mode="json")

    return {
        "model": accel.model,
        "backend": accel.backend,
        "memory_bytes": float(accel.memory_gb) * 1e9,
        "state": accel.state.value,
        "profile_id": profile.profile_id if profile is not None else None,
        "sim_hardware": profile.sim_hardware if profile is not None else None,
        "price_per_hour_usd": price,
        "active_power_w": active_power_w,
        "runtime_capabilities": caps,
        "node_price_per_hour_usd": node.host_price_per_hour_usd,
    }


def _declared_resources(
    cluster: ClusterSpecV2,
) -> tuple[dict[str, SharedResource], list[str]]:
    out: dict[str, SharedResource] = {}
    notes: list[str] = []
    for spec in sorted(cluster.shared_resources, key=lambda r: r.id):
        capacity = bytes_per_s(spec.capacity, spec.unit)
        out[spec.id] = SharedResource(
            id=spec.id,
            capacity_bytes_per_s=capacity,
            reserved_bytes_per_s=bytes_per_s(spec.reserved, spec.unit),
            kind=spec.kind,
            node_id=spec.node,
            source=spec.source,
        )
    return out, notes


def _contention_group_resources(
    cluster: ClusterSpecV2, capacities: Mapping[str, float]
) -> tuple[dict[str, SharedResource], list[str]]:
    """v1's `contention_group`, given the only capacity that is defensible.

    The field names a sharing relation and stops there. A cut bound needs a
    number, and the one number we can defend is the slowest member link: the
    group cannot carry more than its narrowest participant, so using it keeps
    the bound optimistic-but-sound. It is still an invention, so it is recorded
    in `unit_notes` and carries `source: placeholder` - a reader comparing two
    v1 clusters must be able to see that neither capacity was measured.
    """
    members: dict[str, list[str]] = {}
    for link in cluster.links:
        if link.contention_group is not None:
            members.setdefault(link.contention_group, []).append(link.id)

    out: dict[str, SharedResource] = {}
    notes: list[str] = []
    for group in sorted(members):
        capacity = min(capacities[link_id] for link_id in sorted(members[group]))
        out[group] = SharedResource(
            id=group,
            capacity_bytes_per_s=capacity,
            reserved_bytes_per_s=0.0,
            kind="other",
            node_id=None,
            source=Source.PLACEHOLDER,
        )
        notes.append(
            f"contention_group {group!r} declares no capacity (schema_version 1); "
            f"assumed {capacity:.6g} B/s, the slowest of its "
            f"{len(members[group])} member link(s), and reserved 0"
        )
    return out, notes


def _half_duplex_resource(link_id: str, capacity: float) -> SharedResource:
    """The two directions of a half-duplex wire really do contend.

    Everywhere else a `bidir` link becomes two full-capacity edges, which is the
    optimistic reading a bound is allowed. Half duplex is not optimism, it is
    wrong: the wire carries one direction at a time. So the pair is bound to one
    resource whose capacity is the wire's.
    """
    return SharedResource(
        id=f"halfdup:{link_id}",
        capacity_bytes_per_s=capacity,
        reserved_bytes_per_s=0.0,
        kind="other",
        node_id=None,
        source=Source.PLACEHOLDER,
    )


def _snapshot_version(cluster: ClusterSpecV2) -> str:
    """Everything that can differ between two readings of one cluster."""
    return prov.hash_object(
        {
            "snapshot_id": cluster.snapshot_id,
            "reserved": sorted(
                [r.id, bytes_per_s(r.reserved, r.unit)]
                for r in cluster.shared_resources
            ),
            "accelerator_state": sorted(
                [f"{node.id}/{a.id}", a.state.value]
                for node in cluster.nodes
                for a in node.accelerators
            ),
        }
    )


def build_resource_graph(
    cluster: ClusterSpecV2, profiles: Mapping[str, AcceleratorProfile]
) -> ResourceGraph:
    """Normalise a cluster into the graph every later stage reads.

    `profiles` is keyed by accelerator model, as `load_profiles_for` returns it.
    A model with no profile is not an error here - the generator's first stage
    is what rejects it - so the vertex is built with `profile_id: None` and the
    decision is left to whoever asks.
    """
    vertices: dict[str, Vertex] = {}
    unit_notes: list[str] = []

    for node in sorted(cluster.nodes, key=lambda n: n.id):
        for accel in sorted(node.accelerators, key=lambda a: a.id):
            vertices[f"{node.id}/{accel.id}"] = Vertex(
                id=f"{node.id}/{accel.id}",
                kind=VertexKind.ACCELERATOR,
                node_id=node.id,
                attrs=_accelerator_attrs(accel, node, profiles.get(accel.model)),
            )
        for nic in sorted(node.nics, key=lambda n: n.id):
            vertices[f"{node.id}/{nic.id}"] = Vertex(
                id=f"{node.id}/{nic.id}", kind=VertexKind.NIC, node_id=node.id,
                attrs={"type": nic.type, "speed_gbps": nic.speed_gbps},
            )
        for socket in sorted(node.cpu_sockets, key=lambda s: s.id):
            vertices[f"{node.id}/{socket.id}"] = Vertex(
                id=f"{node.id}/{socket.id}", kind=VertexKind.CPU_SOCKET,
                node_id=node.id, attrs={"numa_node": socket.numa_node},
            )
        for switch in sorted(node.pcie_switches, key=lambda s: s.id):
            vertices[f"{node.id}/{switch.id}"] = Vertex(
                id=f"{node.id}/{switch.id}", kind=VertexKind.PCIE_SWITCH,
                node_id=node.id, attrs={"upstream": switch.upstream},
            )

    for switch in sorted(cluster.net_switches, key=lambda s: s.id):
        vertices[switch.id] = Vertex(
            id=switch.id, kind=VertexKind.NET_SWITCH, node_id=None,
            attrs={"ports": switch.ports},
        )

    # Capacity per link first: the v1 contention-group fallback needs them all
    # before it can pick the slowest of a group.
    capacities: dict[str, float] = {}
    for link in cluster.links:
        capacities[link.id] = bytes_per_s(link.bandwidth_gbps, link.bandwidth_unit)

    resources, notes = _declared_resources(cluster)
    unit_notes.extend(notes)
    group_resources, notes = _contention_group_resources(cluster, capacities)
    unit_notes.extend(notes)
    resources.update(group_resources)

    edges: dict[str, DirectedEdge] = {}
    for link in sorted(cluster.links, key=lambda x: x.id):
        capacity = capacities[link.id]
        resource_id = link.shared_resource or link.contention_group
        half_duplex = link.duplex == "half"
        if half_duplex:
            if resource_id is not None:
                # Two resources on one edge cannot both be honoured, and picking
                # silently would make a bound wrong in a way nothing reports.
                raise ValueError(
                    f"link {link.id}: duplex 'half' needs its own shared resource, "
                    f"but the link already names {resource_id!r}; the two would "
                    f"contend for the same edge and only one could be charged"
                )
            resource = _half_duplex_resource(link.id, capacity)
            resources[resource.id] = resource
            resource_id = resource.id
            unit_notes.append(
                f"link {link.id!r} is half duplex: its two directions share "
                f"{resource.id!r} rather than each carrying full capacity"
            )

        directions = [("fwd", link.src, link.dst)]
        if link.direction == "bidir":
            directions.append(("rev", link.dst, link.src))
        for suffix, src, dst in directions:
            edge_id = f"{link.id}:{suffix}"
            edges[edge_id] = DirectedEdge(
                id=edge_id, src=src, dst=dst, link_type=link.type,
                capacity_bytes_per_s=capacity, latency_ns=link.latency_ns,
                rdma_capable=link.rdma, p2p_capable=link.p2p,
                shared_resource_id=resource_id, source=link.source,
                measurements=tuple(link.measurements),
            )

    for resource in sorted(resources.values(), key=lambda r: r.id):
        vertex_id = _resource_vertex_id(resource.id)
        vertices[vertex_id] = Vertex(
            id=vertex_id, kind=VertexKind.SHARED_RESOURCE, node_id=resource.node_id,
            attrs={
                "capacity_bytes_per_s": resource.capacity_bytes_per_s,
                "reserved_bytes_per_s": resource.reserved_bytes_per_s,
                "res_kind": resource.kind,
                "source": resource.source.value,
            },
        )

    return ResourceGraph(
        schema_version=cluster.schema_version,
        cluster_id=cluster.cluster_id,
        vertices=vertices,
        edges=edges,
        shared_resources=resources,
        snapshot_version=_snapshot_version(cluster),
        unit_notes=tuple(unit_notes),
    )


def edges_using(graph: ResourceGraph, resource_id: str) -> Sequence[DirectedEdge]:
    """Every edge charged to one shared resource, in id order."""
    return sorted(
        (e for e in graph.edges.values() if e.shared_resource_id == resource_id),
        key=lambda e: e.id,
    )


def vertex_ids_of(vertices: Iterable[Vertex]) -> tuple[str, ...]:
    return tuple(sorted(v.id for v in vertices))
