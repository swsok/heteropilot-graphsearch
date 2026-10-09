#!/usr/bin/env bash
# gpu0_rebar.sh [out.txt] -- run FROM s8 before every E-G8 run that uses
# a5000-2's GPU 0: resize its BAR1 to 32 GB and record the before/after state.
#
# Why by hand and not at boot: a5000-2's BIOS has no Re-Size BAR option, and
# the RTX A5000 boots at a 256 MiB BAR1, too small for vLLM's NixlConnector to
# register a KV cache for GPUDirect RDMA (GS-39). The size does not survive a
# reboot. A boot-time unit that unbound the GPU hung in `nv_pci_remove` and
# left the node unable to shut down (docs/nodes/a5000.md), so the user chose
# this: run it explicitly, before each run, and record that it was run.
#
# It refuses rather than risk that hang again: no compute process, no open
# /dev/nvidia0, and nvidia-persistenced stopped first. The unbind is watched
# for 30 s; if it has not returned by then, the node needs a power cycle and
# the script says so instead of carrying on.
set -u
A=swsok@192.168.100.112
OUT=${1:-/dev/stdout}
{
  echo "## gpu0_rebar $(date -u +%FT%TZ)"
  ssh -o BatchMode=yes $A 'bash -s' <<'REMOTE'
set -u
DEV=0000:17:00.0; SYS=/sys/bus/pci/devices/$DEV
bar() { sudo lspci -vv -s 17:00.0 | sed -n "s/.*BAR 1: current size: \([0-9]*[MG]B\).*/\1/p"; }
echo "uptime: $(cut -d' ' -f1 /proc/uptime) s"
echo "before: BAR1 $(bar)"
if [ "$(bar)" = 32GB ]; then echo "result: already 32GB"; exit 0; fi
n=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)
o=$(sudo lsof -t /dev/nvidia0 2>/dev/null | wc -l)
if [ "$n" != 0 ] || [ "$o" != 0 ]; then echo "result: REFUSED ($n compute processes, $o holders of /dev/nvidia0)"; exit 1; fi
sudo systemctl stop nvidia-persistenced
( echo $DEV | sudo tee /sys/bus/pci/drivers/nvidia/unbind >/dev/null ) &
w=$!
for i in $(seq 30); do kill -0 $w 2>/dev/null || break; sleep 1; done
if kill -0 $w 2>/dev/null; then echo "result: UNBIND HUNG after 30 s -- do not reboot remotely; power-cycle the node"; exit 2; fi
echo 15 | sudo tee $SYS/resource1_resize >/dev/null; rc=$?
echo $DEV | sudo tee /sys/bus/pci/drivers/nvidia/bind >/dev/null
sudo systemctl start nvidia-persistenced
echo "after: BAR1 $(bar); nvidia-smi BAR1 total $(nvidia-smi -i 0 -q | grep -A1 'BAR1 Memory' | tail -1 | awk '{print $3, $4}')"
[ "$rc" = 0 ] && [ "$(bar)" = 32GB ] && echo "result: resized" || { echo "result: FAILED (resize rc=$rc)"; exit 1; }
REMOTE
  echo "exit=$?"
} >> "$OUT" 2>&1
[ "$OUT" != /dev/stdout ] && tail -6 "$OUT"
