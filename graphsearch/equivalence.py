"""Exact equivalence compression: fold placements that are provably the same.

This is the claim the research rests on, so the discipline here is narrower
than anywhere else in the package: **a hash never merges anything.**

A Weisfeiler-Lehman hash is a cheap, one-sided test. Equal structures hash
equal; equal hashes do not imply equal structures. Merging on the hash alone
would be fast and would occasionally fold two placements that differ in a way
the search was built to see - and nothing downstream could detect it, because
the two would arrive as one candidate with one prediction. So the hash only
buckets, and `is_isomorphic` (VF2) decides. A pair the budget cannot afford to
check is left UNMERGED and marked `HASH_ONLY`: an unproved equivalence is a
missed saving, which costs a simulation, while a wrong one costs the result.

What goes into the labels decides what "the same" means, and two choices are
load-bearing:

* **Identifiers are excluded.** Node and vertex ids are not in any label, so
  two nodes that are alike in every attribute compress. That is the whole
  saving: in the research design's §9 example, A and B are one representative
  and not two.
* **The boundary is included.** Shared resources a placement crosses, with
  their capacity and what is already reserved on them, are part of the graph.
  Two placements identical in every local attribute but crossing different
  uplinks are different candidates, and `include_boundary=False` is the
  ablation that proves it - with the boundary dropped, the oracle harness
  reports the mis-merge rather than the tests asserting it can happen.

`ConflictMatrix` answers a separate question, and one that is easy to conflate
with multiplicity: how many embeddings of one representative could run AT ONCE.
A representative covering 16 placements does not mean 16 deployments fit - they
overlap on devices and on shared capacity. `multiplicity != max_concurrent`,
and `restore.py` (G10) enforces it.
"""

from __future__ import annotations

import enum
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import networkx as nx
from networkx.algorithms.isomorphism import (
    DiGraphMatcher,
    categorical_edge_match,
    categorical_node_match,
)

from graphsearch import paths_root
from graphsearch.embeddings import EmbeddedCandidate
from graphsearch.schema import ResourceGraph, VertexKind

paths_root.ensure_importable()

from planner.util import provenance as prov  # noqa: E402

#: Bumped when the LABELS change. A signature computed under one label scheme
#: is not comparable with one computed under another, and a cache keyed by
#: signature would serve the wrong entry across such a change.
LABEL_SCHEME = "v1"


class EquivalenceLevel(str, enum.Enum):
    #: VF2 confirmed the isomorphism. The only level that merges.
    EXACT = "exact"
    #: Same hash bucket, isomorphism NOT checked (budget). Never merged.
    HASH_ONLY = "hash_only"
    #: Reserved for a future relaxed rule. Nothing produces it today, and
    #: nothing may merge on it without a work order that says how it is sound.
    APPROX = "approx"


@dataclass(frozen=True)
class Signature:
    wl_hash: str
    #: Multiset of vertex and edge labels. A second cheap invariant: two graphs
    #: with different label counts cannot be isomorphic, so this splits buckets
    #: the WL hash happens to collide.
    attr_histogram: str
    #: networkx version and label scheme. A WL hash is only comparable against
    #: itself (GS-2): the same graph hashed by two releases may differ, and an
    #: equivalence class silently re-cut by an upgrade would be invisible.
    tool_version: str

    def bucket(self, prediction_key: str) -> tuple[str, str, str, str]:
        return (prediction_key, self.wl_hash, self.attr_histogram, self.tool_version)


@dataclass
class Representative:
    rep_id: str
    signature: Signature
    level: EquivalenceLevel
    template_id: str
    exemplar: EmbeddedCandidate
    embeddings: list[EmbeddedCandidate] = field(default_factory=list)
    #: embedding id -> {exemplar vertex -> that embedding's vertex}. What
    #: `restore.py` uses to turn a plan back into physical devices.
    role_mappings: dict[str, dict[str, str]] = field(default_factory=dict)
    #: The exemplar's demand on each shared resource, bytes/s.
    resource_usage: dict[str, float] = field(default_factory=dict)

    @property
    def multiplicity(self) -> int:
        """How many placements this stands for. NOT how many can run at once."""
        return len(self.embeddings)


@dataclass(frozen=True)
class ConflictMatrix:
    """Which embeddings cannot coexist, over all representatives."""

    conflicts: frozenset[frozenset[str]] = frozenset()

    def conflicting(self, embedding_id: str) -> frozenset[str]:
        out: set[str] = set()
        for pair in self.conflicts:
            if embedding_id in pair:
                out |= set(pair) - {embedding_id}
        return frozenset(out)

    def max_concurrent(self, representative: Representative) -> int:
        """A GREEDY LOWER BOUND on how many of this rep's embeddings coexist.

        Exact maximum independent set is NP-hard and the number is used to stop
        a caller over-claiming, so a lower bound is the safe side: under-stating
        how many fit refuses a deployment that would have worked, while
        over-stating ships one that does not. Never present this as exact.
        """
        chosen: list[str] = []
        for embedding in sorted(representative.embeddings, key=lambda e: e.id):
            if all(
                frozenset({embedding.id, picked}) not in self.conflicts
                for picked in chosen
            ):
                chosen.append(embedding.id)
        return len(chosen)


@dataclass(frozen=True)
class CompressionPolicy:
    enabled: bool = True
    wl_iterations: int = 3
    #: Wall-clock budget for VF2 across the whole run. None means no budget.
    #: What it cannot afford stays unmerged, never merged on the hash.
    max_vf2_seconds: float | None = None
    #: Include the shared resources a placement crosses. False is the ablation
    #: that shows what dropping them costs; it is not a mode to plan in.
    include_boundary: bool = True
    include_prices: bool = True


DEFAULT_COMPRESSION_POLICY = CompressionPolicy()


@dataclass
class CompressionReport:
    embeddings_in: int = 0
    representatives_out: int = 0
    #: Embeddings folded into an existing representative after a VF2 check.
    exact_merges: int = 0
    #: Buckets left unchecked because the VF2 budget ran out.
    hash_only_groups: int = 0
    vf2_calls: int = 0
    vf2_seconds: float = 0.0

    @property
    def ratio(self) -> float | None:
        if not self.embeddings_in:
            return None
        return self.representatives_out / self.embeddings_in

    def as_dict(self) -> dict:
        return {
            "embeddings_in": self.embeddings_in,
            "representatives_out": self.representatives_out,
            "exact_merges": self.exact_merges,
            "hash_only_groups": self.hash_only_groups,
            "vf2_calls": self.vf2_calls,
            "vf2_seconds": round(self.vf2_seconds, 4),
            "compression_ratio": None if self.ratio is None else round(self.ratio, 6),
        }


def prediction_key(template) -> str:
    """Everything that changes a prediction and is NOT in the candidate graph.

    The bucket key cannot simply be the template id. Two placements on
    different islands are different templates, and folding them is precisely
    the saving this work exists to get -- the research design's §9 counts node
    A and node B as one representative, and a template-keyed bucket would keep
    them apart forever (GS-5).

    It cannot be nothing either. The graph carries hardware, topology, roles and
    parallelism, but not the vLLM knobs, the serving architecture, the dtype or
    the model: two templates differing only in `max_num_seqs` have identical
    graphs and simulate differently, so merging them would be a real mis-merge
    of exactly the kind VF2 is here to prevent.

    So the key is `CandidateConfig.signature()` with the island ids removed --
    what is left of a template once the graph has accounted for placement.
    """
    return prov.hash_object(
        {
            "model": template.model,
            "dtype": template.dtype,
            "serving_arch": template.serving_arch.value,
            "topology_mode": template.topology_mode,
            "knobs": sorted(template.knobs.model_dump().items()),
        }
    )


# --- labels ---------------------------------------------------------------

def _role_of(embedding: EmbeddedCandidate, device_id: str) -> dict:
    for placement in embedding.placements:
        if device_id in placement.ranks:
            assignment = embedding.template.assignments[placement.assignment_index]
            return {
                "role": assignment.role.value,
                "assignment_index": placement.assignment_index,
                "tp": assignment.tp_size,
                "pp": assignment.pp_size,
                "slot": "tp_member",
            }
    return {}


def _vertex_label(
    embedding: EmbeddedCandidate,
    graph: ResourceGraph,
    vertex_id: str,
    policy: CompressionPolicy,
) -> str:
    """What makes two vertices the same KIND of vertex.

    Identifiers are deliberately absent: the whole saving is that two nodes
    alike in every attribute compress into one representative.
    """
    vertex = graph.vertices[vertex_id]
    if vertex.kind is VertexKind.ACCELERATOR:
        label: dict = {
            "kind": vertex.kind.value,
            "model": vertex.attrs.get("model"),
            "backend": vertex.attrs.get("backend"),
            "memory_bytes": vertex.attrs.get("memory_bytes"),
            "profile_id": vertex.attrs.get("profile_id"),
            "power_w": vertex.attrs.get("active_power_w"),
            **_role_of(embedding, vertex_id),
        }
        if policy.include_prices:
            label["price"] = vertex.attrs.get("price_per_hour_usd")
            label["host_price"] = vertex.attrs.get("node_price_per_hour_usd")
        return json.dumps(label, sort_keys=True, default=str)

    if vertex.kind is VertexKind.SHARED_RESOURCE:
        return json.dumps(
            {
                "kind": "shared_resource",
                "capacity": vertex.attrs.get("capacity_bytes_per_s"),
                "reserved": vertex.attrs.get("reserved_bytes_per_s"),
                "res_kind": vertex.attrs.get("res_kind"),
            },
            sort_keys=True,
            default=str,
        )

    return json.dumps({"kind": vertex.kind.value}, sort_keys=True)


def _edge_label(graph: ResourceGraph, edge_id: str) -> str:
    edge = graph.edges[edge_id]
    return json.dumps(
        {
            "link_type": edge.link_type.value,
            "capacity": edge.capacity_bytes_per_s,
            "latency": edge.latency_ns,
            "rdma": edge.rdma_capable,
            "p2p": edge.p2p_capable,
            # Keys only, not values: WHICH conditions were measured is a
            # structural property; the figures themselves are a ranker's input
            # and two links measured to different numbers under the same
            # conditions are still the same kind of link.
            "measurement_keys": sorted(str(m.key) for m in edge.measurements),
        },
        sort_keys=True,
        default=str,
    )


def candidate_graph(
    embedding: EmbeddedCandidate,
    graph: ResourceGraph,
    policy: CompressionPolicy = DEFAULT_COMPRESSION_POLICY,
) -> nx.DiGraph:
    """The labelled subgraph two placements are compared as.

    Vertices: the candidate's devices, what its flows transit, and - unless the
    ablation is on - the shared resources it crosses. Edges: every graph edge
    with both ends inside that set.
    """
    keep = set(embedding.devices) | set(embedding.transit_closure)
    if policy.include_boundary:
        keep |= set(embedding.boundary.transit_vertices)
        keep |= {f"res:{r}" for r in embedding.boundary.shared_resources}
    else:
        keep -= {v for v in keep if v.startswith("res:")}
    keep &= set(graph.vertices)

    out = nx.DiGraph()
    for vertex_id in sorted(keep):
        out.add_node(vertex_id, label=_vertex_label(embedding, graph, vertex_id, policy))
    for edge_id in sorted(graph.edges):
        edge = graph.edges[edge_id]
        if edge.src in keep and edge.dst in keep:
            out.add_edge(edge.src, edge.dst, label=_edge_label(graph, edge_id))
    return out


def _histogram(candidate: nx.DiGraph) -> str:
    labels: dict[str, int] = {}
    for _, data in candidate.nodes(data=True):
        labels[f"v:{data['label']}"] = labels.get(f"v:{data['label']}", 0) + 1
    for _, _, data in candidate.edges(data=True):
        labels[f"e:{data['label']}"] = labels.get(f"e:{data['label']}", 0) + 1
    return prov.hash_object(sorted(labels.items()))


def signature(
    embedding: EmbeddedCandidate,
    graph: ResourceGraph,
    policy: CompressionPolicy = DEFAULT_COMPRESSION_POLICY,
) -> Signature:
    candidate = candidate_graph(embedding, graph, policy)
    return Signature(
        wl_hash=nx.weisfeiler_lehman_graph_hash(
            candidate, node_attr="label", edge_attr="label",
            iterations=policy.wl_iterations,
        ),
        attr_histogram=_histogram(candidate),
        tool_version=f"networkx=={nx.__version__};labels={LABEL_SCHEME}",
    )


# --- compression ----------------------------------------------------------

_NODE_MATCH = categorical_node_match("label", None)
_EDGE_MATCH = categorical_edge_match("label", None)


def _isomorphic(a: nx.DiGraph, b: nx.DiGraph) -> tuple[bool, dict[str, str]]:
    matcher = DiGraphMatcher(a, b, node_match=_NODE_MATCH, edge_match=_EDGE_MATCH)
    if matcher.is_isomorphic():
        return True, dict(matcher.mapping)
    return False, {}


def compress(
    embeddings: Sequence[EmbeddedCandidate],
    graph: ResourceGraph,
    policy: CompressionPolicy = DEFAULT_COMPRESSION_POLICY,
) -> tuple[list[Representative], ConflictMatrix, CompressionReport]:
    """Fold embeddings into representatives, merging only what VF2 confirms.

    The returned list is sorted by `rep_id`, and `rep_id` derives from the
    exemplar's id, so two runs over the same input produce the same partition
    in the same order.
    """
    report = CompressionReport(embeddings_in=len(embeddings))
    if not policy.enabled:
        reps = [
            Representative(
                rep_id=f"rep-{e.id}", signature=signature(e, graph, policy),
                level=EquivalenceLevel.EXACT, template_id=e.template.id,
                exemplar=e, embeddings=[e],
                role_mappings={e.id: {v: v for v in candidate_graph(e, graph, policy)}},
                resource_usage=dict(e.resource_demand),
            )
            for e in sorted(embeddings, key=lambda e: e.id)
        ]
        report.representatives_out = len(reps)
        return reps, conflict_matrix(embeddings, graph), report

    buckets: dict[tuple, list[Representative]] = {}
    graphs: dict[str, nx.DiGraph] = {}
    order: list[Representative] = []
    budget_spent = 0.0

    for embedding in sorted(embeddings, key=lambda e: e.id):
        sig = signature(embedding, graph, policy)
        candidate = candidate_graph(embedding, graph, policy)
        key = sig.bucket(prediction_key(embedding.template))
        merged = False

        for representative in buckets.get(key, []):
            if policy.max_vf2_seconds is not None and budget_spent >= policy.max_vf2_seconds:
                # Out of budget. The bucket stays split and is marked so; an
                # unproved equivalence costs a simulation, a wrong one costs
                # the result.
                if representative.level is not EquivalenceLevel.HASH_ONLY:
                    representative.level = EquivalenceLevel.HASH_ONLY
                    report.hash_only_groups += 1
                break

            started = time.perf_counter()
            same, mapping = _isomorphic(graphs[representative.rep_id], candidate)
            elapsed = time.perf_counter() - started
            budget_spent += elapsed
            report.vf2_calls += 1
            report.vf2_seconds += elapsed

            if same:
                representative.embeddings.append(embedding)
                representative.role_mappings[embedding.id] = mapping
                report.exact_merges += 1
                merged = True
                break

        if not merged:
            representative = Representative(
                rep_id=f"rep-{embedding.id}",
                signature=sig,
                level=EquivalenceLevel.EXACT,
                template_id=embedding.template.id,
                exemplar=embedding,
                embeddings=[embedding],
                role_mappings={embedding.id: {v: v for v in candidate}},
                resource_usage=dict(embedding.resource_demand),
            )
            buckets.setdefault(key, []).append(representative)
            graphs[representative.rep_id] = candidate
            order.append(representative)

    order.sort(key=lambda r: r.rep_id)
    report.representatives_out = len(order)
    return order, conflict_matrix(embeddings, graph), report


def conflict_matrix(
    embeddings: Sequence[EmbeddedCandidate], graph: ResourceGraph
) -> ConflictMatrix:
    """Pairs that cannot be deployed together.

    Two reasons, and both are about the same hardware being asked for twice:
    a shared device, or a shared resource whose available capacity the two
    demands together exceed. Computed over embeddings rather than
    representatives, because two placements of ONE representative are exactly
    the case a caller is most likely to over-claim.
    """
    conflicts: set[frozenset[str]] = set()
    # By id: the same embedding listed twice is one placement, not two that
    # clash with each other, and `frozenset({x, x})` would silently become a
    # one-element "pair" that no caller could interpret.
    unique = {e.id: e for e in embeddings}
    ordered = [unique[k] for k in sorted(unique)]
    for index, a in enumerate(ordered):
        for b in ordered[index + 1 :]:
            if a.devices & b.devices:
                conflicts.add(frozenset({a.id, b.id}))
                continue
            for resource_id in set(a.resource_demand) & set(b.resource_demand):
                resource = graph.shared_resources.get(resource_id)
                if resource is None:
                    continue
                together = a.resource_demand[resource_id] + b.resource_demand[resource_id]
                if together > resource.available_bytes_per_s:
                    conflicts.add(frozenset({a.id, b.id}))
                    break
    return ConflictMatrix(conflicts=frozenset(conflicts))


def representatives_by_template(
    representatives: Sequence[Representative],
) -> Mapping[str, list[Representative]]:
    out: dict[str, list[Representative]] = {}
    for representative in representatives:
        out.setdefault(representative.template_id, []).append(representative)
    return out


def multiplicities(representatives: Sequence[Representative]) -> list[int]:
    """Sorted, for a compression table or a test."""
    return sorted(r.multiplicity for r in representatives)
