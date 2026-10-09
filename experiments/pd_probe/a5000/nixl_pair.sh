#!/usr/bin/env bash
# nixl_pair.sh <n: 1|2> <dir: s8-to-a5k | a5k-to-s8> <outdir>
set -u
n=$1; dir=$2; out=$3; mkdir -p "$out"
A=swsok@192.168.100.11$n
S8ENV="LD_LIBRARY_PATH=/opt/nvidia/nsight-compute/2024.3.2/host/linux-desktop-glibc_2_11_3-x64 UCX_NET_DEVICES=mlx5_0:1 CUDA_VISIBLE_DEVICES=0"
S8PY=/home/swsok/heteropilot/.venv-vllm/bin/python
AENV="UCX_NET_DEVICES=mlx5_1:1 CUDA_VISIBLE_DEVICES=0"
APY='~/.venv-eg8/bin/python'
tag="$dir-a5000-$n"
{ echo "## before"; date -u +%FT%TZ; nvidia-smi --query-gpu=index,uuid,memory.used --format=csv; nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l
  ssh $A "nvidia-smi --query-gpu=index,uuid,memory.used --format=csv; nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l"; } > "$out/$tag.occupancy-before.txt" 2>&1
if [ "$dir" = s8-to-a5k ]; then
  ssh $A "cd /tmp && env $AENV $APY nixl_target.py ${NBYTES:-268435456} /tmp/nixl_meta.json" > "$out/$tag.target.log" 2>&1 &
  tpid=$!
  for i in $(seq 60); do grep -q TARGET_READY "$out/$tag.target.log" && break; sleep 2; done
  scp -q $A:/tmp/nixl_meta.json /tmp/nixl_meta.json
  env $S8ENV UCX_PROTO_INFO=y $S8PY /home/swsok/heteropilot-graphsearch/experiments/pd_probe/nixl_bw.py /tmp/nixl_meta.json ${NBYTES:-268435456} > "$out/$tag.initiator.log" 2>&1
  echo "initiator exit=$?" >> "$out/$tag.initiator.log"
  ssh $A "pkill -f [n]ixl_target.py; rm -f /tmp/nixl_meta.json"; wait $tpid; rm -f /tmp/nixl_meta.json
else
  (cd /tmp && env $S8ENV $S8PY /home/swsok/heteropilot-graphsearch/experiments/pd_probe/nixl_target.py ${NBYTES:-268435456} /tmp/nixl_meta.json) > "$out/$tag.target.log" 2>&1 &
  tpid=$!
  for i in $(seq 60); do grep -q TARGET_READY "$out/$tag.target.log" && break; sleep 2; done
  scp -q /tmp/nixl_meta.json $A:/tmp/nixl_meta.json
  ssh $A "cd /tmp && env $AENV UCX_PROTO_INFO=y $APY nixl_bw.py /tmp/nixl_meta.json ${NBYTES:-268435456}" > "$out/$tag.initiator.log" 2>&1
  echo "initiator exit=$?" >> "$out/$tag.initiator.log"
  pkill -f "[n]ixl_target.py 268435456" ; wait $tpid; rm -f /tmp/nixl_meta.json; ssh $A "rm -f /tmp/nixl_meta.json"
fi
{ echo "## after"; date -u +%FT%TZ; nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l; ssh $A "nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l"; } > "$out/$tag.occupancy-after.txt" 2>&1
grep -E "^ +[0-9]+ " "$out/$tag.initiator.log"; grep -E "TARGET_GOT|TARGET_DONE|XFER_ERR|initiator exit" "$out/$tag.target.log" "$out/$tag.initiator.log"
