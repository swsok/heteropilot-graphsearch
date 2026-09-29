P3(T3)는 계속 진행하되, 그와 병행해 **P6.1–P6.3(논문 초고)** 을 지금 시작한다. 결과가 다 나온 뒤 쓰기 시작하면 실험 설계의 빈틈을 고칠 시간이 없다. 지금 있는 결과(E-G1, E-G1b, E-G2, E-G3, E-G4, E-G6, E-G7)로 본문의 대부분을 확정적으로 쓰고, E-G5와 몇 개 미완 항목은 **자리와 문장 틀만** 잡는다. 브랜치 `paper/draft-v0`, 하위 항목별 커밋, 한 PR.

## 규칙 (WORK_ORDER_paper.md §0 위에 추가)

1. **CLAIMS.md가 문장을 허가한다.** `paper/CLAIMS.md`의 상태가 `Established`인 주장만 서술문(indicative)으로 쓴다. `Pending`은 "Table N reports …"처럼 결과가 채워져도 바뀌지 않을 형태로만 쓰고 `\pending{E-G5}` 매크로로 표시한다(매크로는 초고에서 여백 표시, 최종에서 컴파일 오류가 되게 정의). `Not established`·`Retracted`는 본문에 그 사실을 적는다.
2. **숫자는 손으로 옮기지 않는다.** 모든 수치는 `make tables`가 `experiments/results/*.md`에서 생성한 `paper/tables/*.tex`를 `\input`하거나, 본문 인라인 수치는 `paper/numbers.tex`(스크립트 `scripts/paper/numbers.py`가 results md에서 뽑아 `\newcommand`로 정의)를 통해 넣는다. 본문 `.tex`에 숫자 리터럴이 있으면 `make check`가 실패하게 한다(정규식으로 소수·백분율 검출, 화이트리스트 파일 허용).
3. **출처 배너는 표 각주로.** MOCK / REAL SIM / REAL HARDWARE가 각 표·그림 캡션 끝에 반드시 붙는다(`md_to_tex.py`가 이미 배너 없는 표를 거부하니 캡션까지 전달하게 확장).
4. **지는 결과도 쓴다.** k=4 열세, 비대칭 압축률 0.067, throughput 하한의 느슨함, SIM_ERROR 6–8 %, A40 브리지가 공유 자원이 아니었다는 반증, GS-9 철회 — 전부 본문에 들어간다. 연구설계서 §13 "피할 주장" 두 개(처음으로 그래프 표현 / Top-K로 전역 최적 보장)는 `make check`의 금지 문구 목록에 넣는다.
5. **영어로 쓴다.** 코드 규칙과 같다. 분량 목표 12–14쪽 2단(acmart sigconf 임시).

## P6.1 — CLAIMS.md 갱신 (먼저)

현재 표가 뒤처져 있다. 결과 파일이 있는 행을 갱신하고 근거 파일 경로를 채운다:
- E-G4: "processor-sharing model predicts contended transfer better than pricing alone" → **Established (hardware, location (a) only)**, 각주 "as_planned FAIL은 토폴로지 선언 오류(GS-22); as_measured PASS; 정확도 경계 128 MiB 양방향(GS-23)". 추가 행: "The A40's intra-node PCIe path is not a shared resource: two disjoint peer copies each sustain the single-copy rate" → Established (hardware).
- E-G6: "scales to 128 devices within a stated wall-time budget" → 문구를 등록대로 바꿔 "compression ratio and its own cost as a function of scale and symmetry are reported" → **Established (mock, report-only)**. 실 sim 1조건 미실행은 각주.
- E-G7 no_boundary → **Established (mock)**, 오라클 중점 임계값 방식 각주. baseline fairness → Established.
- 새 행(Not established / Pending 구분): "throughput upper bound is loose by ≥2.6× against measured capacity on this node" → Pending (E-G5 B). "recommended placement meets SLOs on hardware" → Pending. "X-type vs Y-type TTFT differ on shared NIC" → Pending. "SIM_ERROR 6–8 % cause" → Pending (P1.5). "location (b) inter-node contention" → Pending.
- Retracted 절에 GS-9 두 번째 결론이 있는지 확인, 없으면 추가.

## P6.2 — 절별 개요와 초고

먼저 `paper/MAP.md`에 아래 표를 그대로 옮겨 놓고(절 · 연구설계서 § · 근거 파일 · 상태), 그 다음 절별로 쓴다. 각 절의 "주장"은 CLAIMS 행 id로 가리킨다.

| 절 | 연구설계서 | 내용과 근거 | 비워 둘 것 |
|---|---|---|---|
| 1 Introduction | §1, §13 | 문제(이종 클러스터·다양한 버스·SLO 아래 최소 비용 배치는 시뮬레이션 비용이 크다), 핵심 관찰(반복 구조는 정확 동등성으로 접을 수 있지만 **경계의 공유 자원을 보존해야** 안전하다 — §5 반례), 기여 A/B/C를 결과 수치와 함께(E-G3 saving, E-G7 mismerge 검출, k=16 recall). heteropilot 위에 세웠음과 재사용/신규 경계를 한 문장. | E-G5 한 줄(`\pending`) |
| 2 Background | HeteroPilot CLAUDE.md, §4 | execution island 추상화, 섬 단위 후보 열거가 이미 암묵적 압축이라는 점, EnvelopeCache twin 병합이 근사 압축이라는 점(설계서 §0). LLMServingSim과 D3(시뮬레이터에 링크 그래프 없음). | — |
| 3 Problem | §2 | 입력(모델·트래픽·SLO·가격·runtime), 후보 = 실행 가능한 전체 계획, 목적 = 시간당 비용, 제약 표, 다섯 상태(impossible_proven … evaluated)와 "unevaluated ≠ infeasible". | — |
| 4 Resource graph | §3 | 정점 종류, bytes/s 정규화와 v1/v2 스키마, 공유 자원 보조 정점(incidence), 경로 집합·컷 용량·경계 문맥. E-G4의 반증을 여기서 예고: 어떤 자원이 공유인지는 **측정으로 확정**해야 한다. | — |
| 5 Candidates and exact compression | §4, §5 | 템플릿→임베딩(canonical 접기, `skipped_symmetric` 닫힌 식 — GS-25), 후보 그래프 라벨(역할·tp·가격·전력·경계 공유자원), WL bucket → VF2 확정, 해시만으로 병합 금지, bucket 키가 prediction key인 이유(GS-5), 대표 dispatch id(GS-7), 충돌 행렬과 multiplicity ≠ max_concurrent. §9 예제(45→8→5→3)는 개념도 1장. | — |
| 6 Provable elimination and adaptive search | §6, §7 | 다섯 검사와 각 relaxation 목록, "완화가 아니면 강등" 규칙, 컷 하한이 heteropilot stage 4·5를 대체(D122), 서비스 여유도 랭커(risk_proxy·비용·다양성)와 G15 정정(goodput 분모 — GS-12), K 스케줄·예산/인증 모드·SearchAudit, 복원과 예약 재검사. | — |
| 7 Simulator adapter and contention | §8 | compile_embedded와 TopologyLossReport(무엇을 잃었는지 명시, D124/GS-8), P/D 비용을 판정 전에 넣는 훅(D125), 캐시 서명(D126/GS-16), FluidContentionModel(processor sharing, 후보 간 경합 없음 — GS-20). | — |
| 8 Evaluation | §12 | 8.1 설정(fixture·스펙·predictor 세 종류·사전 등록). 8.2 정확성 — E-G3 표(실 sim; correct 3/3, complete False 3/3과 unjudged 수, saving). 8.3 압축률과 비용 — E-G1·E-G6 곡선(장치 수×대칭도), 비대칭 실패 조건. 8.4 기여 A — E-G7 ablation(no_boundary mismerge, 임계값 유도 방식 설명). 8.5 탐색 품질 — E-G1b·E-G2·E-G7 holdout(k=4/8/16 표, heteropilot 관대 채점 각주, k=4 열세 명시). 8.6 경합 모형 — E-G4(양방향 경합 정확, as_planned FAIL과 그 의미, 128 MiB 경계, collective world 2/4 재현). 8.7 실장비 — **E-G5 자리**: 표 세 개의 캡션과 열 머리만. | 8.7 전체 `\pending`; 8.2의 SIM_ERROR 원인 문장; 8.6 위치 (b) 행; 8.5 real-lab holdout 행 |
| 9 Related work | §13 | Helix, Vidur, DistServe, LLMServingSim 2.0, Frontier — 각 "겹치는 부분 / 차별점" 두 줄. 2026 하반기 신규는 웹 검색으로 후보 5편 이내 제안(본문 삽입은 사용자 검토 후). | 신규 문헌 확정 |
| 10 Limitations and future work | §11, §12, §13 | MVP 어댑터가 공유 자원을 시뮬레이터에 못 전달, fluid는 패킷 수준 아님·128 MiB 경계, 실장비는 GPU 노드 간만(RNGD 배포 백엔드 없음), 학습 랭커·혼합 TP·KV 변환은 후속, 인증은 선언한 후보 공간·평가 모형에 한정. | — |
| 11 Conclusion | | 세 기여 한 문장씩, 실장비 결과는 `\pending`. | E-G5 |

**재사용 대 신규 표**(기여 C 요구): heteropilot 모듈(재사용) / 훅 H1–H5(소수정, D120–D126) / graphsearch 13 모듈(신규) 세 열로 `paper/tables/reuse.tex`를 손으로 작성(숫자 아님).

## P6.3 — 파이프라인

- `scripts/paper/numbers.py`: results md에서 지정 셀을 뽑아 `\newcommand{\egthreeSavingAbcde}{2475}` 형식으로 `paper/numbers.tex` 생성. 매핑 파일 `scripts/paper/numbers.yaml`(이름 → 파일·행·열).
- `scripts/paper/figures/`: `scale.py`(있음) + `topk.py`(E-G1b·holdout recall 대 k, 두 arm) + `contention.py`(E-G4 양방향 오차 대 메시지 크기, fluid/null) + `concept_sec9.tex`(TikZ 개념도, 손으로).
- `make check`: 본문 숫자 리터럴 검출, 금지 문구 검출, `\pending` 개수 출력, CLAIMS `Established` 아닌 주장을 서술문으로 쓴 곳 검출(주장 id 주석 `% claim: <id>`를 각 단락에 달고 스크립트가 대조).
- `make paper`가 경고 없이 PDF를 만들고 `make check`가 `\pending` 목록만 남기면 완료.

## 완료 보고

PDF 쪽수, `\pending` 목록(위치·무엇을 기다리는지), `make check` 출력, CLAIMS 갱신 diff 요약, 관련 연구 신규 후보 목록(제목·연도·한 줄 관련성)을 넣어라. 본문 초고에서 **쓰다가 드러난 실험 설계의 빈틈**(예: E-G6 실 sim 미실행, holdout 1개, 하한 느슨함의 정량화 부재)을 별도 목록으로 보고하라 — P3가 진행 중이라 지금은 보완할 수 있다.
