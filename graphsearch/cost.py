"""What a placement costs per hour, and the cheapest one a template could get.

One rule decides the shape of this module: **an incomplete sum is not a cost.**

If any device or host a placement occupies carries no price, the total is
`None` and the plan cannot be scored on cost at all. The tempting alternatives
are both wrong in the same direction:

* summing what *is* priced makes an under-priced plan look cheapest, and the
  more prices are missing the cheaper it looks;
* substituting the accelerator count turns "we do not know what this costs"
  into "this costs 4", and a ranking built on it is a ranking by device count
  wearing a dollar sign.

heteropilot's H1 already takes the other side of this contract:
`pareto.can_score` refuses a `minimize_cost_per_hour` objective on an unpriced
plan and says which price is missing, rather than sorting it last where it
would vanish with no explanation. `missing` here is what makes that message
possible.

A price is also subject to absolute rule 3. `AcceleratorProfile` refuses a
`price_per_hour_usd` with no `price_source` (H2), so an unattributed price
cannot reach this module at all.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from graphsearch import paths_root
from graphsearch.schema import ResourceGraph, Vertex, VertexKind

paths_root.ensure_importable()

from planner.inventory import ExecutionIsland  # noqa: E402
from planner.plan import CandidateConfig  # noqa: E402


@dataclass(frozen=True)
class CostBreakdown:
    """Accelerators, hosts, and whether the two add up to anything.

    `total_usd_per_hour` is None exactly when `missing` is non-empty. The two
    parts are still reported in that case, because "the GPUs come to 8.0 and
    one host price is missing" is a more useful thing to hand a user than a
    bare None.
    """

    accelerator_usd_per_hour: float
    host_usd_per_hour: float
    #: None when anything is unpriced. Never a partial sum.
    total_usd_per_hour: float | None
    #: Vertex or node ids with no price, sorted. What `pareto.can_score` names.
    missing: tuple[str, ...] = ()
    basis: str = ""

    @property
    def is_complete(self) -> bool:
        return self.total_usd_per_hour is not None


def _as_price(value: object) -> float | None:
    """`Vertex.attrs` is `Mapping[str, object]`; narrow, never coerce blindly.

    A non-numeric value here would mean the graph was built wrong, and turning
    it into a float would hide that behind a plausible number.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise TypeError(f"price attribute is {value!r}, which is not a number")


def _device_price(vertex: Vertex) -> float | None:
    return _as_price(vertex.attrs.get("price_per_hour_usd"))


def _host_price(graph: ResourceGraph, node_id: str) -> float | None:
    """Read off any accelerator on that node; G1 copies it onto each of them."""
    for vertex in sorted(graph.vertices.values(), key=lambda v: v.id):
        if vertex.kind is VertexKind.ACCELERATOR and vertex.node_id == node_id:
            return _as_price(vertex.attrs.get("node_price_per_hour_usd"))
    return None


def cost_of_devices(
    devices: Collection[str], graph: ResourceGraph, *, basis: str = "devices + hosts"
) -> CostBreakdown:
    """Per-hour price of these accelerators plus the hosts they sit on.

    A host is charged **once and in full** for every node the placement
    touches. Charging a fraction would need a policy for what the rest of the
    node is doing, and the planner does not model that; charging it once per
    device would double-count a two-GPU replica.
    """
    ordered = sorted(set(devices))
    missing: list[str] = []

    accelerator_total = 0.0
    nodes: set[str] = set()
    for device_id in ordered:
        vertex = graph.vertices.get(device_id)
        if vertex is None or vertex.kind is not VertexKind.ACCELERATOR:
            raise KeyError(f"{device_id!r} is not an accelerator in this graph")
        if vertex.node_id is not None:
            nodes.add(vertex.node_id)
        price = _device_price(vertex)
        if price is None:
            missing.append(device_id)
        else:
            accelerator_total += price

    host_total = 0.0
    for node_id in sorted(nodes):
        price = _host_price(graph, node_id)
        if price is None:
            missing.append(node_id)
        else:
            host_total += price

    complete = not missing
    return CostBreakdown(
        accelerator_usd_per_hour=accelerator_total,
        host_usd_per_hour=host_total,
        total_usd_per_hour=accelerator_total + host_total if complete else None,
        missing=tuple(sorted(missing)),
        basis=(
            f"{basis}: {len(ordered)} accelerator(s), {len(nodes)} host(s) charged in full"
        ),
    )


def cost_lower_bound(
    template: CandidateConfig,
    islands: Mapping[str, ExecutionIsland],
    graph: ResourceGraph,
) -> CostBreakdown:
    """The cheapest any embedding of this template could be.

    Per assignment, the cheapest `total_devices` accelerators its island holds;
    plus each touched node's host price once. An island is node-local, so every
    embedding of an assignment charges that same host - the host half is exact
    rather than a bound, and only the device half is relaxed.

    Used as a sound elimination in `bounds.py` when the objective is cost and an
    incumbent exists: a template whose *floor* is above a plan already in hand
    cannot beat it. Like every other bound it may reject only on arithmetic that
    is optimistic, which is why the cheapest devices are taken and not the first.
    """
    missing: list[str] = []
    accelerator_total = 0.0
    nodes: set[str] = set()
    counted = 0

    for index, assignment in enumerate(template.assignments):
        island = islands.get(assignment.island_id)
        if island is None:
            raise KeyError(
                f"assignment {index} names island {assignment.island_id!r}, "
                f"which is not in this inventory"
            )
        nodes.add(island.node_id)
        need = assignment.total_devices
        prices: list[float] = []
        for accel_id in island.accelerator_ids:
            vertex = graph.vertices.get(f"{island.node_id}/{accel_id}")
            price = None if vertex is None else _device_price(vertex)
            if price is None:
                missing.append(f"{island.node_id}/{accel_id}")
            else:
                prices.append(price)
        if len(prices) < need:
            # Not enough PRICED devices to make a floor. Reported as missing
            # rather than bounded by what is priced: a floor built on a subset
            # would be below anything achievable and would eliminate candidates
            # that are actually cheaper than it claims.
            missing.append(f"{island.id} (priced {len(prices)} of {need} needed)")
            continue
        accelerator_total += sum(sorted(prices)[:need])
        counted += need

    host_total = 0.0
    for node_id in sorted(nodes):
        price = _host_price(graph, node_id)
        if price is None:
            missing.append(node_id)
        else:
            host_total += price

    complete = not missing
    return CostBreakdown(
        accelerator_usd_per_hour=accelerator_total,
        host_usd_per_hour=host_total,
        total_usd_per_hour=accelerator_total + host_total if complete else None,
        missing=tuple(sorted(set(missing))),
        basis=(
            f"lower bound: cheapest {counted} accelerator(s) available in the "
            f"assigned island(s), {len(nodes)} host(s) charged in full"
        ),
    )


def cheapest(breakdowns: Sequence[CostBreakdown]) -> CostBreakdown | None:
    """The cheapest COMPLETE breakdown, or None if none of them is complete.

    Deliberately not "the cheapest of whatever has a total": a caller comparing
    a priced plan against an unpriced one is comparing a number with an absence,
    and the absence must not win by default.
    """
    complete = [b for b in breakdowns if b.is_complete]
    if not complete:
        return None
    return min(complete, key=lambda b: (b.total_usd_per_hour, b.basis))


@dataclass(frozen=True)
class PriceCoverage:
    """How much of a cluster carries a price. For the measurement queue."""

    priced_devices: int = 0
    unpriced_devices: int = 0
    priced_hosts: int = 0
    unpriced_hosts: int = 0
    unpriced: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_complete(self) -> bool:
        return not self.unpriced_devices and not self.unpriced_hosts


def price_coverage(graph: ResourceGraph) -> PriceCoverage:
    """What a cost objective can and cannot score on this cluster.

    A `certify` search cannot terminate without full coverage, so it is worth
    being able to say which prices are missing before the search runs rather
    than after it fails to conclude.
    """
    priced_devices = unpriced_devices = 0
    unpriced: list[str] = []
    nodes: set[str] = set()
    for vertex in sorted(graph.accelerators(), key=lambda v: v.id):
        if vertex.node_id is not None:
            nodes.add(vertex.node_id)
        if _device_price(vertex) is None:
            unpriced_devices += 1
            unpriced.append(vertex.id)
        else:
            priced_devices += 1

    priced_hosts = unpriced_hosts = 0
    for node_id in sorted(nodes):
        if _host_price(graph, node_id) is None:
            unpriced_hosts += 1
            unpriced.append(node_id)
        else:
            priced_hosts += 1

    return PriceCoverage(
        priced_devices=priced_devices,
        unpriced_devices=unpriced_devices,
        priced_hosts=priced_hosts,
        unpriced_hosts=unpriced_hosts,
        unpriced=tuple(sorted(unpriced)),
    )
