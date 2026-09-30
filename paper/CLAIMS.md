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
| C5 | Under a binding SLO the adaptive search reaches higher feasible recall than heteropilot's surrogate top-K at k = 8 and k = 16 | `experiments/results/e_g1b_topk.md` | mock | Established |
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
| C17 | A two-rank and a four-rank all-reduce over one path are different measurements, so `world_size` belongs in the measurement key | `experiments/results/e_g4_microbench.md` (19.34 against 8.71 GB/s busbw) | hardware | Established |
| C18 | Whether the recommendation meets its SLOs on hardware **depends on the placement**, which the planner cannot choose: the same plan meets its latency target on one wire and misses it by a factor of eight on another | `experiments/results/e_g5_real_hardware.md` | hardware | Established[^eg5ttft] |
| C33 | Asked about the placement deployed, the search's verdict matches the hardware's at both TP=2 placements and not at the TP=4 one, where it predicts the target met and the hardware misses it | `experiments/results/e_g5_real_hardware.md` | hardware | Established[^eg5verdict] |
| C19 | The throughput upper bound's optimistic ceiling sits an order of magnitude above measured capacity | `experiments/results/e_g5_real_hardware.md` | hardware | Established[^eg5bound] |
| C20 | A candidate proved impossible really does miss the constraint it was proved to miss, on hardware | `experiments/results/e_g5_real_hardware.md` | hardware | Established, **on one candidate, and the test is weak by construction**[^eg5bound] |
| C21 | Two placements differing only in which wire their tensor-parallel all-reduce crosses differ measurably in served TTFT | `experiments/e_g5/raw/pilot/` | hardware | Established, **intra-node, by a placement the planner cannot name**[^eg5p] |
| C22 | Two concurrent streams over one inter-node NIC take exactly half each, which processor sharing predicts and the intra-node PCIe path does not do | `experiments/results/e_g4_microbench.md` | hardware | Established[^locb] |
| C29 | The inter-node NIC is full duplex: both directions together exceed twice a single stream, where the intra-node pair reaches 1.33x | `experiments/results/e_g4_microbench.md` | hardware | Established |
| C31 | A collective's bandwidth is keyed by **where** it ran as well as by how many ranks: at two ranks the same all-reduce is 3.8x slower across the NIC than inside one node | `experiments/results/e_g4_microbench.md` | hardware | Established[^collb] |
| C30 | Inter-node **P/D** contention, which needs disaggregated prefill | — (E-G5) | hardware | Pending[^disagg] |
| C23 | The compression ratio and the search's own cost are reported as a function of device count and cluster symmetry | `experiments/results/e_g6_scale.md` | mock | Established, **report-only**[^eg6] |
| C24 | Dropping the shared boundary from the signature produces mis-merges | `experiments/results/e_g7_ablation.md` | mock | Established[^eg7] |
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
    direction and fluid is a third high (GS-23). The paper states the FAIL, the
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

[^eg7h]: `real-lab-holdout.v2` — the hardware fixture with one uplink
    reservation changed — now exists and was run. The registered criterion is
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

[^eg5p]: Measured on this node's own wires, not across a NIC: TP=2 on the
    NVLink pair against TP=2 across the PCIe bridge, same model, trace, knobs
    and seed. At the knee the difference is 7.65x in p99 TTFT, and two
    independent knee curves show why — the placement moves the knee from 5 rps
    to 4, costing about 20 % of serving capacity. The claim is worth making
    because **heteropilot cannot express the difference at all**:
    `resolve_devices` maps an island to every one of its accelerator ids, so it
    names a template and never a placement. What is *not* claimed is that this
    is the inter-node P/D condition the matrix registered; see the next row.

[^locb]: Measured 2026-09-29 between two A40 nodes, one Mellanox MT4123
    each on one InfiniBand subnet, with `perftest ib_send_bw`. A single stream
    reaches 88.61 Gbit/s of the 100 the port reports; two concurrent streams
    reach 44.36 each, summing to 88.73. That is processor sharing exactly, and
    it is the opposite of what the intra-node PCIe pairs did (C16), which is
    why the pair of results is worth more than either alone: **the contention
    model was never what was in question, and which resource is genuinely
    shared has to be measured at each location separately.**

    Two of the five registered conditions at this location are still unanswered,
    for reasons that do not merge. `two-independent` is **impossible on this
    hardware** -- each node has exactly one InfiniBand device, so there is no
    pair of disjoint NICs to put two flows on. `collective` is **deferred**: an
    all-reduce over IB needs NCCL, which needs torch on both nodes, and the peer
    has no such environment yet.

[^disagg]: A second node exists, so "one machine" is no longer a reason. The
    other one stands: `planner/deploy/vllm_cuda.py` builds the argv for "one
    aggregated engine" with no `kv_connector` and no producer/consumer role, so
    a disaggregated prefill pair cannot be deployed at all. That is a hook PR to
    that repository, not a measurement waiting to be taken.

[^eg5verdict]: 21 of 27 rows agree; all six disagreements are T3's
    recommendation and feasible-marginal rows, predicted met and measured
    missed. Before GS-30 this could not be asked: every row carried the
    search's own pick, so T1 and T2 had identical predictions. The T3 miss is
    reported as a miss --- a false *met* is the direction that matters to a
    planner --- and is not attributed to a cause this experiment did not
    separate.

[^eg5ttft]: Rerun after GS-30, three repetitions per placement, against a
    550 ms target. On the NVLink pair (T1) the median measured $p99$ TTFT is
    404.5 ms and the target is **met**; the same TP=2 plan across the PCIe
    bridge (T2) measures 3,341.1 ms and **misses**, 8.3x, with the same model,
    trace, knobs, seed and plan. The ranges do not overlap. TPOT and goodput
    clear their targets at both, so latency is the axis that decides. The first
    campaign measured 379.3 and 2,891.3 ms (7.6x); both runs are in the raw
    history and the claim rests on the rerun.

    An earlier reading of one condition alone had this row as *Not
    established*, because the first placement measured happened to be one that
    misses. Three placements make the claim a different and stronger one: not
    that the recommendation fails, but that whether it succeeds is a property
    of a choice the planner has no language for.

    The prediction was 161.7 ms throughout, so the simulator is optimistic by
    2.3 times at the placement that meets its target and by 18 at the one that
    does not --- and it predicts the *same* number for both, which is the
    concrete form of the limitation Section 7 reports. This experiment does not
    separate the candidate causes the work order names (prediction error, the
    contention model, the engine's scheduler), and does not choose the most
    flattering one.

[^eg5bound]: The candidate the throughput bound rejected by the smallest margin
    was deployed and offered the 55 rps floor it was rejected against. It
    reached 2.866 rps, so **`false_infeasible` is zero on hardware** and the
    bound was right. That outcome was expected and the test is registered as
    weak: a bound that is a *relaxation* rejects only what the most optimistic
    arithmetic already misses, and a rejection being correct is not news. The
    number worth having is the ratio --- the ceiling the bound computed,
    54.433 rps, is **19 times** the measured capacity. That looseness is the
    price of soundness, and this is its size on this node.


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
