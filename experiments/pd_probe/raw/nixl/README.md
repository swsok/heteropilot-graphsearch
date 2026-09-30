# NIXL inter-node GPU-to-GPU probe

**REAL HARDWARE.** Two nodes, `s8` (initiator) and `s6` (target), one mlx5_0
each on the same InfiniBand subnet. One 256 MiB buffer on `cuda:0` at each end,
registered with NIXL 1.4.1 and written across with `initialize_xfer("WRITE")`.
Not a benchmark of vLLM: a check that the transport vLLM's `NixlConnector`
would use is present, selects the IB path, and moves bytes between the two
GPUs the search would place a prefill and a decode instance on.

The scripts are `../../nixl_target.py` and `../../nixl_bw.py`. They are probes
rather than harness, and are kept so the numbers below can be reproduced, not
because anything else calls them.

## What the transport chose

UCX 1.22.0 (bundled in the `nixl` wheel), with `UCX_NET_DEVICES=mlx5_0:1`:

```
ucp_context_0 self cfg#1  rma(rc_mlx5/mlx5_0:1)  amo(rc_mlx5/mlx5_0:1)
                          am(rc_mlx5/mlx5_0:1 cma/memory)  ka(ud_mlx5/mlx5_0:1)
```

`rc_mlx5` is accelerated mlx5 RDMA, so the path is the IB fabric and not a TCP
fallback. The `ucx_utils.cpp:635` warning that "accelerated IB support was not
found" refers to GPUDirect Async (GDAKI), which the same log explains needs an
active primary CUDA context; it is not a statement about the RDMA path.

## Correctness

8 MiB of `0x07` written from `s8:cuda:0` into a zeroed `s6:cuda:0`; the target
summed its own buffer and got 58,720,256, which is 8388608 x 7 exactly.

## Bandwidth

Median of 30 transfers after 5 warmup, one flow, `WRITE`, VRAM to VRAM. The
left column is `nixl==0.9.0`, which is the version this repository pins and the
one to read; the right is 1.4.1, run first, kept so that the agreement between
them is on the record rather than asserted.

| bytes | Gbit/s (0.9.0) | Gbit/s (1.4.1) |
| --- | --- | --- |
| 1 Mi | 71.28 | 72.10 |
| 4 Mi | 76.95 | 77.73 |
| 16 Mi | 77.65 | 78.44 |
| 64 Mi | 77.78 | 78.52 |
| 256 Mi | 77.90 | 78.56 |

Saturates from 16 MiB up. The two versions differ by under a percent at every
size, so nothing here turns on which is installed. E-G4's `ib_send_bw`
single-stream median on the same pair is 88.61 Gbit/s, so this reaches 87.9 %
of it. The gap is the difference in what is being read and written -- host
memory there, device memory across PCIe here -- and is reported as the gap
rather than explained away.

## What this does not establish

That vLLM serves across the two nodes. It establishes that NIXL is installable
here, that it selects the IB path, and that GPU-to-GPU RDMA between `s8` and
`s6` works. Everything above the transport is untested.

## Installation, which is not free of traps

`uv pip install nixl==0.9.0 nixl-cu12==0.9.0` adds two packages and changes no
existing version. Do not take a later one: 1.3.2 and 1.4.1 ship a `nixl_ep`
package that stops vLLM starting at all on torch 2.10, for the reason in
`docs/inter_node_pd_options.md`.
The wheel links `libssl.so.3`; Ubuntu 20.04 ships OpenSSL 1.1.1, so the import
fails until a copy of OpenSSL 3 is on `LD_LIBRARY_PATH`. Both nodes happen to
carry one under `/opt/nvidia/nsight-compute/2024.3.2/host/linux-desktop-glibc_2_11_3-x64`.
Setting `UCX_TLS=rc_mlx5,cuda_copy,self` breaks agent construction with
`NIXL_ERR_BACKEND`, because intra-agent setup needs transports the list
excludes; leaving `UCX_TLS` unset lets UCX pick `rc_mlx5` on its own.
