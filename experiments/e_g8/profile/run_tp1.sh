#!/usr/bin/env bash
# run_tp1.sh -- ON an A5000 node: profile Llama-3.1-8B bf16 tp=1 again, with
# R4.2's settings, into a separate clone and a separate hardware name, so the
# committed `A5000` bundle is never touched (E-G3, E-G5 and E-G6 read its tp1).
# The question it answers: is the committed bundle a measurement of THIS
# machine's kind of GPU, within run-to-run noise? (docs/nodes/a5000.md)
#
# HW names the output folder: A5000-a5k2 on a5000-2 (the machine question),
# A5000-a5k1 on a5000-1 (run-to-run noise on the machine R4.2 records).
#
#   HW=A5000-a5k2 bash run_tp1.sh            # ~6.5 h on GPU 0; nothing else on the GPU
#   HW=A5000-a5k1 UV=~/miniforge3/bin/uv bash run_tp1.sh
set -euo pipefail
SHA=60df94352acf5552c189c45223fb842337bcd283     # the submodule pin
HW=${HW:?set HW, e.g. A5000-a5k2}; UV=${UV:-$HOME/.local/bin/uv}
DIR=~/heteropilot-$HW-reprofile
RAW=~/$HW-reprofile-raw; mkdir -p "$RAW"
SRC=${SRC:-https://github.com/swsok/heteropilot.git}   # a5000-1 has no GitHub auth: SRC=~/heteropilot-graphsearch/vendor/heteropilot
[ -d "$DIR" ] || git clone -q "$SRC" "$DIR"
cd "$DIR" && git checkout -q "$SHA"
if [ ! -x .venv-vllm/bin/python ]; then
  $UV venv -q --python 3.12 .venv-vllm
  VLLM_USE_PRECOMPILED=1 $UV pip install -q --python .venv-vllm/bin/python vllm==0.19.0 datasets matplotlib
fi
source .venv-vllm/bin/activate
{ date -u +%FT%TZ; hostname; nvidia-smi -L; nvidia-smi; uptime; } > "$RAW/before.txt" 2>&1
n=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)
[ "$n" = 0 ] || { echo "refusing: $n GPU processes" | tee -a "$RAW/before.txt"; exit 1; }
CUDA_VISIBLE_DEVICES=0 python3 -m profiler profile meta-llama/Llama-3.1-8B --hardware "$HW" \
  --tp 1 --max-num-batched-tokens 2048 --max-num-seqs 256 --attention-max-kv 16384 \
  --attention-chunk-factor 2.0 --attention-kv-factor 2.0 --measurement-iterations 3 \
  --skew-n-factor 2.0 --skew-pc-factor 2.0 --skew-kp-factor 2.0 --skew-kvs-factor 2.0 \
  2>&1 | tee "$RAW/profile-tp1.log"
echo "EXIT=${PIPESTATUS[0]}" >> "$RAW/profile-tp1.log"
{ date -u +%FT%TZ; nvidia-smi; uptime; } > "$RAW/after.txt" 2>&1
find "profiler/perf/$HW" -type f | sort | xargs md5sum > "$RAW/$HW-tp1.md5"
