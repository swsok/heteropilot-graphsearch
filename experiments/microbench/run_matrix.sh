#!/usr/bin/env bash
# E-G4 P2.2: conditions 1-4 of PLAN.md's matrix, at location (a).
#
# Location (a) is the A40 node's shared PCIe host bridge. GPU0-3 sit on NUMA 0
# and GPU4-7 on NUMA 1; 0-1 and 2-3 are NVLink (NV4), and 0-2 / 1-3 cross the
# one host bridge. That bridge IS the shared uplink this experiment is about.
#
# **Location (b), the inter-node NIC, is not run here and is not omitted from
# the result either.** This is one machine with one NIC; there is no second
# node to send to. `analyze.py` reports it as `not run`, because an omitted
# row reads as a row that passed.
#
# Everything is pinned with `numactl --cpunodebind=0 --membind=0` -- both
# halves, which run_pair.py now refuses to let you claim without. Pinning is
# for REPRODUCIBILITY, not speed: heteropilot's docs/nodes/a40.md records
# cross-NUMA beating same-NUMA for host<->GPU bulk on this node kind, and these
# are device-to-device copies, a different transfer with no reason to follow
# that ordering either way.
#
#   bash experiments/microbench/run_matrix.sh
set -u

PY=${PY:-/home/swsok/heteropilot/.venv-vllm/bin/python}
ITERS=${ITERS:-20}                 # PLAN.md registers >= 10; 20 costs seconds
PIN="numactl --cpunodebind=0 --membind=0"
FAILED=0

run() {  # label, then run_pair.py arguments
  local label="$1"; shift
  echo "=== $(date -Is)  $label ==="
  # shellcheck disable=SC2086
  $PIN "$PY" experiments/microbench/run_pair.py \
      --label "$label" --binding numa_pinned --iters "$ITERS" "$@" \
    || { echo "!!! $label FAILED"; FAILED=$((FAILED + 1)); }
  echo
}

# --- condition 1: one transfer, nothing else. The control. ----------------
# Two of them, because "the control" means two different structures here: the
# NVLink pair is the fast path and the across-bridge pair is the one every
# other condition contends on. A single control would leave the contention
# figures without the right denominator.
run a-cond1-single-nvlink-0-1   --condition single --pairs 0-1 --share independent
run a-cond1-single-bridge-0-2   --condition single --pairs 0-2 --share independent

# --- condition 2: two flows over the SAME resource ------------------------
# 0-2 and 1-3 both cross the one NUMA-0 host bridge. This is the case the
# fluid model exists for: processor sharing predicts each gets half.
run a-cond2-two-same-bridge     --condition two-same --pairs 0-2,1-3 --share same

# --- condition 3: two flows over INDEPENDENT resources --------------------
# 0-2 on the NUMA-0 bridge, 4-6 on the NUMA-1 bridge. Disjoint. Both models
# must predict the single-flow time here; this is the implementation check,
# and a model that slows these down is coupling things that are not coupled.
run a-cond3-two-independent     --condition two-independent --pairs 0-2,4-6 --share independent

# --- condition 4: bidirectional ------------------------------------------
# 0->2 and 2->0 at once. PLAN.md expects contention "and asymmetrically":
# PCIe is full duplex per lane, so the two directions may NOT halve each other
# the way condition 2 does. That difference is the point of running it.
run a-cond4-bidirectional-0-2   --condition bidirectional --pairs 0-2,2-0 --share same

# --- background load at 60 %, the condition the matrix registers ----------
# One foreground flow, plus a third process holding a resource at a target
# 60 %. Two variants, and the pair of them is what makes either readable:
#   same        background on the SAME bridge (1-3) -- contention expected
#   independent background on the NUMA-1 bridge (4-6) -- none expected
# `--background-util` is a TARGET; run_pair.py records what was actually
# sustained and analyze.py uses that. A generator that missed its target and a
# model that missed its prediction are different failures and must not cancel.
run a-cond2-bg60-same-bridge    --condition two-same --pairs 0-2 --share same \
    --background-util 0.6 --background-pair 1-3
run a-cond3-bg60-independent    --condition two-independent --pairs 0-2 --share independent \
    --background-util 0.6 --background-pair 4-6
run a-cond4-bidi-bg60-same      --condition bidirectional --pairs 0-2,2-0 --share same \
    --background-util 0.6 --background-pair 1-3

echo "=== $(date -Is)  matrix complete; $FAILED run(s) failed ==="
echo "Condition 5 (collective) is a different instrument:"
echo "    bash experiments/microbench/run_collective.sh"
exit $((FAILED > 0))
