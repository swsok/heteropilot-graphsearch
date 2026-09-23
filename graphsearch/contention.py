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
