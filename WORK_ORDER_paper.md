# 작업지시서 — 연구 실행과 논문 작성 (heteropilot-graphsearch, STEP P0~P7)

> 연구설계서 `docs/HeteroPilot_그래프기반_배치탐색_연구설계.md`를 실행하고 논문으로 완성하는 지시서. 코드 구현 지시서(`WORK_ORDER_graph_search.md`, G0~G15)의 다음 단계다. 일정 문서 `graphsearch_연구실행일정.docx`와 같은 STEP 번호를 쓴다.
> 저장소: `swsok/heteropilot-graphsearch`(구현·실험·논문 전부) · 의존: `vendor/heteropilot`(읽기 전용, 필요한 훅은 `feat/gs-h<N>` PR로) · 작성일: 2026-09-23
> 인력: 사용자 1인 + Claude Code. **실측은 사용자가 직접 한다.** Claude Code는 스크립트·분석·문서를 맡고, 실측 STEP에서는 "사용자에게 넘길 준비물"을 만들고 멈춘다.
> 실험 id: **E-G3~E-G7**을 이 지시서에서 배정한다(E-G1, E-G1b, E-G2는 사용됨). heteropilot `CLAUDE.md`의 `E-G*` 선점에 포함된다.

---

## 0. 규칙

1. **순서** P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7. 병행: P1‖P2(2.1·2.3), P3‖P4, P5‖P6. 각 STEP은 하위 항목(예: P1.2) 단위로 한 브랜치·한 PR(`exp/p<N>-<n>-<이름>` 또는 `paper/<이름>`).
2. **게이트** 기존과 같다: `pytest -q && ruff check . && mypy graphsearch/`, 서브모듈 무수정, CI 녹색. 실험 스크립트도 `ruff`를 통과해야 하고, 결과 md는 재현 명령을 머리에 갖는다.
3. **숫자의 출처를 항상 표시한다.** 모든 결과 md 첫 줄에 배너 셋 중 하나: `MOCK — 성능 수치 아님` / `REAL SIM — LLMServingSim, 캐시 <dir>, 실장비 아님` / `REAL HARDWARE — 노드 시리얼 <…>`. 논문 표는 이 배너를 각주로 옮긴다.
4. **사전 등록.** `docs/preregistration.md`는 append-only. 실험 전에 가설·지표·성공 기준·실패 해석을 적고, 결과 뒤에 기준을 고치지 않는다. 고쳐야 하면 새 항목으로 추가하고 이전 항목을 남긴다.
5. **정확성 두 수(`false_infeasible`, `mismerged_pairs`)가 0이 아니면 멈추고 보고한다.** 테스트를 완화하거나 라벨을 느슨하게 해 통과시키지 않는다.
6. **결과가 가설과 다르면 그대로 쓴다.** 연구설계서 §12 "주요 실패 조건"에 해당하는 결과는 실패로 기록하고 그 조건이 말하는 대로 논문 초점을 옮기는 제안을 함께 적는다.
7. **실측 STEP의 분업.** Claude Code: 스크립트, 실행 대장 템플릿, 원자료 파서, 분석, 표. 사용자: 노드 확인(`whichnode.sh`), 배포 실행, 원자료 커밋. Claude Code는 원자료가 커밋된 뒤 분석을 시작한다. 원자료 없이 숫자를 채우지 않는다.
8. **기록.** graphsearch 결정은 `docs/decisions.md` GS-n(현재 GS-12까지), heteropilot 변경은 D127~D129(남은 블록) — 부족하면 새 블록을 heteropilot `CLAUDE.md`에 선점.

---

## 1. STEP 요약

| STEP | 하위 | 이름 | 산출물 | 담당 |
|---|---|---|---|---|
| P0 | 0.1–0.5 | 마무리·사전 등록·저장소 뼈대 | H5, `docs/preregistration.md`, `paper/` | 🤖 + 👤 |
| P1 | 1.1–1.4 | E-G3 실 sim 정확성 재검증 | `experiments/results/e_g3_real_sim_oracle.md`, wall time 분해 | 🤖 (실행은 A40 노드에서 👤) |
| P2 | 2.1–2.5 | E-G4 경합 모형·microbenchmark | `graphsearch/contention.py::FluidContentionModel`, `experiments/results/e_g4_microbench.md` | 🤖 + 👤(실측) |
| P3 | 3.1–3.4 | E-G5 실장비 검증 | `experiments/e_g5/MATRIX.md`, 배포 하네스, `experiments/results/e_g5_real_hardware.md` | 🤖 + 👤(실측) |
| P4 | 4.1–4.3 | E-G6 확장성 | `graphsearch/synth/cluster_gen.py`, `experiments/results/e_g6_scale.md` | 🤖 |
| P5 | 5.1–5.3 | E-G7 holdout·ablation·baseline 공정성 | `e_g7_holdout.md`, `e_g7_ablation.md` | 🤖 |
| P6 | 6.1–6.4 | 논문 초고 | `paper/`, `paper/CLAIMS.md`, `make paper` | 🤖 + 👤 |
| P7 | 7.1–7.3 | 리뷰·재현 패키지·투고 | `REPRODUCE.md`, 투고본 | 🤖 + 👤 |

---

## 2. STEP

### STEP P0 — 마무리와 사전 등록

**P0.1 G15 확인.** G15 완료 보고를 검토해 GS-12, holdout 표, `service_margin_v1` 보존을 확인한다. k=4에서 여전히 추천이 없으면 `docs/preregistration.md` "알려진 한계"에 한 줄. 랭커를 더 고치지 않는다.

**P0.2 H5 정리.** 이전 지시(heteropilot `chore/remove-graft-config`)가 아직이면 수행: `.mcp.json`·`.ignore` 삭제, `.gitignore` graft 3줄 제거, `git grep graft` 빈 출력, 머지 후 서브모듈 bump. graphsearch `CLAUDE.md`·`.gitignore`에 도구 설정 파일 커밋 금지 규칙.

**P0.3 실측 노드 준비(👤, 🤖는 체크리스트만).** `docs/nodes/PREP.md`를 만든다: 노드별(A40·A5000·RNGD) 체크리스트 — `bash scripts/whichnode.sh` 출력과 가속기 시리얼 기록 · `vendor/heteropilot/.venv` 생성과 `scripts/compile.sh` · `python -m planner plan --num-requests 30` 실 sim 완주 · 노드 간 링크 1회 측정(`experiments/p2_evidence/link_probe.py`, `source: measured`, `LinkMeasurement` 형식) · 결과를 `fixtures/clusters/real-<lab>.v2.yaml` 초안에 기록. 사용자가 채운 값이 들어오면 YAML을 검증(`load_cluster_spec`)한다.

**P0.4 사전 등록 초안.** `docs/preregistration.md`를 아래 골격으로 쓴다. 수치 목표는 `[사용자 확정]`으로 비워 두고 사용자가 채운다.
```
# Pre-registration
## 공통 — 정확성 불변식: 모든 실험에서 false_infeasible = 0, mismerged_pairs = 0
## E-G3 실 sim 오라클: 가설 / 지표(정확성 2수, 압축률, saving) / 성공 기준 / 실패 해석(§12 실패 조건 매핑)
## E-G4 경합 microbench: 조건 5개 / 지표(전송 시간 예측 오차 p50·p90, Null 대 Fluid) / 성공 기준 [사용자 확정: 예 p50≤15 %, p90≤30 %] / 실패 해석
## E-G5 실장비: 매트릭스 / 지표(p99 예측 대 실측, SLO 충족, 경계 대안 위반) / 성공 기준 / 순환 평가 금지 규칙
## E-G6 확장성: 규모·대칭도 격자 / 지표(wall time, VF2 s, 압축률, EXCLUDED_BY_SCOPE) / 실패 조건(saving<0)
## E-G7 holdout·ablation: holdout 목록(지금 확정) / arm 목록 / 지표
## 변경 이력(append-only)
```

**P0.5 논문 저장소 뼈대.** `paper/main.tex`(acmart sigconf 임시), `paper/sections/{intro,background,problem,graph,candidates,search,adapter,eval,related,limits,conclusion}.tex`(각 파일 첫 줄에 연구설계서 대응 § 주석), `paper/tables/`(생성물, gitignore), `paper/figures/`, `paper/CLAIMS.md`(형식: `| 주장 | 근거 파일 | 출처 종류 mock/real-sim/hardware | 상태 |`), `paper/Makefile`(`make paper`, `make tables`, `make figures`), `scripts/paper/md_to_tex.py`(results md 표 → tex). `make paper`가 빈 PDF를 만들면 완료.

**완료 조건** 게이트 통과 · preregistration.md 커밋(수치는 비어 있어도 됨) · `make paper` 성공 · 서브모듈 == H5 sha.

---

### STEP P1 — E-G3: 실제 시뮬레이터로 정확성 재검증

**P1.1 실 predictor 경로 점검(🤖 스크립트, 👤 실행).** `experiments/scripts/e_g3_smoke.sh`: A40 노드에서 `PYTHONPATH` 설정 → `python -m graphsearch plan --predictor sim --service fixtures/service_specs/graph-toy-llama31-8b.yaml --cluster fixtures/clusters/graph-toy-abcde.v2.yaml --num-requests 50 --cache-dir outputs/cache-eg3 --output outputs/eg3-smoke.yaml`. 확인 항목을 스크립트가 출력: compile hook·result hook 호출 로그, `provenance.graph_search`, `provenance.graph_search.topology_loss`. 실 sim 경로에 없는 로그가 있으면 추가한다(기본 경로 불변).

**P1.2 실 sim 완전탐색 oracle.** `experiments/scripts/e_g3_real_sim_oracle.py`: fixture {abcde.v2, shared-nic.v2(3노드), heteropilot heterogeneous-lab} × {oracle(전 임베딩), proposed(exact 압축 + bounds + adaptive, K=전체)} 를 `--predictor sim`, `--cache-dir outputs/cache-eg3`, `--max-workers`로 실행. `livelock_watch.sh`로 감싸는 래퍼 포함. 출력 `experiments/results/e_g3_real_sim_oracle.md`(배너 REAL SIM): 열 = fixture, embeddings, representatives, ratio, sims_oracle, sims_proposed, feasible_recall, cost_regret, false_infeasible, mismerged_pairs, correct. **mismerged가 0이 아닐 때**: 해당 쌍을 같은 노드 순서로 재시뮬레이션해 시뮬레이터 비결정성(인스턴스 번호·`config_builder` 순서)인지 동등성 결함인지 판별하는 `--diagnose-pair a b` 옵션을 넣고, 판별 결과를 md에 적는다.

**P1.3 wall time 분해.** `SearchAudit`에 `timings: dict[str, float]`(enumerate, hash, vf2, bounds, rank, sim) 추가(필드 추가만, 기존 provenance 키 유지). `e_g3_real_sim_oracle.py`가 `saving = t_sim_oracle − (t_sim_proposed + t_hash + t_vf2 + t_bounds)` 열을 추가. 음수면 그대로 보고하고 preregistration의 실패 해석을 인용.

**P1.4 캐시 검증.** 같은 명령 재실행 → `cache_hits == simulations_run`; 캐시 파일 수 == 평가된 대표 수(경계만 다른 대표가 다른 파일). 결과 md에 한 절.

**완료 조건** 세 fixture `correct True`(아니면 P1.2 판별 결과와 수정 PR) · wall time 표 · 캐시 절 · `paper/CLAIMS.md`에 E-G3 근거 행 추가.

---

### STEP P2 — E-G4: 공유 자원 경합 모형과 microbenchmark

**P2.1 설계.** `experiments/microbench/PLAN.md`: 조건 5개(단일 전송 / 동일 NIC 두 흐름 / 독립 NIC 두 흐름 / 양방향 / collective 참여수·크기 변화) × 위치 2개(A40 노드 내 PCIe uplink 공유, 노드 간 NIC) · 메시지 크기 격자 1 MiB–256 MiB(2배 간격) · 반복 ≥10 · 배경 부하 생성 방식(같은 uplink에 지속 전송하는 별도 프로세스, 목표 점유율 60 %) · 기록 형식 = heteropilot `LinkMeasurement`(collective, world_size, msg_size_class, binding, bus_bw_gbps, method, msg_bytes, date, raw). preregistration E-G4 절 채움(수치는 사용자).

**P2.2 실측 스크립트(🤖) → 실행(👤).** `experiments/microbench/run_pair.py`: heteropilot `experiments/p2_evidence/p2p_probe.py`를 import/확장해 두 프로세스를 동시에 띄우는 모드(`--concurrent 2 --share same|independent`), 배경 부하 모드(`--background-util 0.6`), 결과를 `experiments/microbench/raw/<date>-<node-serial>/*.json`으로. 실행 대장 템플릿 `experiments/microbench/LOG.md`. Claude Code는 여기서 멈추고 사용자 실행을 기다린다.

**P2.3 FluidContentionModel.** `graphsearch/contention.py`에 추가.
```python
class FluidContentionModel(ContentionModel):
    """Processor-sharing over shared resources: at any instant the active flows on a
    resource split (capacity - reserved) equally; a flow's rate is the min over its path.
    Event-driven (flow start/finish); not packet-level. Named in every record."""
    def transfer_times_ns(self, flows, graph, start_ns) -> Mapping[str, float]
```
규칙: `reserved`는 상시 활성 flow로 취급(용량에서 선차감). 후보 간 경합 없음(후보는 대안이며 동시에 배포되지 않음) — 경합 상대는 외부 예약과 후보 내부 동시 flow(dp>1의 여러 P/D)만. `tests/test_contention.py`: 단일 = latency + bytes/cap · 동일 자원 두 flow 동시 = 각 bytes/(cap/2)(+latency) · 독립 자원 = 단일과 동일 · reserved 6/10 → 잔여 4 · 시작 시각이 다른 두 flow의 구간별 분배 · 결정론.

**P2.4 모형 대 실측.** 원자료 커밋 후 `experiments/microbench/analyze.py` → `experiments/results/e_g4_microbench.md`(배너 REAL HARDWARE): 열 = 위치, 조건, msg_bytes, 실측 p50/p90 (ms), Null 예측, Fluid 예측, 오차 Null, 오차 Fluid, 판정(preregistration 한계). 실측 값은 `fixtures/clusters/real-<lab>.v2.yaml`의 `measurements`에도 반영(측정값이므로 `source: measured`). **모형을 고쳐야 하면** 고친 내용과 이유를 GS-n에 적고, 맞추는 데 쓴 데이터 파일 목록을 preregistration에 기록해 P3 검증에서 제외한다.

**P2.5 연결.** CLI `--contention null|fluid`(기본 null, 기본 경로 불변). result hook의 P/D 전송 시간과 `features_for`의 TTFT 항이 선택된 모형을 쓴다. 테스트: toy-shared-nic(3노드) X→Z·Y→Z 대표가 `fluid`에서 TTFT가 다르고 `null`에서 같다(mock 경로에서는 mock의 예약 차감이 이미 있으므로 이 테스트는 `--predictor sim` 컴파일 결과 dict 또는 result hook 산출로 확인). GS-n: "경합 모형은 fluid이며 패킷 수준이 아니다; 후보 간 경합은 모델하지 않는다".

**완료 조건** 테스트 통과 · `e_g4_microbench.md`(사용자 실측 후) · preregistration 판정 기록 · `paper/CLAIMS.md` E-G4 행.

---

### STEP P3 — E-G5: 실장비 검증

**P3.1 매트릭스.** `experiments/e_g5/MATRIX.md`: 모델 2(Llama-3.1-8B, + 장비가 허용하는 1개) × 부하 패턴 2(정상·burst, `burstiness` 스펙 값) × 토폴로지 조건 3(단일 노드 aggregated / 노드 간 P/D 독립 uplink / 노드 간 P/D 공유 uplink + 배경 부하 60 %) × 부하 수준 3 × 반복 3 = 108 조건, 각 조건에 추천 1 + 경계 대안 1 → 216 배포. 조건별 예상 시간과 총 장비 시간, **축소안**(부하 2개 → 144 배포)을 함께. 미지원 조합(RNGD P/D — `planner/deploy`에 furiosa 백엔드 없음) 표시. 경계 대안의 정의: 추천 다음 순위 중 `risk_proxy`가 1에 가장 가까운 feasible 판정 후보 1개 + 하한에 걸린 가장 아슬아슬한 IMPOSSIBLE 후보 1개(후자는 실측으로 하한이 실제로 안전한지 검증 — false_infeasible의 실장비 판).

**P3.2 YAML과 하네스(🤖).** `fixtures/clusters/real-<lab>.v2.yaml` 완성(P0.3·P2.4 측정값, `shared_resources`에 배경 부하를 `reserved`로, 가격은 `price_source` 명시 — 없으면 placeholder이고 비용 목적 결과는 참고용). `experiments/e_g5/deploy_and_bench.py`: 한 조건에 대해 (a) `python -m graphsearch plan --predictor sim` → 추천·경계 대안 추출, (b) heteropilot `planner/deploy/vllm_cuda.py`로 배포(노드 간 P/D는 vLLM disaggregated prefill 설정; 스크립트가 설정 파일을 생성), (c) `python -m bench run` 부하 생성, (d) per-request 로그·provenance 수집 → `experiments/e_g5/raw/<condition>/<rep>/`. 실행 대장 `experiments/e_g5/LOG.md`. 배경 부하는 `experiments/microbench/run_pair.py --background-util`. Claude Code는 하네스를 dry-run(`--dry-run`이 설정 파일만 생성)으로 검증하고 멈춘다.

**P3.3 실행(👤).** 매일 원자료 커밋. 노드 시리얼 확인.

**P3.4 분석(🤖).** `experiments/e_g5/analyze.py` → `experiments/results/e_g5_real_hardware.md`(배너 REAL HARDWARE): 조건, 추천 id, 예측 p99 TTFT/TPOT/goodput, 실측 p99(3회 중앙값·범위, heteropilot `planner/util/percentile.py` linear), SLO 충족, 경계 대안 같은 열, 하한 경계 후보의 실측(안전했는가). 보정은 **기존 accuracy domain만** 사용, 이번 데이터로 새 도메인 생성 금지(순환 평가). 별도 소절: 공유 uplink 조건에서 X형과 Y형 배치의 실측 TTFT 차이 — 연구 반례의 실장비 근거. 실패(추천이 SLO 위반)는 그대로 기록하고 원인 후보(예측 오차·경합 모형·스케줄러)를 적는다.

**완료 조건** 표 생성 · preregistration E-G5 판정 · `paper/CLAIMS.md` E-G5 행(Established/Not).

---

### STEP P4 — E-G6: 확장성

**P4.1 합성 생성기.** `graphsearch/synth/cluster_gen.py`: 인자 `--nodes --devices-per-node --device-kinds --uplink-kinds --shared-fraction --symmetry {0..1} --seed` → `schema_version: 2` YAML(전부 placeholder). `symmetry`는 같은 속성 노드의 비율. 테스트: 결정론, 로드 검증, symmetry=1이면 모든 노드 동일. 격자: {32, 64, 128} 장치 × symmetry {0, 0.5, 1} = 9개.

**P4.2 trace.** heteropilot `workloads/generators` 재사용으로 부하 3수준 trace; 합성임을 파일 머리에.

**P4.3 실행.** `experiments/scripts/e_g6_scale.py`: 9 클러스터 × mock(전체) + 32장치·symmetry 1 한 조건만 실 sim(`--predictor sim`, 캐시). `--max-embeddings-per-template N` 상한과 `EXCLUDED_BY_SCOPE` 수 보고. 출력 `experiments/results/e_g6_scale.md` + `paper/figures/scale_*.pdf`(장치 수 대 wall time·VF2 s·압축률, symmetry별 선). 실패 조건(비대칭에서 ratio≈1, saving<0) 명시.

**완료 조건** 표·그림 · 실패 조건 기록 · CLAIMS 행.

---

### STEP P5 — E-G7: holdout·ablation·baseline 공정성

**P5.1 holdout.** preregistration에 적힌 holdout 2개(합성 1개는 P4 격자에 없는 seed·symmetry, 실장비 YAML 변형 1개)에서 E-G1b 형식 표. 랭커·δ·하한 수정 금지.

**P5.2 ablation.** `experiments/scripts/e_g7_ablation.py`: arm = {full, no_boundary(`include_boundary=False`), no_compression, no_bounds(`--bounds none`), ranker=binned, ranker=service_margin_v1, no_diversity, contention=null vs fluid}. 열 = 정확성 2수, ratio, sims, recall, regret, first_feasible_at_sim. **no_boundary arm의 mismerged>0이 기여 A의 직접 근거**이므로 그 쌍의 id와 TTFT를 부록 표로.

**P5.3 baseline 공정성.** heteropilot `search(surrogate=BinnedRooflineRanker, top_k)` · `oracle()` · `greedy`를 같은 후보 공간·predictor·캐시로 실행. 템플릿 단위 판정의 관대 채점 방식을 각주로. heteropilot `docs/surrogate_topk_regret.md`의 "K=50에도 놓치는 사례"를 재현해 포함.

**완료 조건** `e_g7_holdout.md`, `e_g7_ablation.md`, 공정성 절 초안 · CLAIMS 행.

---

### STEP P6 — 논문 초고

**P6.1 클레임 감사.** `paper/CLAIMS.md` 완성. 금지 목록: "처음으로 클러스터를 그래프로 표현", "Top-K로 전역 최적 보장", mock 수치를 성능으로 인용. 철회된 결론(GS-9 등)은 본문에서 "초기 가설은 …였으나"로.

**P6.2 초고.** 절 ↔ 연구설계서 § ↔ 결과 파일 매핑표를 `paper/MAP.md`에 먼저 쓰고 절별로 초고. 코드 재사용 대 신규 기여 경계 표(heteropilot 모듈 / graphsearch 모듈 / 훅 H1~H5) 필수. 분량 12–14쪽 2단.

**P6.3 파이프라인.** `make tables`(results md → tex), `make figures`(E-G6 곡선, E-G7 ablation 막대, E-G5 예측 대 실측 산점), 개념도 1장(§9 A–E 예제)은 수작업 허용. `make paper`가 최신 결과로 PDF.

**P6.4 관련 연구.** 연구설계서 §13의 5편 + 2026 하반기 신규 검색(웹). 각 논문 "겹치는 부분 / 차별점" 두 줄. 사용자 검토 후 확정.

**완료 조건** 전 절 초고 PDF · CLAIMS 전 항목에 근거 파일 · 모든 표가 `make tables` 산출.

---

### STEP P7 — 리뷰·재현·투고

**P7.1 내부 리뷰.** Claude Code가 리뷰어 2인 역할(A: 주장이 근거를 넘는가, B: 재현 가능한가)로 `paper/REVIEW_internal.md` 작성 → 항목별 수정 또는 한계 절 이동, 처리 기록.

**P7.2 재현 패키지.** `REPRODUCE.md`: 표·그림 번호별 명령, 고정 커밋·서브모듈 sha, 캐시 아카이브 위치, 예상 시간, 구분(mock 수분 / real-sim 캐시 포함 수십 분 / hardware 재현 불가·원자료 제공). 깨끗한 컨테이너에서 표 1개 재현 성공 로그 첨부.

**P7.3 투고(👤).** 학회 결정 후 템플릿·분량 조정은 Claude Code.

---

## 3. 완료 보고 형식(모든 STEP 공통)

```
STEP P<N>.<n> 완료 — 브랜치/PR/sha
게이트: pytest <n> passed · ruff · mypy · 서브모듈 porcelain 빈 출력 · CI
산출물: <결과 md 경로> (배너: MOCK|REAL SIM|REAL HARDWARE)
정확성 두 수: false_infeasible=<>, mismerged_pairs=<>
preregistration 대비 판정: 통과/실패/미정(사용자 수치 대기)
지시와 다르게 한 것: <있으면 이유와 함께>
사용자가 해야 할 것: <실측 실행, 수치 확정, 머지 승인 등>
```
