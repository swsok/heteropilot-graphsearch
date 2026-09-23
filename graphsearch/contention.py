"""How long a set of flows takes when they share the wire. Interface only, for now.

The MVP prices every flow as if it had the cut to itself. That is the
optimistic direction a bound is allowed, and it is stated on every
`CutCapacity` -- but it is also the single largest thing this work does not
model, so the seam is cut now rather than discovered later.

`NullContentionModel` is what the MVP uses: latency plus bytes over the
bottleneck, each flow alone. It is not a placeholder to be quietly improved --
it is the model the results were produced under, and a result computed with it
may not be compared against one computed with a real contention model without
saying so.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence

from graphsearch.demand import CommFlow
from graphsearch.paths import effective_bottleneck_bytes_per_s
from graphsearch.schema import ResourceGraph


class ContentionModel(ABC):
    """Transfer time per flow, given that they run together."""

    #: Named in every report that used it, so two results computed under
    #: different models cannot be compared by accident.
    name: str = "abstract"

    @abstractmethod
    def transfer_times_ns(
        self,
        flows: Sequence[CommFlow],
        graph: ResourceGraph,
        start_ns: float = 0.0,
    ) -> Mapping[str, float]:
        """flow_id -> nanoseconds. Same keys as `flows`, always."""
        raise NotImplementedError


class NullContentionModel(ContentionModel):
    """Each flow alone on its own path. What the MVP actually used.

    A flow's time is its path latency plus its bytes over the effective
    bottleneck -- the nominal capacity with any external reservation taken off.
    Flows sharing a resource do not slow each other down here, which is exactly
    the limitation `TopologyLossReport` reports and `D124` records.
    """

    name = "null"

    def transfer_times_ns(
        self,
        flows: Sequence[CommFlow],
        graph: ResourceGraph,
        start_ns: float = 0.0,
    ) -> Mapping[str, float]:
        out: dict[str, float] = {}
        for flow in flows:
            if not flow.allowed_paths:
                out[flow.flow_id] = float("inf")
                continue
            best = flow.allowed_paths[0].best
            if best is None:
                out[flow.flow_id] = float("inf")
                continue
            capacity = effective_bottleneck_bytes_per_s(graph, best)
            if capacity <= 0:
                out[flow.flow_id] = float("inf")
                continue
            out[flow.flow_id] = (
                start_ns + best.latency_ns + flow.bytes_per_event / capacity * 1e9
            )
        return out


DEFAULT_CONTENTION_MODEL = NullContentionModel()


def tp_allreduce_tpot_ms(
    flow: CommFlow,
    graph: ResourceGraph,
    model: str,
    *,
    contention: ContentionModel = DEFAULT_CONTENTION_MODEL,
) -> float:
    """Milliseconds this TP group adds to ONE output token.

    Shared by `bounds._check_comm_latency` and the graph-aware mock on purpose.
    They used to compute it separately, and they disagreed: the mock charged one
    all-reduce per token where the bound charges `2 x layers`, so the mock could
    return a TPOT below the floor that admitted the candidate. That breaks the
    invariant the whole oracle argument rests on -- a mock faster than a bound
    makes an oracle disagreement meaningless -- and a docstring saying "never
    faster" is not a mechanism. One function is.

    The caller supplies the capacity: the bound divides by a CUT (optimistic,
    and it must be), the mock by its path bottleneck. Only the per-token
    multiplier lives here, because that is the part they were disagreeing about.
    """
    from graphsearch.demand import tp_allreduces_per_output_token

    times = contention.transfer_times_ns([flow], graph)
    per_allreduce_ns = times.get(flow.flow_id, float("inf"))
    if per_allreduce_ns == float("inf"):
        return float("inf")
    return tp_allreduces_per_output_token(model) * per_allreduce_ns / 1e6


def allreduces_per_token(model: str) -> int:
    """Re-exported so a caller need not import `demand` for this alone."""
    from graphsearch.demand import tp_allreduces_per_output_token

    return tp_allreduces_per_output_token(model)
