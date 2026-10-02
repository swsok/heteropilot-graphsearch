# 작업지시서 — 투고본 수정 (heteropilot-graphsearch, STEP R1~R8)

> 2026-10-02 논문 리뷰(`paper_review_ispass27_2026-10-02.md`)의 §5 권장 순서를 실행하는 지시서. 선행 지시서 `WORK_ORDER_paper.md`(P0~P7)의 규칙 §0은 전부 그대로 적용된다.
> 저장소: `swsok/heteropilot-graphsearch` main `e77d265` 이후 · 서브모듈 `vendor/heteropilot b339adf`(읽기 전용; 변경은 heteropilot PR → bump) · 작성일: 2026-10-02
> 목표: ISPASS 2027(예상 마감 12월 초 초록·중순 본문) 투고본. **약 10주.**
> 인력: 사용자 1인 + Claude Code. 실측과 결정은 사용자, 스크립트·분석·문서·조판은 Claude Code.

---

## 0. 규칙 (P0~P7 규칙 위에 추가)

1. **PDF가 게이트다.** 지금까지 `make check`는 컴파일을 하지 않아 표가 컬럼 밖으로 잘려 나간 것을 못 잡았다. R1에서 `make check-pdf`를 만들고, 이후 **모든 paper PR은 `make pdf && make check-pdf` 통과**가 머지 조건이다. 완료 보고에는 쪽수와 Overfull 목록(0건이어야 함)을 넣는다.
2. **사후 분석과 등록 외 확장은 라벨을 단다.** 등록된 판정은 바꾸지 않는다. 새 실험(E-G8)은 첫 요청 전에 사전 등록 row 10으로 등록한다. 기존 arm의 반복 추가(P/D 쌍)는 "post-registration extension"으로 별도 표에 보고하고 등록 기준의 판정에 섞지 않는다.
3. **HeteroPilot은 3인칭으로 명명하고 인용한다**(사용자 결정 2026-10-02). 본문에서 "the planner this work extends / the existing planner"는 첫 정의 한 문장만 남기고 전부 `HeteroPilot~\cite{heteropilot}`로 바꾼다. HeteroPilot의 설계는 이 논문이 기대는 최소한만 서술하고, 어떤 것도 이 논문의 기여로 쓰지 않는다(Table VI가 경계). 인용 대상은 R6의 arXiv 프리프린트다.
4. **익명성.** 심사용 PDF와 아카이브에 GitHub 계정·리포 URL·deviation 번호(D-nnn)·사용자 이름이 들어가면 안 된다. `make check`에 금지 패턴(`swsok`, `github.com/`, `D1[0-9][0-9]`, `GS-[0-9]`)을 추가한다. 결정 로그 번호는 결과 md와 CLAIMS에만 남는다.
5. **숫자는 여전히 손으로 옮기지 않는다.** 새 결과(E-G6 실 sim 행, E-G3 재실행, E-G8)도 results md → `numbers.yaml`/`md_to_tex.py` 경로로만 본문에 들어간다.
6. **결과 md의 배너는 표 하나에 하나.** E-G6에 REAL SIM 행이 생기면 MOCK 표와 **다른 표**로 쓴다. 한 표에 두 출처를 섞지 않는다.
7. **브랜치·PR.** 하위 항목 단위 한 PR(`paper/r<N>-<n>-<이름>`, `exp/r<N>-<n>-<이름>`). 서브모듈 포인터가 바뀌는 PR(R4.2)은 단독으로 내고 402 테스트 + heteropilot golden 테스트 전체를 돌린다.

---

## 1. STEP 요약

| STEP | 주 | 이름 | 산출물 | 담당 |
|---|---|---|---|---|
| R1 | 1 | 표 파이프라인·PDF 게이트·배치 | `scripts/paper/tables.yaml`, `make check-pdf`, 잘린 열 복구, Table VI 이동 | 🤖 |
| R2 | 1–2 | 참고문헌과 HeteroPilot 명명 | `paper/refs.bib`(≥30), 본문 `\cite`, 3인칭 명명, 익명성 패턴 | 🤖 + 👤(검토) |
| R3 | 2 | 그림과 문체 | 노드 토폴로지 그림, 초록 150단어, §VIII 질문–답 서두, 누락 문장 3개 | 🤖 |
| R4 | 2–4 | E-G6 실 sim 1조건 · A5000 프로파일 → E-G3 complete | `e_g6_scale.md` REAL SIM 표, heteropilot 프로파일 PR + bump, `e_g3_real_sim_oracle.md` 재실행 절 | 🤖 + 👤(프로파일러) |
| R5 | 3–6 | **E-G8** 이종 노드 간 P/D 실측 (A40 ↔ A5000) + P/D 반복 추가 | 사전 등록 row 10, `real-s8a5k.v2.yaml`, `experiments/e_g8/`, `e_g8_hetero_pd.md`, 논문 §VIII.H | 🤖 + 👤(실측) |
| R6 | 2–6 | HeteroPilot arXiv 프리프린트 | heteropilot 리포 `paper/`(6–8쪽), arXiv 번호 → `refs.bib` | 👤(서술) + 🤖(뼈대·사실 목록) |
| R7 | 7–8 | 2차 내부 리뷰·재현 패키지·태그 | `REVIEW_internal.md` 2차, `REPRODUCE.md`, 익명 스냅샷, 태그 `ispass27-submission-v2` | 🤖 + 👤 |
| R8 | 9–10 | 투고 | 초록 등록, PDF, 익명성 체크리스트 | 👤 |

병행: R1→R2→R3는 순차(같은 파일을 건드림). R4·R5·R6은 R1 다음부터 병행. R5의 장비 준비(사용자)는 다음 주 A5000 도착 즉시 시작.

---

## 2. STEP

### STEP R1 — 표 파이프라인, PDF 게이트, 배치 (1주)

**현상.** `md_to_tex.py`가 results md의 모든 열을 단일 컬럼 `table`에 `\small`로 넣어 Table I·II·IV·V가 287–660 pt 넘친다. Table I에서 `false_infeasible`·`mismerged_pairs`·`complete`·`unjudged`, Table V에서 `vs T1`·`range`·`measured`가 PDF에 없다. Table II는 오른쪽 컬럼의 Fig. 2·Table IV 위로 넘친다. 9쪽은 Table VI 하나로 2/3이 비어 있다.

**R1.1 열 선택과 이름 매핑.** `scripts/paper/tables.yaml`을 만든다: 표 라벨별 `columns:` 화이트리스트(순서 포함), `labels:`(`compression_ratio`→`ratio`, `false_infeasible`→`false inf.`, `mismerged_pairs`→`mis-merged`, `t_vf2_s`→`VF2 (s)` 등), `width: column|page`(page면 `table*`), `size: small|footnotesize|scriptsize`. `md_to_tex.py`가 이 파일을 읽고, 매핑에 없는 표는 **모든 열 + `column`** 이라는 지금 동작을 유지하되 열이 7개를 넘으면 경고를 낸다. 표별 지정:
- Table I (E-G3): `fixture, embeddings, representatives, ratio, false inf., mis-merged, complete, unjudged, saving (s)` — `table*`.
- Table II (E-G6): `devices, symmetry, embeddings, representatives, ratio, t_vf2, t_total` — `column`, `footnotesize`. 나머지 timing 열은 아카이브 표.
- Table IV (E-G7 holdout): `fixture, embeddings, representatives, ratio, false inf., mis-merged, recall@16 (ours / surrogate)`.
- Table V (E-G5): `placement, devices, p99 TTFT pred, predicted, p99 TTFT median, range, vs T1, measured` — `table*`. TPOT·goodput은 본문 한 문장("둘 다 두 배치에서 목표 이내")과 매크로로.
- Table III (criterion-2)는 그대로.

**R1.2 배너 각주 통합.** MOCK 세 문장이 Table II·III·IV에 세 번 반복된다. 캡션에는 `[MOCK]` 태그만 남기고, §VIII.A 끝에 "Provenance tags" 한 문단으로 세 태그의 뜻을 한 번만 적는다. `md_to_tex.py`의 "배너 없는 표 거부"는 유지(태그는 반드시 캡션에).

**R1.3 `make check-pdf`.** `scripts/paper/check_pdf.py`: `main.log`에서 `Overfull \hbox`가 **20 pt 초과**면 실패(위치 출력), `undefined references`/`Citation ... undefined` 있으면 실패, `pdfinfo` 쪽수를 세어 참고문헌 시작 쪽(`\bibliography` 앵커를 `\label{sec:refs}`로 잡아 `.aux`에서 읽음) 이전이 **9쪽 초과**면 실패, 0.4절의 익명성 패턴을 `pdftotext` 출력에서 검색해 있으면 실패. `make check`가 `check-pdf`를 포함하도록 Makefile 수정(단 `make check`만 치면 PDF가 없을 때 "run make pdf first"로 실패).

**R1.4 배치.** Table VI를 `[t]`에서 §II 또는 §X 가까이로(`table*`+`[!t]` 또는 `[h]`), 9쪽 공백 제거. 공백이 생긴 만큼 ISPASS 컷(`REVIEW_internal.md` "Length cut" 절)에서 아카이브로 보낸 표 7개 중 **E-G5 일치표(agree/disagree 3×3)와 E-G7 ablation 전체 표**를 우선 복구한다. 9쪽 한도는 `check-pdf`가 지킨다.

**R1.5 REPRODUCE.** fresh clone에서 `make paper`는 `outputs/e_g6/scale.json`(아카이브 입력)이 없어 실패하고 `make pdf`는 된다는 사실을 "Building the paper" 절에 적는다.

**완료 조건.** `make pdf && make check-pdf` 통과, Overfull 0건, 쪽수 ≤ 9(참고문헌 전), 네 표의 지정 열이 `pdftotext`에서 모두 보임(테스트 `tests/test_paper_tables.py`: tables.yaml의 모든 열 이름이 생성된 `.tex`에 있는지, 그리고 `scripts/paper/check_pdf.py`가 가짜 로그로 실패/통과하는지).

---

### STEP R2 — 참고문헌과 HeteroPilot 명명 (1–2주)

**현상.** `\cite` 0건, `.bib` 없음. Related Work가 7개 시스템을 이름만 부른다. HeteroPilot은 "the planner this work extends"로 숨겨져 있으면서 Table VI에 모듈 경로와 D-번호가 노출된다.

**R2.1 `paper/refs.bib`.** 최소 30편. 반드시 들어갈 것: Helix, ThunderServe, ShuntServe, DistServe, Splitwise, Mooncake, Vidur, LLMServingSim(2.0), Frontier, ASTRA-sim, Chakra, vLLM, NIXL/Dynamo(사용한 전송 경로), Sarathi-Serve(chunked prefill — spec의 knob), Llumnix, Mélange·HexGen(이종 GPU 비용 최적화 — 가장 가까운 경쟁), Alpa·Galvatron(병렬화 탐색), Weisfeiler–Leman(Shervashidze 2011)·VF2(Cordella 2004)·networkx(Hagberg 2008), processor sharing(Kleinrock 1967 또는 Massoulié–Roberts 1999), 사전 등록 관행(Nosek et al. 2018 — §VIII.A의 근거), 그리고 **`heteropilot`**(R6의 arXiv 프리프린트; 번호 확정 전까지 `note = {arXiv preprint, number pending}`, `make check`가 "pending"을 세어 보고). 각 항목은 DOI 또는 arXiv id를 가진다(WebSearch로 확인, 추측 금지). 2026 하반기 신규 문헌은 P6 보고의 후보 목록에서 사용자가 승인한 것만.

**R2.2 본문 `\cite`.** 위치: §I(문제 설정에 Helix·DistServe·vLLM), §II(HeteroPilot, LLMServingSim, ASTRA-sim), §IV(측정 키 — 해당 없음), §V(WL, VF2, networkx), §VI(없음), §VII(processor sharing), §VIII.A(사전 등록), §IX(전부), §X(NIXL). `\bibliography{refs}` 복원, `check-pdf`가 undefined citation을 잡는다.

**R2.3 HeteroPilot 명명.** 규칙 0.3. §II 첫 문장에서 한 번 정의("HeteroPilot~\cite{heteropilot} describes a cluster as execution islands…"), 이후 "HeteroPilot". Table VI: 열 머리 "Reused unmodified (HeteroPilot)", 가운데 열은 **훅 이름만**(`H1 compile hook`, `H2 cost objective`…), D-번호 삭제. `README`/`MAP.md`는 그대로(저장소 문서는 익명성 대상이 아님).

**R2.4 익명성 패턴.** 규칙 0.4의 패턴을 `check.py`(소스)와 `check_pdf.py`(PDF 텍스트) 양쪽에 넣는다.

**완료 조건.** `check-pdf` 통과(undefined citation 0), §IX의 모든 시스템명 뒤에 `\cite`, "the existing planner"/"the planner this work extends" 출현 ≤ 1, 익명성 패턴 0건. 보고에 참고문헌 목록(키·제목·연도·DOI)과 "사용자 확인 필요" 표시.

---

### STEP R3 — 그림과 문체 (2주차)

**R3.1 토폴로지 그림.** `scripts/paper/figures/topology.py`: `fixtures/clusters/real-a40x8.v2.yaml`을 읽어 8-GPU 노드(NVLink 쌍, PCIe 스위치, CPU 소켓, NIC)를 그리고 T1(0,1)·T2(0,2)·T3(0–3)을 색으로 표시, 측정 수치(52.64 / 25.12 / 8.71 GB/s)는 fixture의 `measurements`에서 읽어 라벨로. 데이터에서 생성하므로 숫자 리터럴 규칙을 지킨다. §I 두 번째 문단 옆(`figure`, 컬럼 폭). Fig. 1(설계 개념도)은 §V로 내리거나 아카이브로.

**R3.2 초록.** 150단어 이내. 구조: 문제(2문장) → 방법(2) → 결과 세 수치(8.3×, false_infeasible 0, 절감) → 지는 결과 한 문장(P/D 경합 과대 예측). 매크로 사용.

**R3.3 §VIII 서두 통일.** 각 소절(B–G, R5 후 H) 첫 문장을 **"질문 — 한 줄 답"** 으로: 예 "Does the search eliminate anything feasible? No: on all three fixtures `false_infeasible` is \egthreeFalseInf{} among the placements the simulator judged." 이어서 지금 본문. "That …"으로 시작하는 문장을 절반 이하로; 한 문장에 세미콜론·em-dash 전환 2개 이상이면 쪼갠다.

**R3.4 누락 문장 3개.** (a) §VIII.G에 바닥 민감도 한 문장(GS-38: 1.4–1.6에서 normal-low T1/T2 seed 42·44만 달라짐; 매크로). (b) §X에 GS-35(burst 패턴이 시뮬레이터에 역수로 전달됐고 등록 전 수정) 한 줄. (c) §X에 "hardware heterogeneous in interconnect, not in accelerator" 한 문장 — **R5가 끝나면 이 문장을 E-G8 결과로 교체**한다(지금은 자리 확보).

**R3.5 사후(post hoc) 설명 중복.** GS-38 재예측이 §VIII.G 한 문단과 §X.c에 두 번 설명된다. §VIII.G는 수치, §X는 한 줄 참조로.

**완료 조건.** `check-pdf` 통과, 초록 ≤ 150단어(`check.py`에 카운트 추가), 리뷰어 A 패스(모든 수정 문장이 CLAIMS 상태를 넘지 않는지) `REVIEW_internal.md`에 R3 절로 기록.

---

### STEP R4 — E-G6 실 sim 1조건, A5000 프로파일, E-G3 complete (2–4주)

**R4.1 E-G6 실 sim.** 32장치·symmetry 1.0·seed 42, `--predictor sim`, 전용 캐시 `outputs/cache-eg6-real/`, `max_workers`는 노드 코어 수(하드웨어 측정과 동시 실행 금지). 측정: 압축 전·후 시뮬레이션 수, 오라클 wall time(전수) 대 탐색 wall time(압축+검사 포함), saving. **등록된 실패 조건**(saving < 0 on fully symmetric)을 이 행이 처음으로 실 평가자로 판정한다 — 사전 등록 append(기준 변경 없음, "E-G6 실 sim 1조건을 추가 실행함, 실패 조건 그대로"). 결과는 `e_g6_scale.md`에 **별도 표**(REAL SIM 배너) + 논문 §VIII.C에 한 문단과 Table II 아래 1행 표(`table`, REAL SIM). saving이 음수면 규칙 P0.6대로 그대로 쓰고 §X.a의 "demote to cache key" 문장을 결과로 연결한다.

**R4.2 A5000 프로파일(👤 → 🤖).** A5000 노드에서 `vendor/heteropilot/profiler/profile.sh`를 `TP_DEGREES`에 1·2(·4, 4장이면)를 넣어 Llama-3.1-8B bf16 실행 → `profiles/perf/A5000/...` 생성. 이것은 heteropilot 데이터이므로 **heteropilot PR**(D129 또는 다음 블록, "A5000 tp=2/4 프로파일 추가") → 머지 → graphsearch 서브모듈 bump PR(단독, 402 테스트 + heteropilot golden 전체). Claude Code는 실행 명령·점검표(`docs/nodes/a5000.md` 기록 항목: UUID, 드라이버, 바인딩, 부하)를 준비하고 결과를 검증(프로파일 파일 수·크기·tp 키).

**R4.3 E-G3 재실행.** bump 후 toy 두 fixture(`graph-toy-abcde`, `graph-toy-shared-nic`)를 같은 설정으로 재실행. 기대: `FileNotFoundError` 42건 소멸, `complete=True`. `heterogeneous-lab`의 KV 고갈 24건은 그대로(별개 원인). 결과는 `e_g3_real_sim_oracle.md`에 **새 절**("Re-run after A5000 tp=2 profile, 2026-10-xx")로 append — 원래 표를 덮어쓰지 않는다. 정확성 두 수가 0이 아니면 멈추고 보고. CLAIMS: "Established, for the placements the simulator judged" 행을 complete 결과에 맞춰 갱신, 논문 §VIII.B의 한정 문장을 줄인다.

**완료 조건.** R4.1 표 + 논문 반영, R4.2 bump PR 머지, R4.3 두 fixture `complete=True`·정확성 2수 0, `check-pdf` 통과.

---

### STEP R5 — E-G8: 이종 노드 간 P/D 실측 (A40 ↔ A5000) + P/D 반복 추가 (3–6주)

**질문.** (1) 가속기가 다른 두 노드에 걸친 P/D 배치에 대해 탐색의 판정(수정된 어댑터, GS-38)이 실장비와 일치하는가. (2) 시뮬레이터가 `heterogeneous-lab`에서 보고한 "큰 장치 prefill → 작은 장치 decode의 KV 고갈"이 실장비에서도 나는가, 아니면 시뮬레이터의 메모리 모델 문제인가. (3) C30(NIC 경합이 모형보다 훨씬 작음)이 두 번째 링크에서도 재현되는가. 이 실험이 제목의 "heterogeneous"를 실장비로 뒷받침한다.

**실험 id.** **E-G8**. heteropilot `CLAUDE.md`의 E-G* 선점 목록에 docs-only PR로 추가(E-G3~E-G7과 같은 방식).

**R5.0 경로 탐침(👤, A5000 도착 직후 1일).** (a) A5000 노드 ↔ `s8`(A40) 사이 NIC 종류 확인: InfiniBand면 `pd_probe/nixl_bw.py` 그대로, Ethernet이면 NIXL UCX/TCP 백엔드로 `nixl_bw.py` 실행 — 둘 다 raw 커밋. (b) `docs/nodes/PREP.md` D항 `xnode-a40-a5000` 링크 측정(≥10회). (c) A5000에서 vLLM 0.19.0 + nixl 0.9.0으로 decode 인스턴스 단독 기동 확인(24 GB → `--max-model-len 8192`, KV 블록 수 기록). 탐침 결과로 **경로 결정**: NIXL이 되면 R5.2로, 안 되면 대안 D(아래)로.

**R5.1 fixture와 사전 등록 row 10(🤖, 첫 요청 전).** `build_cluster_s8a5k.py`로 `real-s8a5k.v2.yaml`을 R5.0 raw에서 생성(`source: measured`; A5000 가격·전력은 `price_source` 명시, 없으면 placeholder). **row 10 등록 내용**: 조건 — D1: prefill A40(s8) → decode A5000, D2: prefill A5000 → decode A40, 각각 `independent`/`shared`(0.6 duty, E-G4(b) 생성기); 템플릿은 row 7 규칙(seed 42, 조건별 1회 고정); 부하는 row 7(b)의 knee 파일럿 규칙(drain 보정 goodput ≥ 0.9); 3 반복 ABAB; 지표 — 1차: 탐색 판정(met/MISSED, TTFT·TPOT·goodput) 대 실측 일치 여부(D1·D2 × independent); 2차: row 7(c) KV 구간 쌍 평균 차(shared − independent)와 fluid 예측의 부호·0.5–2× 일치; 3차: D2에서 decode KV 고갈(엔진 preemption/abort 수) 보고. **기준**: 1차는 판정 일치 수 보고 + "false met은 miss로 센다"(E-G5와 동일), 2차는 row 7과 같은 부호+배율 기준, 3차는 report-only. **명시할 것**: 이 실험은 **수정된 어댑터(GS-38)로 예측한 첫 등록 실험**이다; 파일럿·탐침 raw는 fitted set으로 제외; 가속기 간 TP(mixed-vendor TP)는 범위 밖(§X.f 그대로). 예측값(`raw/e_g8/prediction-*.json`)을 row 10과 같은 커밋에 넣는다.

**R5.2 하네스(🤖).** `experiments/e_g8/`: `pd_arm.py`·`pd_router.py`를 이종 쌍으로 일반화(노드별 vLLM 인자, A5000의 `--gpu-memory-utilization`·`--max-model-len`, 직렬 번호·UUID 기록), E-G4(b) 배경 생성기 호출, raw 스키마는 E-G5 P/D arm과 동일 + `decode_preemptions`, `kv_blocks_total/used_peak`. dry-run(mock 엔진)으로 raw 파서·분석까지 통과시킨 뒤 사용자에게 넘긴다. 분석 `analyze.py` → `experiments/results/e_g8_hetero_pd.md`(REAL HARDWARE 배너, 표: 판정 일치 / 쌍 차 대 예측 / KV 고갈).

**R5.3 실행(👤).** 파일럿(템플릿 고정, knee) → row 10 커밋 → D1·D2 × independent/shared × 3 반복 = 12 run. 매일 raw 커밋. 하드웨어 측정 중 R4.1 시뮬레이션 금지.

**R5.4 P/D 반복 추가(👤 + 🤖, 같은 주).** `s8–s6` 기존 arm(row 7 프로토콜 그대로, 1 rps, 150 요청)을 **6쌍 추가**(seeds 45–50, ABAB). 등록 외 확장이므로 row 10에 "(d) extension: 6 additional pairs under row 7's protocol, reported in a separate table, not part of row 7's verdict"로 함께 등록. 분석: 9쌍의 평균 차와 95 % CI → "효과 크기 상한 X ms"로 보고. row 7의 판정(기준 미충족)은 그대로.

**R5.5 논문 반영(🤖).** §VIII.H "Heterogeneous inter-node disaggregation" 1쪽 이내: 질문–답 서두, 표 1개(`table*`), KV 고갈 결과 한 문단(시뮬레이터 결과와 대조), C30 두 번째 링크 결과 한 문단. CLAIMS 신규 행(E-G8 ×3, P/D 확장 ×1). §I·초록·§XI에 "accelerator-heterogeneous on hardware" 한 문장(결과가 뒷받침할 때만). R3.4(c) 문장 교체. §X.d 갱신.

**대안 D(R5.0에서 NIXL 경로가 안 될 때).** A5000 노드를 **집계 배치 T4**(A5000 tp=2 또는 tp=4, spec S)로 E-G5 매트릭스에 추가하고 같은 프로토콜(3 반복, 판정 일치)로 측정한다. P/D 없이도 "다른 가속기 위의 배치에 대한 판정"이 실측되므로 제목의 heterogeneous는 뒷받침되나 질문 (2)·(3)은 비게 된다. 이 경우 row 10을 그 내용으로 등록하고 §X에 "inter-node P/D measured on homogeneous pair only"를 남긴다.

**완료 조건.** row 10이 첫 요청 전 커밋되었음이 git 이력으로 확인됨, 12 run raw + 6쌍 raw 커밋, `e_g8_hetero_pd.md`, CLAIMS 갱신, §VIII.H, `check-pdf` 통과. 정확성 두 수는 이 실험에 해당 없음(판정 일치 수와 false met 수를 보고).

---

### STEP R6 — HeteroPilot arXiv 프리프린트 (2–6주, 👤 서술)

**목적.** 규칙 0.3의 인용 대상. 6–8쪽 IEEEtran, 성능 평가 없음(설계 서술). heteropilot 리포의 `paper/`에 두고 PR로 관리(graphsearch가 아니라 **heteropilot의 산출물**).

**🤖가 하는 것.** (a) 뼈대: 서론(문제: 이종 클러스터 서빙 계획), 설계(인벤토리·실행 섬·후보 생성 stage 1–5·predictor 인터페이스·S3/D112 측정 선택·배포 백엔드), 공학 원칙(deviation 기록·golden 테스트·`source: placeholder`), 현재 한계(섬 단위 후보가 배치를 구분 못 함 — graphsearch 논문을 "확장"으로 한 문장 예고), 결론. (b) **사실 목록**: `vendor/heteropilot/docs/deviations.md`와 `CLAUDE.md`에서 설계 결정을 번호·날짜·한 줄로 뽑은 표 — 사용자가 서술할 때 쓰는 원료. (c) 모듈 인벤토리 표(Table VI의 왼쪽 열을 heteropilot 쪽에서 본 것). (d) 참고문헌 초안(R2.1과 공유).

**👤가 하는 것.** 설계 의도와 결정 이력의 서술, 저자·소속, arXiv 제출(6주차 목표). 번호가 나오면 `refs.bib`의 `heteropilot` 항목을 채우고 `make check`의 pending 0.

**주의.** 이 프리프린트는 HeteroPilot 본 논문의 신규성을 소진하지 않도록 **평가 결과를 넣지 않는다**. graphsearch 논문의 §II가 서술하는 범위를 넘는 세부(예: 후보 생성 stage별 알고리즘)는 프리프린트에 있어도 되지만, graphsearch 논문은 그것을 인용만 한다.

---

### STEP R7 — 2차 내부 리뷰, 재현 패키지, 태그 (7–8주)

**R7.1 리뷰어 A·B 재실행**(P7.1과 같은 방식) + **리뷰어 C(조판·인용)**: 모든 표의 지정 열이 PDF에 보이는가(`pdftotext` 대조), 모든 그림 캡션에 출처 태그, `\cite` 없는 시스템명 0, 익명성 패턴 0, 9쪽. `REVIEW_internal.md`에 "Second review (R7)" 절.

**R7.2 REPRODUCE.** 아카이브 호스팅(사용자 결정: Zenodo 제한 공개 권장) 반영; **심사용 익명 스냅샷**: `git clone --recurse-submodules` 후 `.git` 제거, `swsok`·이름 패턴 grep 0건 확인, tarball에 gitignored 입력(E-G3 cold-run·캐시, E-G6 grid·`scale.json`, E-G5/E-G8 outputs) 포함, SHA256 기록. REPRODUCE.md에 E-G6 실 sim·E-G3 재실행·E-G8 명령 추가.

**R7.3 태그.** 머지 완료된 main에 `ispass27-submission-v2`(기존 태그는 두되 REPRODUCE가 가리키는 이름을 v2로). heteropilot 쪽 bump된 sha에도 같은 이름 태그(👤).

---

### STEP R8 — 투고 (9–10주, 👤)

ISPASS 2027 CFP 게시 확인(쪽수·마감·템플릿 변경 여부 — 변경 시 R1.3의 쪽수 상수만 수정), 초록 등록, PDF 업로드, 익명성 체크리스트(저자 메타데이터 제거 `pdfinfo`, arXiv 프리프린트는 3인칭 인용 유지).

---

## 3. 사용자가 직접 하는 일 (시간순)

| 주 | 일 |
|---|---|
| 1 | R2.1 참고문헌 후보 승인(특히 2026 신규), HeteroPilot 프리프린트 저자·범위 결정 |
| 다음 주(A5000 도착) | R5.0 경로 탐침(NIC 종류, NIXL 전송, vLLM 기동), PREP.md D항 `xnode-a40-a5000`; R4.2 프로파일러 실행 → heteropilot PR 머지 |
| 3–6 | R5.3 E-G8 12 run + R5.4 6쌍 실행, 매일 raw 커밋; R6 프리프린트 서술·arXiv 제출 |
| 7–8 | R7.2 아카이브 호스팅 결정·업로드, R7.3 heteropilot 태그 |
| 9–10 | R8 투고 |

## 4. 완료 보고 형식 (모든 STEP 공통, P0~P7 §3에 추가)

`make pdf && make check-pdf` 출력(쪽수, Overfull 0, undefined 0, 익명성 0), 바뀐 CLAIMS 행, 사전 등록 append 번호, 그리고 **"쓰다가/돌리다가 드러난 것"** 목록(예: tables.yaml로 뺀 열 중 본문이 참조하는 것, E-G8 하네스에서 A5000 메모리 때문에 바꾼 인자). R5는 추가로 row 10 커밋 sha와 첫 raw 파일의 타임스탬프를 나란히 적는다.
