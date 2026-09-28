#!/usr/bin/env bash
# E-G3 P1.1 -- does the REAL simulator path work, and does it carry the
# evidence the rest of E-G3 will read?
#
# This is not an experiment. It produces no table and claims nothing. It runs
# one small `--predictor sim` plan and then checks, one item at a time, that
# the things E-G3's oracle harness depends on are actually present:
#
#   1. the run reached the simulator at all;
#   2. the compile hook fired FOR THE CANDIDATES WE BOUND -- without it the
#      simulator is told nothing about which devices a placement uses, and two
#      placements differing only in the uplink they cross come back identical;
#   3. the result hook fired, so the P/D handoff is priced over the path this
#      placement takes rather than by heteropilot's class default;
#   4. `provenance.graph_search` is in the written plan;
#   5. `provenance.graph_search.topology_loss` is there and names what the
#      simulator could not be told.
#
# Every check prints PASS or FAIL with what it looked for. The script exits
# non-zero if any failed, and says which.
#
# RUN IT ON A NODE WITH THE SIMULATOR BUILT, through that venv:
#
#     bash experiments/scripts/e_g3_smoke.sh
#
# It finds `vendor/heteropilot/.venv/bin/python` itself and refuses if it is
# missing -- see docs/nodes/PREP.md step B.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/vendor/heteropilot/.venv/bin/python"
SERVICE="fixtures/service_specs/graph-toy-llama31-8b.yaml"
CLUSTER="fixtures/clusters/graph-toy-abcde.v2.yaml"
CACHE_DIR="${CACHE_DIR:-outputs/cache-eg3}"
OUT_YAML="${OUT_YAML:-outputs/eg3-smoke.yaml}"
LOG="${LOG:-outputs/eg3-smoke.log}"
NUM_REQUESTS="${NUM_REQUESTS:-50}"
K_SCHEDULE="${K_SCHEDULE:-2}"

export PYTHONPATH="$ROOT:$ROOT/vendor/heteropilot"

fails=0
check() {  # check <name> <condition-exit-code> <what it looked for>
    if [ "$2" -eq 0 ]; then
        printf 'PASS  %s\n' "$1"
    else
        printf 'FAIL  %s\n        looked for: %s\n' "$1" "$3"
        fails=$((fails + 1))
    fi
}

# --- the node, named before anything is claimed about it ---------------------
echo "=== node ====================================================="
bash vendor/heteropilot/scripts/whichnode.sh 2>&1 | sed -n '1,12p'
echo

if [ ! -x "$VENV_PY" ]; then
    cat >&2 <<EOF
e_g3_smoke: $VENV_PY does not exist.

--predictor sim needs LLMServingSim and ASTRA-Sim built in that venv, and the
Chakra converter runs in-process so it must be THAT interpreter. Follow
docs/nodes/PREP.md step B on this node, then run this again.
EOF
    exit 2
fi

mkdir -p "$(dirname "$OUT_YAML")" "$CACHE_DIR"
rm -f "$OUT_YAML"

# --- the run -----------------------------------------------------------------
echo "=== plan --predictor sim ====================================="
echo "python  : $VENV_PY"
echo "service : $SERVICE"
echo "cluster : $CLUSTER"
echo "requests: $NUM_REQUESTS   k-schedule: $K_SCHEDULE   cache: $CACHE_DIR"
echo

start=$(date +%s)
"$VENV_PY" -m graphsearch plan \
    --predictor sim \
    --service "$SERVICE" \
    --cluster "$CLUSTER" \
    --num-requests "$NUM_REQUESTS" \
    --k-schedule "$K_SCHEDULE" \
    --cache-dir "$CACHE_DIR" \
    --output "$OUT_YAML" 2>&1 | tee "$LOG"
status=${PIPESTATUS[0]}
elapsed=$(( $(date +%s) - start ))
echo
echo "exit $status after ${elapsed}s; log in $LOG"
echo

# --- the checks --------------------------------------------------------------
echo "=== checks ==================================================="
check "the run completed" "$status" "exit 0 from python -m graphsearch plan"

! grep -q "MOCK PREDICTOR" "$LOG"
check "this was NOT the mock" $? "no MOCK PREDICTOR banner in the output"

grep -qE '^  hooks: bound [1-9]' "$LOG"
check "the binder bound candidates" $? "a 'hooks: bound N over M batch(es)' line with N > 0"

grep -qE '^  hooks:.*compile [1-9][0-9]*/' "$LOG"
check "the compile hook APPLIED" $? \
    "'compile <applied>/<seen>' with applied > 0 -- 0 means the simulator was never told the devices"

grep -qE '^  hooks:.*result [0-9]+/[1-9]' "$LOG"
check "the result hook was called" $? "'result <applied>/<seen>' with seen > 0"

test -f "$OUT_YAML"
check "the plan was written" $? "$OUT_YAML"

if [ -f "$OUT_YAML" ]; then
    "$VENV_PY" - "$OUT_YAML" <<'PY'
import sys
import yaml

data = yaml.safe_load(open(sys.argv[1]))
provenance = (data or {}).get("provenance") or {}
search = provenance.get("graph_search")
if search is None:
    print("        provenance.graph_search is absent")
    sys.exit(1)
loss = search.get("topology_loss")
if loss is None:
    print("        provenance.graph_search.topology_loss is absent")
    sys.exit(2)
calls = search.get("hook_calls") or {}
print(f"        graph_search keys: {sorted(search)}")
print(f"        topology_loss    : {loss}")
print(f"        hook_calls       : {calls}")
if not calls.get("compile_applied"):
    print("        compile_applied is 0: this run judged TEMPLATES")
    sys.exit(3)
PY
    check "provenance.graph_search.topology_loss is present" $? \
        "provenance.graph_search.topology_loss in $OUT_YAML"
fi

echo
if [ "$fails" -ne 0 ]; then
    echo "e_g3_smoke: $fails check(s) FAILED. The real-simulator path is not"
    echo "ready for E-G3; fix what failed before running the oracle harness."
    exit 1
fi
echo "e_g3_smoke: every check passed. Cache is in $CACHE_DIR; reuse it with"
echo "the same --cache-dir so E-G3's runs do not resimulate what this did."
