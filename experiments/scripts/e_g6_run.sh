#!/usr/bin/env bash
# E-G6, with a wall-clock ceiling and the node named.
#
# No watchdog with progress detection here, and for the same reason E-G3's
# wrapper turns it off (GS-18): `livelock_watch` reads the SIMULATOR's tick
# lines from the wrapped command's stdout, and this run uses the mock
# predictor, which has none. What it can still give is a ceiling and a
# process-group kill, so that is what it is asked for.
#
# Everything here runs on CPU against the mock. It needs no GPU and no built
# simulator, so it is safe to run while another tenant holds the accelerators.
#
#     bash experiments/scripts/e_g6_run.sh
#     CEILING=3600 bash experiments/scripts/e_g6_run.sh --devices 32 64

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python
WATCH="$ROOT/vendor/heteropilot/experiments/scripts/livelock_watch.sh"
CEILING="${CEILING:-14400}"
LOG="${LOG:-outputs/e_g6/run.log}"

export PYTHONPATH="$ROOT:$ROOT/vendor/heteropilot"
mkdir -p "$(dirname "$LOG")"

echo "=== node ====================================================="
bash vendor/heteropilot/scripts/whichnode.sh 2>&1 | sed -n '1,10p'
echo
echo "python  : $PY"
echo "ceiling : ${CEILING}s"
echo

echo "--- the three load levels ---"
"$PY" experiments/scripts/e_g6_traces.py --out outputs/e_g6/traces || exit 1
echo

start=$(date +%s)
if [ -x "$WATCH" ]; then
    bash "$WATCH" -g 0 -s 0 -t "$CEILING" -- \
        "$PY" experiments/scripts/e_g6_scale.py "$@" 2>&1 | tee "$LOG"
    status=${PIPESTATUS[0]}
else
    echo "WARNING: $WATCH missing; no ceiling, no process-group kill." >&2
    "$PY" experiments/scripts/e_g6_scale.py "$@" 2>&1 | tee "$LOG"
    status=${PIPESTATUS[0]}
fi
elapsed=$(( $(date +%s) - start ))

echo
echo "exit $status after ${elapsed}s; log in $LOG"
case "$status" in
    0) echo "E-G6: read experiments/results/e_g6_scale.md, then make figures." ;;
    124) echo "E-G6: the ${CEILING}s ceiling expired. Raise CEILING, or run" ;
         echo "      fewer cells with --devices / --only-symmetry." ;;
    *) echo "E-G6: exited $status. Read $LOG." ;;
esac
exit "$status"
