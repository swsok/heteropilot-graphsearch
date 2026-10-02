# E-G5 — why T1 and T2 predicted the same thing

> Moved here from `experiments/results/` in P7.2: it is a hand-run diagnostic
> of the harness (the record behind GS-30), not a results file -- no script
> generates it and the paper cites none of it.

> **REAL SIM, used as a diagnostic.** Every figure here is `--predictor sim`
> (LLMServingSim) on the committed fixture; none is a hardware measurement. They
> are used to answer a question about this repository's harness, not about any
> machine.

E-G5's raw files report the same `p99_ttft_ms` --- 503.0858152199978 --- for
T1, for T2 and for all three repetitions. Two readings were put to it and
**both were falsified**. What follows is what was actually checked, because a
claim withdrawn on a guess is no better than the claim.

## The two hypotheses, and how each died

| hypothesis | check | result |
| --- | --- | --- |
| the harness never bound the compile hook (GS-13 family) | `hook_calls` on a **cold** cache | **falsified.** `compile_applied 8/8` |
| the simulator does not respond to TP all-reduce bandwidth (D3/D124) | one tp2 candidate, only `link_bw` changed | **falsified.** See below |

The first looked true at the start: the harness's own cache directory was warm,
and a run that hits cache never calls the compile hook, so `compile_applied`
read 0. It reads 8/8 the moment the cache is cold. Declaring GS-13 on that
would have sent three E-G5 conditions to be rerun for a reason that was not
the reason.

The second: one candidate, one spec, only `link_bw` altered through the hook
the search itself uses.

| `link_bw` GB/s | p99 TTFT ms | p99 TPOT ms |
| --- | --- | --- |
| 112.5 | 23383.29 | 24.51 |
| 25.12 | 26159.66 | 25.63 |
| 10.05 | 31708.49 | 27.89 |
| 1.0 | 119709.65 | 71.29 |

The first attempt at this table showed no response at all, and was wrong: it
had picked a `tp1-dp2` candidate, and tensor-parallel degree one has no
all-reduce to be slowed down. The candidate has to be `tp2` or the experiment
does not ask the question. That is recorded rather than quietly fixed.

## What the cause actually is

The graph does tell the placements apart. `compile_embedded` puts this
cluster's two-device placements into three classes:

| `link_bw` GB/s | placements |
| --- | --- |
| 112.5 | the four NVLink pairs, including T1's `(gpu0, gpu1)` |
| 25.12 | the PCIe pairs, including T2's `(gpu0, gpu2)` |
| 10.05 | the same PCIe pairs, once the holdout reserves their uplink |

So the hook runs, the graph discriminates, and the simulator responds. The
identical numbers come from none of those.

`run_plan` passes `max_devices=len(topology.devices)` and **no placement**.
T1 and T2 are therefore the same search, with the same arguments, returning the
same candidate id --- and the second is served entirely from cache. The
placement is applied afterwards, as `placement_override`, and nothing is
predicted again.

Under the budget the harness uses, every feasible plan came out on an NVLink
pair, and 194 placements went **unevaluated** --- including T2's own
`(gpu0, gpu2)`. Unevaluated is not infeasible. The harness prints a feasible
NVLink placement's metrics beside a measurement taken at a placement the search
never judged, and nothing in the raw file says so.

This is the same family as GS-13 and not the same defect: the hook is bound and
applied, and the missing step is the one that asks for the deployed placement's
own verdict. For T2 the honest value is `unknown_measurement`. E-G5's three
conditions are rerun on that basis (GS-30).

## What this does not say

It does not say the simulator's TTFT is *accurate* in its response to
bandwidth, only that it has one. It does not say T2 is infeasible: the search
never reached it. And it does not bear on the hardware measurements in
`e_g5_real_hardware.md`, which were taken at the placements named and are
unaffected --- what is withdrawn is the predicted column beside them.
