"""What a candidate actually sends, and when it is on the critical path.

Three consumers read this and they must agree, or the search contradicts
itself: the bound (G7) divides a flow's bytes by the cut, the ranker (G8)
divides them by a measured path, and the adapter (G11) hands the simulator a
link bandwidth derived from the same route. If those three each computed "how
much does a TP group send" on their own, a fix to one would silently leave the
other two wrong.

**The all-reduce formula is a deliberate second implementation.**
`planner/candidate_generator.py` already has it, in the stage-4 topology bound,
and the obvious move is to import it. It is not exported, extracting it would
mean editing heteropilot for our convenience, and a shared implementation would
make the two agree *by construction* - which sounds good until you notice that
agreement then proves nothing. So the arithmetic is written out again here, and
`tests/test_demand.py` parses the floor out of heteropilot's own rejection
string and checks the two land within 0.05 ms. If either side drifts, that test
says so; a shared helper would not have.

A flow is bytes and a count, never a time. Turning it into a time needs a path
or a cut, and which of those is correct depends on the caller - so it is the
caller's to do.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from graphsearch import paths_root
from graphsearch.paths import DEFAULT_POLICY, PathPolicy, PathSet, path_set
from graphsearch.schema import ResourceGraph

paths_root.ensure_importable()

from planner.inventory import ExecutionIsland  # noqa: E402
from planner.plan import CandidateConfig, IslandAssignment, Role, ServingArch  # noqa: E402
from planner.spec import ServiceSpec  # noqa: E402
from planner.util import kv_transfer  # noqa: E402
from planner.util import memory as memutil  # noqa: E402

CriticalPath = Literal["ttft", "tpot", "both", "none"]


class FlowKind(str, enum.Enum):
    TP_ALLREDUCE = "tp_allreduce"
    PP_ACTIVATION = "pp_activation"
    PD_KV_TRANSFER = "pd_kv_transfer"
    INGRESS = "ingress"
    EGRESS = "egress"


@dataclass(frozen=True)
class CommFlow:
    flow_id: str
    kind: FlowKind
    #: Vertex ids, sorted. For a collective these are the ranks; for ingress
    #: and egress, the device and the NIC.
    participants: tuple[str, ...]
    bytes_per_event: float
    events_per_request: float
    #: Which SLO this flow's time lands in. `none` means it is real traffic
    #: that no latency target charges for - it still consumes a shared
    #: resource, which is why it is enumerated at all.
    on_critical_path: CriticalPath
    allowed_paths: tuple[PathSet, ...] = ()
    assumptions: tuple[str, ...] = ()

    @property
    def bytes_per_request(self) -> float:
        return self.bytes_per_event * self.events_per_request


# --- the arithmetic -------------------------------------------------------

def tp_allreduce_bytes(model: str, dtype: str, tp: int) -> float:
    """Bytes one rank moves in one ring all-reduce of a hidden-sized tensor.

    `hidden * bytes_per_elem * 2(tp-1)/tp`. The ring factor is why tp=2 and
    tp=4 are not the same figure over one wire, and why heteropilot asks its
    topology model for a world-size-specific bandwidth rather than an island
    default.

    tp=1 is 0: there is no collective to run.
    """
    if tp < 1:
        raise ValueError(f"tp must be >= 1, got {tp}")
    if tp == 1:
        return 0.0
    cfg = memutil.model_config(model)
    payload = cfg["hidden_size"] * (memutil.dtype_bits(dtype) // 8)
    return float(payload) * (2.0 * (tp - 1) / tp)


def tp_allreduces_per_output_token(model: str) -> int:
    """Two per layer - attention output and MLP output."""
    return 2 * memutil.model_config(model)["num_hidden_layers"]


def pd_kv_bytes(
    model: str, dtype: str, kv_cache_dtype: str, prompt_tokens: int
) -> float:
    """KV bytes a prefill engine hands a decode engine for one request.

    Sized at tp=1 on purpose, by `planner.util.kv_transfer`: the whole
    per-token KV cache crosses the wire however the prefill engine sharded it.
    Reused rather than reimplemented - unlike the all-reduce formula, there is
    no second implementation to cross-check here, so sharing is the safer side.
    """
    per_token = kv_transfer._kv_bytes_per_token(model, dtype, kv_cache_dtype)
    return float(per_token) * float(prompt_tokens)


def pp_activation_bytes(model: str, dtype: str, batch_tokens: int = 1) -> float:
    """One hidden-sized activation crossing a pipeline stage boundary."""
    cfg = memutil.model_config(model)
    return float(cfg["hidden_size"] * (memutil.dtype_bits(dtype) // 8) * batch_tokens)


# --- placements -----------------------------------------------------------

@dataclass(frozen=True)
class RankGroup:
    """One replica's ranks, as physical vertex ids."""

    assignment_index: int
    replica: int
    role: Role
    tp_size: int
    pp_size: int
    ranks: tuple[str, ...]


def placements_from_islands(
    template: CandidateConfig, islands: Mapping[str, ExecutionIsland]
) -> tuple[RankGroup, ...]:
    """A stand-in placement: take each island's first free devices, in order.

    G5 replaces this with real enumeration over every physical embedding. Until
    then it lets the demand model be exercised against a `CandidateConfig`,
    which names islands and not devices.
    """
    groups: list[RankGroup] = []
    for index, assignment in enumerate(template.assignments):
        island = islands[assignment.island_id]
        need = assignment.devices_per_replica
        cursor = 0
        for replica in range(assignment.dp_replicas):
            ids = island.accelerator_ids[cursor : cursor + need]
            cursor += need
            if len(ids) < need:
                raise ValueError(
                    f"island {island.id} has {len(island.accelerator_ids)} devices, "
                    f"too few for {assignment.dp_replicas} replicas of "
                    f"{need} (assignment {index})"
                )
            groups.append(
                RankGroup(
                    assignment_index=index,
                    replica=replica,
                    role=assignment.role,
                    tp_size=assignment.tp_size,
                    pp_size=assignment.pp_size,
                    ranks=tuple(f"{island.node_id}/{d}" for d in ids),
                )
            )
    return tuple(groups)


# --- flows ----------------------------------------------------------------

def _pair_paths(
    graph: ResourceGraph, members: Sequence[str], policy: PathPolicy
) -> tuple[PathSet, ...]:
    ordered = sorted(set(members))
    return tuple(
        path_set(graph, a, b, policy)
        for i, a in enumerate(ordered)
        for b in ordered[i + 1 :]
    )


def _nic_of(graph: ResourceGraph, vertex_id: str) -> str | None:
    """The first NIC on the same node, in id order. None if the node has none."""
    node_id = graph.vertices[vertex_id].node_id if vertex_id in graph.vertices else None
    if node_id is None:
        return None
    from graphsearch.schema import VertexKind

    nics = sorted(
        v.id
        for v in graph.vertices.values()
        if v.kind is VertexKind.NIC and v.node_id == node_id
    )
    return nics[0] if nics else None


def _tp_flow(
    group: RankGroup, index: int, spec: ServiceSpec, graph: ResourceGraph,
    policy: PathPolicy,
) -> CommFlow | None:
    if group.tp_size < 2:
        return None
    per_token = tp_allreduces_per_output_token(spec.model)
    return CommFlow(
        flow_id=f"tp:{group.assignment_index}:{group.replica}",
        kind=FlowKind.TP_ALLREDUCE,
        participants=tuple(sorted(group.ranks)),
        bytes_per_event=tp_allreduce_bytes(
            spec.model, spec.service.dtype, group.tp_size
        ),
        # Per REQUEST, so the per-token figure is multiplied by the median
        # output length. p50 and not p99: unlike TTFT, a TPOT target is a
        # per-token rate and the tail length does not change the rate.
        events_per_request=float(per_token * spec.traffic.output_tokens.p50),
        on_critical_path="tpot",
        allowed_paths=_pair_paths(graph, group.ranks, policy),
        assumptions=(
            f"ring all-reduce, factor 2(tp-1)/tp at tp={group.tp_size}",
            f"{per_token} all-reduces per output token (2 per layer)",
            "no overlap with compute",
        ),
    )


def _pp_flow(
    group: RankGroup, spec: ServiceSpec, graph: ResourceGraph, policy: PathPolicy
) -> CommFlow | None:
    if group.pp_size < 2:
        return None
    return CommFlow(
        flow_id=f"pp:{group.assignment_index}:{group.replica}",
        kind=FlowKind.PP_ACTIVATION,
        participants=tuple(sorted(group.ranks)),
        bytes_per_event=pp_activation_bytes(spec.model, spec.service.dtype),
        events_per_request=float(group.pp_size - 1),
        # Both: a stage boundary is crossed once on the way to the first token
        # and again for every token after it.
        on_critical_path="both",
        allowed_paths=_pair_paths(graph, group.ranks, policy),
        assumptions=("one hidden-sized activation per stage boundary",),
    )


def _pd_flows(
    groups: Sequence[RankGroup], spec: ServiceSpec, graph: ResourceGraph,
    policy: PathPolicy,
) -> list[CommFlow]:
    """Prefill replica i hands decode replica i its KV, pairwise by index.

    The router's real policy is not this, but the planner does not model a
    router; what a bound needs is that each prefill has somewhere to send to and
    that the path it would take is priced. Pairing by index is stated as an
    assumption rather than presented as the schedule.
    """
    prefill = [g for g in groups if g.role is Role.PREFILL]
    decode = [g for g in groups if g.role is Role.DECODE]
    if not prefill or not decode:
        return []

    bytes_p50 = pd_kv_bytes(
        spec.model, spec.service.dtype, spec.service.kv_cache_dtype,
        spec.traffic.input_tokens.p50,
    )
    tail = []
    for name in ("p95", "p99"):
        tokens = getattr(spec.traffic.input_tokens, name)
        if tokens is not None:
            tail_bytes = pd_kv_bytes(
                spec.model, spec.service.dtype, spec.service.kv_cache_dtype, tokens
            )
            tail.append(f"{name} prompt {tokens} tok -> {tail_bytes:.6g} B")

    out: list[CommFlow] = []
    for index in range(max(len(prefill), len(decode))):
        src = prefill[index % len(prefill)]
        dst = decode[index % len(decode)]
        # The first rank of each side: the KV lands on one device and is
        # re-sharded locally, so the wire carries it once.
        a, b = sorted(src.ranks)[0], sorted(dst.ranks)[0]
        out.append(
            CommFlow(
                flow_id=f"pd:{index}",
                kind=FlowKind.PD_KV_TRANSFER,
                participants=(a, b),
                bytes_per_event=bytes_p50,
                events_per_request=1.0,
                on_critical_path="ttft",
                allowed_paths=(path_set(graph, a, b, policy),),
                assumptions=(
                    "prefill replica i -> decode replica i, paired by index; the "
                    "router's real policy is not modelled",
                    "sized at the p50 prompt; the tail is listed below and is "
                    "what a p99 TTFT check should use",
                    *tail,
                ),
            )
        )
    return out


def _edge_flows(
    group: RankGroup, spec: ServiceSpec, graph: ResourceGraph, policy: PathPolicy
) -> list[CommFlow]:
    """Request in, tokens out. Not on any latency target, but real traffic.

    They are enumerated because they consume the same uplink a collective does,
    and a cut that ignored them would over-state what is left for one.
    """
    first = sorted(group.ranks)[0]
    nic = _nic_of(graph, first)
    if nic is None:
        return []
    bytes_per_elem = memutil.dtype_bits(spec.service.dtype) // 8
    out: list[CommFlow] = []
    for kind, tokens, src, dst in (
        (FlowKind.INGRESS, spec.traffic.input_tokens.p50, nic, first),
        (FlowKind.EGRESS, spec.traffic.output_tokens.p50, first, nic),
    ):
        out.append(
            CommFlow(
                flow_id=f"{kind.value}:{group.assignment_index}:{group.replica}",
                kind=kind,
                participants=(src, dst),
                # Token ids on the way in, logits/ids on the way out: small
                # next to a KV transfer, and deliberately not modelled as text.
                bytes_per_event=float(tokens * bytes_per_elem),
                events_per_request=1.0,
                on_critical_path="none",
                allowed_paths=(path_set(graph, src, dst, policy),),
                assumptions=("token ids only; serialisation overhead not modelled",),
            )
        )
    return out


def flows_for(
    template: CandidateConfig,
    placements: Sequence[RankGroup],
    spec: ServiceSpec,
    graph: ResourceGraph,
    policy: PathPolicy = DEFAULT_POLICY,
) -> tuple[CommFlow, ...]:
    """Every flow one candidate runs, in a stable order.

    Sorted by `(kind, flow_id)` so two runs produce the same tuple and a
    signature built over it is reproducible.
    """
    flows: list[CommFlow] = []
    for index, group in enumerate(placements):
        tp = _tp_flow(group, index, spec, graph, policy)
        if tp is not None:
            flows.append(tp)
        pp = _pp_flow(group, spec, graph, policy)
        if pp is not None:
            flows.append(pp)
        flows.extend(_edge_flows(group, spec, graph, policy))

    if template.serving_arch is ServingArch.PD_SPLIT:
        flows.extend(_pd_flows(placements, spec, graph, policy))

    flows.sort(key=lambda f: (f.kind.value, f.flow_id))
    ids = [f.flow_id for f in flows]
    if len(set(ids)) != len(ids):  # pragma: no cover - a construction bug
        raise ValueError(f"duplicate flow_id in {ids}")
    return tuple(flows)


def assignment_of(template: CandidateConfig, group: RankGroup) -> IslandAssignment:
    return template.assignments[group.assignment_index]
