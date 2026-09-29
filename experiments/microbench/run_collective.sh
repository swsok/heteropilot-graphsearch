#!/usr/bin/env bash
# E-G4 P2.2, condition 5: all-reduce at world size 2 and 4.
#
# A different instrument from run_matrix.sh on purpose. Conditions 1-4 are peer
# COPIES, timed by `run_pair.py`; a collective is NCCL ranks under `torchrun`,
# and reporting one under the other's label is the mislabelling this harness
# exists to prevent -- so `run_pair.py --condition collective` refuses.
#
# heteropilot's own `experiments/p2_evidence/link_probe.py` already does this,
# reports `busbw` (the figure comparable with a link rate) alongside `algbw`
# (what the application sees), and is imported here **unmodified**: the
# boundary rule is that only hook PRs reach that repository, and a benchmark is
# not a hook.
#
# `world_size` is part of the `LinkMeasurement` key and this is why:
# heteropilot's A40 bridge measures 19.29 GB/s for a two-rank all-reduce and
# 8.8 for a four-rank one. One wire, 2.2x apart. Filing one under the other's
# key is the substitution the key exists to stop.
#
#   bash experiments/microbench/run_collective.sh
set -u

HP=vendor/heteropilot
TORCHRUN=${TORCHRUN:-/home/swsok/heteropilot/.venv-vllm/bin/torchrun}
OUT=$PWD/experiments/microbench/raw/collective-$(date +%F)
mkdir -p "$OUT"
FAILED=0

run() {  # label, nproc, ranks, then env assignments
  local label="$1" nproc="$2" ranks="$3"; shift 3
  echo "=== $(date -Is) $label (world $nproc, ranks $ranks) $* ==="
  # Pinned to NUMA 0 like the rest of location (a): GPU0-3 are the NUMA-0
  # devices, and an unpinned collective is a figure under a label that does
  # not describe it.
  ( cd "$HP" && env "$@" MASTER_ADDR=127.0.0.1 MASTER_PORT=29573 \
      numactl --cpunodebind=0 --membind=0 \
      "$TORCHRUN" --nproc-per-node="$nproc" --master-port=29573 \
      experiments/p2_evidence/link_probe.py \
      --ranks "$ranks" --label "$label" --out "$OUT/${label}.json" ) 2>&1 \
    | grep -vE '^\[|WARNING|warnings.warn|^\s*$' \
    || { echo "!!! $label FAILED"; FAILED=$((FAILED + 1)); }
  echo
}

# World 2, inside the NVLink pair and across the PCIe bridge. The pair of
# numbers the cluster spec guesses at.
run c-world2-nvlink-0-1  2 0,1
run c-world2-bridge-0-2  2 0,1  CUDA_VISIBLE_DEVICES=0,2
# World 4: the whole NUMA-0 half, which is the TP=4 group a real candidate runs
# on. Not the same measurement as world 2 and not filed as one.
run c-world4-numa0       4 0,1,2,3

echo "=== $(date -Is) collective complete; $FAILED failed ==="
echo "raw: $OUT"
exit $((FAILED > 0))
