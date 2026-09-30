# Inter-node P/D disaggregation: what blocks it here, and what else exists

Written because the paper said, at `conclusion.tex`, that the inter-node case
"needs a disaggregation path that does not yet exist". That is wrong, and this
note is the correction plus the evidence for it. The sentence at
`limits.tex:74` --- "the deployment backend builds a configuration for a single
aggregated engine" --- was already right and does not change.

Two kinds of statement appear below and are kept apart on purpose. **Measured
here** means a command was run on `s8` or `s6` and its output is in
`experiments/pd_probe/raw/`. **Reported** means a survey of published
documentation, which is evidence about what other people have written, not
about this hardware.

## Measured here: vLLM does it, and did it

vLLM 0.19.0, as installed in `/home/swsok/heteropilot/.venv-vllm`, carries the
whole mechanism: `--kv-transfer-config` parses from argv, `kv_role` takes
`kv_producer` / `kv_consumer` / `kv_both`, and the registry holds
`NixlConnector`, `LMCacheConnectorV1`, `MooncakeConnector`, `MultiConnector`
and `OffloadingConnector`.

It was run. Prefill on `s8` GPU 0, decode on GPU 1, NIXL between them: the
prefill instance handed back fourteen KV block ids with its engine id, side
channel host and port, and the decode instance pulled them and produced the
completion. `experiments/pd_probe/raw/vllm_pd/`.

The transport was measured separately across the two machines: a CUDA buffer
moved from `s8:cuda:0` to `s6:cuda:0` at 77.90 Gbit/s over `rc_mlx5/mlx5_0:1`,
byte content verified, which is 87.9 % of E-G4's `ib_send_bw` single-stream
median on the same pair. `experiments/pd_probe/raw/nixl/`.

### The disaggregated answer is not the aggregated answer

Greedy, prefix caching off on both, three prompts: two identical, one diverging
after 57 of 66 characters --- and reproducibly so, while two *aggregated*
engines on different GPUs agree exactly and each is repeatable. The difference
is the hand-off. The raw file has the controls; the point for planning is that
a P/D arm and an aggregated arm do not produce the same token stream, so a
comparison between them has to say so rather than assume it away.

## Measured here: what actually blocks it is this repository's own dependency

`planner/deploy/vllm_cuda.py` declares four boundaries:

| line | refuses | inter-node P/D hits it |
| --- | --- | --- |
| 204 | `assignment.role is not Role.AGGREGATED` | yes |
| 272 | `host != "local"` | yes, for the second node |
| 280 | `len(plan.candidate.assignments) != 1`, "needs a router" | yes, always |
| 287 | `dp_replicas != 1 or pp_size != 1` | no |

`Role.PREFILL` and `Role.DECODE` already exist in `planner/plan.py` and map one
to one onto `kv_producer` / `kv_consumer`. The first two are small. The third
is the real one and heteropilot names it itself: **there is no router in the
deploy layer.** `RoutingPolicy` is used by the planner and the simulator and by
nothing under `planner/deploy/`. The probe above worked around it by making the
two HTTP calls by hand.

The simulator arm is not affected. `planner/predictor/llmservingsim.py` emits
`pd_type` per instance and `num_nodes` from the island structure, and P1.5
found P/D candidates among the E-G3 runs. Inter-node P/D is missing from the
**hardware** arm only.

## Measured here: which connector this environment can actually take

| connector | what it costs this venv | verdict |
| --- | --- | --- |
| `NixlConnector` | `nixl==0.9.0` + `nixl-cu12==0.9.0`, two packages, no version changes | **used, and it works** |
| `MooncakeConnector` | `mooncake-transfer-engine` + `msgpack`, two packages, no version changes | untried, but installable |
| `P2pNcclConnector` | `msgpack` only | untried, but installable |
| `LMCacheConnectorV1` | torch 2.10 to 2.14, transformers 4.57 to 5.17, triton 3.6 to 3.8 | **refused**: it rebuilds the environment that was matched to `s6` |

### Pin `nixl` to 0.9.0, and the reason is not the one you would guess

`nixl` 1.4.1 and 1.3.2 both ship a `nixl_ep` package holding MoE all-to-all
binaries for torch 2.11, 2.12 and 2.13. This environment is torch 2.10. vLLM's
`has_nixl_ep()` is `find_spec("nixl_ep") is not None`, which sees the directory
and cannot see the missing binary, and the import guarded by it at
`fused_moe/all2all_utils.py:46` is unconditional. So installing either version
**stops vLLM starting at all**, on a dense model with no MoE layer, through
`kernel_warmup -> fp8 -> fused_moe/oracle`. `nixl==0.9.0` has no `nixl_ep` at
all and needs no workaround.

The wheel links `libssl.so.3` and Ubuntu 20.04 ships OpenSSL 1.1.1, so a copy
of OpenSSL 3 has to be on `LD_LIBRARY_PATH`; both nodes carry one under
`/opt/nvidia/nsight-compute/`. Setting `UCX_TLS` by hand breaks agent
construction, because intra-agent setup needs transports a hand-written list
omits; leaving it unset lets UCX pick `rc_mlx5` itself, which it does.

## Reported: the landscape, from a documentation survey

Not verified on this hardware. Cross-node P/D is documented by vLLM itself
(NixlConnector, MooncakeConnector and P2pNcclConnector each with a multi-machine
example), NVIDIA Dynamo, Mooncake, SGLang, TensorRT-LLM, llm-d, Ray Serve LLM
and AIBrix. The one entry where "not available" is closer to true is
**DistServe**, whose README mentions only generic Ray multi-node and neither
claims nor demonstrates cross-node P/D.

Three reported caveats are worth carrying because they are checkable and two of
them were checked:

- vLLM still labels disaggregated prefilling experimental, and its own
  documentation says it does not improve throughput --- it separates TTFT from
  ITL. Not verified here.
- vLLM's NIXL integration test launches two GPUs on **one** machine, so the
  cross-node path is documented but not covered upstream by CI. Not verified
  here, and it is the most useful caveat for a paper.
- 0.19's `NixlConnector` is pull-only. **Verified here**: the only transfer in
  `nixl_connector.py` is `make_prepped_xfer("READ", ...)`, and no
  `NixlPushConnector` or `NixlPullConnector` exists in this version.

## What this means for the paper

Not "no path exists". The defensible claims, in order of strength:

1. **No stack exposes P/D placement as a searchable design space.** Placement
   is operator-specified everywhere --- which is this paper's thesis, stated
   about the one case where the gap is widest, and it survives every stack in
   the table above.
2. vLLM's cross-node P/D is documented but not covered by upstream CI, so its
   cross-node behaviour is reported rather than validated.
3. The hardware arm of this campaign does not run it because the deployment
   layer this work extends has no router, not because the serving stack cannot.

Recorded as GS-28.
