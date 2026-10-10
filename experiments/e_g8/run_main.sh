#!/usr/bin/env bash
# E-G8 validation runs (row 11): each direction at 1 rps, ABAB -- for 42,
# 43, 44, `independent` then `shared`. 12 runs. Writes under raw/runs/.
# REAL HARDWARE: nothing else on s8 or a5k2 GPU 0, no simulation meanwhile.
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
PY=vendor/heteropilot/.venv/bin/python
for d in D1 D2; do
  for rep in 42 43 44; do
    for c in independent shared; do
      $PY experiments/e_g8/pd_arm.py --mode run --direction "$d" --condition "$c" \
          --rep "$rep" --rps 1 || echo "RUN_FAIL $d $c $rep"
    done
  done
done
echo MAIN_DONE
