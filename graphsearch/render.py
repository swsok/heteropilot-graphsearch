"""The "Graph search:" block, appended after heteropilot's own render output.

heteropilot's `planner/__main__.py` is not modified: its renderer produces what
it always did, and this adds a block underneath. A reader who knows the
planner's output sees it unchanged, then sees what the graph search did to
reach it.

The block leads with the counts that are NOT verdicts. A search that evaluated
sixteen of fifty-four representatives and found nothing feasible has said
something very different from a cluster that cannot serve the workload, and the
difference has to be visible without reading provenance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from graphsearch.adaptive import SearchAudit
from graphsearch.equivalence import CompressionReport
from graphsearch.restore import RestoredPlan


def render_graph_block(
    audit: SearchAudit,
    compression: CompressionReport | None = None,
    restored: Sequence[RestoredPlan] = (),
    loss_reports: Mapping[str, object] | None = None,
) -> str:
    lines: list[str] = []
    report = compression
    merge_note = ""
    if report is not None:
        merge_note = (
            f" (exact merges {report.exact_merges}, hash-only "
            f"{report.hash_only_groups}, VF2 {report.vf2_seconds:.1f} s)"
        )
    lines.append(
        f"Graph search: {audit.generated_templates} templates -> "
        f"{audit.embeddings} embeddings -> {audit.representatives} "
        f"representatives{merge_note}"
    )
    lines.append(
        f"  impossible_proven {audit.impossible_proven} | "
        f"excluded_by_scope {audit.excluded_by_scope} | "
        f"deferred_heuristic {audit.deferred_heuristic} | "
        f"unknown_measurement {audit.unknown_measurement} | "
        f"evaluated {audit.evaluated}"
    )
    lines.append(
        f"  simulations {audit.simulations_run} (cache hits {audit.cache_hits}) | "
        f"K reached {audit.k_reached} | termination: {audit.termination}"
    )
    if audit.unevaluated_ids:
        lines.append(
            f"  NOT EVALUATED: {len(audit.unevaluated_ids)} representative(s) "
            f"standing for {audit.unevaluated_placements} placement(s). These "
            f"were not judged infeasible -- they were not judged."
        )
    certificate = audit.certificate
    if certificate:
        lines.append(
            f"  certificate: nothing unevaluated can beat "
            f"{certificate.get('incumbent_usd_per_hour')}/h "
            f"(min lower bound {certificate.get('min_unevaluated_lower_bound')}, "
            f"epsilon {certificate.get('epsilon')})"
        )
    else:
        lines.append("  certificate: none")

    if restored:
        for plan in restored:
            holds = (
                ", ".join(
                    f"{k} {v:.3g} B/s"
                    for k, v in sorted(plan.shared_resource_reservations.items())
                )
                or "nothing shared"
            )
            lines.append(
                f"  restored {plan.plan.plan_id}: {', '.join(plan.device_ids)} ; "
                f"reservations {holds}"
            )

    dropped = sorted(
        {
            resource
            for report_ in (loss_reports or {}).values()
            for resource in getattr(report_, "dropped_shared_resources", [])
        }
    )
    if dropped:
        lines.append(
            f"  simulator could not represent: {', '.join(dropped)} -- two "
            f"placements differing only in these get the same metrics"
        )
    return "\n".join(lines)
