# R5.0 — path probes between the A40 node and the two A5000 nodes

**REAL HARDWARE.** Revision step R5.0 (`WORK_ORDER_revision.md`). These probes
had to decide **which KV path E-G8 can use** before its registration (row 11)
is written. They are probes, not the experiment. Nothing here is a
prediction or a verdict. Every raw file is under `../raw/` or
`../../microbench/raw/`, with `nvidia-smi` occupancy before and after each run
where a GPU was used. Every run that used a GPU found no other process on any
GPU, before or after.

Nodes: `s8` (A40, ConnectX-6 `mlx5_0`), `a5000-1` and `a5000-2` (2 x RTX A5000
each, ConnectX-5 `mlx5_1`), one InfiniBand EDR fabric. Node details and the
BAR1 history are in `docs/nodes/a5000.md`. Model:
`meta-llama/Llama-3.1-8B` at revision `d04e592`, the same four shards on all
three nodes (sha256 prefixes `f8b9704a c28b25e7 d8e9504d e4486f35`). These
shards are byte-identical to `NousResearch/Meta-Llama-3.1-8B`, which E-G5
served. vLLM 0.19.0, `nixl==0.9.0`/`nixl-cu12==0.9.0`, torch 2.10.0+cu128 on
all three nodes; on the A5000s these are in `~/.venv-eg8`.

## Scripts (this directory)

| script | what it runs |
| --- | --- |
| `nixl_pair.sh <n> <s8-to-a5k\|a5k-to-s8> <out>` | `../nixl_target.py` on the receiving node and `../nixl_bw.py` on the sending node, with `UCX_PROTO_INFO=y` on the sender. `NBYTES` sets the buffer size (default 256 MiB) |
| `decode_probe.sh <n> <out> [util]` | one vLLM decode instance (`kv_consumer`, `NixlConnector`) alone on `a5000-<n>` GPU 0. `CFG` overrides the connector config |
| `pd_two_node.sh <n> <D1\|D2> <out>` | a prefill engine and a decode engine on two nodes, then `../pd_client.py` six times. D1 is `s8` prefill to A5000 decode, D2 the reverse. `S8BUF` and `ABUF` (`cuda`/`cpu`) set each end's `kv_buffer_device` |
| `nccl_xnode.sh <n> <rep> <out>` | heteropilot's `link_probe.py`, unmodified, under a two-node `torchrun`: rank 0 on `s8`, rank 1 on the A5000 |

`../../microbench/run_nic.py` gained `--local-ib-dev` and `--peer-ib-dev`.
`ibstat` and `ib_send_bw` otherwise take the first HCA, which on the A5000s is
the uncabled `mlx5_0`.

## Results

### `ib_send_bw`, one stream, host memory (`run_nic.py --condition single`)

Mean of the nine sizes, 1 to 256 MiB:

| direction | `a5000-1` | `a5000-2` |
| --- | --- | --- |
| A5000 -> `s8` | 53.5 Gb/s | 52.6 Gb/s |
| `s8` -> A5000 | 57.3 Gb/s | 58.0 Gb/s |

Files: `microbench/raw/2026-10-09-nic-s8-a5000-<n>/` (A5000 sends) and
`2026-10-09-nic-s8-to-a5000-<n>/` (`s8` sends). Both directions sit below the
EDR line rate, near the PCIe Gen3 x8 slot each A5000 NIC is in. The ~4 Gb/s
asymmetry is reported, not explained.

### NIXL, GPU memory to GPU memory (`raw/nixl-a5000/`)

Median of 30 transfers after 5 warm-up, one flow, `WRITE`, Gbit/s:

| bytes | `s8`->`a5000-1` | `a5000-1`->`s8` | `s8`->`a5000-2` | `a5000-2`->`s8` | `s8`->`a5000-2` (BAR1 32 GB) | `a5000-2`->`s8` (BAR1 32 GB) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Mi | 52.79 | 49.10 | 52.67 | 47.53 | 53.57 | 48.56 |
| 4 Mi | 56.77 | 51.07 | 56.33 | 49.82 | 56.71 | 50.97 |
| 16 Mi | 57.44 | 48.52 | 57.14 | 46.50 | 57.49 | 47.81 |
| 64 Mi | 57.65 | 48.62 | 57.33 | 46.57 | 57.71 | 47.93 |
| 256 Mi | **cannot register** | — | — | — | 57.76 | 47.94 |

The first four columns ran at a 64 MiB buffer (`NBYTES=67108864`) because
**a 256 MiB buffer cannot be registered on an A5000 whose BAR1 is 256 MiB**:
`ibv_reg_mr(... length=268435456) failed: Bad address`
(`raw/nixl-a5000/failed-256MiB/`). The last two columns are `a5000-2` GPU 0
after its BAR1 was resized to 32 GB (`raw/nixl-a5000/rebar32g/`). There UCX
chooses `rc_mlx5/mlx5_1:1` zero-copy "from cuda/GPU0 to cuda/dev[0]". That
is GPUDirect RDMA, with no host bounce.

`TARGET_GOT first_notif_sum` is 58,720,256 (8 MiB of 0x07) in some runs and
29,360,128 in others. The target sums its first 8 MiB at its first
notification, and how far the 1 MiB / 4 MiB transfers have got by then
varies. It is a liveness check, not a byte-exact one.

### vLLM decode alone on an A5000 (`raw/vllm-decode-a5000/`)

`--max-model-len 8192 --gpu-memory-utilization 0.9` (0.6, E-G5's value, leaves
14.4 GB, below the 16 GB of weights):

| `kv_buffer_device` | `a5000-1` | `a5000-2` |
| --- | --- | --- |
| `cuda` (default), BAR1 256 MiB | **engine fails to start**: KV registration, `ibv_reg_mr` of 1,050,673,152 bytes | same |
| `cpu` (host buffer) | starts; KV cache 46,368 tokens, 5.66x concurrency at 8,192 | starts; 46,144 tokens, 5.63x |

### vLLM prefill/decode across two nodes (`raw/vllm_pd_a40_a5000/`)

Six `pd_client.py` calls per pair (32 output tokens). The six completions are
identical within each pair.

| buffers (`s8` / A5000) | pair | result | prefill call | decode call (incl. KV pull) |
| --- | --- | --- | --- | --- |
| `cuda` / `cpu` (files in `failed-mixed-buffers/`) | all four | **fails**: decode-side handshake `NIXL_ERR_NOT_FOUND` in `prep_xfer_dlist`, then HTTP 500 and the engine exits | — | — |
| `cpu` / `cpu` (`*-hostbuf-both`) | D1 `a5000-1` | 6/6 | 0.09–0.14 s | 0.753–0.756 s (first 0.938) |
| | D1 `a5000-2` | 6/6 | 0.08–0.19 s | 0.780–0.787 s (first 0.952) |
| | D2 `a5000-1` | 6/6 | 0.07–0.11 s | 0.927–0.968 s (first 1.093) |
| | D2 `a5000-2` | 6/6 | 0.07–0.09 s | 0.924–0.927 s (first 1.034) |
| `cuda` / `cuda`, `a5000-2` GPU 0 at BAR1 32 GB (`*-gpubuf-rebar32g`) | D1 `a5000-2` | 6/6 | 0.055–0.056 s | 0.772–0.773 s (first 0.938) |
| | D2 `a5000-2` | 6/6 | 0.061–0.063 s | 0.918–0.920 s (first 1.027) |

The first D1 attempt failed for a different reason: `s8`'s
`meta-llama/Llama-3.1-8B` cache held only `README.md` and `LICENSE`. Its logs are kept in
`failed-a40-no-weights/`. The weights were copied from `a5000-2`, and every
run above was made after that.

### NCCL all-reduce across the fabric (`microbench/raw/2026-10-09-nic-collective-s8-a5000-<n>/`)

PREP.md step D, `xnode-a40-a5000`. World 2, one rank per node, 10 runs each.
`NCCL_IB_HCA` is `mlx5_0` on `s8` and `mlx5_1` on the A5000. Rank 1 runs with
`CUDA_VISIBLE_DEVICES=1,0` because `link_probe.py` binds `cuda:{rank}`, which
puts it on physical GPU 0. The first `a5000-2` attempt, without that, failed
with "invalid device ordinal" (`failed-device-ordinal/`).

| pair | busbw at 64 MiB, GB/s: median (min–max) of 10 |
| --- | --- |
| `s8` - `a5000-1` | 5.645 (5.588–5.671) |
| `s8` - `a5000-2` | 5.491 (5.451–5.513) |

**NCCL did not use GPUDirect RDMA** in any of the 20 runs: `GDR 0` in every
rank-0 log. That is NCCL's own default for this GPU-NIC topology (`nvidia-smi
topo -m`: `SYS` on `a5000-1`, `NODE` on `a5000-2`), and it is left at that
default. These are therefore host-staged collective figures, which is what a
`LinkMeasurement` from them must say. The `p2p` block in each JSON is rank 0's
local copies on `s8`, as in the A40 pair's file.

## What this decides, and what it does not

- The transport works between the A40 and both A5000 nodes, and NIXL selects
  the IB path.
- **vLLM's `NixlConnector` needs both ends to use the same buffer kind.** On
  an A5000 with a 256 MiB BAR1, only `cpu`/`cpu` works. That path stages KV
  through host memory at both ends, which is not the path E-G5's A40 pair used.
- **The GPUDirect path, the one E-G5 used, works on `a5000-2` GPU 0 once its
  BAR1 is 32 GB.** That resize is done at run time and is lost on reboot. On
  `a5000-1`, enabling Re-Size BAR in the BIOS did not change BAR1.
- Which path E-G8 registers is the user's decision, recorded with row 11.
