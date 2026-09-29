#!/usr/bin/env python
"""E-G4 P2.4: the two contention models against what the wire actually did.

**REAL HARDWARE.** Every measured figure here comes from
`experiments/microbench/raw/`, on the node whose serials those files carry. The
predictions are computed; the measurements are not.

For each (location, condition, message size) both models predict a transfer
time for the same flows over the same graph, and the error is
`|predicted - measured| / measured` at p50 and p90. The pre-registration's
E-G4 limits decide the verdict, and they are read from this file's constants
rather than restated in prose, so the table and the claim cannot drift.

**Two topology declarations, run side by side, and the difference between them
is the result.**

  as_planned   What `PLAN.md` fixed before any of this was measured: GPU0-2
               and GPU1-3 "share one PCIe host bridge -- this is the shared
               uplink". This is the declaration the verdict is computed on,
               because it is the one that was registered.

  as_measured  What the raw files support: the bottleneck for a peer copy is
               the ENDPOINT's own PCIe x16 port, and two copies between
               disjoint device pairs share nothing. **Fitted on the files
               listed in `FITTED_ON`**, which is why it cannot be used for the
               registered verdict and is excluded from P3's validation set.

The distinction that matters, and the one this file exists to make: a
processor-sharing model is not falsified by these numbers. What is falsified is
the claim about WHICH resource is shared. Those are different corrections with
different consequences, and collapsing them would have produced either a model
rewritten to fit a topology error, or a topology quietly edited to save a
model.

    python experiments/microbench/analyze.py \\
        --out experiments/results/e_g4_microbench.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.util.percentile import percentile  # noqa: E402

from graphsearch.contention import (  # noqa: E402
    FluidContentionModel,
    NullContentionModel,
)
from graphsearch.demand import CommFlow, FlowKind  # noqa: E402
from graphsearch.paths import Path as GPath  # noqa: E402
from graphsearch.paths import PathSet  # noqa: E402
from graphsearch.schema import ResourceGraph, SharedResource, Source  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
RAW = ROOT / "experiments" / "microbench" / "raw"

BANNER = (
    "> **REAL HARDWARE.** Every measured column comes from "
    "`experiments/microbench/raw/`, on the node whose serials those files "
    "carry. The predicted columns are computed. Nothing here is a mock and "
    "nothing here is a simulation."
)

#: `docs/preregistration.md`, E-G4, registered 2026-09-28 before any of this
#: was measured. Read here rather than restated in prose so the table and the
#: claim cannot drift apart.
LIMIT_P50 = 0.15          # fluid, under contention
LIMIT_P90 = 0.30          # fluid, under contention
LIMIT_AGREE = 0.05        # null vs fluid, WITHOUT contention

#: The raw files the `as_measured` declaration was derived from. Registered
#: here and appended to `docs/preregistration.md`: anything fitted on these is
#: excluded from P3's validation, because a model that was shown the answer
#: cannot also be tested by it (work order P2.4).
#: All eight, not the three that actually drove the conclusion. Every file in
#: this run was in front of the author when the `as_measured` declaration was
#: written, and "which ones did I really use" is not a distinction a reader can
#: check. It costs nothing to be conservative here: P3 measures served TTFT and
#: TPOT, not bus bandwidth, so excluding these excludes nothing P3 needs.
FITTED_ON = (
    "a-cond1-single-bridge-0-2.json",
    "a-cond1-single-nvlink-0-1.json",
    "a-cond2-bg60-same-bridge.json",
    "a-cond2-two-same-bridge.json",
    "a-cond3-bg60-independent.json",
    "a-cond3-two-independent.json",
    "a-cond4-bidi-bg60-same.json",
    "a-cond4-bidirectional-0-2.json",
)

GB = 1e9


# --- the two declarations -------------------------------------------------

@dataclass(frozen=True)
class Declaration:
    """A statement about which resource a device pair's traffic occupies."""

    name: str
    why: str

    def resources_for(self, src: int, dst: int) -> frozenset[str]:
        raise NotImplementedError


@dataclass(frozen=True)
class AsPlanned(Declaration):
    """PLAN.md: 0-2 and 1-3 cross one host bridge, and that bridge is the uplink."""

    def resources_for(self, src: int, dst: int) -> frozenset[str]:
        if _nvlink(src, dst):
            return frozenset()
        return frozenset({f"bridge:numa{src // 4}"})


@dataclass(frozen=True)
class AsMeasured(Declaration):
    """The endpoint's own x16 port is the bottleneck; disjoint pairs share nothing."""

    def resources_for(self, src: int, dst: int) -> frozenset[str]:
        if _nvlink(src, dst):
            return frozenset()
        return frozenset({f"port:gpu{src}", f"port:gpu{dst}"})


def _nvlink(src: int, dst: int) -> bool:
    """NV4 pairs on this node: (0,1) (2,3) (4,5) (6,7). From `nvidia-smi topo -m`."""
    return src // 2 == dst // 2


#: Measured single-flow plateaus at 256 MiB, condition 1. These are the
#: capacities both declarations are given, so the two differ ONLY in which
#: resource is shared -- not in how fast anything is.
PCIE_PLATEAU_GBPS = 25.12
NVLINK_PLATEAU_GBPS = 52.64


def build_graph(
    declaration: Declaration,
    pairs: list[tuple[int, int]],
    background: dict | None = None,
) -> ResourceGraph:
    """The resources these flows touch, with any background load as `reserved`.

    The background generator is **not** a flow. It is traffic this planner does
    not control, which is exactly what `reserved_bytes_per_s` means, and both
    models subtract it before doing anything else. Its rate is
    `bytes_moved / wall_s` from the raw file -- the time-averaged rate it
    actually sustained, never `target_util`, because a generator that missed
    its target and a model that missed its prediction are different failures
    and must not cancel.
    """
    resources: dict[str, SharedResource] = {}
    reserved: dict[str, float] = {}
    touched = list(pairs)
    if background and background.get("wall_s"):
        bg_pair = tuple(int(x) for x in background["pair"].split("-"))
        rate = background["bytes_moved"] / background["wall_s"]
        for resource_id in declaration.resources_for(*bg_pair):
            reserved[resource_id] = rate
        touched.append(bg_pair)  # type: ignore[arg-type]

    for src, dst in touched:
        for resource_id in declaration.resources_for(src, dst):
            resources[resource_id] = SharedResource(
                id=resource_id,
                capacity_bytes_per_s=PCIE_PLATEAU_GBPS * GB,
                reserved_bytes_per_s=reserved.get(resource_id, 0.0),
                kind="pcie_uplink",
                node_id=None,
                # The number is measured; which resource carries it is the
                # declaration's claim, and that claim is what is on trial.
                source=Source.MEASURED,
            )
    return ResourceGraph(
        schema_version=2,
        cluster_id="a40x8-microbench",
        vertices={},
        edges={},
        shared_resources=resources,
        snapshot_version="microbench",
        unit_notes=(
            f"capacities are the condition-1 measured plateaus: "
            f"{PCIE_PLATEAU_GBPS} GB/s PCIe, {NVLINK_PLATEAU_GBPS} GB/s NVLink",
        ),
    )


def flow_for(
    declaration: Declaration, src: int, dst: int, nbytes: int, latency_ns: float
) -> CommFlow:
    plateau = NVLINK_PLATEAU_GBPS if _nvlink(src, dst) else PCIE_PLATEAU_GBPS
    path = GPath(
        edges=(f"{src}->{dst}",),
        bottleneck_bytes_per_s=plateau * GB,
        latency_ns=latency_ns,
        shared_resources=declaration.resources_for(src, dst),
    )
    return CommFlow(
        flow_id=f"{src}-{dst}",
        kind=FlowKind.PD_KV_TRANSFER,
        participants=(f"gpu{src}", f"gpu{dst}"),
        bytes_per_event=float(nbytes),
        events_per_request=1.0,
        on_critical_path="none",
        allowed_paths=(PathSet(src=f"gpu{src}", dst=f"gpu{dst}", paths=(path,)),),
    )


# --- the measurement ------------------------------------------------------

#: Condition 1's own smallest median, used as the fixed per-transfer overhead
#: both models are given. Calling it `latency` would overstate it: it is call
#: overhead plus link latency plus whatever the 1 MiB copy does not amortise,
#: measured, not decomposed. It is the SAME constant for both models, so it
#: cannot favour either.
def overhead_ns(single: dict) -> float:
    smallest = single["sizes"]["1MiB"]["pairs"]
    pair = next(iter(smallest.values()))
    measured_s = percentile(sorted(pair["samples_s"]), 50)
    ideal_s = single["sizes"]["1MiB"]["msg_bytes"] / (PCIE_PLATEAU_GBPS * GB)
    return max(0.0, (measured_s - ideal_s) * 1e9)


def rows_for(raw: dict, declaration: Declaration, latency_ns: float) -> list[dict]:
    pairs = [tuple(int(x) for x in p.split("-")) for p in raw["pairs"]]
    null, fluid = NullContentionModel(), FluidContentionModel()

    out: list[dict] = []
    for _size_key, block in sorted(
        raw["sizes"].items(), key=lambda kv: kv[1]["msg_bytes"]
    ):
        nbytes = block["msg_bytes"]
        graph = build_graph(declaration, pairs, block.get("background"))  # type: ignore[arg-type]
        flows = [
            flow_for(declaration, src, dst, nbytes, latency_ns)
            for src, dst in pairs  # type: ignore[misc]
        ]
        predicted = {
            "null": null.transfer_times_ns(flows, graph),
            "fluid": fluid.transfer_times_ns(flows, graph),
        }
        for (src, dst), key in zip(pairs, raw["pairs"], strict=True):  # type: ignore[misc]
            samples = sorted(block["pairs"][key]["samples_s"])
            flow_id = f"{src}-{dst}"
            row = {
                "label": raw["label"],
                "condition": raw["condition"],
                "share": raw["share"],
                "background_duty": (block.get("background") or {}).get(
                    "achieved_duty_cycle"
                ),
                "flow": flow_id,
                "msg_bytes": nbytes,
                "msg_size_class": block["msg_size_class"],
                "declaration": declaration.name,
                "p50_ms": percentile(samples, 50) * 1e3,
                "p90_ms": percentile(samples, 90) * 1e3,
            }
            for model in ("null", "fluid"):
                row[f"{model}_ms"] = predicted[model][flow_id] / 1e6
                for pct in ("p50", "p90"):
                    measured = row[f"{pct}_ms"]
                    row[f"err_{model}_{pct}"] = (
                        abs(row[f"{model}_ms"] - measured) / measured
                        if measured > 0
                        else float("inf")
                    )
            out.append(row)
    return out


#: Which conditions the pre-registration's "under contention" clause covers.
#: `two-same` and `bidirectional` put two flows on what PLAN.md declared to be
#: one resource; `single` and `two-independent` do not, and are judged by the
#: agreement clause instead.
CONTENDED = {"two-same", "bidirectional"}


def verdict(rows: list[dict]) -> list[dict]:
    """One judgement per (declaration, condition), against the registered limits."""
    out = []
    for declaration in sorted({r["declaration"] for r in rows}):
        for condition in sorted({r["condition"] for r in rows}):
            group = [
                r for r in rows
                if r["declaration"] == declaration and r["condition"] == condition
            ]
            if not group:
                continue
            contended = condition in CONTENDED
            fluid50 = statistics.median(r["err_fluid_p50"] for r in group)
            fluid90 = statistics.median(r["err_fluid_p90"] for r in group)
            null50 = statistics.median(r["err_null_p50"] for r in group)
            if contended:
                passed = fluid50 <= LIMIT_P50 and fluid90 <= LIMIT_P90
                beats = fluid50 <= null50
                rule = (
                    f"fluid p50 <= {LIMIT_P50:.0%} and p90 <= {LIMIT_P90:.0%}, "
                    f"and fluid must beat null"
                )
                passed = passed and beats
            else:
                agree = max(
                    abs(r["fluid_ms"] - r["null_ms"]) / r["null_ms"]
                    for r in group if r["null_ms"] > 0
                )
                passed = agree <= LIMIT_AGREE
                rule = f"null and fluid agree within {LIMIT_AGREE:.0%}"
                fluid50 = agree
            out.append({
                "declaration": declaration,
                "condition": condition,
                "contended": contended,
                "rule": rule,
                "fluid_p50": fluid50,
                "fluid_p90": fluid90,
                "null_p50": null50,
                "passed": passed,
            })
    return out


# --- the report -----------------------------------------------------------

COLUMNS = [
    ("condition", "condition"), ("flow", "flow"), ("MiB", "mib"),
    ("class", "msg_size_class"),
    ("p50 ms", "p50_ms"), ("p90 ms", "p90_ms"),
    ("null ms", "null_ms"), ("fluid ms", "fluid_ms"),
    ("err null p50", "err_null_p50"), ("err fluid p50", "err_fluid_p50"),
    ("err fluid p90", "err_fluid_p90"),
]


def table(rows: list[dict]) -> list[str]:
    out = ["| " + " | ".join(h for h, _ in COLUMNS) + " |"]
    out.append("| " + " | ".join("---" for _ in COLUMNS) + " |")
    for row in rows:
        cells = []
        for _, key in COLUMNS:
            if key == "mib":
                cells.append(str(row["msg_bytes"] >> 20))
            elif key.startswith("err_"):
                cells.append(f"{row[key]:.1%}")
            elif key.endswith("_ms"):
                cells.append(f"{row[key]:.3f}")
            else:
                cells.append(str(row[key]))
        out.append("| " + " | ".join(cells) + " |")
    return out


def verdict_table(verdicts: list[dict]) -> list[str]:
    head = ["declaration", "condition", "clause", "fluid", "null", "verdict"]
    out = ["| " + " | ".join(head) + " |",
           "| " + " | ".join("---" for _ in head) + " |"]
    for v in verdicts:
        out.append(
            f"| `{v['declaration']}` | {v['condition']} | {v['rule']} | "
            f"{v['fluid_p50']:.1%}"
            + (f" / {v['fluid_p90']:.1%} p90" if v["contended"] else "")
            + f" | {v['null_p50']:.1%} | "
            + ("**PASS**" if v["passed"] else "**FAIL**")
            + " |"
        )
    return out


def band_table(rows: list[dict], declaration: str) -> list[str]:
    """Fluid error per condition per size, because the median hides a regime.

    The `bidirectional` case is the reason this exists: the fluid model is
    within 1 % of the wire from 8 to 64 MiB and a third out at 128 and above.
    One median over the grid reports neither, and a reader would take it for
    uniform accuracy that happens to be mediocre.
    """
    sizes = sorted({r["msg_bytes"] for r in rows})
    head = ["condition / flow"] + [f"{b >> 20}M" for b in sizes]
    out = ["| " + " | ".join(head) + " |",
           "| " + " | ".join("---" for _ in head) + " |"]
    keys = sorted({(r["label"], r["flow"]) for r in rows if r["declaration"] == declaration})
    for label, flow in keys:
        cells = []
        for nbytes in sizes:
            match = [
                r for r in rows
                if r["declaration"] == declaration and r["label"] == label
                and r["flow"] == flow and r["msg_bytes"] == nbytes
            ]
            cells.append(f"{match[0]['err_fluid_p50']:.0%}" if match else "-")
        out.append(f"| `{label}` {flow} | " + " | ".join(cells) + " |")
    return out


def markdown(rows: list[dict], verdicts: list[dict], args) -> str:
    out = ["# E-G4 — the contention model against the wire", "", BANNER, ""]
    out.append(
        "Conditions 1-4 of `experiments/microbench/PLAN.md`, at location (a): "
        "the A40 node's shared PCIe path, GPU0-3 on NUMA 0, pinned with "
        "`numactl --cpunodebind=0 --membind=0` (both halves). "
        f"{args.iters_note}"
    )
    out.append("")
    out.append(
        "**Location (b), the inter-node NIC, is `not run`.** This is one "
        "machine with one NIC and there is no second node to send to. It is "
        "reported rather than omitted: an omitted row reads as a row that "
        "passed, and half a matrix is not a matrix."
    )

    out += ["", "## One path, three questions", ""]
    out.append(
        "The same wire answers differently depending on what crosses it, which "
        "is why a measurement is keyed by the collective and the number of "
        "ranks rather than stored as *the* bandwidth of a link:"
    )
    out.append("")
    out.append(
        "| what was run | ranks | GB/s |\n"
        "| --- | --- | --- |\n"
        f"| peer copy across the PCIe bridge | 2 | {PCIE_PLATEAU_GBPS} |\n"
        "| all-reduce busbw across the same bridge | 2 | 19.34 |\n"
        "| all-reduce busbw, the TP=4 group | 4 | 8.71 |\n"
        f"| peer copy over NVLink | 2 | {NVLINK_PLATEAU_GBPS} |"
    )

    out += ["", "## The verdict, against the registered limits", ""]
    out += verdict_table(verdicts)
    out.append("")
    out.append(
        "**The registered verdict is the `as_planned` one.** `as_measured` is "
        "fitted on the files in the next section and is shown for one reason: "
        "to separate two corrections that would otherwise be confused."
    )

    out += ["", "## What actually failed, and what did not", ""]
    out.append(
        "The `two-same` row is the whole result. `PLAN.md` fixed, before any "
        "of this ran, that GPU0-2 and GPU1-3 \"share one PCIe host bridge — "
        "this is the shared uplink\". Processor sharing over that declaration "
        "predicts each of two concurrent copies gets half. **Measured, each "
        "got all of it**: 25.11 and 25.11 GB/s at 256 MiB against 25.12 GB/s "
        "for the same copy alone, and the same shape at every size in the "
        "grid."
    )
    out.append("")
    out.append(
        "25.1 GB/s is a PCIe 4.0 x16 running out of lanes. The bottleneck for "
        "a peer copy on this node is **the endpoint's own x16 port**, not a "
        "bridge behind it, so two copies between disjoint device pairs share "
        "nothing and neither slows the other down."
    )
    out.append("")
    out.append(
        "So the fluid model is **not** what these numbers falsify. Processor "
        "sharing over a genuinely shared resource is still processor sharing; "
        "what was wrong is the claim about which resource is shared. Those "
        "are different corrections — one rewrites `graphsearch/contention.py`, "
        "the other rewrites a line of YAML in a cluster fixture — and a table "
        "that reported only \"fluid: 100% error\" would have invited the "
        "first when the second is what the data supports."
    )

    out += ["", "## Where the model is exact, and where it stops being", ""]
    out.append(
        "The `bidirectional` case is the one worth reading carefully, and a "
        "single median over the grid would have hidden it. 0→2 and 2→0 at "
        "once **do** contend, and from 4 to 64 MiB they contend by exactly "
        "the factor processor sharing predicts — fluid is within **0.1 to 2.5 %** "
        "of the wire there, against 48-50 % for null. That is the clearest "
        "evidence in this file that the model is doing real work."
    )
    out.append("")
    out.append(
        "At **128 MiB and above the regime changes**: the pair reaches 16.7 "
        "GB/s per direction, an aggregate of 33.4 GB/s over a path that "
        "carries 25.1 GB/s one way. That is 1.33x a single direction, where "
        "everything below 128 MiB gives 1.0x, and fluid is then a third high. "
        "Something starts overlapping the two directions at large transfers "
        "that does not at small ones; **this file does not establish what**, "
        "and naming a cause here would be inventing one."
    )
    out.append("")
    out.append(
        "The registered limits are met at the median and the band above 128 "
        "MiB is recorded as the boundary of the model's accuracy, not smoothed "
        "into it. Fitting a capacity that lands on 33.4 GB/s would have made "
        "this table read clean and made the next node's prediction wrong "
        "silently — a capacity chosen because it reproduces the answer is not "
        "a measurement of anything."
    )
    out.append("")
    out += band_table(rows, "as_measured")
    out.append("")
    out.append(
        "Fluid p50 error per point under `as_measured`. The 1-2 MiB column "
        "is overhead-dominated everywhere and the mid sizes are noisy "
        "point-to-point (`a-cond4-bidi-bg60-same` 2-0 swings between 0 and "
        "33 % across neighbouring sizes); `bandwidth_gbps_min`/`_max` and "
        "every raw sample are in the raw files, and PLAN.md's reason for "
        "requiring repetitions is heteropilot's own record of two runs of one "
        "trial disagreeing by 38 %. The `bg60` rows carry "
        "a background generator that sustained a **measured** duty cycle of "
        "0.585 to 0.600 against its 0.6 target, moving 24.6-25.1 GB/s while "
        "busy — entered into the graph as `reserved`, never as a flow, "
        "because it is traffic this planner does not control. Under "
        "`as_planned` that reservation sits on the bridge the foreground is "
        "declared to cross: 15.0 GB/s off a 25.1 GB/s bridge leaves 10.1, so "
        "both models predict the foreground drops to about 10 GB/s and takes "
        "**2.5x as long** (146 % error at 256 MiB). **It measured 25.12 GB/s, "
        "exactly its unloaded rate.** A third process saturating 1-3 six "
        "seconds in ten does nothing to 0-2 -- which is the same finding as "
        "`two-same`, reached by a different route, and the reason a "
        "reservation on the wrong resource is not a conservative error."
    )

    out += ["", "## What the `as_measured` column was fitted on", ""]
    out.append(
        "Registered here and in `docs/preregistration.md`. Anything fitted on "
        "these files is **excluded from P3's validation set** — a model shown "
        "the answer cannot also be tested by it (work order P2.4):"
    )
    out.append("")
    for name in FITTED_ON:
        out.append(f"- `experiments/microbench/raw/*/{name}`")

    out += ["", "## Condition 5 — the collective, and why `world_size` is a key", ""]
    out.append(
        "Measured on this node, busbw plateau at 64 MiB: **19.34 GB/s at "
        "world 2** across the bridge, **8.71 GB/s at world 4**. heteropilot's "
        "own `docs/nodes/a40.md` records 19.29 and 8.8 for the same two. One "
        "wire, 2.2x apart, reproduced independently — which is the argument "
        "for `world_size` being part of the `LinkMeasurement` key rather than "
        "a note beside it. NVLink at world 2 measured 52.32 GB/s p2p."
    )

    out += ["", "## The grid", ""]
    out += table([r for r in rows if r["declaration"] == "as_planned"])

    out += ["", "## Reproducing", ""]
    out.append("```bash")
    out.append("bash experiments/microbench/run_matrix.sh       # conditions 1-4")
    out.append("bash experiments/microbench/run_collective.sh   # condition 5")
    out.append("export PYTHONPATH=$PWD:$PWD/vendor/heteropilot")
    out.append(f"python experiments/microbench/analyze.py --out {args.out}")
    out.append("```")
    out.append("")
    out.append(
        "`p50` and `p90` are heteropilot's own `planner/util/percentile.py` "
        "(linear), over the per-copy samples in the raw files. Both models are "
        "given the same fixed per-transfer overhead, taken from condition 1's "
        "own 1 MiB median, so it cannot favour either."
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="experiments/results/e_g4_microbench.md")
    parser.add_argument("--json-out", default="outputs/e_g4/microbench.json")
    parser.add_argument("--raw", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.raw or RAW
    files = sorted(
        p for p in root.glob("*/*.json") if not p.parent.name.startswith("collective")
    )
    if not files:
        raise SystemExit(
            f"no raw files under {root}. Run experiments/microbench/run_matrix.sh "
            f"first -- this script computes no measurement of its own."
        )

    loaded = {p.name: json.loads(p.read_text()) for p in files}

    refused = [
        name for name, raw in loaded.items()
        if not raw.get("occupancy_stable") or not raw.get("binding_claim_is_consistent")
    ]
    if refused:
        print(
            "refusing: the GPU process set changed mid-run, or a binding claim "
            f"was not consistent, in {sorted(refused)}",
            file=sys.stderr,
        )
        return 1

    single = loaded.get("a-cond1-single-bridge-0-2.json")
    if single is None:
        raise SystemExit(
            "condition 1 (a-cond1-single-bridge-0-2) is missing, and it is the "
            "control every other condition's overhead constant comes from."
        )
    latency_ns = overhead_ns(single)

    declarations = [
        AsPlanned("as_planned", "PLAN.md: 0-2 and 1-3 share one host bridge"),
        AsMeasured("as_measured", "the endpoint x16 port is the bottleneck"),
    ]
    rows: list[dict] = []
    for declaration in declarations:
        for name in sorted(loaded):
            rows.extend(rows_for(loaded[name], declaration, latency_ns))

    verdicts = verdict(rows)
    args.iters_note = (
        f"{loaded[sorted(loaded)[0]]['iters']} repetitions per point; "
        f"PLAN.md registers at least 10."
    )
    text = markdown(rows, verdicts, args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(text)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps({"rows": rows, "verdicts": verdicts,
                        "fitted_on": list(FITTED_ON),
                        "overhead_ns": latency_ns}, indent=2, sort_keys=True) + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
