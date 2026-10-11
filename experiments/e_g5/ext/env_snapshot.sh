#!/usr/bin/env bash
# One node's serving environment, for comparing against row 7's runs
# (2026-10-01): package versions with each one's install time, the driver,
# the kernel and when the module was loaded, and who holds GPU 0.
#   env_snapshot.sh <venv-python>
PY=${1:?venv python}
echo "host: $(hostname)  date: $(date -Is)"
echo "kernel: $(uname -r)  up since: $(uptime -s)"
echo "driver: $(cat /proc/driver/nvidia/version | head -1)"
echo "nvidia.ko loaded since boot; module file mtime: $(stat -c %y $(modinfo -n nvidia 2>/dev/null) 2>/dev/null)"
$PY - <<'PYEOF'
import importlib.metadata as md, os, datetime
for name in ("vllm", "torch", "nixl", "nixl-cu12", "ucx-py-cu12", "transformers", "flashinfer-python"):
    try:
        d = md.distribution(name)
    except md.PackageNotFoundError:
        continue
    t = datetime.datetime.fromtimestamp(os.path.getmtime(d._path)).isoformat(timespec="seconds")
    print(f"pkg {name}=={d.version}  installed {t}")
PYEOF
echo "dpkg changes to nvidia/cuda/ucx/rdma since 2026-09-25:"
zgrep -h -E " (install|upgrade|remove) .*(nvidia|cuda|ucx|rdma|mlnx|ofed|libibverbs)" /var/log/dpkg.log* 2>/dev/null \
  | awk '$1 >= "2026-09-25"' | sort | tail -20
echo "GPU 0: $(nvidia-smi -i 0 --query-gpu=uuid,memory.used --format=csv,noheader); compute apps on GPU 0: $(nvidia-smi -i 0 --query-compute-apps=pid --format=csv,noheader | wc -l)"
