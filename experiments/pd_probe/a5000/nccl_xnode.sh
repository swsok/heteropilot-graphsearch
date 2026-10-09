#!/usr/bin/env bash
# nccl_xnode.sh <n> <rep> <outdir>: one 2-node all-reduce run, rank 0 on s8, rank 1 on a5000-n
n=$1; rep=$2; out=$3; mkdir -p "$out"; A=swsok@192.168.100.11$n; port=$((29600 + rep))
label=xnode-a40-a5000-$n-r$rep
ssh $A "cd ~/heteropilot-graphsearch/vendor/heteropilot && NCCL_SOCKET_IFNAME=ibp179s0f1 NCCL_IB_HCA=mlx5_1 NCCL_DEBUG=INFO CUDA_VISIBLE_DEVICES=1,0 timeout 600 ~/.venv-eg8/bin/torchrun --nnodes 2 --node-rank 1 --nproc-per-node 1 --master-addr 192.168.210.108 --master-port $port experiments/p2_evidence/link_probe.py --ranks 0,1 --label $label --out /tmp/$label.json" > "$out/$label.rank1.log" 2>&1 &
rpid=$!
( cd /home/swsok/heteropilot-graphsearch/vendor/heteropilot && NCCL_SOCKET_IFNAME=ibs8 NCCL_IB_HCA=mlx5_0 NCCL_DEBUG=INFO timeout 600 /home/swsok/heteropilot/.venv-vllm/bin/torchrun --nnodes 2 --node-rank 0 --nproc-per-node 1 --master-addr 192.168.210.108 --master-port $port experiments/p2_evidence/link_probe.py --ranks 0,1 --label $label --out "$out/$label.json" ) > "$out/$label.rank0.log" 2>&1
echo "rank0 exit=$?" >> "$out/$label.rank0.log"; wait $rpid; echo "rank1 exit=$?" >> "$out/$label.rank1.log"
ssh $A "rm -f /tmp/$label.json"
python3 - "$out/$label.json" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception as e: print("NO_JSON",e); sys.exit()
ar=d.get("allreduce",[]); big=[r for r in ar if r["bytes"]>=4<<20]
print("busbw GB/s >=4MiB:", " ".join(f"{r['bytes']>>20}M:{r['busbw_gbps']:.2f}" for r in big))
PY
grep -h -E "NET/IB|GDRDMA|via NET|Using network" "$out/$label.rank0.log" | head -3 | cut -c1-200
