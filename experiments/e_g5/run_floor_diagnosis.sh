#!/usr/bin/env bash
# GS-38 (b, c): the cache-only floor diagnosis, under the adapter the
# registered runs used.
#
# heteropilot's envelope key bands `link_bw`, and the GS-38 adapter moves T1,
# T2 and T3 into other bands, so under it every lookup of the registered
# predictions misses. This builds a scratch tree that is this checkout with
# exactly one file replaced -- `graphsearch/adapter.py` as of 367ba74, the
# commit before GS-38 -- and everything else linked, then runs the diagnosis
# from it. `floor_diagnosis.py` refuses to write its file on any cache miss.
#
#     bash experiments/e_g5/run_floor_diagnosis.sh
#
# Needs the registered caches: outputs/e_g5/cache and outputs/cache-eg5-high
# (gitignored; see REPRODUCE.md for the archive).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRE="$(mktemp -d)/pre-gs38"
mkdir -p "$PRE"
cp -r "$ROOT/graphsearch" "$PRE/graphsearch"
rm -rf "$PRE/graphsearch/__pycache__"
git -C "$ROOT" show 367ba74:graphsearch/adapter.py > "$PRE/graphsearch/adapter.py"
for entry in "$ROOT"/* "$ROOT"/.[!.]*; do
    name="$(basename "$entry")"
    case "$name" in graphsearch|.git) continue ;; esac
    ln -s "$entry" "$PRE/$name"
done
cd "$PRE"
PYTHONPATH="$PRE:$PRE/vendor/heteropilot" \
    "$PRE/vendor/heteropilot/.venv/bin/python" experiments/e_g5/floor_diagnosis.py "$@"
