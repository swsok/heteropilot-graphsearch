# P/D probe

Not an experiment in the `E-G*` series. These are the checks that settled one
question the paper had answered the wrong way round: whether a disaggregation
path exists for the inter-node case. `docs/inter_node_pd_options.md` is the
write-up and `docs/decisions.md` GS-28 is the decision.

Two probes, both **REAL HARDWARE**, both recorded under `raw/`:

- `raw/nixl/` --- NIXL agent to NIXL agent, `s8:cuda:0` to `s6:cuda:0`, over
  InfiniBand. Run with `nixl_target.py` on the far node and `nixl_bw.py` on the
  near one. Answers whether the transport exists and how fast it is.
- `raw/vllm_pd/` --- vLLM prefill instance to vLLM decode instance, one node,
  two GPUs. `pd_client.py` does by hand what a router would do; `pd_equiv.py`
  asks whether the disaggregated answer equals the aggregated one, and
  `pd_control.py` is the control that says the answer is not about GPUs.

Both need `nixl==0.9.0` and `nixl-cu12==0.9.0` --- not a later one, for the
reason in the write-up --- and a copy of OpenSSL 3 on `LD_LIBRARY_PATH`.
