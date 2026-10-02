# Internal review (P7.1)

Two reviewer roles, run as separate passes over the draft at `dbcebf4`
(branch `paper/p7-1-internal-review`, stacked on `exp/e-g5-expand` / PR #42):

- **Reviewer A** -- does any sentence claim more than its evidence supports?
  Checked against `experiments/results/*.md`, `docs/decisions.md` (GS-30..38),
  `docs/preregistration.md` (rows 1-9) and `CLAIMS.md`.
- **Reviewer B** -- can every table, figure and number be reproduced from this
  repository, and how? Every mock results file was regenerated into a scratch
  directory and compared; E-G4 and E-G5 were re-analysed from the committed raw
  files; `numbers.tex` and the generated tables were rebuilt.

Each finding is settled in one of three ways, recorded in the last column:
**fixed** (the text or code now says what the evidence supports), **limits**
(moved to the limitations section as a stated limit), or **P7.2** (a
reproduction-package item, settled in `REPRODUCE.md`). Nothing is closed as
"won't fix" without a reason in the row.

## Reviewer A -- claims against evidence

| id | where | finding | severity | disposition |
| --- | --- | --- | --- | --- |
| A-1 | `main.tex`, `intro.tex` | "sevenfold" / "a factor of seven": the registered T2/T1 ratio is 8.3x (`\egfiveTtwoOverTone`); 7.6x was the first campaign. A spelled-out number also escapes the literal check. | must | fixed: `main.tex:94`, `intro.tex:31`, `conclusion.tex:38` -- `\egfiveTtwoOverTone{}x` (8.3), no spelled-out factor |
| A-2 | `eval.tex` C18, abstract, intro, conclusion | "meets on one wire, misses on the other" is partly by construction: the 550 ms target was set at 1.5x T1's pilot p99, between T1 and T2. The threshold-free evidence is the ratio with non-overlapping ranges. | must | fixed: `eval.tex:284-298`, `intro.tex:27-34`, abstract, conclusion -- lead with the ratio, medians and non-overlapping ranges (new macros); met/missed stated as partly by construction, target derived from T1's pilot (prereg "E-G5 -- the two specs / Derivation"); CLAIMS C18 + fn eg5ttft. The 550 ms and 1.5x are in no results-md cell, so the body names the derivation without the numbers |
| A-3 | `eval.tex` C33 | "21 of 27 rows" counts 9 duplicate marginal rows and 9 bound-stress rows that agree trivially; independent recommendation deployments are T1 3/3, T2 3/3, T3 0/3. | must | fixed: `eval.tex:304-320` -- counts independent recommendation deployments (`\egfiveReps`: every one at T1, T2; none at T3); marginal and bound-stress rows said not to be further tests; CLAIMS C33 + fn eg5verdict |
| A-4 | `eval.tex` C33, `limits.tex` | GS-38 is absent: every registered E-G5 prediction used the first-pair link figure (T1 too). Post hoc, T3 agreement 3/18 -> 17/18 but T1 8/10 -> 6/10. The adapter description in limits is contradicted. | must | fixed: `eval.tex:322-341` (new C34, labelled post hoc: T3 agree 3->17/18, FP 15->0; T1 8->6/10), `limits.tex:63-80` (corrected adapter described; registered rows used the first-pair figure); CLAIMS C34 + fn eg5post |
| A-5 | `adapter.tex`, `limits.tex` | "names every resource it dropped": GS-38's dropped rank pairs were not reported by the loss report. | must | fixed: `adapter.tex:26-31`, `limits.tex:74-78` -- the report names dropped shared resources only and did not report GS-38's ignored rank pairs |
| A-6 | `eval.tex` C19/C20 | "the two boundary alternatives are deployed": the feasible-marginal one duplicated the recommendation (GS-37/38); only the bound-rejected one is a separate test. | must | fixed: `eval.tex:356-361` -- only the bound-stress alternative is a separate test; feasible-marginal repeated the recommendation (GS-37/38) |
| A-7 | `eval.tex` E-G6 | "the compression must not cost more than it saves ... It does not": `e_g6_scale.md` says the mock table cannot evaluate this; E-G3 answers it at toy scale. | must | fixed: `eval.tex:122-128` -- the mock grid cannot evaluate the failure condition; E-G3 answers it at toy scale |
| A-8 | `eval.tex`, `limits.tex` | "the asymmetric ratio 0.067 ... finds almost nothing to fold": 0.067 is a 15x fold; only `graph-toy-asym` (1.0) folds nothing. | must | fixed: `eval.tex:114-119`, `limits.tex:29-34` -- 0.067 is a substantial fold; nothing folds only on `graph-toy-asym` (`\egoneRatioAsym`, new) |
| A-9 | `eval.tex`, `limits.tex` | above 128 MiB the model is "optimistic by a third": fluid over-predicts transfer time there -- it is pessimistic. | must | fixed: `eval.tex:269-273`, `limits.tex:59-60`, CLAIMS fn eg4 -- pessimistic: predicts transfers about a third slower than measured |
| A-10 | `search.tex`, `eval.tex` | "higher feasible recall at K = 8 and 16": tie at K=8 on the E-G2 holdouts, lower on real-lab-holdout (C32); the win holds on E-G1b and synth-holdout-1. | must | fixed: `search.tex:82-88`, `eval.tex:170-175` -- higher at every K on E-G1b; on E-G2 holdouts level at 8, higher at 16, K=4 tie/trail; lower on real-lab-holdout; CLAIMS C5 scoped |
| A-11 | `related.tex` | "the hardware campaign could not deploy [P/D]": it did, through the harness (GS-32/34). | must | fixed: `related.tex:37-40` -- deployed through the experiment's own harness, backend has no router |
| A-12 | `eval.tex` C21, abstract, intro | C21 is `% pending` but its only evidence is the pilot raw directory -- the fitted set, excluded from validation -- with no results file or macro. | must | fixed: C21 paragraph removed from `eval.tex`; knee claims removed from abstract (`main.tex:71`) and intro; limits: `limits.tex:121-128` (`% not-established`) -- knee shift seen only in excluded pilot runs; CLAIMS C21 -> Not established |
| A-13 | `CLAIMS.md` fn eg5ttft | "the prediction was 161.7 ms throughout ... the same number for both" is the withdrawn GS-30 reading; the table now has T1 503.1, T2 630.8. | must | fixed: `CLAIMS.md` fn eg5ttft -- per-placement predictions (T1 503.1, T2 630.8, T3 212.4 medians), GS-30 reading removed |
| A-14 | `eval.tex` E-G5 | the widened matrix (row 8, GS-37) is absent; the T2/T1 ratio is level-dependent (1.1x low, 8.3x knee, 1.4x high). | should | fixed: `eval.tex:343-354` (new C35, registered row 8: ratio 1.1x / 8.3x / 1.4x by level; T3 predicted met everywhere, met on hardware only at normal-low); C18 scoped to the knee |
| A-15 | abstract, intro, conclusion | "no feasible candidate was wrongly eliminated ... in every experiment" exceeds scope: judged placements only; E-G4/E-G5 carry no such counts; hardware tests one candidate. | should | fixed: abstract `main.tex:87-90`, `intro.tex:78-82`, `conclusion.tex:22-28` -- scoped to exhaustive-oracle experiments, judged placements; hardware tests one candidate |
| A-16 | abstract, `adapter.tex` | contention model "exactly right on another [bus]": on that NIC the P/D effect was 0.11x the prediction (C30, criterion not met). | should | fixed: abstract `main.tex:95-101` -- borne out on the NIC, but the P/D effect was far smaller than predicted |
| A-17 | `limits.tex` | P/D "+1.57 ms" without "not distinguishable from zero" (SD 1.67, n=3). | should | fixed: `limits.tex:101-103` -- SD `\egfivePdSd` (new) over three pairs, not distinguishable from zero |
| A-18 | `limits.tex` | "each of these was registered before the experiment that could have revealed it": several were found after. | should | fixed: `limits.tex:20-26` -- some stated in advance, others found by running and recorded with their decision |
| A-19 | `limits.tex` | "a candidate it has effectively judged": a crash is not a verdict (GS-17). | should | fixed: `limits.tex:48-51` -- the raise carries a reason, not a verdict (GS-17) |
| A-20 | `adapter.tex`, `background.tex`, `related.tex` | inconsistent about what the simulator is told: the adapter does pass a per-placement bottleneck. | should | fixed: `adapter.tex:18-27`, `background.tex:38-44`, `related.tex:46-50` -- per-placement bottleneck is passed; shared resources are not |
| A-21 | `graph.tex` C17 | "one PCIe path ... 8.71 GB/s for the four-rank all-reduce": the world-4 group spans two NVLink pairs and the bridge. | should | fixed: `graph.tex:44-53`, CLAIMS C17 -- the world-4 group spans two NVLink pairs and the bridge |
| A-22 | `search.tex` | the cut bound "is a proof and not an estimate": a proof relative to the declared cluster description. | should | fixed: `search.tex:47-50` -- a proof relative to the declared cluster description |
| A-23 | `eval.tex` C24, abstract, intro, conclusion | `no_boundary` "produces mis-merges": the input table shows 0; the one mis-merged pair is in criterion 2's table, not input. | should | fixed: `eval.tex:134-144`, abstract, intro, conclusion, CLAIMS C24 -- corpus row shows 0 (ruler), the mis-merge is criterion 2's counterexample pair |
| A-24 | `eval.tex` setup | "hardware is an eight-GPU node": a second node was used for inter-node measurements. | should | fixed: `eval.tex:33-36` -- second node over InfiniBand for inter-node measurements |
| A-25 | `eval.tex`, `limits.tex` | "every fixture is fictional, with one exception": two hardware-derived clusters plus one derived holdout. | should | fixed: `eval.tex:38-46`, `limits.tex:111-118` -- three exceptions: a40x8, s8s6, and the derived holdout (assumed reservation) |
| A-26 | `background.tex` | "five hooks": four (reuse table, GS-32: no H5). | should | fixed: `background.tex:49` (and header comment) -- four hooks. `MAP.md` still says H1-H5 (not edited) |
| A-27 | `eval.tex` setup | once row 9's analyses are cited, say that post-hoc analyses test no registered prediction. | should | fixed: `eval.tex:50-53` -- post-hoc analyses labelled and test no registered prediction |
| A-28 | `CLAIMS.md` fn eg5verdict | "not attributed to a cause": GS-38 gives a post-hoc candidate cause. | should | fixed: `CLAIMS.md` fn eg5verdict -- GS-38 gives a post-hoc candidate cause (C34) |
| A-29 | `CLAIMS.md` fn locb | "`collective` is deferred": it was measured (C31). | note | fixed: `CLAIMS.md` fn locb -- `collective` since measured (C31); one condition unanswered |
| A-30 | `eval.tex` | the 128 MiB paragraph is tagged C17; it is C15's evidence. | note | fixed: `eval.tex:269` -- tagged C15 |
| A-31 | `eval.tex` figure caption | "at K=4 the graph search is behind": it ties on one holdout. | note | fixed: `eval.tex:161` caption -- ties on one holdout, behind on the other |
| A-32 | `candidates.tex` vs `adapter.tex` | two different caches called "the cache". | note | fixed: `candidates.tex:53-59`, `adapter.tex:54-59` -- bucket key contains the prediction key; the oracle's per-placement result cache is named as a different cache |
| A-33 | `eval.tex`, `CLAIMS.md` | "one uplink reservation": it is a PCIe port (`port-gpu0`). | note | fixed: `eval.tex:193-194`, CLAIMS fn eg7h -- one PCIe-port reservation (`port-gpu0`) |
| A-34 | `limits.tex` | for TP > 2 the demand label and the pre-GS-38 evaluator shared the first-pair blind spot, so `mismerged_pairs = 0` there is not independent evidence. | note | limits: `limits.tex:82-87` -- for TP > 2 demand labels and the pre-GS-38 evaluator shared the first-pair blind spot; mismerged = 0 there is not independent evidence |
| A-35 | `related.tex` | no bibliography: related-work statements are uncited (P6.4). | note | no change: citations left for P6.4; no uncited statement added |

## Reviewer B -- reproducibility

All 55 generated tables and the 40 macros rebuild byte-identically; every mock
results file regenerates byte-identically apart from the echoed `--out` path;
E-G4 and E-G5 re-analyse byte-identically from the committed raw files; 5 of 6
figures are identical once `CreationDate` is stripped.

| id | where | finding | severity | disposition |
| --- | --- | --- | --- | --- |
| B-1 | `.gitignore:29` | `paper/tables/*.tex` also ignores the hand-written `reuse.tex`, never committed; a fresh clone cannot build the paper (`limits.tex` inputs it). | must | fixed: `.gitignore` un-ignores `paper/tables/reuse.tex`, now committed (3d319d1) |
| B-2 | `e_g3_sim_error_causes.md` | the documented command omits the required `--work-dir`; the work dir no longer exists; C14 has no raw source short of a 1.6 h cold rerun. | must | P7.2 fixed: the script emits `--work-dir`, and the md's block is corrected to match; the work dir no longer exists, so `REPRODUCE.md` says C14 is re-derived by a cold run, not re-read |
| B-3 | C21 | no generated artefact behind the claim (same as A-12). | must | fixed with A-12: C21 is not established; its body paragraph is removed and the pilot observation is a limit |
| B-4 | E-G3 timings | rerunning against the cache overwrites cold timings with warm ones, and `make numbers` would carry them into the paper unchecked. | should | P7.2 fixed: E-G3 timing macros carry `where: {cold: "True"}`, so a warm row fails the lookup (checked on a copy with one row flipped) |
| B-5 | `e_g3_oracle_run.sh` | never writes `outputs/eg3.json`, which the cache check reads; the md's reproduce block omits the cache-check step. | should | P7.2 fixed: `e_g3_oracle_run.sh` writes `JSON_OUT` (default `outputs/eg3.json`); `REPRODUCE.md` lists the cache-check step |
| B-6 | `e_g5_real_hardware.md` | the reproduce block names one condition of 45, `$PRE` is undefined, other entry points unlisted. | should | P7.2 fixed: the grid launcher is committed (`experiments/e_g5/run_grid.sh`) and so is the pre-GS-38 diagnosis tree (`run_floor_diagnosis.sh`, rerun byte-identical); the md's block names both |
| B-7 | `e_g5_topology_prediction.md` | hand-written, no generator or reproduce command. | should | P7.2 fixed: moved to `docs/diagnostics/` -- a hand-run diagnostic behind GS-30, not a results file |
| B-8 | figures | missing inputs make `make figures` skip silently; PDFs embed `CreationDate`; `topk_synthetic_holdout.pdf` is stale (and unused, as are `scale_*.pdf`). | should | fixed (3d319d1): `savefig` writes no `CreationDate` (two runs byte-identical); a missing input or matplotlib is a non-zero exit; `make figures` derives `outputs/e_g4/microbench.json` from raw first; all six PDFs regenerated, `topk_synthetic_holdout.pdf` refreshed |
| B-9 | `paper/Makefile` | `paper` does not depend on `numbers`. | should | fixed (3d319d1): `paper: tables numbers figures pdf` |
| B-10 | every reproduce block | bare `python` is 3.8 here; the code needs 3.10; `pyproject.toml` has no `requires-python`. | should | P7.2 fixed in `REPRODUCE.md` (3.10, `.venv/bin/python`); `pyproject.toml` deliberately has no `[project]` table, like heteropilot's |
| B-11 | `outputs/` | caches and archived JSON (about 18 MB) are gitignored and need an archive. | should | P7.2 fixed: `scripts/reproduce/archive_outputs.sh` packs the seven inputs (about 18 MB) with a checksum manifest; hosting is decided at submission |
| B-12 | submodule `.venv` | heteropilot's `.gitignore` does not cover `.venv`; building it on a fresh clone dirties the submodule and fails the gate. | should | P7.2 fixed in `REPRODUCE.md`: the `info/exclude` lines for the submodule's venvs |
| B-N1 | `md_to_tex.py` | tables are named by position; inserting one above an `\input` table relabels it. | note | noted; no `\input` table is positional-sensitive today (the paper inputs only first tables and the E-G4/E-G7 ones checked here) |
| B-N2 | `numbers.yaml` | 9 of 40 macros are unused in the body. | note | noted; unused macros are harmless and kept for the tables they check |
| B-N3 | results md | reproduce blocks sit at the end, not the head. | note | P7.2: each results file's block is generated by its script; `REPRODUCE.md` is the single index at the head of the package |
| B-N4 | branch | the fixed commit for `REPRODUCE.md` must be taken after PR #42 merges. | note | P7.2: `REPRODUCE.md` pins the commit tagged at submission, after the stack merges |
| B-N5 | simulator prerequisites | apt packages, submodule init, the post-`compile.sh` lines, the sim interpreter. | note | P7.2 fixed in `REPRODUCE.md` (setup and simulator sections) |

## Found while applying the fixes

| id | where | finding | disposition |
| --- | --- | --- | --- |
| W-1 | `docs/preregistration.md`, "Known limitations" | says the ranker overtakes the surrogate at K = 8; `e_g2_topk_holdout.md` shows a tie at K = 8 on both holdouts. | the preregistration is append-only and is not edited; the paper follows the results file (A-10) and this row records the difference |
| W-2 | `paper/MAP.md` | "hooks H1-H5" | fixed: H1-H4, no H5 (GS-32) |
| W-3 | C18 | the 550 ms target and its 1.5x derivation are in no results-file cell, so the body states the derivation without the numbers rather than as literals | kept that way; the numbers are in the preregistration, which the sentence cites |

## Verification pass (reviewer A, after the fixes)

31 of 35 confirmed fixed as written; every new macro checked against its
source cell and `numbers.tex` regenerated byte-identically. Residuals, fixed
after the pass:

| id | finding | disposition |
| --- | --- | --- |
| A-10 | "higher recall at every K on the toy corpus" does not say those are the in-sample diagnosis fixtures | fixed: `search.tex`, `eval.tex` say so |
| V-1 | C33's bold lead "the search tells the two pairs apart" unqualified, though C34 shows T1 agreement falls once the adapter is corrected | fixed: "with the registered adapter", forward reference to the correction |
| V-2 | C35 "the knee is where the wire decides": above the knee the wires still differ in verdict | fixed: the ratio is largest at the knee; the verdict differs at and above it, not below |
| V-3 | C34 "identifies a cause": a post-hoc re-prediction is consistent with one, and is still short at high load | fixed: "consistent with ... still short in magnitude at the highest load" |
| V-4 | stale `% pending` on the C13/C14 paragraph in `limits.tex` | fixed: removed |
| V-5 | A-23's text cites the criterion-2 result, but its table was not in the paper | fixed: `\input{e_g7_ablation_4}` (full 2 representatives / 0 mis-merged; `no_boundary` 1 / 1) beside the paragraph |
| V-6 | A-32 was taken on the text alone | checked in code: `Signature.bucket(prediction_key)` (`graphsearch/equivalence.py`) carries the planner's prediction key; the sentence stands |

## Length cut for ISPASS (9 pages)

IEEEtran conference 10pt put the draft at 13 pages; ISPASS allows 9 (no
bibliography yet, so the whole PDF). After the cut: **9 pages**, `make check`
passes, no Overfull box or undefined reference in the final TeX pass (the four
`TU/ptm` font-shape warnings come from the template and are unchanged). Every
P7.1 qualification is kept in at least one place; where a statement appeared in
several sections, the copies were removed and the qualified one kept.

| cut | kind | where its evidence still lives |
| --- | --- | --- |
| `e_g2_topk_holdout` table | removed (figure shows it) | `topk_holdout.pdf` (Fig.); `experiments/results/e_g2_topk_holdout.md`; in-sample/holdout scoping (A-10) stays in `eval.tex` Search quality |
| `e_g3_real_sim_oracle_2` table (timings) | removed (macros carry it) | `\egthreeSimOracleAbcde`, `\egthreeSimProposedAbcde`, `\egthreeSavingAbcde` in eval; `e_g3_real_sim_oracle.md` table 1 |
| `e_g4_microbench_2` table (verdicts) | removed (macros + figure) | `\egfour*` macros in eval; `contention_error.pdf`; `e_g4_microbench.md` |
| `e_g1_toy_pilot` table | removed (secondary) | `e_g3_real_sim_oracle` covers three of the four fixtures; graph-toy-asym ratio via `\egoneRatioAsym`; `e_g1_toy_pilot.md` |
| `e_g1b_topk` table | removed (secondary) | the in-sample sentence in eval; `e_g1b_topk.md` |
| `e_g7_baseline_fairness` table | removed (secondary) | the "scored generously" paragraph in eval; `e_g7_baseline_fairness.md` (C25) |
| `e_g7_ablation` corpus-wide table | removed (`e_g7_ablation_4` carries C24) | the "property of the ruler" sentence in eval; `e_g7_ablation.md` |
| abstract | rewritten, 366 -> about 210 words | same claims; A-15 scope (exhaustive-oracle experiments, judged placements), one-candidate bound test, knee scoping kept |
| intro | the C18/C21 paragraph and the planner paragraph merged; contributions shortened | qualifications kept: pilot-derived target, knee, judged placements, one hardware candidate |
| background | "approximate merging" folded into "execution islands"; the simulator paragraph reduced to a pointer | `adapter.tex` |
| problem | candidate + objective merged; the five-state list inlined | unchanged content, minus the unpriced-device reasoning (now one clause) |
| graph, candidates | paragraphs merged; the "which resource is shared" paragraph reduced to a pointer | eval, Contention model |
| search | the recall-by-K paragraph **dropped** from this section; ranking paragraphs merged; "what was not reached" merged into the budget paragraph | eval, Search quality (A-10 wording intact) |
| adapter | the corrected-adapter description moved here from limits (C34); predictor binding and cache paragraphs merged; the accuracy-domain sentence dropped | eval, 128 MiB paragraph (A-9, pessimistic) |
| limits | opening paragraph, "contention model is fluid", "every fixture but three", "what a certificate certifies" dropped as duplicates; others shortened | eval Setup (fixtures), eval 128 MiB (A-9), adapter (not packet-level), search (certificate); GS-38 first-pair limits, judged-placements scope and C21 kept in limits |
| conclusion | four paragraphs -> one | same claims, same qualifications (exhaustive-oracle scope, one-candidate bound test, knee, P/D miss) |

### Verification of the cut (reviewer A)

Every A-n and V-n qualification is kept at least once (file:line per item in
the reviewer's report); no shortened sentence is stronger; every `\ref` resolves
to a table still in the paper; every number whose table was cut is a macro.
Open, for the submission rather than the text:

| id | note | status |
| --- | --- | --- |
| D-1 | four sentences point to "the artifact" (timing table, toy-corpus table, corpus-wide ablation, toy-corpus recall); under double-blind a reviewer cannot see it | the toy-corpus recall now carries its numbers in the text (two macros from `e_g1b_topk.md`); the rest needs an anonymised artifact link at submission (user decision) |
| D-2 | "registered" / "preregistration" and "accompanying repository" appear with no anonymised pointer | same as D-1 |
| D-3 | the reuse table plus "hooks" and "golden tests" may identify the extended planner | check against the 2027 anonymity rules when the call appears |

## Revision R1.4: layout, and the two restored tables

| id | what | where it lives now |
| --- | --- | --- |
| L-1 | Table VI (reuse) moved from Limitations to Background, `[!t]`; the near-empty page 9 is gone | `background.tex`, top of page 2 |
| L-2 | the E-G5 placement table's `\input` moved to the start of its subsection, so the `table*` lands on the page after its first reference instead of two pages later | `eval.tex`, Hardware |
| L-3 | **restored, but not the table the work order named.** The "agree/disagree 3x3" table in the results file counts all 27 rows, including the 9 duplicate feasible-marginal rows and 9 bound-stress rows -- the overcount A-3 removed. `analyze.py` now writes a second table counting independent recommendation deployments only (T1 3/3, T2 3/3, T3 0/3), and that is the one the paper restores and cites; the all-rows table stays in the results file | `e_g5_real_hardware_3`, C33 |
| L-4 | restored: the corpus-wide E-G7 ablation, with chosen columns | `e_g7_ablation`, C24 |
