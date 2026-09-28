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
from dataclasses import dataclass

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
        *,
        starts: Mapping[str, float] | None = None,
    ) -> Mapping[str, float]:
        """flow_id -> nanoseconds. Same keys as `flows`, always.

        `start_ns` shifts every flow; `starts` offsets them individually,
        flow_id -> nanoseconds after `start_ns`. A flow absent from `starts`
        begins at `start_ns`. The second exists because contention depends on
        WHEN flows overlap: two transfers that never coincide do not contend,
        and a model that assumed they all began together would report a
        slowdown that never happened.
        """
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
        *,
        starts: Mapping[str, float] | None = None,
    ) -> Mapping[str, float]:
        offsets = dict(starts or {})
        out: dict[str, float] = {}
        for flow in flows:
            begin = start_ns + offsets.get(flow.flow_id, 0.0)
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
                begin + best.latency_ns + flow.bytes_per_event / capacity * 1e9
            )
        return out


@dataclass(frozen=True)
class _Active:
    """One flow's state while the event loop runs. Sorted by id, always."""

    flow_id: str
    begin_ns: float
    bytes_total: float
    link_cap: float
    resources: tuple[str, ...]


class FluidContentionModel(ContentionModel):
    """Processor-sharing over shared resources.

    At any instant the active flows on a resource split `capacity - reserved`
    equally, and a flow's rate is the minimum over the resources on its path
    (its own link bottleneck included). Event-driven -- the rates are recomputed
    whenever a flow starts or finishes -- and **not packet-level**: there is no
    queue, no window, no loss, and no notion of a burst. It is named in every
    record because a result computed under it may not be compared against one
    computed under `null` without saying so.

    **What contends with what.** Two things, and deliberately not a third:

    * an **external reservation**, which is treated as a permanently active
      flow and subtracted from capacity before anything else
      (`SharedResource.available_bytes_per_s`);
    * **flows inside one candidate** that overlap in time -- the several P/D
      transfers of a `dp > 1` deployment, say.

    **Candidates do not contend with each other.** They are alternatives; the
    search evaluates many and deploys one. Pricing two candidates as if both
    were running would model a cluster nobody is going to build.

    **This is not max-min fair, on purpose.** A flow held back by a bottleneck
    elsewhere on its path does not return its unused share to the others: the
    split on each resource is a flat `available / active`. Max-min fairness
    would predict a higher rate for the flow that is not bottlenecked, so this
    model is the pessimistic one of the two. That is stated rather than fixed
    because it is the model the E-G4 numbers will be produced under, and
    "we later improved it" is how two incomparable result sets get compared.

    **It must never be used by a bound.** A pruning stage may reject only when
    the most optimistic arithmetic already misses the constraint, and this model
    is by construction never faster than `null` -- sharing a resource can only
    slow a flow down. `null` is therefore the one the bounds use, and
    `tests/test_contention.py` pins that fluid is never the faster of the two.
    """

    name = "fluid"

    #: A guard on the event loop, not a modelling parameter. Each iteration
    #: either starts or finishes at least one flow, so `2 * len(flows) + 2` is
    #: already generous; exceeding it means a rate went to zero without the
    #: zero-capacity check catching it, and an infinite loop is a worse bug
    #: report than a raised exception.
    _MAX_EVENTS = 10_000

    def transfer_times_ns(
        self,
        flows: Sequence[CommFlow],
        graph: ResourceGraph,
        start_ns: float = 0.0,
        *,
        starts: Mapping[str, float] | None = None,
    ) -> Mapping[str, float]:
        offsets = dict(starts or {})
        out: dict[str, float] = {}
        active: list[_Active] = []

        for flow in sorted(flows, key=lambda f: f.flow_id):
            best = flow.allowed_paths[0].best if flow.allowed_paths else None
            if best is None:
                out[flow.flow_id] = float("inf")
                continue
            link_cap = effective_bottleneck_bytes_per_s(graph, best)
            if link_cap <= 0:
                out[flow.flow_id] = float("inf")
                continue
            if flow.bytes_per_event <= 0:
                # No bytes: latency only. It still never occupies a resource,
                # so it is resolved here instead of entering the loop, where a
                # zero-byte flow would take a share it does not use.
                out[flow.flow_id] = (
                    start_ns + offsets.get(flow.flow_id, 0.0) + best.latency_ns
                )
                continue
            active.append(
                _Active(
                    flow_id=flow.flow_id,
                    # Latency first, then the bytes drain: a flow occupies the
                    # wire only once its first byte is on it.
                    begin_ns=start_ns + offsets.get(flow.flow_id, 0.0) + best.latency_ns,
                    bytes_total=flow.bytes_per_event,
                    link_cap=link_cap,
                    resources=tuple(sorted(best.shared_resources)),
                )
            )

        if not active:
            return out

        available = {
            resource_id: graph.shared_resources[resource_id].available_bytes_per_s
            for flow_state in active
            for resource_id in flow_state.resources
            if resource_id in graph.shared_resources
        }

        remaining = {f.flow_id: f.bytes_total for f in active}
        by_id = {f.flow_id: f for f in active}
        now = min(f.begin_ns for f in active)
        pending = set(remaining)

        for _ in range(self._MAX_EVENTS):
            if not pending:
                break
            running = sorted(f for f in pending if by_id[f].begin_ns <= now)
            if not running:
                now = min(by_id[f].begin_ns for f in pending)
                continue

            counts: dict[str, int] = {}
            for flow_id in running:
                for resource_id in by_id[flow_id].resources:
                    counts[resource_id] = counts.get(resource_id, 0) + 1

            rates: dict[str, float] = {}
            for flow_id in running:
                state = by_id[flow_id]
                rate = state.link_cap
                for resource_id in state.resources:
                    share = available.get(resource_id)
                    if share is None:
                        continue
                    rate = min(rate, share / counts[resource_id])
                rates[flow_id] = rate

            if any(rate <= 0 for rate in rates.values()):
                for flow_id, rate in rates.items():
                    if rate <= 0:
                        out[flow_id] = float("inf")
                        pending.discard(flow_id)
                continue

            finish_in = min(remaining[f] / rates[f] * 1e9 for f in running)
            waiting = [by_id[f].begin_ns for f in pending if by_id[f].begin_ns > now]
            next_start = min(waiting) - now if waiting else float("inf")
            step = min(finish_in, next_start)

            for flow_id in running:
                remaining[flow_id] -= rates[flow_id] * step / 1e9
            now += step

            for flow_id in sorted(running):
                # A float epsilon, not a tolerance to be tuned: `step` was
                # chosen so the first finisher lands exactly on zero, and the
                # subtraction above can leave it a few ulps either side.
                if remaining[flow_id] <= 1e-9 * by_id[flow_id].bytes_total:
                    out[flow_id] = now
                    pending.discard(flow_id)
        else:
            raise RuntimeError(
                f"fluid contention did not settle in {self._MAX_EVENTS} events "
                f"for {sorted(pending)}; each event should start or finish a "
                f"flow, so this is a rate that never reached zero capacity"
            )

        for flow_id in pending:
            out[flow_id] = float("inf")
        return out


DEFAULT_CONTENTION_MODEL = NullContentionModel()

#: Selectable by name, so a CLI flag and a report label cannot drift apart.
CONTENTION_MODELS: dict[str, ContentionModel] = {
    "null": DEFAULT_CONTENTION_MODEL,
    "fluid": FluidContentionModel(),
}


def contention_model(name: str) -> ContentionModel:
    """The model called `name`, or a refusal that lists the real ones."""
    try:
        return CONTENTION_MODELS[name]
    except KeyError:
        raise SystemExit(
            f"unknown contention model {name!r}; one of "
            f"{sorted(CONTENTION_MODELS)}"
        ) from None


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
