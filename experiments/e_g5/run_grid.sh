#!/usr/bin/env bash
# E-G5 on hardware, the whole registered matrix, in the order it was run.
#
# REAL HARDWARE: every deployment occupies GPUs on this node and on s6/s8 for
# the P/D arm. Run it only on a node nobody else is using --
# `deploy_and_bench.py` refuses to start beside another GPU tenant and records
# the occupancy before and after each run in its provenance file.
#
#     bash experiments/e_g5/run_grid.sh            # aggregated matrix only
#     WITH_PD=1 bash experiments/e_g5/run_grid.sh  # plus the P/D arm (row 7)
#
# Order matters for `high`: `high_scope.py` evaluates each pattern x topology
# exhaustively at seed 42 (preregistration row 8 a) and writes
# `raw/high-scope/`, which the `high` deployments read; it is CPU-only and
# simulator-bound (60 workers, several hours on a 64-core node).

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
PY=vendor/heteropilot/.venv/bin/python

"$PY" -u experiments/e_g5/high_scope.py

for pl in normal:knee normal:low normal:high burst:low burst:knee burst:high; do
    pattern=${pl%%:*}; level=${pl##*:}
    for topo in T1 T2 T3; do
        for rep in 42 43 44; do
            "$PY" -u experiments/e_g5/deploy_and_bench.py \
                --condition "llama31-8b__${pattern}__${topo}__${level}" --rep "$rep" \
                --knee-rps 4 --predictor sim
        done
    done
done

if [ "${WITH_PD:-0}" = 1 ]; then
    # Row 7: the template is fixed once (pd-select), predicted at the
    # registered rate (pd-predict), then measured as ABAB pairs.
    "$PY" -u experiments/e_g5/deploy_and_bench.py --mode pd-select --condition x --predictor sim
    "$PY" -u experiments/e_g5/deploy_and_bench.py --mode pd-predict --condition x --rps 1 --predictor sim
    for rep in 42 43 44; do
        for cond in pd-independent pd-shared; do
            "$PY" -u experiments/e_g5/deploy_and_bench.py \
                --mode pd --condition "$cond" --rep "$rep" --rps 1 --predictor sim
        done
    done
fi

"$PY" experiments/e_g5/analyze.py --out experiments/results/e_g5_real_hardware.md
