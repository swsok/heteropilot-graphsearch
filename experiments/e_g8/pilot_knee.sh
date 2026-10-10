#!/usr/bin/env bash
# E-G8 knee pilot (row 7 (b)'s rule): the fixed template of each direction at
# 1, 1.5, 2, 3 rps, condition `independent`, one run each. Writes under
# raw/pilot/knee-rps<r>/ -- excluded from validation. REAL HARDWARE: run with
# nothing else on s8 or a5k2 GPU 0, and no simulation on this node meanwhile.
#
#   experiments/e_g8/pilot_knee.sh [D1 D2]
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
PY=vendor/heteropilot/.venv/bin/python
DIRS=("${@:-D1 D2}")
for d in ${DIRS[@]}; do
  for r in 1 1.5 2 3; do
    $PY experiments/e_g8/pd_arm.py --mode run --direction "$d" --condition independent \
        --rep 1 --rps "$r" --pilot-label "knee-rps$r" || echo "KNEE_FAIL $d $r"
  done
done
echo KNEE_DONE
