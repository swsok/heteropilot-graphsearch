#!/usr/bin/env bash
# E-G3, the way it has to be launched. Two things this wrapper exists for, and
# neither is convenience:
#
#   1. **The interpreter.** Since heteropilot D27 the Chakra converter runs
#      in-process, so whichever venv starts the run decides which protobuf
#      converts the trace. `vendor/heteropilot/.venv/bin/python`, always.
#      `python -m graphsearch` refuses anything else, and this makes the
#      refusal impossible to hit by accident.
#
#   2. **A wall-clock ceiling that reaches the simulator's children.**
#      `livelock_watch.sh` runs the command with `setsid`, so its kill hits the
#      whole process group -- the harness AND the `python -m serving` children
#      it spawned. A bare `timeout` would leave those orphaned.
#
#      **Its progress detection is deliberately OFF here (`-g 0 -s 0`), and
#      that is not laziness.** The D23 detector reads `Running Instance[...]`
#      lines from the wrapped command's own stdout. Those lines belong to
#      `python -m serving`, which this harness starts as a SUBPROCESS whose
#      output goes to that simulation's own log. The watchdog therefore sees a
#      driver that never says anything, and its grace timer fires: the first
#      full three-fixture run here was killed at 901s with "the run never
#      started reporting" while 66 simulations had already completed and eight
#      more were running. Left on, it does not protect the run -- it ends it,
#      with a verdict that says the opposite of what happened.
#
#      What protects a single simulation is the predictor's own `timeout_s`
#      (`--timeout`, heteropilot's default 900s per simulation), which is the
#      right layer for it: one hung simulation is abandoned and the other 287
#      continue.
#
# It does NOT decide anything about the experiment. Every parameter is passed
# through, and the defaults are the script's own.
#
#     bash experiments/scripts/e_g3_oracle_run.sh
#     bash experiments/scripts/e_g3_oracle_run.sh --only graph-toy-shared-nic
#     bash experiments/scripts/e_g3_oracle_run.sh --max-workers 8
#
# Environment:
#     MAX_WORKERS   concurrent simulations (default 4). Result assembly stays
#                   sequential in candidate order whatever this is, so the
#                   output is byte-identical to a serial run.
#     CACHE_DIR     cache root; the arms use <root>/oracle and <root>/proposed.
#     CEILING       overall wall-clock ceiling in seconds (default 28800 = 8h).
#                   Exit 124 means it expired, which is `timeout`'s own code.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/vendor/heteropilot/.venv/bin/python"
WATCH="$ROOT/vendor/heteropilot/experiments/scripts/livelock_watch.sh"
CACHE_DIR="${CACHE_DIR:-outputs/cache-eg3}"
MAX_WORKERS="${MAX_WORKERS:-4}"
CEILING="${CEILING:-28800}"
OUT="${OUT:-experiments/results/e_g3_real_sim_oracle.md}"
LOG="${LOG:-outputs/eg3-oracle.log}"

export PYTHONPATH="$ROOT:$ROOT/vendor/heteropilot"

if [ ! -x "$VENV_PY" ]; then
    echo "e_g3_oracle_run: $VENV_PY does not exist." >&2
    echo "Follow docs/nodes/PREP.md step B on this node first." >&2
    exit 2
fi

mkdir -p "$(dirname "$LOG")" "$CACHE_DIR"

echo "=== node ====================================================="
bash vendor/heteropilot/scripts/whichnode.sh 2>&1 | sed -n '1,10p'
echo
echo "python      : $VENV_PY"
echo "cache root  : $CACHE_DIR   (arms use $CACHE_DIR/{oracle,proposed})"
echo "max workers : $MAX_WORKERS"
echo "output      : $OUT"
echo

start=$(date +%s)
if [ -x "$WATCH" ]; then
    # `-g 0 -s 0`: no progress detection -- see the header. `-t` is the only
    # thing being asked of it, plus the process-group kill that reaches the
    # simulator children. `--` is required; it parses its own flags until then.
    bash "$WATCH" -g 0 -s 0 -t "$CEILING" -- \
        "$VENV_PY" experiments/scripts/e_g3_real_sim_oracle.py \
        --predictor sim --cache-dir "$CACHE_DIR" \
        --max-workers "$MAX_WORKERS" --out "$OUT" "$@" 2>&1 | tee "$LOG"
    status=${PIPESTATUS[0]}
else
    # Not a silent fallback: without it there is no ceiling and no
    # process-group kill, so an abandoned run leaves simulator children behind.
    echo "WARNING: $WATCH is missing; running with no wall-clock ceiling and" >&2
    echo "no process-group kill. Simulator children may outlive an abort." >&2
    "$VENV_PY" experiments/scripts/e_g3_real_sim_oracle.py \
        --predictor sim --cache-dir "$CACHE_DIR" \
        --max-workers "$MAX_WORKERS" --out "$OUT" "$@" 2>&1 | tee "$LOG"
    status=${PIPESTATUS[0]}
fi
elapsed=$(( $(date +%s) - start ))

echo
echo "exit $status after ${elapsed}s; log in $LOG"
case "$status" in
    0)
        echo "E-G3: every fixture correct. Read $OUT, the saving_s column second."
        ;;
    1)
        echo "E-G3: a fixture is NOT correct. Do not relax the test. Run"
        echo "      --diagnose-pair A B and record its verdict in $OUT."
        ;;
    3)
        echo "E-G3: livelock_watch reports a TICK STALL -- the simulator"
        echo "      stopped making progress. A harness finding, not a result."
        ;;
    4)
        echo "E-G3: livelock_watch reports no progress. That detector is"
        echo "      supposed to be OFF here (-g 0 -s 0); if you see this, the"
        echo "      flags did not reach it. Read the header of this script."
        ;;
    124)
        echo "E-G3: the ${CEILING}s ceiling expired. Not a result -- raise"
        echo "      CEILING, or run one fixture at a time with --only."
        ;;
    *)
        echo "E-G3: exited $status. Read $LOG."
        ;;
esac
exit "$status"
