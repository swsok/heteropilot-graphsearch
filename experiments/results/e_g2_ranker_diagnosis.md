# E-G2 — why the ranker recommended nothing at k=4

> **MockPredictor results. Not performance numbers.** The mock is the ground truth for THIS question -- how far the ranker's estimate sits from the predictor it is ranking for -- and for no other.

Fixtures used for diagnosis: **graph-toy-abcde** and **graph-toy-shared-nic** only, under `graph-toy-llama31-8b-tight.yaml`. Anything derived from these numbers is validated on holdouts the diagnosis never saw (`e_g2_topk_holdout.md`).

## graph-toy-abcde

180 templates → 528 embeddings → 78 representatives, 0 proven impossible by the bounds and never ranked, **78 ranked**. SLO: TTFT 1000.0 ms, TPOT 20.0 ms, 10.0 rps demanded. The oracle found 16 feasible embeddings.

### 1. Band-1 misclassification

| | actual feasible | actual infeasible |
| --- | --- | --- |
| **predicted feasible** (`risk_proxy ≤ 1`) | 8 | **4** |
| **predicted infeasible** | 0 | 66 |

False positives decomposed by what the oracle actually violated: **TTFT 4**, TPOT 0, goodput 4 (TTFT alone, TPOT fine: 4). A candidate can violate more than one, so these need not sum to 4.

Every ranked representative, in the ranker's order. Ratios are `estimate / SLO` for the ranker and `oracle p99 / SLO` for the actual (goodput: `demanded / achieved`); above 1 is a miss.

| # | representative | arch | tp | dev | ttft̂ | tpot̂ | goodput̂ | risk | $/h | ttft | tpot | goodput | pred | actual | top4 | top4+div |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cuda-toygpu-nodeA-tp2-dp1-s32-t2048@f8e0f394e31f | aggregated | 2 | 2 | 0.000 | 0.526 | 0.085 | 0.526 | 5.000 | 5.820 | 0.631 | 2.479 | yes | no | yes | yes |
| 2 | cuda-toygpu-nodeA-tp2-dp1-s32-t8192@f8e0f394e31f | aggregated | 2 | 2 | 0.000 | 0.526 | 0.085 | 0.526 | 5.000 | 5.820 | 0.631 | 2.479 | yes | no | yes | yes |
| 3 | cuda-toygpu-nodeC-tp2-dp1-s32-t2048@ac5be5033867 | aggregated | 2 | 2 | 0.000 | 0.526 | 0.085 | 0.526 | 5.000 | 5.820 | 0.631 | 2.479 | yes | no | yes | no |
| 4 | cuda-toygpu-nodeC-tp2-dp1-s32-t8192@ac5be5033867 | aggregated | 2 | 2 | 0.000 | 0.526 | 0.085 | 0.526 | 5.000 | 5.820 | 0.631 | 2.479 | yes | no | yes | no |
| 5 | cuda-toygpu-nodeA-tp2-dp1-s128-t2048@f8e0f394e31f | aggregated | 2 | 2 | 0.000 | 0.527 | 0.085 | 0.527 | 5.000 | 0.433 | 0.631 | 1.000 | yes | yes | no | no |
| 6 | cuda-toygpu-nodeA-tp2-dp1-s128-t8192@f8e0f394e31f | aggregated | 2 | 2 | 0.000 | 0.527 | 0.085 | 0.527 | 5.000 | 0.433 | 0.631 | 1.000 | yes | yes | no | no |
| 7 | cuda-toygpu-nodeC-tp2-dp1-s128-t2048@ac5be5033867 | aggregated | 2 | 2 | 0.000 | 0.527 | 0.085 | 0.527 | 5.000 | 0.433 | 0.631 | 1.000 | yes | yes | no | no |
| 8 | cuda-toygpu-nodeC-tp2-dp1-s128-t8192@ac5be5033867 | aggregated | 2 | 2 | 0.000 | 0.527 | 0.085 | 0.527 | 5.000 | 0.433 | 0.631 | 1.000 | yes | yes | no | no |
| 9 | cuda-toygpu-nodeA-tp2-dp1-s256-t2048@f8e0f394e31f | aggregated | 2 | 2 | 0.000 | 0.527 | 0.085 | 0.527 | 5.000 | 0.331 | 0.632 | 1.000 | yes | yes | no | no |
| 10 | cuda-toygpu-nodeA-tp2-dp1-s256-t8192@f8e0f394e31f | aggregated | 2 | 2 | 0.000 | 0.527 | 0.085 | 0.527 | 5.000 | 0.331 | 0.632 | 1.000 | yes | yes | no | no |
| 11 | cuda-toygpu-nodeC-tp2-dp1-s256-t2048@ac5be5033867 | aggregated | 2 | 2 | 0.000 | 0.527 | 0.085 | 0.527 | 5.000 | 0.331 | 0.632 | 1.000 | yes | yes | no | no |
| 12 | cuda-toygpu-nodeC-tp2-dp1-s256-t8192@ac5be5033867 | aggregated | 2 | 2 | 0.000 | 0.527 | 0.085 | 0.527 | 5.000 | 0.331 | 0.632 | 1.000 | yes | yes | no | no |
| 13 | cuda-toygpu-nodeA-tp1-dp1-s32-t2048@5b5d48e8d6b6 | aggregated | 1 | 1 | 0.000 | 1.046 | 0.385 | 1.046 | 3.000 | 10.840 | 1.255 | 4.957 | no | no | no | yes |
| 14 | cuda-toygpu-nodeA-tp1-dp1-s32-t8192@5b5d48e8d6b6 | aggregated | 1 | 1 | 0.000 | 1.046 | 0.385 | 1.046 | 3.000 | 10.840 | 1.255 | 4.957 | no | no | no | no |
| 15 | cuda-toygpu-nodeC-tp1-dp1-s32-t2048@693a423f1a60 | aggregated | 1 | 1 | 0.000 | 1.046 | 0.385 | 1.046 | 3.000 | 10.840 | 1.255 | 4.957 | no | no | no | no |
| 16 | cuda-toygpu-nodeC-tp1-dp1-s32-t8192@693a423f1a60 | aggregated | 1 | 1 | 0.000 | 1.046 | 0.385 | 1.046 | 3.000 | 10.840 | 1.255 | 4.957 | no | no | no | no |
| 17 | cuda-toygpu-nodeA-tp1-dp2-s32-t2048@c6986e4ea522 | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 5.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 18 | cuda-toygpu-nodeA-tp1-dp2-s32-t8192@c6986e4ea522 | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 5.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 19 | cuda-toygpu-nodeC-tp1-dp2-s32-t2048@19cd39e60b94 | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 5.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 20 | cuda-toygpu-nodeC-tp1-dp2-s32-t8192@19cd39e60b94 | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 5.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 21 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeB-tp1-dp1)-s32-t2048@42c32dab7cba | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | yes |
| 22 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeB-tp1-dp1)-s32-t8192@42c32dab7cba | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 23 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeC-tp1-dp1)-s32-t2048@137da20ee85d | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 24 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeC-tp1-dp1)-s32-t8192@137da20ee85d | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 25 | mix(cuda-toygpu-nodeC-tp1-dp1+cuda-toygpu-nodeD-tp1-dp1)-s32-t2048@00c92bb4a527 | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 26 | mix(cuda-toygpu-nodeC-tp1-dp1+cuda-toygpu-nodeD-tp1-dp1)-s32-t8192@00c92bb4a527 | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 27 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeB-tp1-dp1 D)-s32-t2048@42c32dab7cba | pd_split | 1 | 2 | 0.010 | 1.046 | 0.385 | 1.046 | 6.000 | 10.878 | 1.255 | 4.957 | no | no | no | no |
| 28 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeB-tp1-dp1 D)-s32-t8192@42c32dab7cba | pd_split | 1 | 2 | 0.010 | 1.046 | 0.385 | 1.046 | 6.000 | 10.878 | 1.255 | 4.957 | no | no | no | no |
| 29 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeC-tp1-dp1 D)-s32-t2048@137da20ee85d | pd_split | 1 | 2 | 0.019 | 1.046 | 0.385 | 1.046 | 6.000 | 10.916 | 1.255 | 4.957 | no | no | no | no |
| 30 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeC-tp1-dp1 D)-s32-t8192@137da20ee85d | pd_split | 1 | 2 | 0.019 | 1.046 | 0.385 | 1.046 | 6.000 | 10.916 | 1.255 | 4.957 | no | no | no | no |
| 31 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeA-tp1-dp1 D)-s32-t2048@24b8207686e4 | pd_split | 1 | 2 | 0.019 | 1.046 | 0.385 | 1.046 | 6.000 | 10.916 | 1.255 | 4.957 | no | no | no | no |
| 32 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeA-tp1-dp1 D)-s32-t8192@24b8207686e4 | pd_split | 1 | 2 | 0.019 | 1.046 | 0.385 | 1.046 | 6.000 | 10.916 | 1.255 | 4.957 | no | no | no | no |
| 33 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeD-tp1-dp1 D)-s32-t2048@00c92bb4a527 | pd_split | 1 | 2 | 0.019 | 1.046 | 0.385 | 1.046 | 6.000 | 10.916 | 1.255 | 4.957 | no | no | no | no |
| 34 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeD-tp1-dp1 D)-s32-t8192@00c92bb4a527 | pd_split | 1 | 2 | 0.019 | 1.046 | 0.385 | 1.046 | 6.000 | 10.916 | 1.255 | 4.957 | no | no | no | no |
| 35 | cuda-toygpu-nodeA-tp1-dp1-s128-t2048@5b5d48e8d6b6 | aggregated | 1 | 1 | 0.000 | 1.047 | 0.385 | 1.047 | 3.000 | 13.248 | 1.256 | 1.240 | no | no | no | no |
| 36 | cuda-toygpu-nodeA-tp1-dp1-s128-t8192@5b5d48e8d6b6 | aggregated | 1 | 1 | 0.000 | 1.047 | 0.385 | 1.047 | 3.000 | 13.248 | 1.256 | 1.240 | no | no | no | no |
| 37 | cuda-toygpu-nodeC-tp1-dp1-s128-t2048@693a423f1a60 | aggregated | 1 | 1 | 0.000 | 1.047 | 0.385 | 1.047 | 3.000 | 13.248 | 1.256 | 1.240 | no | no | no | no |
| 38 | cuda-toygpu-nodeC-tp1-dp1-s128-t8192@693a423f1a60 | aggregated | 1 | 1 | 0.000 | 1.047 | 0.385 | 1.047 | 3.000 | 13.248 | 1.256 | 1.240 | no | no | no | no |
| 39 | cuda-toygpu-nodeA-tp1-dp2-s128-t2048@c6986e4ea522 | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 5.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 40 | cuda-toygpu-nodeA-tp1-dp2-s128-t8192@c6986e4ea522 | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 5.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 41 | cuda-toygpu-nodeC-tp1-dp2-s128-t2048@19cd39e60b94 | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 5.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 42 | cuda-toygpu-nodeC-tp1-dp2-s128-t8192@19cd39e60b94 | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 5.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 43 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeB-tp1-dp1)-s128-t2048@42c32dab7cba | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 44 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeB-tp1-dp1)-s128-t8192@42c32dab7cba | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 45 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeC-tp1-dp1)-s128-t2048@137da20ee85d | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 46 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeC-tp1-dp1)-s128-t8192@137da20ee85d | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 47 | mix(cuda-toygpu-nodeC-tp1-dp1+cuda-toygpu-nodeD-tp1-dp1)-s128-t2048@00c92bb4a527 | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 48 | mix(cuda-toygpu-nodeC-tp1-dp1+cuda-toygpu-nodeD-tp1-dp1)-s128-t8192@00c92bb4a527 | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 49 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeB-tp1-dp1 D)-s128-t2048@42c32dab7cba | pd_split | 1 | 2 | 0.010 | 1.047 | 0.385 | 1.047 | 6.000 | 13.286 | 1.256 | 1.240 | no | no | no | no |
| 50 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeB-tp1-dp1 D)-s128-t8192@42c32dab7cba | pd_split | 1 | 2 | 0.010 | 1.047 | 0.385 | 1.047 | 6.000 | 13.286 | 1.256 | 1.240 | no | no | no | no |
| 51 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeC-tp1-dp1 D)-s128-t2048@137da20ee85d | pd_split | 1 | 2 | 0.019 | 1.047 | 0.385 | 1.047 | 6.000 | 13.324 | 1.256 | 1.240 | no | no | no | no |
| 52 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeC-tp1-dp1 D)-s128-t8192@137da20ee85d | pd_split | 1 | 2 | 0.019 | 1.047 | 0.385 | 1.047 | 6.000 | 13.324 | 1.256 | 1.240 | no | no | no | no |
| 53 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeA-tp1-dp1 D)-s128-t2048@24b8207686e4 | pd_split | 1 | 2 | 0.019 | 1.047 | 0.385 | 1.047 | 6.000 | 13.324 | 1.256 | 1.240 | no | no | no | no |
| 54 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeA-tp1-dp1 D)-s128-t8192@24b8207686e4 | pd_split | 1 | 2 | 0.019 | 1.047 | 0.385 | 1.047 | 6.000 | 13.324 | 1.256 | 1.240 | no | no | no | no |
| 55 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeD-tp1-dp1 D)-s128-t2048@00c92bb4a527 | pd_split | 1 | 2 | 0.019 | 1.047 | 0.385 | 1.047 | 6.000 | 13.324 | 1.256 | 1.240 | no | no | no | no |
| 56 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeD-tp1-dp1 D)-s128-t8192@00c92bb4a527 | pd_split | 1 | 2 | 0.019 | 1.047 | 0.385 | 1.047 | 6.000 | 13.324 | 1.256 | 1.240 | no | no | no | no |
| 57 | cuda-toygpu-nodeA-tp1-dp1-s256-t2048@5b5d48e8d6b6 | aggregated | 1 | 1 | 0.000 | 1.048 | 0.385 | 1.048 | 3.000 | 0.868 | 1.257 | 1.000 | no | no | no | no |
| 58 | cuda-toygpu-nodeA-tp1-dp1-s256-t8192@5b5d48e8d6b6 | aggregated | 1 | 1 | 0.000 | 1.048 | 0.385 | 1.048 | 3.000 | 0.868 | 1.257 | 1.000 | no | no | no | no |
| 59 | cuda-toygpu-nodeC-tp1-dp1-s256-t2048@693a423f1a60 | aggregated | 1 | 1 | 0.000 | 1.048 | 0.385 | 1.048 | 3.000 | 0.868 | 1.257 | 1.000 | no | no | no | no |
| 60 | cuda-toygpu-nodeC-tp1-dp1-s256-t8192@693a423f1a60 | aggregated | 1 | 1 | 0.000 | 1.048 | 0.385 | 1.048 | 3.000 | 0.868 | 1.257 | 1.000 | no | no | no | no |
| 61 | cuda-toygpu-nodeA-tp1-dp2-s256-t2048@c6986e4ea522 | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 5.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 62 | cuda-toygpu-nodeA-tp1-dp2-s256-t8192@c6986e4ea522 | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 5.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 63 | cuda-toygpu-nodeC-tp1-dp2-s256-t2048@19cd39e60b94 | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 5.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 64 | cuda-toygpu-nodeC-tp1-dp2-s256-t8192@19cd39e60b94 | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 5.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 65 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeB-tp1-dp1)-s256-t2048@42c32dab7cba | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 66 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeB-tp1-dp1)-s256-t8192@42c32dab7cba | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 67 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeC-tp1-dp1)-s256-t2048@137da20ee85d | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 68 | mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeC-tp1-dp1)-s256-t8192@137da20ee85d | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 69 | mix(cuda-toygpu-nodeC-tp1-dp1+cuda-toygpu-nodeD-tp1-dp1)-s256-t2048@00c92bb4a527 | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 70 | mix(cuda-toygpu-nodeC-tp1-dp1+cuda-toygpu-nodeD-tp1-dp1)-s256-t8192@00c92bb4a527 | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 71 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeB-tp1-dp1 D)-s256-t2048@42c32dab7cba | pd_split | 1 | 2 | 0.010 | 1.048 | 0.385 | 1.048 | 6.000 | 0.906 | 1.257 | 1.000 | no | no | no | no |
| 72 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeB-tp1-dp1 D)-s256-t8192@42c32dab7cba | pd_split | 1 | 2 | 0.010 | 1.048 | 0.385 | 1.048 | 6.000 | 0.906 | 1.257 | 1.000 | no | no | no | no |
| 73 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeC-tp1-dp1 D)-s256-t2048@137da20ee85d | pd_split | 1 | 2 | 0.019 | 1.048 | 0.385 | 1.048 | 6.000 | 0.944 | 1.257 | 1.000 | no | no | no | no |
| 74 | pd(cuda-toygpu-nodeA-tp1-dp1 P + cuda-toygpu-nodeC-tp1-dp1 D)-s256-t8192@137da20ee85d | pd_split | 1 | 2 | 0.019 | 1.048 | 0.385 | 1.048 | 6.000 | 0.944 | 1.257 | 1.000 | no | no | no | no |
| 75 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeA-tp1-dp1 D)-s256-t2048@24b8207686e4 | pd_split | 1 | 2 | 0.019 | 1.048 | 0.385 | 1.048 | 6.000 | 0.944 | 1.257 | 1.000 | no | no | no | no |
| 76 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeA-tp1-dp1 D)-s256-t8192@24b8207686e4 | pd_split | 1 | 2 | 0.019 | 1.048 | 0.385 | 1.048 | 6.000 | 0.944 | 1.257 | 1.000 | no | no | no | no |
| 77 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeD-tp1-dp1 D)-s256-t2048@00c92bb4a527 | pd_split | 1 | 2 | 0.019 | 1.048 | 0.385 | 1.048 | 6.000 | 0.944 | 1.257 | 1.000 | no | no | no | no |
| 78 | pd(cuda-toygpu-nodeC-tp1-dp1 P + cuda-toygpu-nodeD-tp1-dp1 D)-s256-t8192@00c92bb4a527 | pd_split | 1 | 2 | 0.019 | 1.048 | 0.385 | 1.048 | 6.000 | 0.944 | 1.257 | 1.000 | no | no | no | no |

### 2. Residuals, `actual / predicted`

- **ttft**: n=24 p50=569.302 p90=1133.963 max=1384.961
- **tpot**: n=78 p50=1.200 p90=1.200 max=1.200
- **goodput**: n=78 p50=5.188 p90=12.860 max=29.092

### 3. The four that were chosen at k=4

- `cuda-toygpu-nodeA-tp2-dp1-s32-t2048@f8e0f394e31f` (aggregated, tp2, 2 dev, 5.0 $/h): in band 1 because risk 0.526 = max(ttft̂ 0.000, tpot̂ 0.526, goodput̂ 0.085); actually violates TTFT, goodput (ttft 5.820, tpot 0.631, goodput 2.479).
- `cuda-toygpu-nodeA-tp2-dp1-s32-t8192@f8e0f394e31f` (aggregated, tp2, 2 dev, 5.0 $/h): in band 1 because risk 0.526 = max(ttft̂ 0.000, tpot̂ 0.526, goodput̂ 0.085); actually violates TTFT, goodput (ttft 5.820, tpot 0.631, goodput 2.479).
- `cuda-toygpu-nodeC-tp2-dp1-s32-t2048@ac5be5033867` (aggregated, tp2, 2 dev, 5.0 $/h): in band 1 because risk 0.526 = max(ttft̂ 0.000, tpot̂ 0.526, goodput̂ 0.085); actually violates TTFT, goodput (ttft 5.820, tpot 0.631, goodput 2.479).
- `cuda-toygpu-nodeC-tp2-dp1-s32-t8192@ac5be5033867` (aggregated, tp2, 2 dev, 5.0 $/h): in band 1 because risk 0.526 = max(ttft̂ 0.000, tpot̂ 0.526, goodput̂ 0.085); actually violates TTFT, goodput (ttft 5.820, tpot 0.631, goodput 2.479).

### 4. Hypotheses, in numbers

**H-a — TTFT estimate has no prefill compute and no queueing.** 38 representatives miss the TTFT; 4 of them were ranked comfortable. Among violators the ranker's `ttft_ratio` is n=38 p50=0.000 p90=0.019 max=0.019 while the actual is n=38 p50=10.878 p90=13.324 max=13.324. The transfer term the ranker does have accounts for this share of the actual p99 TTFT: n=78 p50=0.000 p90=0.002 max=0.020; a single prefill roofline pass (weights once + p50 prompt KV) would account for n=78 p50=0.022 p90=0.044 max=0.044. `GreedyEstimate` carries no prefill field -- `roofline_tpot_ms` is decode-only by design -- so the term would have to be computed from `memutil` as this script does.

**H-b — `goodput_ratio` is inert.** Over all ranked representatives it is n=78 p50=0.193 p90=0.385 max=0.385; 0 are above 1. 38 representatives actually miss the demanded goodput; their `goodput_ratio` is n=38 p50=0.385 p90=0.385 max=0.385 against an actual n=38 p50=2.479 p90=4.957 max=4.957. Which term is binding (`== risk_proxy`): ttft 0, tpot 78, goodput 0.

**H-c — the band is sorted by cost, so the marginal ones lead.** Band 1 has 12 members, 8 actually feasible; its `risk_proxy` is n=12 p50=0.527 p90=0.527 max=0.527 -- feasible members n=8 p50=0.527 p90=0.527 max=0.527, infeasible members n=4 p50=0.526 p90=0.526 max=0.526. The four chosen have risk [0.526, 0.526, 0.526, 0.526] and cost [5.0, 5.0, 5.0, 5.0]; they are the cheapest in the band: yes. The first actually-feasible band-1 member sits at rank 5.

**Diversity.** Plain top-4 contains 0 feasible; with `DiversityQuota()` the top-4 contains 0 feasible. (`cuda-toygpu-nodeA-tp2-dp1-s32-t2048@f8e0f394e31f, cuda-toygpu-nodeA-tp2-dp1-s32-t8192@f8e0f394e31f, cuda-toygpu-nodeA-tp1-dp1-s32-t2048@5b5d48e8d6b6, mix(cuda-toygpu-nodeA-tp1-dp1+cuda-toygpu-nodeB-tp1-dp1)-s32-t2048@42c32dab7cba`)

### 5. Conclusion

**H-b is supported, and it is the cause.** Every false positive is a `max_num_seqs=32` placement whose `s128`/`s256` siblings on the same devices are feasible. The ceiling `goodput_ratio` divides by admits as many sequences as the KV cache holds and never reads the knob, so it reads the same 0.526-band risk for both; the mock, like an engine, stops at 32, utilisation goes to 2.479 of capacity and queueing drives the TTFT to 10.878x the SLO. Re-scoring the same rows with the knob-aware `greedy.estimate` throughput as the denominator (`service_margin`) gives a confusion matrix of tp=8 fp=0 fn=0 tn=70: the 4 flipped rows are exactly the false positives (ceiling → estimate → actual: 0.085 → 2.066 → 2.479; 0.085 → 2.066 → 2.479), and the goodput residual `actual/predicted` falls from n=78 p50=5.188 p90=12.860 max=29.092 to n=78 p50=1.933 p90=3.866 max=3.866.

**H-a's premise is true and its remedy is immaterial.** The TTFT estimate is 0 for every non-P/D placement against an actual of up to 13.3x, but a prefill roofline pass covers at most 4.4 % of that TTFT; the rest is queueing, which is utilisation, which is H-b's term. Adding the prefill term alone changes 0 verdicts. It is added anyway -- same physics as the bound, and better than the zero it replaces -- and recorded in `RankFeatures.basis`.

**H-c is not supported.** Inside band 1 the feasible and infeasible members have the same `risk_proxy` to three decimals (n=8 p50=0.527 p90=0.527 max=0.527 vs n=4 p50=0.526 p90=0.526 max=0.526) and the same cost; there is no margin gradient a δ-tier could sort on, so no two-stage sort is introduced. Diversity does not help either (0 → 0 feasible in the top four): the quota spreads over structures, and the misclassification is inside one.

## graph-toy-shared-nic

108 templates → 288 embeddings → 60 representatives, 0 proven impossible by the bounds and never ranked, **60 ranked**. SLO: TTFT 1000.0 ms, TPOT 20.0 ms, 10.0 rps demanded. The oracle found 12 feasible embeddings.

### 1. Band-1 misclassification

| | actual feasible | actual infeasible |
| --- | --- | --- |
| **predicted feasible** (`risk_proxy ≤ 1`) | 8 | **4** |
| **predicted infeasible** | 0 | 48 |

False positives decomposed by what the oracle actually violated: **TTFT 4**, TPOT 0, goodput 4 (TTFT alone, TPOT fine: 4). A candidate can violate more than one, so these need not sum to 4.

Every ranked representative, in the ranker's order. Ratios are `estimate / SLO` for the ranker and `oracle p99 / SLO` for the actual (goodput: `demanded / achieved`); above 1 is a miss.

| # | representative | arch | tp | dev | ttft̂ | tpot̂ | goodput̂ | risk | $/h | ttft | tpot | goodput | pred | actual | top4 | top4+div |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cuda-toygpu-nodeX-tp2-dp1-s32-t2048@5dfef3a9a468 | aggregated | 2 | 2 | 0.000 | 0.525 | 0.085 | 0.525 | 5.000 | 5.820 | 0.629 | 2.479 | yes | no | yes | yes |
| 2 | cuda-toygpu-nodeX-tp2-dp1-s32-t8192@5dfef3a9a468 | aggregated | 2 | 2 | 0.000 | 0.525 | 0.085 | 0.525 | 5.000 | 5.820 | 0.629 | 2.479 | yes | no | yes | yes |
| 3 | cuda-toygpu-nodeY-tp2-dp1-s32-t2048@50a58329ec48 | aggregated | 2 | 2 | 0.000 | 0.525 | 0.085 | 0.525 | 5.000 | 5.820 | 0.629 | 2.479 | yes | no | yes | no |
| 4 | cuda-toygpu-nodeY-tp2-dp1-s32-t8192@50a58329ec48 | aggregated | 2 | 2 | 0.000 | 0.525 | 0.085 | 0.525 | 5.000 | 5.820 | 0.629 | 2.479 | yes | no | yes | no |
| 5 | cuda-toygpu-nodeX-tp2-dp1-s128-t2048@5dfef3a9a468 | aggregated | 2 | 2 | 0.000 | 0.525 | 0.085 | 0.525 | 5.000 | 0.433 | 0.630 | 1.000 | yes | yes | no | no |
| 6 | cuda-toygpu-nodeX-tp2-dp1-s128-t8192@5dfef3a9a468 | aggregated | 2 | 2 | 0.000 | 0.525 | 0.085 | 0.525 | 5.000 | 0.433 | 0.630 | 1.000 | yes | yes | no | no |
| 7 | cuda-toygpu-nodeY-tp2-dp1-s128-t2048@50a58329ec48 | aggregated | 2 | 2 | 0.000 | 0.525 | 0.085 | 0.525 | 5.000 | 0.433 | 0.630 | 1.000 | yes | yes | no | no |
| 8 | cuda-toygpu-nodeY-tp2-dp1-s128-t8192@50a58329ec48 | aggregated | 2 | 2 | 0.000 | 0.525 | 0.085 | 0.525 | 5.000 | 0.433 | 0.630 | 1.000 | yes | yes | no | no |
| 9 | cuda-toygpu-nodeX-tp2-dp1-s256-t2048@5dfef3a9a468 | aggregated | 2 | 2 | 0.000 | 0.526 | 0.085 | 0.526 | 5.000 | 0.331 | 0.631 | 1.000 | yes | yes | no | no |
| 10 | cuda-toygpu-nodeX-tp2-dp1-s256-t8192@5dfef3a9a468 | aggregated | 2 | 2 | 0.000 | 0.526 | 0.085 | 0.526 | 5.000 | 0.331 | 0.631 | 1.000 | yes | yes | no | no |
| 11 | cuda-toygpu-nodeY-tp2-dp1-s256-t2048@50a58329ec48 | aggregated | 2 | 2 | 0.000 | 0.526 | 0.085 | 0.526 | 5.000 | 0.331 | 0.631 | 1.000 | yes | yes | no | no |
| 12 | cuda-toygpu-nodeY-tp2-dp1-s256-t8192@50a58329ec48 | aggregated | 2 | 2 | 0.000 | 0.526 | 0.085 | 0.526 | 5.000 | 0.331 | 0.631 | 1.000 | yes | yes | no | no |
| 13 | cuda-toygpu-nodeX-tp1-dp1-s32-t2048@7d36012c2000 | aggregated | 1 | 1 | 0.000 | 1.046 | 0.385 | 1.046 | 3.000 | 10.840 | 1.255 | 4.957 | no | no | no | yes |
| 14 | cuda-toygpu-nodeX-tp1-dp1-s32-t8192@7d36012c2000 | aggregated | 1 | 1 | 0.000 | 1.046 | 0.385 | 1.046 | 3.000 | 10.840 | 1.255 | 4.957 | no | no | no | no |
| 15 | cuda-toygpu-nodeY-tp1-dp1-s32-t2048@8a5235922f1b | aggregated | 1 | 1 | 0.000 | 1.046 | 0.385 | 1.046 | 3.000 | 10.840 | 1.255 | 4.957 | no | no | no | no |
| 16 | cuda-toygpu-nodeY-tp1-dp1-s32-t8192@8a5235922f1b | aggregated | 1 | 1 | 0.000 | 1.046 | 0.385 | 1.046 | 3.000 | 10.840 | 1.255 | 4.957 | no | no | no | no |
| 17 | cuda-toygpu-nodeX-tp1-dp2-s32-t2048@b95373fe39dd | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 5.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 18 | cuda-toygpu-nodeX-tp1-dp2-s32-t8192@b95373fe39dd | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 5.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 19 | cuda-toygpu-nodeY-tp1-dp2-s32-t2048@3878b093bbbf | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 5.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 20 | cuda-toygpu-nodeY-tp1-dp2-s32-t8192@3878b093bbbf | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 5.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 21 | mix(cuda-toygpu-nodeX-tp1-dp1+cuda-toygpu-nodeY-tp1-dp1)-s32-t2048@2f8ade5063d6 | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | yes |
| 22 | mix(cuda-toygpu-nodeX-tp1-dp1+cuda-toygpu-nodeY-tp1-dp1)-s32-t8192@2f8ade5063d6 | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 23 | mix(cuda-toygpu-nodeY-tp1-dp1+cuda-toygpu-nodeZ-tp1-dp1)-s32-t2048@55b485062c0b | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 24 | mix(cuda-toygpu-nodeY-tp1-dp1+cuda-toygpu-nodeZ-tp1-dp1)-s32-t8192@55b485062c0b | aggregated | 1 | 2 | 0.000 | 1.046 | 0.193 | 1.046 | 6.000 | 10.840 | 1.255 | 2.479 | no | no | no | no |
| 25 | pd(cuda-toygpu-nodeX-tp1-dp1 P + cuda-toygpu-nodeY-tp1-dp1 D)-s32-t2048@2f8ade5063d6 | pd_split | 1 | 2 | 0.024 | 1.046 | 0.385 | 1.046 | 6.000 | 10.935 | 1.255 | 4.957 | no | no | no | no |
| 26 | pd(cuda-toygpu-nodeX-tp1-dp1 P + cuda-toygpu-nodeY-tp1-dp1 D)-s32-t8192@2f8ade5063d6 | pd_split | 1 | 2 | 0.024 | 1.046 | 0.385 | 1.046 | 6.000 | 10.935 | 1.255 | 4.957 | no | no | no | no |
| 27 | pd(cuda-toygpu-nodeY-tp1-dp1 P + cuda-toygpu-nodeZ-tp1-dp1 D)-s32-t2048@55b485062c0b | pd_split | 1 | 2 | 0.010 | 1.046 | 0.385 | 1.046 | 6.000 | 10.878 | 1.255 | 4.957 | no | no | no | no |
| 28 | pd(cuda-toygpu-nodeY-tp1-dp1 P + cuda-toygpu-nodeZ-tp1-dp1 D)-s32-t8192@55b485062c0b | pd_split | 1 | 2 | 0.010 | 1.046 | 0.385 | 1.046 | 6.000 | 10.878 | 1.255 | 4.957 | no | no | no | no |
| 29 | cuda-toygpu-nodeX-tp1-dp1-s128-t2048@7d36012c2000 | aggregated | 1 | 1 | 0.000 | 1.047 | 0.385 | 1.047 | 3.000 | 13.248 | 1.256 | 1.240 | no | no | no | no |
| 30 | cuda-toygpu-nodeX-tp1-dp1-s128-t8192@7d36012c2000 | aggregated | 1 | 1 | 0.000 | 1.047 | 0.385 | 1.047 | 3.000 | 13.248 | 1.256 | 1.240 | no | no | no | no |
| 31 | cuda-toygpu-nodeY-tp1-dp1-s128-t2048@8a5235922f1b | aggregated | 1 | 1 | 0.000 | 1.047 | 0.385 | 1.047 | 3.000 | 13.248 | 1.256 | 1.240 | no | no | no | no |
| 32 | cuda-toygpu-nodeY-tp1-dp1-s128-t8192@8a5235922f1b | aggregated | 1 | 1 | 0.000 | 1.047 | 0.385 | 1.047 | 3.000 | 13.248 | 1.256 | 1.240 | no | no | no | no |
| 33 | cuda-toygpu-nodeX-tp1-dp2-s128-t2048@b95373fe39dd | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 5.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 34 | cuda-toygpu-nodeX-tp1-dp2-s128-t8192@b95373fe39dd | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 5.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 35 | cuda-toygpu-nodeY-tp1-dp2-s128-t2048@3878b093bbbf | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 5.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 36 | cuda-toygpu-nodeY-tp1-dp2-s128-t8192@3878b093bbbf | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 5.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 37 | mix(cuda-toygpu-nodeX-tp1-dp1+cuda-toygpu-nodeY-tp1-dp1)-s128-t2048@2f8ade5063d6 | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 38 | mix(cuda-toygpu-nodeX-tp1-dp1+cuda-toygpu-nodeY-tp1-dp1)-s128-t8192@2f8ade5063d6 | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 39 | mix(cuda-toygpu-nodeY-tp1-dp1+cuda-toygpu-nodeZ-tp1-dp1)-s128-t2048@55b485062c0b | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 40 | mix(cuda-toygpu-nodeY-tp1-dp1+cuda-toygpu-nodeZ-tp1-dp1)-s128-t8192@55b485062c0b | aggregated | 1 | 2 | 0.000 | 1.047 | 0.193 | 1.047 | 6.000 | 0.698 | 1.256 | 1.000 | no | no | no | no |
| 41 | pd(cuda-toygpu-nodeX-tp1-dp1 P + cuda-toygpu-nodeY-tp1-dp1 D)-s128-t2048@2f8ade5063d6 | pd_split | 1 | 2 | 0.024 | 1.047 | 0.385 | 1.047 | 6.000 | 13.343 | 1.256 | 1.240 | no | no | no | no |
| 42 | pd(cuda-toygpu-nodeX-tp1-dp1 P + cuda-toygpu-nodeY-tp1-dp1 D)-s128-t8192@2f8ade5063d6 | pd_split | 1 | 2 | 0.024 | 1.047 | 0.385 | 1.047 | 6.000 | 13.343 | 1.256 | 1.240 | no | no | no | no |
| 43 | pd(cuda-toygpu-nodeY-tp1-dp1 P + cuda-toygpu-nodeZ-tp1-dp1 D)-s128-t2048@55b485062c0b | pd_split | 1 | 2 | 0.010 | 1.047 | 0.385 | 1.047 | 6.000 | 13.286 | 1.256 | 1.240 | no | no | no | no |
| 44 | pd(cuda-toygpu-nodeY-tp1-dp1 P + cuda-toygpu-nodeZ-tp1-dp1 D)-s128-t8192@55b485062c0b | pd_split | 1 | 2 | 0.010 | 1.047 | 0.385 | 1.047 | 6.000 | 13.286 | 1.256 | 1.240 | no | no | no | no |
| 45 | cuda-toygpu-nodeX-tp1-dp1-s256-t2048@7d36012c2000 | aggregated | 1 | 1 | 0.000 | 1.048 | 0.385 | 1.048 | 3.000 | 0.868 | 1.257 | 1.000 | no | no | no | no |
| 46 | cuda-toygpu-nodeX-tp1-dp1-s256-t8192@7d36012c2000 | aggregated | 1 | 1 | 0.000 | 1.048 | 0.385 | 1.048 | 3.000 | 0.868 | 1.257 | 1.000 | no | no | no | no |
| 47 | cuda-toygpu-nodeY-tp1-dp1-s256-t2048@8a5235922f1b | aggregated | 1 | 1 | 0.000 | 1.048 | 0.385 | 1.048 | 3.000 | 0.868 | 1.257 | 1.000 | no | no | no | no |
| 48 | cuda-toygpu-nodeY-tp1-dp1-s256-t8192@8a5235922f1b | aggregated | 1 | 1 | 0.000 | 1.048 | 0.385 | 1.048 | 3.000 | 0.868 | 1.257 | 1.000 | no | no | no | no |
| 49 | cuda-toygpu-nodeX-tp1-dp2-s256-t2048@b95373fe39dd | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 5.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 50 | cuda-toygpu-nodeX-tp1-dp2-s256-t8192@b95373fe39dd | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 5.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 51 | cuda-toygpu-nodeY-tp1-dp2-s256-t2048@3878b093bbbf | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 5.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 52 | cuda-toygpu-nodeY-tp1-dp2-s256-t8192@3878b093bbbf | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 5.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 53 | mix(cuda-toygpu-nodeX-tp1-dp1+cuda-toygpu-nodeY-tp1-dp1)-s256-t2048@2f8ade5063d6 | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 54 | mix(cuda-toygpu-nodeX-tp1-dp1+cuda-toygpu-nodeY-tp1-dp1)-s256-t8192@2f8ade5063d6 | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 55 | mix(cuda-toygpu-nodeY-tp1-dp1+cuda-toygpu-nodeZ-tp1-dp1)-s256-t2048@55b485062c0b | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 56 | mix(cuda-toygpu-nodeY-tp1-dp1+cuda-toygpu-nodeZ-tp1-dp1)-s256-t8192@55b485062c0b | aggregated | 1 | 2 | 0.000 | 1.048 | 0.193 | 1.048 | 6.000 | 0.477 | 1.257 | 1.000 | no | no | no | no |
| 57 | pd(cuda-toygpu-nodeX-tp1-dp1 P + cuda-toygpu-nodeY-tp1-dp1 D)-s256-t2048@2f8ade5063d6 | pd_split | 1 | 2 | 0.024 | 1.048 | 0.385 | 1.048 | 6.000 | 0.963 | 1.257 | 1.000 | no | no | no | no |
| 58 | pd(cuda-toygpu-nodeX-tp1-dp1 P + cuda-toygpu-nodeY-tp1-dp1 D)-s256-t8192@2f8ade5063d6 | pd_split | 1 | 2 | 0.024 | 1.048 | 0.385 | 1.048 | 6.000 | 0.963 | 1.257 | 1.000 | no | no | no | no |
| 59 | pd(cuda-toygpu-nodeY-tp1-dp1 P + cuda-toygpu-nodeZ-tp1-dp1 D)-s256-t2048@55b485062c0b | pd_split | 1 | 2 | 0.010 | 1.048 | 0.385 | 1.048 | 6.000 | 0.906 | 1.257 | 1.000 | no | no | no | no |
| 60 | pd(cuda-toygpu-nodeY-tp1-dp1 P + cuda-toygpu-nodeZ-tp1-dp1 D)-s256-t8192@55b485062c0b | pd_split | 1 | 2 | 0.010 | 1.048 | 0.385 | 1.048 | 6.000 | 0.906 | 1.257 | 1.000 | no | no | no | no |

### 2. Residuals, `actual / predicted`

- **ttft**: n=12 p50=506.523 p90=1384.961 max=1384.961
- **tpot**: n=60 p50=1.200 p90=1.200 max=1.200
- **goodput**: n=60 p50=5.188 p90=12.860 max=29.092

### 3. The four that were chosen at k=4

- `cuda-toygpu-nodeX-tp2-dp1-s32-t2048@5dfef3a9a468` (aggregated, tp2, 2 dev, 5.0 $/h): in band 1 because risk 0.525 = max(ttft̂ 0.000, tpot̂ 0.525, goodput̂ 0.085); actually violates TTFT, goodput (ttft 5.820, tpot 0.629, goodput 2.479).
- `cuda-toygpu-nodeX-tp2-dp1-s32-t8192@5dfef3a9a468` (aggregated, tp2, 2 dev, 5.0 $/h): in band 1 because risk 0.525 = max(ttft̂ 0.000, tpot̂ 0.525, goodput̂ 0.085); actually violates TTFT, goodput (ttft 5.820, tpot 0.629, goodput 2.479).
- `cuda-toygpu-nodeY-tp2-dp1-s32-t2048@50a58329ec48` (aggregated, tp2, 2 dev, 5.0 $/h): in band 1 because risk 0.525 = max(ttft̂ 0.000, tpot̂ 0.525, goodput̂ 0.085); actually violates TTFT, goodput (ttft 5.820, tpot 0.629, goodput 2.479).
- `cuda-toygpu-nodeY-tp2-dp1-s32-t8192@50a58329ec48` (aggregated, tp2, 2 dev, 5.0 $/h): in band 1 because risk 0.525 = max(ttft̂ 0.000, tpot̂ 0.525, goodput̂ 0.085); actually violates TTFT, goodput (ttft 5.820, tpot 0.629, goodput 2.479).

### 4. Hypotheses, in numbers

**H-a — TTFT estimate has no prefill compute and no queueing.** 28 representatives miss the TTFT; 4 of them were ranked comfortable. Among violators the ranker's `ttft_ratio` is n=28 p50=0.000 p90=0.024 max=0.024 while the actual is n=28 p50=10.840 p90=13.286 max=13.343. The transfer term the ranker does have accounts for this share of the actual p99 TTFT: n=60 p50=0.000 p90=0.002 max=0.025; a single prefill roofline pass (weights once + p50 prompt KV) would account for n=60 p50=0.023 p90=0.044 max=0.044. `GreedyEstimate` carries no prefill field -- `roofline_tpot_ms` is decode-only by design -- so the term would have to be computed from `memutil` as this script does.

**H-b — `goodput_ratio` is inert.** Over all ranked representatives it is n=60 p50=0.193 p90=0.385 max=0.385; 0 are above 1. 28 representatives actually miss the demanded goodput; their `goodput_ratio` is n=28 p50=0.385 p90=0.385 max=0.385 against an actual n=28 p50=2.479 p90=4.957 max=4.957. Which term is binding (`== risk_proxy`): ttft 0, tpot 60, goodput 0.

**H-c — the band is sorted by cost, so the marginal ones lead.** Band 1 has 12 members, 8 actually feasible; its `risk_proxy` is n=12 p50=0.525 p90=0.526 max=0.526 -- feasible members n=8 p50=0.525 p90=0.526 max=0.526, infeasible members n=4 p50=0.525 p90=0.525 max=0.525. The four chosen have risk [0.525, 0.525, 0.525, 0.525] and cost [5.0, 5.0, 5.0, 5.0]; they are the cheapest in the band: yes. The first actually-feasible band-1 member sits at rank 5.

**Diversity.** Plain top-4 contains 0 feasible; with `DiversityQuota()` the top-4 contains 0 feasible. (`cuda-toygpu-nodeX-tp2-dp1-s32-t2048@5dfef3a9a468, cuda-toygpu-nodeX-tp2-dp1-s32-t8192@5dfef3a9a468, cuda-toygpu-nodeX-tp1-dp1-s32-t2048@7d36012c2000, mix(cuda-toygpu-nodeX-tp1-dp1+cuda-toygpu-nodeY-tp1-dp1)-s32-t2048@2f8ade5063d6`)

### 5. Conclusion

**H-b is supported, and it is the cause.** Every false positive is a `max_num_seqs=32` placement whose `s128`/`s256` siblings on the same devices are feasible. The ceiling `goodput_ratio` divides by admits as many sequences as the KV cache holds and never reads the knob, so it reads the same 0.525-band risk for both; the mock, like an engine, stops at 32, utilisation goes to 2.479 of capacity and queueing drives the TTFT to 10.840x the SLO. Re-scoring the same rows with the knob-aware `greedy.estimate` throughput as the denominator (`service_margin`) gives a confusion matrix of tp=8 fp=0 fn=0 tn=52: the 4 flipped rows are exactly the false positives (ceiling → estimate → actual: 0.085 → 2.066 → 2.479; 0.085 → 2.066 → 2.479), and the goodput residual `actual/predicted` falls from n=60 p50=5.188 p90=12.860 max=29.092 to n=60 p50=1.933 p90=3.866 max=3.866.

**H-a's premise is true and its remedy is immaterial.** The TTFT estimate is 0 for every non-P/D placement against an actual of up to 13.3x, but a prefill roofline pass covers at most 4.4 % of that TTFT; the rest is queueing, which is utilisation, which is H-b's term. Adding the prefill term alone changes 0 verdicts. It is added anyway -- same physics as the bound, and better than the zero it replaces -- and recorded in `RankFeatures.basis`.

**H-c is not supported.** Inside band 1 the feasible and infeasible members have the same `risk_proxy` to three decimals (n=8 p50=0.525 p90=0.526 max=0.526 vs n=4 p50=0.525 p90=0.525 max=0.525) and the same cost; there is no margin gradient a δ-tier could sort on, so no two-stage sort is introduced. Diversity does not help either (0 → 0 feasible in the top four): the quota spreads over structures, and the misclassification is inside one.

## Reproducing

```bash
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
python experiments/scripts/e_g2_ranker_diagnosis.py \
    --out experiments/results/e_g2_ranker_diagnosis.md
```
