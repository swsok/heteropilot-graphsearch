# vLLM prefill/decode disaggregation, two nodes

**REAL HARDWARE.** Prefill on `s8` GPU 0 (`kv_role: kv_producer`, side channel
`192.168.210.108:5600`), decode on `s6` GPU 0 (`kv_role: kv_consumer`, side
channel `192.168.210.106:5700`), `NixlConnector` between them over the
InfiniBand subnet. `NousResearch/Meta-Llama-3.1-8B`, vLLM 0.19.0,
`nixl==0.9.0` on both, `--max-model-len 4096`,
`--gpu-memory-utilization 0.6`, `--no-enable-prefix-caching` on both.

The same probe as `../vllm_pd/`, with the decode instance on the other
machine. Still no router: `pd_client.py` makes the two HTTP calls by hand.

## It works

Fourteen KV blocks, named by id, handed from `s8` and pulled by `s6` across the
fabric; the decode instance produced the completion.

```
do_remote_prefill true    remote_host 192.168.210.108
remote_block_ids  [[107 .. 120]]    remote_port 5600
remote_engine_id  bc04f108-18c7-4d3f-a3d5-4a4daa9192df
```

Latency, five repetitions after the first:

| | seconds |
| --- | --- |
| prefill call (`max_tokens: 1`) | 0.058 |
| decode call (24 tokens, includes the KV pull) | 0.917 |

The first call of a fresh pair was 0.109 and 1.350; it is reported separately
rather than folded into the median, because one cold sample is not the same
measurement.

## The divergence is worse across nodes, and that is the new number

Same three prompts, same greedy settings, same controls as `../vllm_pd/`:

| prompt | one node | two nodes |
| --- | --- | --- |
| `InfiniBand differs from Ethernet in three ways. First,` | same | **differs** |
| `The capital of France is Paris, and the capital of Japan is` | same | same |
| `def fibonacci(n): ... return` | differs | differs |

Three repetitions of the whole set give the same three rows every time. The
first prompt diverges on a word:

```
aggregated     ... it is a switched fabric, not a bus. Second, ...
disaggregated  ... it is a switched fabric, not a shared bus. Second, ...
```

The control is what makes this readable. Two **aggregated** engines --- one on
`s8`, one on `s6`, different machines --- give the same answer to the prompt
that the disaggregated path gets wrong, and each is repeatable on its own. So
the machine is not the variable and neither is run-to-run noise: the variable
is the hand-off, and it perturbs more across the fabric than it did across a
PCIe bus.

What is **not** claimed here is a mechanism. The measurement says the
disaggregated token stream differs from the aggregated one on two of three
prompts inter-node and one of three intra-node, deterministically. Why the
inter-node path perturbs more is not established by these runs, and the
obvious candidates --- a different prefill batch shape, a different block
layout, the transfer itself --- are not distinguished by anything measured.

## The trap, reproduced independently on the second machine

`s6` was first brought up with `nixl==1.4.1` and its engine refused to start
with `ModuleNotFoundError: No module named 'nixl_ep_cu12.nixl_ep_cpp_torch210'`
through exactly the import chain recorded in `../vllm_pd/`:
`kernel_warmup -> fp8 -> fused_moe/oracle -> all2all_utils -> nixl_ep`. Pinning
`s6` to 0.9.0 and removing the `nixl_ep*` directories cleared it. The two
machines were configured hours apart and failed identically, which is the
closest thing to a replication this note has.
