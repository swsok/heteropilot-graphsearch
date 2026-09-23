G13 검토 결과다. 게이트(pytest 266 / ruff / mypy / 서브모듈 무수정 / heteropilot 훅·골든 146 / E-G1 재현 바이트 동일)는 전부 확인했고 합격이다. GS-5, GS-7은 지시서의 결함을 코드가 바로잡은 것이 맞고, GS-4가 지적한 지시서 수치 오류도 인정한다.

그러나 **G13 완료 판정은 보류**한다. 연구 기여 A(경계 공유 자원을 보존하는 압축)의 존재 증명이 코드로 나오지 않았고, GS-9의 두 번째 결론("경합 모형이 없어 MVP는 그 차이를 보일 수 없다")은 틀렸다. 원인은 모형 한계가 아니라 구현 누락 두 개다. 아래를 **STEP G14(정정)**와 heteropilot **STEP H4**로 처리하라. 순서는 적힌 대로.

## 왜 반례가 재현되지 않았나 (검토 중 직접 확인한 사실)

1. `grep -rn enable_pd graphsearch tests experiments` → 0건. `CandidateGenerator`의 기본 `enable_pd=False`가 그대로 쓰여 `PD_KV_TRANSFER` flow가 파이프라인 어디서도 생성된 적이 없다. uplink를 지나는 flow는 `INGRESS/EGRESS`(critical path `"none"`)뿐이었다.
2. `graph-toy-shared-nic`이 2노드다. X↔Y P/D는 어느 방향이든 X와 Y의 uplink를 **둘 다** 지나므로 비교 대상이 없다. 연구설계서 §5의 반례는 두 prefill 쌍(X pair, Y pair)이 **같은 제3의 decode 상대**와 통신할 때 드러난다.

fixture에 `nodeZ`(Y와 동일, reserved 0)를 추가하고 `enable_pd=True`로 생성해 `P on X(tp2)+D on Z(tp2)`와 `P on Y(tp2)+D on Z(tp2)` 두 임베딩을 **현재 코드에 그대로** 통과시킨 결과:

```
include_boundary=True : reps=2 merges=0      정확 압축은 X/Y를 분리
include_boundary=False: reps=1 merges=1      ablation은 병합
oracle p99 TTFT: X-pair 5882.2 ms / Y-pair 5867.8 ms
rep(multiplicity 2) distinct oracle ttft [5867.8, 5882.2]  <-- MISMERGE 검출
```

즉 예약 차감(`effective_bottleneck` 10e9→4e9), 경계 서명, oracle 검출기 전부 이미 동작한다. 빠진 것은 플래그와 3노드 fixture다. 현재 파일럿 표의 shared-nic 행(`ratio 1.0, mismerged 0`)은 반례를 시험한 결과가 아니라 반례가 없는 입력의 결과다.

## P/D를 켜면 발화하는 잠복 결함 4개 (G14에서 §2 조치보다 먼저 고칠 것)

**A. P/D 전송 비용이 sim 경로에서 0이 된다** — `adaptive.py::_replace_pd_cost` / `_undo_heteropilot_pd`. heteropilot이 더한 class-default 전송 비용을 **빼기만** 하고 `adapter.apply_pd_transfer_cost_embedded`는 어디서도 호출되지 않는다(`grep apply_pd_transfer_cost_embedded graphsearch/adaptive.py` → 0건). `test_the_pd_transfer_is_charged_once`도 "뺀 값"만 assert 한다. mock은 `predict` 안에서 자기 경로 비용을 이미 더하므로 우연히 맞지만, `--predictor sim`에서는 시뮬레이터가 전송을 무료로 두므로 최종 TTFT에 전송 비용이 전혀 없다. 게다가 feasibility 판정은 `evaluate_candidates` 안에서 heteropilot 비용 포함 상태로 이미 내려졌으므로 지표만 바꾸면 판정과 지표가 어긋난다. 비용은 **판정 전에** 들어가야 한다 → H4.

**B. 캐시 그래프 서명이 배치 크기 1일 때만 적용** — `adaptive.py::_evaluate`의 `cache.with_graph_signature(...) if len(batch) == 1 else cache`. 배치가 2 이상이면 서명 없는 캐시를 쓰고, `EnvelopeKey`는 경계를 모르므로 경계만 다른 두 대표(X→Z, Y→Z)가 같은 키로 충돌해 둘째가 첫째의 지표를 받는다. 캐시가 만드는 mismerge이고 oracle 검사 밖이다. `test_a_warm_cache_is_used_on_the_second_run`은 hits==sims만 보므로 못 잡는다.

**C. TTFT 하한이 복제본 간 P/D·PP flow를 합산** — `bounds.py::_check_comm_latency` TTFT 절의 `ttft_ms +=`. `dp=2`면 `prefill i → decode i` flow가 2개인데 이는 서로 다른 요청의 병렬 전송이다. 한 요청의 TTFT에 둘을 더하면 하한이 실제보다 커져 완화가 아니다.

**D. mock의 TPOT 가산이 하한과 다른 물리** — `tests/graph_fixtures.py::GraphAwareMockPredictor.predict`가 `TP_ALLREDUCE` flow당 all-reduce **1회**를 토큰당 TPOT에 더한다. 하한은 `tp_allreduces_per_output_token = 2·layers`회를 곱한다. "mock은 어떤 하한보다 빠르지 않다"는 docstring 불변식이 깨진다.

---

## STEP H4 — heteropilot 훅 (브랜치 `feat/gs-h4-pd-and-cache-hooks`, 먼저)

1. `planner/optimizer/exhaustive.py::evaluate_candidates(..., pd_transfer: bool = True)`. `False`면 `apply_pd_transfer_cost`를 호출하지 않고 `pd_transfers`도 비운다. 기본값에서 바이트 동일.
2. `planner/predictor/__init__.py` 또는 `llmservingsim.py`: `LLMServingSimPredictor.set_result_hook(fn: Callable[[CandidateConfig, SimResult], SimResult] | None)`. `predict`가 `SimResult`를 반환하기 직전에 훅을 적용한다(캐시 `put` 전, 즉 캐시에는 훅 적용 후 값이 들어간다 — 그래야 캐시 hit에서도 같은 지표). 훅이 None이면 기존 경로.
3. `planner/envelope.py`: `EnvelopeCache.__init__(..., signature_of: Callable[[CandidateConfig], str | None] | None = None)`. `_path()`에서 `signature_of`가 있고 반환값이 None이 아니면 `graph_signature`와 같은 방식으로 이름에 접어 넣는다(둘 다 있으면 `signature_of` 우선). 기본 None에서 파일명 불변.
4. 테스트 `tests/test_search_hooks.py`에 추가: (i) `pd_transfer=False`로 P/D 후보 평가 → `pd_transfers == []`, TTFT가 sim 원값; 기본값이면 기존과 동일. (ii) result hook이 TTFT를 +100 하면 feasibility 판정이 그 값으로 내려지고 캐시 entry에도 +100이 저장됨. (iii) `signature_of`가 다른 문자열을 주는 두 동일 `CandidateConfig` → 다른 `_path`. golden(`test_search.py`, `test_render.py`) 바이트 동일.
5. `docs/deviations.md` **D125** "P/D 전송 비용과 예측 후처리는 호출자가 대체할 수 있어야 하며 판정 전에 들어가야 한다(graphsearch 3-A)", **D126** "EnvelopeKey는 후보의 물리 경계를 모르므로 호출자 서명 훅을 둔다(graphsearch 3-B)". 머지 후 sha를 알려라. graphsearch 서브모듈을 그 sha로 올린다.

## STEP G14 — 정정 (graphsearch, 브랜치 `feat/g14-pd-counterexample`; 필요하면 D→C→B→A→E→F 순으로 PR 분할)

**D. mock 물리 정정.** `GraphAwareMockPredictor.predict`에서 `tpot_add += layers_term * seconds * 1e3`, `layers_term = demand.tp_allreduces_per_output_token(spec.model)`. 이 계산을 `contention.NullContentionModel`의 한 함수로 옮겨 `bounds._check_comm_latency`와 mock이 **같은 함수**를 호출하게 한다. 테스트: 임의 임베딩에 대해 `mock TPOT ≥ comm_latency floor` property (`tests/test_fixtures.py`).

**C. TTFT 하한 정정.** `_check_comm_latency` TTFT 절을 요청 경로 단위로: 같은 `assignment_index` 쌍의 `PD_KV_TRANSFER` flow들 중 **최소** 시간(가장 낙관적 복제본 쌍)을 취하고, `PP_ACTIVATION`은 stage 순서로만 합산한다. `relaxations`에 `"fastest replica pair"` 추가. `tests/test_bounds.py` (i) 완화 property에 `dp=2` P/D 케이스 추가(H4 전에는 `pd_transfer` 기본값으로 돈다).

**B. 캐시 서명 정정.** H4 머지 후 `_evaluate`에서 `cache.with_graph_signature(...) if len(batch)==1 else cache` 분기를 제거하고, `EnvelopeCache(signature_of=lambda c: self._signature_by_embedding_id.get(c.id))`로 대표별 서명을 준다(`_candidate_for`가 exemplar 임베딩 id를 candidate id로 쓰므로 매핑 가능). H4 전 임시로는 대표별로 `evaluate_candidates`를 나눠 호출해도 된다(plan_id_base 누적). 회귀 테스트 `tests/test_adaptive.py`: 경계만 다른 두 대표(아래 F의 3노드 fixture, X→Z와 Y→Z)를 **한 배치, 캐시 있음**으로 평가 → 두 plan의 `p99_ttft_ms`가 다르고 두 번째 실행에서 둘 다 cache hit.

**A. P/D 비용 일원화.** H4 머지 후: `AdaptiveSearch._evaluate`와 `oracle.run_oracle`이 `evaluate_candidates(..., pd_transfer=False)`를 호출하고, `adapter.bind`가 predictor에 `set_result_hook`으로 `apply_pd_transfer_cost_embedded`를 등록한다(P/D 아닌 후보는 그대로 통과). mock도 `predict` 안의 PD 가산을 제거하고 **같은 result hook**을 쓴다(TP 가산은 D의 함수로 유지). `_undo_heteropilot_pd`와 `_replace_pd_cost` 삭제. `test_the_pd_transfer_is_charged_once`를 "최종 p99_ttft_ms == sim 원값 + embedded 전송(p99 프롬프트 기준)"으로 다시 쓰고, 판정이 그 값으로 내려졌음(feasible/infeasible 경계 스펙에서)을 assert. `pd_transfer` provenance에 `basis: "graphsearch embedded path"` 명시.

**E. P/D 생성 켜기.** `__main__.py`의 `CandidateGenerator(...)`, `oracle.run_proposed`, `tests/test_oracle_agreement.py::world`, `experiments/scripts/e_g1_toy_pilot.py` 전부 `enable_pd=True`. CLI 플래그 `--no-enable-pd`로 끌 수 있게. `docs/decisions.md` **GS-11**: "graphsearch는 P/D를 기본 생성한다 — heteropilot CLI 기본(False)과 다르며, 연구 반례가 P/D 전송에 있기 때문".

**F. 3노드 반례 fixture.** `fixtures/clusters/graph-toy-shared-nic.v2.yaml`에 `nodeZ`(nodeY 복제, `uplink-nodeZ` reserved 0, `l-nodeZ-nv`/`l-nodeZ-uplink`/`l-nodeZ-sw`) 추가, v1 사본도 동기화, 파일 머리 주석에 "X pair와 Y pair가 같은 decode 상대 Z와 통신할 때만 차이가 드러난다"를 적어라. `tests/test_oracle_agreement.py`의 ablation 테스트를 지시서 G12 (ii) 원안으로 복원: `include_boundary=True`에서 `mismerged_pairs == []`, **`include_boundary=False`에서 `mismerged_pairs`가 비어 있지 않아야 통과**. 위 재현 스크립트의 두 템플릿(P on X/Y tp2 + D on Z tp2, `s32-t2048`)을 그대로 쓰면 된다. `test_equivalence.py`의 shared-uplink 서명 테스트도 3노드 기준으로 고쳐라.

**G. GS-9 개정.** 두 번째 단락을 지우지 말고 아래에 "2026-09-2x 철회: 원인은 `enable_pd` 미사용과 2노드 fixture였다. 3노드+P/D에서 mismerge가 검출된다(수치)"를 덧붙여라. 파일럿 md의 shared-nic 해설도 같은 방식으로 정정.

**H. 파일럿 재실행 + E-G1b.** `e_g1_toy_pilot.py` 재실행(shared-nic 행이 바뀌어야 한다 — 바뀌지 않으면 위 어딘가가 덜 된 것). 그리고 `E-G1b`: SLO가 실제로 binding하는 스펙(toy 스펙 사본에 `tpot.max_ms`·`ttft.max_ms`를 낮춘 것, 파일명 `graph-toy-llama31-8b-tight.yaml`)으로 heteropilot `search(surrogate=BinnedRooflineRanker, top_k∈{4,8,16})` 대 `AdaptiveSearch(service_margin, (4,8,16))` 대 oracle을 비교해 `feasible_recall`, `cost_regret`, `first_feasible_at_sim`(첫 feasible이 나온 시뮬 순번) 표를 `experiments/results/e_g1b_topk.md`에 쓴다. 헤더의 MOCK 배너 유지.

**I. 소소한 것들(한 커밋).** `requirements.txt`를 `networkx>=3.5`로 올리고 `pyproject.toml` `[tool.pytest.ini_options] filterwarnings`로 3.5 해시 변경 경고를 걸러라(GS-2에 "3.5 미만과 캐시 비호환" 한 줄). README에 "mock만 쓸 때는 `--recursive` 불필요, CI는 `submodules: true`" 명시. 파일럿 표 각주에 `cost_regret "-"`는 가격 부재로 채점 불가라는 뜻임을 적어라. `bounds._COMM_RELAXATIONS`에 "external reservation snapshot taken as an upper bound on outside load" 추가.

## 완료 조건

`pytest -q && ruff check . && mypy graphsearch/` 통과 · `git -C vendor/heteropilot status --porcelain` 빈 출력 · 서브모듈 sha == H4 머지 sha · 복원된 ablation 테스트가 **비어 있지 않은** `mismerged_pairs`로 통과 · 새 캐시 충돌 회귀 테스트 통과 · `e_g1_toy_pilot.md`의 shared-nic 행이 `compression_ratio < 1.0`으로 바뀌고 `correct True` 유지 · `e_g1b_topk.md` 생성 · GS-9 개정, GS-11 추가, D125·D126 기록.

완료 보고에는 H4 sha, 서브모듈 bump 커밋, 파일럿 표의 shared-nic 행 전후, ablation 테스트의 mismerged_pairs 실제 값을 넣어라.
