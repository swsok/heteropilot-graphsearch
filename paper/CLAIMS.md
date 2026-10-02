# Claims audit

Every assertion the paper makes, the file that carries its evidence, what kind
of number that evidence is, and whether it is established yet. A sentence in
`sections/*.tex` that is not a row here does not go in the paper.

The columns are the four the work order fixes: claim, evidence file, source kind
(`mock` / `real-sim` / `hardware`), status. `—` in the evidence column means the
experiment has not run; such a row may not be written into the draft in the
indicative.

**Status vocabulary.** `Established` — the evidence file exists, its numbers
support the claim, and its provenance banner matches the source kind.
`Pending` — the experiment is registered in `docs/preregistration.md` and has
not produced its file. `Not established` — the experiment ran and did not
support the claim; the row stays, with the file, and the paper says so.
It also covers a claim whose only evidence is a fitted set excluded from
validation (C21): nothing that could test it has run.
`Retracted` — a claim that was made and withdrawn; it stays here so the draft
cannot quietly reacquire it.

**A status may be qualified, and the qualification travels with the claim.**
E-G3's correctness row reads "Established, for the placements the simulator
judged" because `complete` is False on all three fixtures: between 4.5 % and
21 % of placements came back `SIM_ERROR` and have no verdict either way. Dropping the clause would
turn a bounded result into an unbounded one, which is the failure this file
exists to prevent.

---

## The claims

| id | Claim | Evidence file | Source kind | Status |
| --- | --- | --- | --- | --- |
| C1 | Exact equivalence compression folds a non-trivial fraction of the placement space on a symmetric cluster | `experiments/results/e_g1_toy_pilot.md` | mock | Established |
| C2 | Compression and bound-based elimination lose no feasible candidate: `false_infeasible = 0` | `experiments/results/e_g1_toy_pilot.md` | mock | Established |
| C3 | Compression merges no two placements the evaluator prices differently: `mismerged_pairs = 0` | `experiments/results/e_g1_toy_pilot.md` | mock | Established |
| C4 | On an asymmetric cluster the compression ratio is 1.0, and the corpus reports it rather than avoiding it | `experiments/results/e_g1_toy_pilot.md` | mock | Established |
| C5 | Under a binding SLO the adaptive search reaches higher feasible recall than heteropilot's surrogate top-K at k = 8 and k = 16 on the E-G1b corpus (on the E-G2 holdouts it is level at k = 8 and higher at k = 16; see C6 and C32) | `experiments/results/e_g1b_topk.md` | mock | Established |
| C6 | At k = 4 the adaptive search does **not** beat that surrogate — it ties on one holdout fixture and trails on the other | `experiments/results/e_g2_topk_holdout.md` | mock | Established |
| C7 | The ranker's goodput term must divide by a knob-aware throughput estimate, not by the elimination bound's optimistic ceiling | `experiments/results/e_g2_ranker_diagnosis.md` | mock | Established |
| C8 | The correction generalises to fixtures the diagnosis never saw | `experiments/results/e_g2_topk_holdout.md` | mock | Established |
| C9 | A ranker change cannot move either correctness number | `tests/test_oracle_agreement.py` | — (test) | Established |
| C10 | The correctness result survives replacing the mock with LLMServingSim | `experiments/results/e_g3_real_sim_oracle.md` | real-sim | Established, **for the placements the simulator judged** |
| C11 | The compression's own cost is smaller than the simulation time it saves | `experiments/results/e_g3_real_sim_oracle.md` (`saving_s`) | real-sim | Established |
| C12 | The compression ratio is a property of the graph, not of the predictor | `e_g1_toy_pilot.md` and `e_g3_real_sim_oracle.md` agree to four decimals on all three shared fixtures | mock + real-sim | Established |
| C13 | Between 4.5 % and 21 % of placements fail to simulate at all (`SIM_ERROR`), and are reported as `unknown_measurement` rather than infeasible | `experiments/results/e_g3_real_sim_oracle.md` (`unjudged`, `complete`) | real-sim | Established as a limitation; cause **not** established |
| C14 | Those failures have **two** causes, not one: a missing profile for a tensor-parallel degree, and a decode instance exhausting its KV mid-run | `experiments/results/e_g3_sim_error_causes.md` | real-sim | Established[^simerr] |
| C15 | A processor-sharing contention model predicts measured transfer time better than pricing each flow alone | `experiments/results/e_g4_microbench.md` | hardware | Established, **at location (a) only, and within 4–64 MiB**[^eg4] |
| C16 | The A40's intra-node PCIe path is **not** a shared resource: two concurrent peer copies between disjoint device pairs each sustain the single-copy rate | `experiments/results/e_g4_microbench.md` | hardware | Established |
| C17 | A two-rank all-reduce across the PCIe bridge and a four-rank all-reduce on two NVLink pairs joined by it are different measurements, so `world_size` belongs in the measurement key | `experiments/results/e_g4_microbench.md` (19.34 against 8.71 GB/s busbw) | hardware | Established |
| C18 | At the load knee of the registered spec (normal x knee), the same plan's median p99 TTFT differs 8.3x between two placements of it, with non-overlapping ranges over three repetitions each; against a target derived beforehand from the faster placement's pilot it meets on one wire and misses on the other. The planner cannot choose between them | `experiments/results/e_g5_real_hardware.md` | hardware | Established[^eg5ttft] |
| C33 | Asked about the placement deployed, the search's verdict on the recommendation matches the hardware's in every independent deployment at both TP=2 placements (3/3 each) and in none at the TP=4 one (0/3), where it predicts the target met and the hardware misses it | `experiments/results/e_g5_real_hardware.md` | hardware | Established[^eg5verdict] |
| C19 | The throughput upper bound's optimistic ceiling sits an order of magnitude above measured capacity | `experiments/results/e_g5_real_hardware.md` | hardware | Established[^eg5bound] |
| C20 | A candidate proved impossible really does miss the constraint it was proved to miss, on hardware | `experiments/results/e_g5_real_hardware.md` | hardware | Established, **on one candidate, and the test is weak by construction**[^eg5bound] |
| C21 | The slower wire moves the saturation knee itself, not only the latency at it | `experiments/e_g5/raw/pilot/` | hardware | Not established — pilot (fitted) data, no results file[^eg5p] |
| C22 | Two concurrent streams over one inter-node NIC take exactly half each, which processor sharing predicts and the intra-node PCIe path does not do | `experiments/results/e_g4_microbench.md` | hardware | Established[^locb] |
| C29 | The inter-node NIC is full duplex: both directions together exceed twice a single stream, where the intra-node pair reaches 1.33x | `experiments/results/e_g4_microbench.md` | hardware | Established |
| C31 | A collective's bandwidth is keyed by **where** it ran as well as by how many ranks: at two ranks the same all-reduce is 3.8x slower across the NIC than inside one node | `experiments/results/e_g4_microbench.md` | hardware | Established[^collb] |
| C30 | On an inter-node P/D deployment, a 0.6-duty background on the shared NIC lengthens the KV interval far less than the fluid model predicts: the registered agreement criterion is **not met** | `experiments/results/e_g5_real_hardware.md` | hardware | Established[^disagg] |
| C34 | **Post hoc** (preregistration row 9, GS-38; not registered, nothing redeployed): with the adapter corrected to every rank pair and the measured all-reduce at `world_size = tp`, re-predicting every deployed row removes T3's false positives (agreement 3 -> 17 of 18 recommendation/closest-miss rows, false positives 15 -> 0) and lowers T1's agreement (8 -> 6 of 10) | `experiments/results/e_g5_real_hardware.md` (GS-38 section), `docs/decisions.md` GS-38 | hardware + real-sim | Established, **post hoc**[^eg5post] |
| C35 | In the widened matrix (row 8) the T2/T1 ratio depends on load (normal pattern: 1.1x low, 8.3x knee, 1.4x high), and T3's recommendation is predicted met at every level of both patterns while the hardware meets it only at normal-low | `experiments/results/e_g5_real_hardware.md` (widened matrix), `docs/decisions.md` GS-37 | hardware | Established |
| C23 | The compression ratio and the search's own cost are reported as a function of device count and cluster symmetry | `experiments/results/e_g6_scale.md` | mock | Established, **report-only**[^eg6] |
| C24 | Dropping the shared boundary from the signature mis-merges the counterexample pair (criterion 2), which the full relation keeps apart; the corpus-wide row cannot show it | `experiments/results/e_g7_ablation.md` | mock | Established[^eg7] |
| C25 | The baseline comparison is fair: same candidate space, predictor and cache, with the template-level scoring credited generously to the baseline | `experiments/results/e_g7_baseline_fairness.md` | mock | Established |
| C26 | On both holdouts, fixed before the scaling grid ran, the invariant holds: no feasible placement removed, nothing mis-merged | `experiments/results/e_g7_holdout.md` | mock | Established |
| C32 | The search reaches higher recall at k = 16 than heteropilot's surrogate on `synth-holdout-1`, and **does not** on `real-lab-holdout` | `experiments/results/e_g7_holdout.md` | mock | Established, and the registered criterion is **not met** on the hardware-derived holdout[^eg7h] |

[^eg4]: The verdict computed on the topology `experiments/microbench/PLAN.md`
    registered — `as_planned` — is **FAIL**, at 93.1 % median error. That is a
    wrong declaration of which resource is shared, not a wrong model (GS-22):
    run on the declaration the measurements support, the same model is 1.8 %
    out, and on `bidirectional`, where the pairs genuinely do share endpoints,
    it is within 0.1–2.5 % of the wire against 48–50 % for null. The accuracy
    domain ends at 128 MiB bidirectional, where the pair reaches 1.33x a single
    direction and fluid is a third high --- it predicts those transfers a third
    slower than measured, so the model is pessimistic there (GS-23). The paper states the FAIL, the
    reason, and the boundary; it does not quote the 1.8 % as the result.

[^eg6]: Registered as report-only in `docs/preregistration.md`: E-G6 has **no
    success target**, only the failure condition `saving < 0` at symmetry 1.
    The grid is mock, and the one real-sim condition the research design asks
    for has **not** been run. Research design section 12 forbids presenting a
    128-device simulation as large-scale accuracy validation, and this row is
    written so it cannot be read that way.

[^eg7]: The first attempt found zero mis-merges, because a fixed tight spec
    made both placements infeasible and the oracle agreed they were equally
    bad. The threshold is now derived from the oracle itself, which is what the
    existing test does. The paper explains the derivation rather than quoting
    the count alone, because a mis-merge count depends on where the threshold
    sits.

[^eg7h]: `real-lab-holdout.v2` — the hardware fixture with one PCIe-port
    reservation (`port-gpu0`) changed — now exists and was run. The registered criterion is
    "`full` arm `feasible_recall` at k = 16 ≥ heteropilot arm's at k = 16", and
    on this fixture it is **0.1429 against 0.5**: not met. The registered
    response, written before the run, is that the ranker was fitted to the
    diagnosis corpus and the claim about it narrows to those fixtures; that is
    what is done here rather than an explanation being offered. What fails is
    the ranking, not the correctness: the invariant holds on this fixture too,
    which is why C26 and C32 are separate rows. The reservation raised on
    `port-gpu0` is not a physical claim — E-G4 showed these ports are not
    physically shared — but a variation of the topology assumption the search
    must respond to, and it does: it takes the feasible set from 64 plans to
    52, the twelve leaving being evaluated and rejected rather than
    unevaluated.

[^eg5p]: Downgraded from Established at P7.1 (internal review A-12). The
    pilot measured TP=2 on the NVLink pair against TP=2 across the PCIe
    bridge at several rates and appeared to move the knee from 5 rps to 4.
    Those pilot runs are the fitted set the E-G5 spec was derived from and are
    excluded from validation; no results file carries them and no macro reads
    them. The placement difference itself is C18, on the validation runs. The
    knee shift stays here, not established, so the draft cannot quietly
    reacquire it.

[^locb]: Measured 2026-09-29 between two A40 nodes, one Mellanox MT4123
    each on one InfiniBand subnet, with `perftest ib_send_bw`. A single stream
    reaches 88.61 Gbit/s of the 100 the port reports; two concurrent streams
    reach 44.36 each, summing to 88.73. That is processor sharing exactly, and
    it is the opposite of what the intra-node PCIe pairs did (C16), which is
    why the pair of results is worth more than either alone: **the contention
    model was never what was in question, and which resource is genuinely
    shared has to be measured at each location separately.**

    One of the five registered conditions at this location is unanswered.
    `two-independent` is **impossible on this hardware** -- each node has
    exactly one InfiniBand device, so there is no pair of disjoint NICs to put
    two flows on. `collective` was deferred when this row was first written
    and has since been measured (C31).

[^disagg]: Preregistration row 7. Template fixed, 1 rps from a knee
    pilot (the highest rate not saturated), ABAB pairs paired request by
    request. The mean pair change is +1.57 ms (SD 1.67 ms over three pairs,
    so not distinguishable from zero) against a predicted +14.45 ms, ratio
    0.11; the band was 0.5 to 2. The deployment is the experiment harness's,
    not heteropilot's, which has no router (D128). Row 5's earlier attempt is
    kept and not validated: its repetitions deployed two templates and its
    load saturated them (GS-33).

[^eg5verdict]: Counted by independent deployment of the recommendation
    at normal x knee: T1 3/3, T2 3/3, T3 0/3, every T3 disagreement a predicted
    *met* measured missed. The results table's "21 of 27 rows" also counts the
    feasible-marginal rows, which deployed the recommendation's own template
    at the same devices (GS-37, GS-38: one configuration measured twice), and
    the bound-stress rows, which agree trivially; neither is a further test.
    Before GS-30 this could not be asked: every row carried the search's own
    pick, so T1 and T2 had identical predictions. The T3 miss is reported as a
    miss --- a false *met* is the direction that matters to a planner. The
    registered experiment does not attribute it to a cause; GS-38 gives a
    candidate cause **post hoc** (the adapter told the simulator the group's
    first NVLink pair), which is C34 and is not a registered result.

[^eg5ttft]: Rerun after GS-30, three repetitions per placement, at
    normal x knee. On the NVLink pair (T1) the median measured $p99$ TTFT is
    404.5 ms; the same TP=2 plan across the PCIe bridge (T2) measures
    3,341.1 ms, 8.3x, with the same model, trace, knobs, seed and plan. The
    ranges do not overlap ([352.2, 421.3] against [3056.0, 3400.1]), and
    that ratio is the threshold-free evidence. Against the 550 ms target T1
    meets and T2 misses, but the target was set at 1.5x T1's pilot p99
    (preregistration, "E-G5 — the two specs / Derivation"), between the two
    placements by construction, so the met/missed split is not independent of
    the ratio. TPOT and goodput clear their targets at both, so latency is the
    axis that decides. The first campaign measured 379.3 and 2,891.3 ms
    (7.6x); both runs are in the raw history and the claim rests on the rerun.
    The ratio is the knee's: in the widened matrix it is 1.1x below the knee
    and 1.4x above it (C35).

    An earlier reading of one condition alone had this row as *Not
    established*, because the first placement measured happened to be one that
    misses. Three placements make the claim a different and stronger one: not
    that the recommendation fails, but that whether it succeeds is a property
    of a choice the planner has no language for.

    The search's prediction differs by placement (GS-30): median over the
    three repetitions, T1
    503.1 ms (met), T2 630.8 ms (missed), T3 212.4 ms (met). So the verdict
    matches at both pairs while the magnitude at T2 is about 5x short, and at
    T3 the verdict is wrong (C33). This experiment does not separate the
    candidate causes the work order names (prediction error, the contention
    model, the engine's scheduler); the post-hoc adapter correction (C34) is
    one candidate cause and is reported as post hoc.

[^eg5bound]: The candidate the throughput bound rejected by the smallest margin
    was deployed and offered the 55 rps floor it was rejected against. It
    reached 2.866 rps, so **`false_infeasible` is zero on hardware** and the
    bound was right. That outcome was expected and the test is registered as
    weak: a bound that is a *relaxation* rejects only what the most optimistic
    arithmetic already misses, and a rejection being correct is not news. The
    number worth having is the ratio --- the ceiling the bound computed,
    54.433 rps, is **19 times** the measured capacity. That looseness is the
    price of soundness, and this is its size on this node.


[^eg5post]: Preregistration row 9 is explicit that none of its four
    analyses tests a registered prediction: each was computed after the
    hardware results were known. The original predicted column, the hardware
    column and every registered verdict are unchanged; the re-prediction is a
    second column beside them. Before -> after, the link figure the simulator
    is given: T1 112.5 -> 39.24 GB/s, T2 25.12 -> 19.34, T3 112.5 -> 8.71.
    The T3 magnitude is still short at high load, and normal-low seed 43
    becomes a false negative. The same first-pair read remains in the demand
    labels, the contention models and the ranker's cut margin (GS-38, "not
    fixed here").

[^collb]: 5.07 GB/s busbw across the NIC against 19.34 inside one node, both at
    two ranks, same torch and same NCCL at each end. At **four** ranks the two
    are within two per cent and the inter-node figure is the higher, because
    that run places two ranks per node so half of each all-reduce stays on the
    local bus --- while the four-rank intra-node run is the case where that bus
    is already the bottleneck. Two different mixtures of two wires; the
    contributions are not decomposed and the result file says so. What the rows
    establish is the keying, in either direction, not an ordering.


[^simerr]: Established by re-running E-G3's oracle arm with the simulator's
    working directory preserved and reading the tracebacks. All three fixtures
    reproduced their recorded counts exactly.

    | fixture | failures | exception |
    | --- | --- | --- |
    | graph-toy-abcde | 24 | `FileNotFoundError` |
    | graph-toy-shared-nic | 18 | `FileNotFoundError` |
    | heterogeneous-lab | 24 | `RuntimeError` |

    The first is **no profile data** for tp=2 on that hardware --- the bundle
    holds tp1 only --- and the simulator refuses rather than extrapolating,
    which is the right refusal. The second is the simulator's memory model
    finding a decode instance out of KV mid-run and raising instead of
    returning a verdict; every one of those is a P/D candidate with prefill on
    the 96 GB device and decode on the 24 GB one, and the **reverse direction
    succeeds**.

    **Both stay `unknown_measurement`.** A missing profile is not a property of
    the placement and a crash is not a verdict. The memory bound is not at
    fault for the second either: it checks weights plus *one median request's*
    KV and declares that relaxation in its own proof, so it cannot reject on
    steady-state KV without assuming a concurrency the most optimistic
    arithmetic does not force.


## Retracted

| id | Claim | Where it was withdrawn | Why |
| --- | --- | --- | --- |
| C27 | The oracle can compare templates rather than placements | `docs/decisions.md` GS-9 | An oracle that does not see the placement makes the correctness check vacuous; retracted with numbers at G14. |
| C28 | The shared-NIC ablation cannot produce a detectable mis-merge, so keeping those placements apart is a bet on a contention model that does not exist yet | `docs/decisions.md` GS-9, second finding | Wrong, and for three findable reasons: `enable_pd` defaulted to False so no `PD_KV_TRANSFER` flow had ever been generated; the fixture had two nodes, so a P/D candidate crossed both uplinks either way round; and `bind_predictor` bound the compile hook but not the result hook. With `nodeZ`, `enable_pd=True` and both hooks bound, the counterexample comes out of the current code — `experiments/results/e_g7_ablation.md`. |

The draft writes a retracted claim as "the initial hypothesis was \dots, and the
measurement said otherwise", never by omission. A hypothesis that was tested and
failed is a result.

## Claims this paper does not make

Fixed by research design section 13, and checked at P6.1 against every sentence
of the draft:

1. **"The first to represent a cluster as a graph."** Helix does graph-based
   placement and scheduling already.
2. **"Top-K guarantees a global optimum."** It does not, heteropilot already has
   a Top-K, and this search's own contribution is that it *reports* what it
   never evaluated.
3. **Any mock figure quoted as performance.** Every fixture in this repository
   is fictional. A `mock` row above may support a claim about the *search* and
   never a claim about hardware.
4. **A simulation at 128 devices presented as large-scale accuracy validation.**
   Research design section 12 forbids it by name.
5. **A number computed from a `placeholder` input presented as measured.** The
   five provenance states never merge, and neither do the source kinds in the
   table above.
