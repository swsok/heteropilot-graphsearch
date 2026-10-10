#!/usr/bin/env bash
# E-G8 pilot pairs (row 7 (d)'s order, ABAB): at the run rate, three
# `independent` / `shared` pairs per direction, for the SD of the pair-mean
# change that sets the repetitions (three, or six if the SD is not below half
# the prediction). Writes under raw/pilot/pairs/ -- excluded from validation.
# REAL HARDWARE: nothing else on s8 or a5k2 GPU 0, no simulation meanwhile.
#
#   experiments/e_g8/pilot_pairs.sh [RPS] [D1 D2]
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
PY=vendor/heteropilot/.venv/bin/python
RPS=${1:-1}
shift || true
DIRS=("${@:-D1 D2}")
for d in ${DIRS[@]}; do
  for rep in 1 2 3; do
    for c in independent shared; do
      $PY experiments/e_g8/pd_arm.py --mode run --direction "$d" --condition "$c" \
          --rep "$rep" --rps "$RPS" --pilot-label pairs || echo "PAIR_FAIL $d $c $rep"
    done
  done
done
echo PAIRS_DONE
