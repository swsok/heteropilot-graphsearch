# vLLM prefill/decode disaggregation, one node, two GPUs

**REAL HARDWARE.** `s8`, `NousResearch/Meta-Llama-3.1-8B`, vLLM 0.19.0. Prefill
instance on GPU 0 (`kv_role: kv_producer`, side channel port 5600), decode
instance on GPU 1 (`kv_role: kv_consumer`, port 5700), both
`--kv-transfer-config '{"kv_connector":"NixlConnector", ...}'`,
`--max-model-len 4096`, `--gpu-memory-utilization 0.6`.

This is a probe of the serving stack, not an experiment about placement. It
exists to settle one question the paper had answered the other way: whether a
disaggregation path exists at all.

## There is no router, so the two calls were made by hand

`planner/deploy/` has none, and neither does the installed vLLM wheel. The
probe therefore does what a router would: POST to the prefill instance with
`max_tokens: 1` and `kv_transfer_params: {"do_remote_decode": true}`, take the
`kv_transfer_params` it returns, and POST the real request to the decode
instance with that dict verbatim. The dict already carries
`do_remote_prefill: true`, so the proxy adds nothing.

What came back from the prefill instance:

```
do_remote_decode  false
do_remote_prefill true
remote_block_ids  [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15]]
remote_engine_id  561f5bba-c7de-4fc5-a58f-cce846c483f1
remote_host       192.168.210.108
remote_port       5600
remote_request_id cmpl-b4a7807f1f498c84-0-8d0596ed
```

Fourteen KV blocks, named by id, pulled by the decode instance over NIXL. The
decode instance then produced the completion.

## One trap, which cost a wrong conclusion before it was caught

`nixl` 1.4.1 ships a `nixl_ep` package holding MoE all-to-all binaries built
for torch 2.11, 2.12 and 2.13. This environment is on torch 2.10. vLLM's
`has_nixl_ep()` is `find_spec("nixl_ep") is not None`, a presence check that
cannot see the missing binary, and the import at
`fused_moe/all2all_utils.py:46` is unconditional inside that guard. So
**installing nixl stops vLLM from starting at all**, on a dense model that has
no MoE layer, with `ModuleNotFoundError: nixl_ep_cpp_torch210` raised through
`kernel_warmup -> fp8 -> fused_moe/oracle`. nixl 1.3.2 ships the same three
binaries and does not help. Renaming the three `nixl_ep*` directories out of
the way clears it and costs nothing here, because nothing in this campaign
serves an MoE model.

## The disaggregated answer is not the aggregated answer, and that is measured

Greedy decoding (`temperature: 0.0`), `max_tokens: 24`, three prompts,
`--no-enable-prefix-caching` on both instances so that cache state cannot be
the explanation. "Aggregated" is the decode instance serving the whole request
itself, with no hand-off.

| prompt | aggregated == disaggregated |
| --- | --- |
| `InfiniBand differs from Ethernet in three ways. First,` | same |
| `The capital of France is Paris, and the capital of Japan is` | same |
| `def fibonacci(n): ... return` | **differs** |

On the third it agrees for 57 of 66 characters and then takes a different
branch:

```
aggregated     ... def fibonacci2(n):\n    a, b = 0,
disaggregated  ... def fibonacci2(n):\n    if n <= 1:\n
```

Two controls, run under the same configuration, say this is not noise:

- the same engine asked twice gives the same answer: **yes**;
- two *aggregated* engines on **different GPUs** give the same answer: **yes**;
- the disaggregated path over three repetitions gives the same answer: **yes**.

So the difference is attributable to the hand-off itself, it is deterministic,
and it is not a GPU-to-GPU effect. The KV computed on the producer --- which
ran that request with `max_tokens: 1`, so under a different batch shape --- is
close enough to agree for most of a completion and not close enough to be the
same tensor. A near-tie in the logits then decides differently.

This is recorded as a property of the path, not as a defect. It does mean that
a P/D arm of E-G5 measures latency under a serving configuration whose token
stream is not identical to the aggregated arm's, and any comparison between
them has to say so.

## First failed attempt, kept because it was wrong in an instructive way

The first equivalence run left prefix caching at its default, and the
aggregated answer to the third prompt changed between two runs of the harness
(`a, b = 0,` cold, `if n <= 1:` once three disaggregated requests had warmed
the cache). Read alone, that run said disaggregation matched. It did not: the
aggregated baseline had moved. The confound is why both instances are now
started with `--no-enable-prefix-caching`, which is the knob heteropilot gained
in D127.

## The divergence is not a NIXL version artefact

Everything above was first run under `nixl` 1.4.1 with its `nixl_ep`
directories renamed out of the way, and then again under `nixl==0.9.0`, which
needs no workaround. Both give the same three rows, the same divergence on the
same prompt at the same point, and the same clean controls. The version that
should be used is 0.9.0, for the reason in `docs/inter_node_pd_options.md`;
the finding does not depend on which one is installed.
