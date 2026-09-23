"""Allowed paths, cut capacity, and what sits outside a candidate but affects it.

This is where a bound stops being "the slowest link on one route" and becomes
"the total capacity of the cut between these ranks". The difference matters: two
accelerators joined by four parallel 10 GB/s links are not a 10 GB/s pair, and a
bound that says they are will reject a candidate that would have worked. A
pruning stage may only reject when the *most optimistic* arithmetic already
misses the constraint, so the optimistic arithmetic has to be right.

Three deliberate choices, each of which makes the answer larger (more
optimistic) rather than smaller, because that is the safe direction for a
lower bound on time:

* **Nominal capacities, not measured ones.** A measured effective bandwidth is
  an average, not a guaranteed ceiling (heteropilot D112), so it cannot floor a
  transfer time. Measurements travel on the edges for a ranker to use.
* **No per-flow contention.** Every flow is priced as if it had the cut to
  itself. Modelling the interaction is `contention.py`'s job, from G11, and the
  MVP ships a null implementation.
* **A shared resource is modelled as one gate.** `to_networkx` splits it into
  `res:<id>_in -> res:<id>_out` with the available capacity on the middle edge.
  That bounds the *total* through the resource correctly, and it also lets flow
  enter by one member link and leave by another, which real hardware would not.
  Over-connecting inflates the cut, which is again the optimistic direction.
  It is recorded in `CutCapacity.assumptions` rather than left for a reader to
  rediscover.

**An external reservation is subtracted first.** A cut computed over full
capacity, when something outside this deployment already holds 6 of 10 GB/s, is
not optimistic - it is wrong, and no later measurement rescues a plan sized
against bandwidth that was never there.
"""

from __future__ import annotations

import itertools
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import networkx as nx

from graphsearch import paths_root
from graphsearch.schema import DirectedEdge, ResourceGraph, VertexKind

paths_root.ensure_importable()

from planner.inventory import LinkType  # noqa: E402

#: Suffixes for the two halves a shared resource is split into.
_RES_IN = "_in"
_RES_OUT = "_out"


@dataclass(frozen=True)
class PathPolicy:
    """Which paths a caller is willing to count.

    `require_rdma` treats an UNSTATED capability as not satisfied, the same way
    an unmeasurable constraint is reported rather than assumed (heteropilot D2).
    A v1 cluster states nothing, so the flag is opt-in and off by default;
    turning it on there correctly finds no paths, and the reason says why.
    """

    max_hops: int = 8
    require_rdma: bool = False
    allowed_types: frozenset[LinkType] | None = None


#: The default for every entry point. Frozen, so one shared instance is safe,
#: and a single object makes "no policy was given" visible in a traceback.
DEFAULT_POLICY = PathPolicy()


@dataclass(frozen=True)
class Path:
    edges: tuple[str, ...]
    #: Slowest LINK on the path. Shared-resource availability is deliberately
    #: not folded in - see `effective_bottleneck_bytes_per_s`.
    bottleneck_bytes_per_s: float
    latency_ns: float
    shared_resources: frozenset[str]

    @property
    def hops(self) -> int:
        return len(self.edges)


@dataclass(frozen=True)
class PathSet:
    src: str
    dst: str
    #: Sorted by (hops, -bottleneck, edge ids), so a caller taking `paths[0]`
    #: gets the same path on every run.
    paths: tuple[Path, ...] = ()
    notes: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.paths)

    @property
    def best(self) -> Path | None:
        return self.paths[0] if self.paths else None


@dataclass(frozen=True)
class CutCapacity:
    src_set: frozenset[str]
    dst_set: frozenset[str]
    bytes_per_s: float
    #: Resources running at their available capacity in the max-flow solution:
    #: the ones a measurement would most change.
    saturating_resources: frozenset[str]
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class BoundaryContext:
    """What lies outside a candidate's devices but decides its communication.

    The equivalence layer reads this. Two placements identical in every local
    attribute but crossing different uplinks are NOT interchangeable, and
    `shared_resources` plus `reserved_bytes_per_s` is what tells them apart.
    """

    transit_vertices: frozenset[str] = frozenset()
    shared_resources: frozenset[str] = frozenset()
    reserved_bytes_per_s: Mapping[str, float] = field(default_factory=dict)


# --- edge filtering -------------------------------------------------------

def _edge_admitted(edge: DirectedEdge, policy: PathPolicy) -> tuple[bool, str | None]:
    if policy.allowed_types is not None and edge.link_type not in policy.allowed_types:
        return False, f"link_type {edge.link_type.value} not in allowed_types"
    if policy.require_rdma:
        if edge.rdma_capable is None:
            return False, "rdma not stated (unstated is not satisfied)"
        if edge.rdma_capable is False:
            return False, "rdma stated false"
    return True, None


def admitted_edges(
    graph: ResourceGraph, policy: PathPolicy
) -> tuple[list[DirectedEdge], tuple[str, ...]]:
    """Edges the policy allows, and a note per reason anything was dropped."""
    kept: list[DirectedEdge] = []
    reasons: dict[str, int] = {}
    for edge in sorted(graph.edges.values(), key=lambda e: e.id):
        ok, why = _edge_admitted(edge, policy)
        if ok:
            kept.append(edge)
        elif why is not None:
            reasons[why] = reasons.get(why, 0) + 1
    notes = tuple(
        f"{count} edge(s) excluded: {why}" for why, count in sorted(reasons.items())
    )
    return kept, notes


# --- networkx rendering ---------------------------------------------------

def to_networkx(graph: ResourceGraph, policy: PathPolicy = DEFAULT_POLICY) -> nx.DiGraph:
    """A flow network over the admitted edges, with each resource as one gate.

    A shared resource becomes `res:<id>_in -> res:<id>_out` carrying its
    AVAILABLE capacity, and every edge charged to it is routed through that
    pair. This bounds the total correctly. It also lets flow enter by one member
    link and leave by another, which the hardware would not do; that
    over-connects the graph and inflates the cut, which is the optimistic
    direction a bound is allowed. `cut_capacity` records it.

    Nodes and edges are added in sorted order so that anything downstream which
    iterates the graph is deterministic.
    """
    out = nx.DiGraph()
    edges, _ = admitted_edges(graph, policy)

    for vertex_id in sorted(graph.vertices):
        if graph.vertices[vertex_id].kind is VertexKind.SHARED_RESOURCE:
            continue
        out.add_node(vertex_id)

    gated = {e.shared_resource_id for e in edges if e.shared_resource_id}
    for resource_id in sorted(gated):
        resource = graph.shared_resources[resource_id]
        node_in = f"res:{resource_id}{_RES_IN}"
        node_out = f"res:{resource_id}{_RES_OUT}"
        out.add_node(node_in)
        out.add_node(node_out)
        out.add_edge(
            node_in, node_out,
            capacity=resource.available_bytes_per_s,
            latency_ns=0.0, resource=resource_id, gate=True,
        )

    for edge in edges:
        if edge.shared_resource_id is None:
            _accumulate(out, edge.src, edge.dst, edge)
            continue
        node_in = f"res:{edge.shared_resource_id}{_RES_IN}"
        node_out = f"res:{edge.shared_resource_id}{_RES_OUT}"
        _accumulate(out, edge.src, node_in, edge)
        _accumulate(out, node_out, edge.dst, edge)
    return out


def _accumulate(out: nx.DiGraph, src: str, dst: str, edge: DirectedEdge) -> None:
    """Parallel links between one pair add up; a DiGraph holds one edge."""
    if out.has_edge(src, dst):
        data = out[src][dst]
        data["capacity"] += edge.capacity_bytes_per_s
        data["latency_ns"] = min(data["latency_ns"], edge.latency_ns)
        data["links"] = tuple(sorted({*data["links"], edge.id}))
    else:
        out.add_edge(
            src, dst,
            capacity=edge.capacity_bytes_per_s,
            latency_ns=edge.latency_ns,
            resource=edge.shared_resource_id,
            links=(edge.id,),
            gate=False,
        )


# --- paths ----------------------------------------------------------------

def _device_graph(
    graph: ResourceGraph, policy: PathPolicy
) -> tuple[nx.DiGraph, dict[tuple[str, str], list[DirectedEdge]]]:
    """Devices only, resources recorded as an edge attribute rather than a hop.

    Enumerating paths over the split flow network would report the gate vertices
    as hops and make `max_hops` mean something different for a shared link than
    for a private one.
    """
    out = nx.DiGraph()
    parallel: dict[tuple[str, str], list[DirectedEdge]] = {}
    for vertex_id in sorted(graph.vertices):
        if graph.vertices[vertex_id].kind is not VertexKind.SHARED_RESOURCE:
            out.add_node(vertex_id)
    edges, _ = admitted_edges(graph, policy)
    for edge in edges:
        parallel.setdefault((edge.src, edge.dst), []).append(edge)
        if not out.has_edge(edge.src, edge.dst):
            out.add_edge(edge.src, edge.dst)
    return out, parallel


def path_set(
    graph: ResourceGraph, src: str, dst: str, policy: PathPolicy = DEFAULT_POLICY
) -> PathSet:
    """Simple paths from `src` to `dst`, shortest first, capped at `max_hops`.

    Where two links join the same pair, the fastest is taken for the path's
    bottleneck: a path is one route, and the caller that wants the pair's total
    capacity wants `cut_capacity` instead.
    """
    device_graph, parallel = _device_graph(graph, policy)
    _, notes = admitted_edges(graph, policy)

    if src not in device_graph or dst not in device_graph:
        return PathSet(src=src, dst=dst, notes=(*notes, f"{src} or {dst} is not a vertex"))
    if src == dst:
        return PathSet(src=src, dst=dst, notes=(*notes, "src and dst are the same vertex"))

    found: list[Path] = []
    try:
        for hop_list in nx.shortest_simple_paths(device_graph, src, dst):
            if len(hop_list) - 1 > policy.max_hops:
                break
            chosen: list[DirectedEdge] = []
            for a, b in itertools.pairwise(hop_list):
                chosen.append(
                    max(parallel[(a, b)], key=lambda e: (e.capacity_bytes_per_s, e.id))
                )
            found.append(
                Path(
                    edges=tuple(e.id for e in chosen),
                    bottleneck_bytes_per_s=min(e.capacity_bytes_per_s for e in chosen),
                    latency_ns=sum(e.latency_ns for e in chosen),
                    shared_resources=frozenset(
                        e.shared_resource_id for e in chosen if e.shared_resource_id
                    ),
                )
            )
    except nx.NetworkXNoPath:
        pass

    found.sort(key=lambda p: (p.hops, -p.bottleneck_bytes_per_s, p.edges))
    if not found:
        notes = (*notes, f"no path from {src} to {dst} under this policy")
    return PathSet(src=src, dst=dst, paths=tuple(found), notes=notes)


def effective_bottleneck_bytes_per_s(graph: ResourceGraph, path: Path) -> float:
    """The path's bottleneck with external reservations taken off.

    Kept separate from `Path.bottleneck_bytes_per_s` because the two answer
    different questions: one is a property of the wire, the other is what this
    deployment can actually have today. A predictor and a ranker want this one.
    """
    limits = [path.bottleneck_bytes_per_s]
    limits.extend(
        graph.shared_resources[r].available_bytes_per_s for r in sorted(path.shared_resources)
    )
    return min(limits)


# --- cuts -----------------------------------------------------------------

_BASE_ASSUMPTIONS = (
    "max-flow over NOMINAL capacities minus external reservation; measured "
    "effective bandwidths are not used, because an average is not a ceiling",
    "no per-flow contention: each flow is priced as if it had the cut to itself",
    "a shared resource is one gate, so flow may enter by one member link and "
    "leave by another; this over-connects and inflates the cut, which is the "
    "optimistic direction a bound is allowed",
)

#: Super source/sink ids. `$` cannot appear in a vertex id: those are
#: `<node>/<device>`, a bare switch id, or `res:<id>`.
_SUPER_SRC = "$src"
_SUPER_DST = "$dst"


def cut_capacity(
    graph: ResourceGraph,
    src_set: Collection[str],
    dst_set: Collection[str],
    policy: PathPolicy = DEFAULT_POLICY,
) -> CutCapacity:
    """Optimistic total capacity from `src_set` to `dst_set`.

    This is the number a communication-latency bound divides into, so it must
    never be *under*-stated: a cut smaller than reality rejects a candidate that
    would have met its SLO, which is exactly the failure the "a pruning stage is
    a relaxation" rule forbids.
    """
    sources, sinks = sorted(set(src_set)), sorted(set(dst_set))
    flow_graph = to_networkx(graph, policy)
    _, filter_notes = admitted_edges(graph, policy)
    assumptions = (*_BASE_ASSUMPTIONS, *filter_notes)

    overlap = set(sources) & set(sinks)
    if overlap:
        raise ValueError(
            f"cut_capacity: {sorted(overlap)} is on both sides; a cut between a "
            f"set and itself is not defined"
        )
    missing = [v for v in (*sources, *sinks) if v not in flow_graph]
    if not sources or not sinks or missing:
        why = (
            "one side is empty"
            if not sources or not sinks
            else f"{missing} unreachable under this policy"
        )
        return CutCapacity(
            src_set=frozenset(sources), dst_set=frozenset(sinks), bytes_per_s=0.0,
            saturating_resources=frozenset(),
            assumptions=(*assumptions, f"no capacity: {why}"),
        )

    flow_graph.add_node(_SUPER_SRC)
    flow_graph.add_node(_SUPER_DST)
    for vertex in sources:
        flow_graph.add_edge(_SUPER_SRC, vertex, capacity=float("inf"))
    for vertex in sinks:
        flow_graph.add_edge(vertex, _SUPER_DST, capacity=float("inf"))

    value, flow = nx.maximum_flow(flow_graph, _SUPER_SRC, _SUPER_DST)

    saturating = {
        data["resource"]
        for a, b, data in flow_graph.edges(data=True)
        if data.get("gate")
        and data["capacity"] > 0
        and flow[a][b] >= data["capacity"] - 1e-9
    }
    if value == 0.0:
        assumptions = (*assumptions, "no path carries flow under this policy")
    return CutCapacity(
        src_set=frozenset(sources),
        dst_set=frozenset(sinks),
        bytes_per_s=float(value),
        saturating_resources=frozenset(saturating),
        assumptions=assumptions,
    )


# --- boundary -------------------------------------------------------------

def boundary_context(
    graph: ResourceGraph,
    devices: Collection[str],
    paths: Iterable[PathSet],
) -> BoundaryContext:
    """Everything the candidate touches that is not one of its own devices.

    Two placements can hold identical accelerators and still be different
    candidates, because one of them crosses a NIC something else is already
    using. That is what this carries into the equivalence signature; without it,
    the two fold together and the search loses a difference it was built to see.
    """
    own = set(devices)
    transit: set[str] = set()
    resources: set[str] = set()
    for path_set_ in paths:
        for path in path_set_.paths:
            for edge_id in path.edges:
                edge = graph.edges[edge_id]
                transit.update({edge.src, edge.dst} - own)
                if edge.shared_resource_id is not None:
                    resources.add(edge.shared_resource_id)
    return BoundaryContext(
        transit_vertices=frozenset(transit),
        shared_resources=frozenset(resources),
        reserved_bytes_per_s={
            r: graph.shared_resources[r].reserved_bytes_per_s for r in sorted(resources)
        },
    )


def all_pairs(
    graph: ResourceGraph, members: Sequence[str], policy: PathPolicy = DEFAULT_POLICY
) -> tuple[PathSet, ...]:
    """Every ordered pair's path set, in sorted order. Used by the demand layer."""
    ordered = sorted(set(members))
    return tuple(
        path_set(graph, a, b, policy)
        for a in ordered
        for b in ordered
        if a != b
    )
