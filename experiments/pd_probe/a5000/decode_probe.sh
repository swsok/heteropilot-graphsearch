#!/usr/bin/env bash
# decode_probe.sh <n> <outdir> [gpu_mem_util]: vLLM decode (kv_consumer, NixlConnector) alone on a5000-<n>
n=$1; out=$2; util=${3:-0.9}; A=swsok@192.168.100.11$n; ib=192.168.210.11$n; mkdir -p "$out"; tag=decode-a5000-$n-util$util${TAGSUF:-}
ssh $A "date -u +%FT%TZ; nvidia-smi; nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l" > "$out/$tag.occupancy-before.txt" 2>&1
DEF='{"kv_connector":"NixlConnector","kv_role":"kv_consumer"}'; cfg="${CFG:-$DEF}"
ssh $A "CUDA_VISIBLE_DEVICES=0 UCX_NET_DEVICES=mlx5_1:1 VLLM_NIXL_SIDE_CHANNEL_HOST=$ib VLLM_NIXL_SIDE_CHANNEL_PORT=5700 HF_HUB_OFFLINE=1 setsid nohup ~/.venv-eg8/bin/vllm serve meta-llama/Llama-3.1-8B --host 0.0.0.0 --port 8200 --max-model-len 8192 --gpu-memory-utilization $util --no-enable-prefix-caching --max-num-seqs 256 --max-num-batched-tokens 2048 --dtype bfloat16 --kv-cache-dtype auto --kv-transfer-config '$cfg' > /tmp/eg8_decode.log 2>&1 < /dev/null & echo \$!" > "$out/$tag.pid"
status=timeout
for i in $(seq 120); do
  if ssh $A "curl -sf http://127.0.0.1:8200/health >/dev/null"; then status=healthy; break; fi
  if ! ssh $A "kill -0 \$(cat /dev/stdin)" < "$out/$tag.pid" 2>/dev/null; then status=exited; break; fi
  sleep 5
done
echo "status=$status after ${i}x5s" > "$out/$tag.status"
ssh $A "nvidia-smi --query-gpu=memory.used,memory.total --format=csv" >> "$out/$tag.status"
scp -q $A:/tmp/eg8_decode.log "$out/$tag.vllm.log"
ssh $A "pkill -f '[v]llm serve meta-llama'; sleep 5; pkill -9 -f '[v]llm serve meta-llama'; sleep 2; nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l; rm -f /tmp/eg8_decode.log" > "$out/$tag.occupancy-after.txt" 2>&1
cat "$out/$tag.status"; grep -i -E "GPU KV cache size|Maximum concurrency|num_gpu_blocks|blocks|nixl|NIXL|register|ERROR|Error" "$out/$tag.vllm.log" | grep -v -i "warn.*deprecat" | head -20 | cut -c1-220
