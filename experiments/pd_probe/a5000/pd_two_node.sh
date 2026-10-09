#!/usr/bin/env bash
# pd_two_node.sh <n> <D1|D2> <outdir>   D1: prefill s8 -> decode a5000-n ; D2: prefill a5000-n -> decode s8
# S8BUF / ABUF = cuda | cpu: NixlConnector kv_buffer_device on s8 / on the A5000 (default cuda both).
# vLLM 0.19 needs the two to match: a mixed pair fails its handshake (NIXL_ERR_NOT_FOUND).
n=$1; d=$2; out=$3; mkdir -p "$out"; A=swsok@192.168.100.11$n; AIB=192.168.210.11$n; S8BUF=${S8BUF:-cuda}; ABUF=${ABUF:-cuda}; tag=$d-a5000-$n-s8$S8BUF-a5k$ABUF
OSSL=/opt/nvidia/nsight-compute/2024.3.2/host/linux-desktop-glibc_2_11_3-x64
S8V=/home/swsok/heteropilot/.venv-vllm/bin/vllm; S8PY=/home/swsok/heteropilot/.venv-vllm/bin/python
COMMON="meta-llama/Llama-3.1-8B --host 0.0.0.0 --max-model-len 8192 --no-enable-prefix-caching --max-num-seqs 256 --max-num-batched-tokens 2048 --dtype bfloat16 --kv-cache-dtype auto"
if [ $d = D1 ]; then s8role=kv_producer; arole=kv_consumer; s8port=8100; aport=8200; else s8role=kv_consumer; arole=kv_producer; s8port=8200; aport=8100; fi
{ date -u +%FT%TZ; nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l; ssh $A "nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l"; } > "$out/$tag.occupancy-before.txt"
CUDA_VISIBLE_DEVICES=0 UCX_NET_DEVICES=mlx5_0:1 VLLM_NIXL_SIDE_CHANNEL_HOST=192.168.210.108 VLLM_NIXL_SIDE_CHANNEL_PORT=5600 HF_HUB_OFFLINE=1 LD_LIBRARY_PATH=$OSSL \
  setsid nohup $S8V serve $COMMON --port $s8port --gpu-memory-utilization 0.6 --kv-transfer-config "{\"kv_connector\":\"NixlConnector\",\"kv_role\":\"$s8role\",\"kv_buffer_device\":\"$S8BUF\"}" > "$out/$tag.s8.vllm.log" 2>&1 < /dev/null &
acfg="{\\\"kv_connector\\\":\\\"NixlConnector\\\",\\\"kv_role\\\":\\\"$arole\\\",\\\"kv_buffer_device\\\":\\\"$ABUF\\\"}"
ssh $A "CUDA_VISIBLE_DEVICES=0 UCX_NET_DEVICES=mlx5_1:1 VLLM_NIXL_SIDE_CHANNEL_HOST=$AIB VLLM_NIXL_SIDE_CHANNEL_PORT=5700 HF_HUB_OFFLINE=1 setsid nohup ~/.venv-eg8/bin/vllm serve $COMMON --port $aport --gpu-memory-utilization 0.9 --kv-transfer-config \"$acfg\" > /tmp/eg8_pd.log 2>&1 < /dev/null &"
ok=no
for i in $(seq 120); do
  curl -sf http://127.0.0.1:$s8port/health >/dev/null && curl -sf http://$AIB:$aport/health >/dev/null && { ok=yes; break; }
  sleep 5
done
echo "healthy=$ok after ${i}x5s" > "$out/$tag.client.log"
if [ $ok = yes ]; then
  if [ $d = D1 ]; then P=http://127.0.0.1:8100; D=http://$AIB:8200; else P=http://$AIB:8100; D=http://127.0.0.1:8200; fi
  for r in 1 2 3 4 5 6; do echo "## rep $r" >> "$out/$tag.client.log"; timeout 300 $S8PY /home/swsok/heteropilot-graphsearch/experiments/pd_probe/pd_client.py $P $D meta-llama/Llama-3.1-8B >> "$out/$tag.client.log" 2>&1; done
fi
scp -q $A:/tmp/eg8_pd.log "$out/$tag.a5000.vllm.log"
ssh $A "pkill -f '[v]llm serve meta-llama'; sleep 5; pkill -9 -f '[v]llm serve meta-llama'; rm -f /tmp/eg8_pd.log"
pkill -f "[v]llm serve meta-llama/Llama-3.1-8B"; sleep 5; pkill -9 -f "[v]llm serve meta-llama/Llama-3.1-8B"; sleep 3
{ date -u +%FT%TZ; nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l; ssh $A "nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l"; } > "$out/$tag.occupancy-after.txt"
grep -E "healthy=|PREFILL_S|PD_OK|NO_KV|Error|error" "$out/$tag.client.log" | head -16
