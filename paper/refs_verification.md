# refs.bib verification (R2.1)

Checked 2026-10-02. Methods: Crossref REST API (`api.crossref.org/works/<doi>` or bibliographic query), arXiv API (`export.arxiv.org/api/query?id_list=`), and WebFetch of the publisher page. Author lists are copied from the source named in the "source" column. Where the conference version and the arXiv version disagree, the venue version wins (noted). dblp could not be used: its API sits behind a bot challenge from this host.

Test build: `tectonic` with `IEEEtran.cls` + `IEEEtran.bst`, `\nocite{*}`: 39 `\bibitem`s, no BibTeX errors. Keys are unique and braces balance.

## Confirmed (36 papers + 2 software + 1 placeholder)

| key | title | venue/year | DOI or arXiv | source checked | notes |
|---|---|---|---|---|---|
| helix | Helix: Serving Large Language Models over Heterogeneous GPUs and Network via Max-Flow | ASPLOS 2025 | 10.1145/3669940.3707215; arXiv:2406.01566 | Crossref; arxiv.org/abs/2406.01566 | |
| thunderserve | ThunderServe: High-performance and Cost-efficient LLM Serving in Cloud Environments | MLSys 2025 (Proc. MLSys 7) | arXiv:2502.09334 | proceedings.mlsys.org/paper_files/paper/2025/hash/c2a0e26dd9ee7d57e92bb1c24b39659a-Abstract-Conference.html | MLSys has no DOI |
| shuntserve | ShuntServe: Cost-efficient LLM serving on heterogeneous spot GPU clusters | Future Generation Computer Systems 186, 2027 | 10.1016/j.future.2026.108760 | Crossref | Journal volume dated 2027 (online 2026). Only "ShuntServe" publication found; confirm it is the one intended |
| distserve | DistServe: Disaggregating Prefill and Decoding for Goodput-optimized LLM Serving | OSDI 2024, pp. 193-210 | arXiv:2401.09670 | usenix.org/conference/osdi24/presentation/zhong-yinmin | USENIX: no DOI |
| splitwise | Splitwise: Efficient Generative LLM Inference Using Phase Splitting | ISCA 2024 | 10.1109/ISCA59077.2024.00019; arXiv:2311.18677 | Crossref | An IEEE Micro 2025 version (10.1109/MM.2025.3575361, adds R. Fonseca) also exists; not included |
| mooncake | Mooncake: Trading More Storage for Less Computation -- A KVCache-centric Architecture for Serving LLM Chatbot | FAST 2025, pp. 155-170 | arXiv:2407.00079 | usenix.org/conference/fast25/presentation/qin; arXiv API | FAST title and author list (9) differ from the arXiv v4 ("Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving", 7 authors); FAST version used |
| vidur | Vidur: A Large-Scale Simulation Framework for LLM Inference | MLSys 2024 (Proc. MLSys 6) | arXiv:2405.05465 | proceedings.mlsys.org/.../b74a8de47d2b3c928360e0a011f48351-Abstract-Conference.html | MLSys author order (Ramjee before Tumanov) differs from arXiv; MLSys order used |
| llmservingsim | LLMServingSim: A HW/SW Co-Simulation Infrastructure for LLM Inference Serving at Scale | IISWC 2024 | 10.1109/IISWC63097.2024.00012; arXiv:2408.05499 | Crossref; arXiv API | |
| llmservingsim2 | LLMServingSim 2.0: A Unified Simulator for Heterogeneous and Disaggregated LLM Serving Infrastructure | ISPASS 2026 | 10.1109/ISPASS69572.2026.00012 | Crossref | Separate publication from 1.0. Pages "1-14" as Crossref gives them |
| llmservingsim2cal | LLMServingSim2.0: A Unified Simulator for Heterogeneous Hardware and Serving Techniques in LLM Infrastructure | IEEE CAL 24(2), 2025 | 10.1109/LCA.2025.3628325 | Crossref | Earlier 4-page letter of 2.0 (3 authors). Cite one or both; likely `llmservingsim2` alone |
| frontier | Frontier: Simulating the Next Generation of LLM Inference Systems | arXiv 2025 | arXiv:2508.03148 | arXiv API | No venue found |
| frontier2 | Frontier: Towards Comprehensive and Accurate LLM Inference Simulation | arXiv 2026 | arXiv:2605.21312 | arXiv API | Later, longer Frontier paper (different 3rd author). Choose one |
| astrasim | ASTRA-SIM: Enabling SW/HW Co-Design Exploration for Distributed DL Training Platforms | ISPASS 2020 | 10.1109/ISPASS48437.2020.00018 | Crossref | |
| astrasim2 | ASTRA-sim2.0: Modeling Hierarchical Networks and Disaggregated Systems for Large-model Training at Scale | ISPASS 2023 | 10.1109/ISPASS57527.2023.00035; arXiv:2303.14006 | Crossref; arXiv API | |
| chakra | Chakra: Advancing Performance Benchmarking and Co-design using Standardized Execution Traces | arXiv 2023 | arXiv:2305.14516 | arXiv API | No peer-reviewed venue found; cited as preprint |
| themis | Themis: A Network Bandwidth-Aware Collective Scheduling Policy for Distributed Training of DL Models | ISCA 2022 | 10.1145/3470496.3527382; arXiv:2110.04478 | Crossref; arXiv API | Crossref title is just "Themis"; full title from arXiv |
| vllm | Efficient Memory Management for Large Language Model Serving with PagedAttention | SOSP 2023 | 10.1145/3600006.3613165; arXiv:2309.06180 | Crossref | |
| sarathiserve | Taming Throughput-Latency Tradeoff in LLM Inference with Sarathi-Serve | OSDI 2024, pp. 117-134 | arXiv:2403.02310 | usenix.org/conference/osdi24/presentation/agrawal | |
| llumnix | Llumnix: Dynamic Scheduling for Large Language Model Serving | OSDI 2024, pp. 173-191 | arXiv:2406.03243 | usenix.org/conference/osdi24/presentation/sun-biao | |
| melange | Mélange: Cost Efficient Large Language Model Serving by Exploiting GPU Heterogeneity | arXiv 2024 | arXiv:2404.14527 | arXiv API | No venue found in search; cited as preprint |
| hexgen | HexGen: Generative Inference of Large Language Model over Heterogeneous Environment | ICML 2024, PMLR 235:21946-21961 | arXiv:2311.11514 | proceedings.mlr.press/v235/jiang24f.html (via search) ; arXiv API | |
| alpa | Alpa: Automating Inter- and Intra-Operator Parallelism for Distributed Deep Learning | OSDI 2022, pp. 559-578 | arXiv:2201.12023 | usenix.org/conference/osdi22/presentation/zheng-lianmin | 12 authors, all listed |
| galvatron | Galvatron: Efficient Transformer Training over Multiple GPUs Using Automatic Parallelism | PVLDB 16(3), 2022 | 10.14778/3570690.3570697; arXiv:2211.13878 | Crossref; arXiv API | Crossref issue year 2022 (arXiv says "VLDB 2023") |
| wlkernel | Weisfeiler-Lehman Graph Kernels | JMLR 12:2539-2561, 2011 | **none exists** (JMLR issues no DOIs) | jmlr.org/papers/v12/shervashidze11a.html | Exception to the DOI/arXiv rule: confirmed on publisher page, cited with URL |
| vf2 | A (Sub)Graph Isomorphism Algorithm for Matching Large Graphs | IEEE TPAMI 26(10), 2004 | 10.1109/TPAMI.2004.75 | Crossref | Authors as initials, as Crossref gives them |
| networkx | Exploring Network Structure, Dynamics, and Function using NetworkX | SciPy 2008, pp. 11-15 | **none exists** | osti.gov/biblio/960616; scienceopen.com record | Exception to the DOI/arXiv rule; cited with OSTI URL |
| kleinrock1967 | Time-shared Systems: A Theoretical Treatment | J. ACM 14(2):242-261, 1967 | 10.1145/321386.321388 | Crossref (title + subtitle fields) | |
| massoulie1999 | Bandwidth Sharing: Objectives and Algorithms | IEEE INFOCOM 1999, vol. 3, pp. 1395-1403 | 10.1109/INFCOM.1999.752159 | Crossref | The DOI ...752178 I first tried is a different paper (Mo et al.). Journal version: IEEE/ACM ToN 10(3), 2002, 10.1109/TNET.2002.1012364, not included |
| nosek2018 | The Preregistration Revolution | PNAS 115(11):2600-2606, 2018 | 10.1073/pnas.1708274114 | Crossref | |
| orca | Orca: A Distributed Serving System for Transformer-Based Generative Models | OSDI 2022, pp. 521-538 | **none exists** (no DOI, no arXiv) | usenix.org/conference/osdi22/presentation/yu | Exception: confirmed on USENIX page, cited with URL. Drop if the rule must be literal |
| flexgen | FlexGen: High-Throughput Generative Inference of LLMs with a Single GPU | ICML 2023, PMLR 202:31094-31116 | arXiv:2303.06865 | proceedings.mlr.press/v202/sheng23a.html | PMLR lists 10 authors; arXiv lists 14. PMLR list used |
| deepspeedinference | DeepSpeed-Inference: Enabling Efficient Inference of Transformer Models at Unprecedented Scale | SC22 | 10.1109/SC41404.2022.00051; arXiv:2207.00032 | Crossref | SC author order differs from arXiv; Crossref (SC) order used |
| alpaserve | AlpaServe: Statistical Multiplexing with Model Parallelism for Deep Learning Serving | OSDI 2023, pp. 663-679 | arXiv:2302.11665 | usenix.org/conference/osdi23/presentation/li-zhouhan | |
| tetriinfer | Inference without Interference: Disaggregate LLM Inference for Mixed Downstream Workloads | arXiv 2024 | arXiv:2401.11181 | arXiv API | Preprint (TetriInfer) |
| spotserve | SpotServe: Serving Generative Large Language Models on Preemptible Instances | ASPLOS 2024 | 10.1145/3620665.3640411; arXiv:2311.15566 | Crossref | |
| megatron | Megatron-LM: Training Multi-Billion Parameter Language Models Using Model Parallelism | arXiv 2019 | arXiv:1909.08053 | arXiv API | |
| dynamo | NVIDIA Dynamo: A Datacenter Scale Distributed Inference Serving Framework | software, 2025 | n/a (**software**) | github.com/ai-dynamo/dynamo (via search) | @misc, accessed 2026-10-02. year=2025 is the public release year; verify if it matters |
| nixl | NIXL: NVIDIA Inference Xfer Library | software, 2025 | n/a (**software**) | github.com/ai-dynamo/nixl (via search) | @misc, accessed 2026-10-02; same year caveat |
| heteropilot | HeteroPilot: Planning LLM Serving on Heterogeneous Clusters | -- | -- | -- | **PLACEHOLDER, not verified**: title provisional, author "Anonymous", arXiv number pending |

Count: 36 confirmed papers with a DOI or arXiv id, of which 3 (`wlkernel`, `networkx`, `orca`) have neither because none exists and are confirmed on the publisher page instead; plus 2 software entries and 1 placeholder. 39 entries in all.

## UNCONFIRMED

None. Every required item and every optional item that was tried was confirmed.

## Choices for the paper author

- Frontier: two arXiv papers (`frontier` 2025, `frontier2` 2026). Pick the one the text means.
- LLMServingSim 2.0: ISPASS 2026 paper (`llmservingsim2`) and an earlier CAL letter (`llmservingsim2cal`).
- Processor sharing: both Kleinrock 1967 and Massoulié & Roberts 1999 are included.
- ShuntServe: the only publication found is the FGCS journal article; check it is the one meant.
