#!/usr/bin/env bash
# P7.2: reproduce one paper table in a container that has never seen this
# machine's checkout -- no venv, no outputs/, no caches, no untracked file.
#
# What goes in is exactly what is committed: `git archive` of this commit and
# of the pinned heteropilot submodule. Inside, a fresh Python 3.10 venv is
# built from requirements.txt, the E-G1 toy pilot (MOCK) is regenerated over
# its own committed copy, and both the results file and the LaTeX table made
# from it must come out byte-identical to the committed ones.
#
#     bash scripts/reproduce/clean_container.sh            # E-G1 (default)
#     LOG=path bash scripts/reproduce/clean_container.sh
#
# Needs docker and network access to PyPI and to uv's Python downloads. The
# base image is only a carrier for `uv`; the interpreter the code runs on is the
# one uv installs (3.10, the version CI and heteropilot pin).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${IMAGE:-python:3.11-slim}"
LOG="${LOG:-$ROOT/experiments/reproduce/clean-container.log}"

if [ -n "$(git -C "$ROOT" status --porcelain -- . ':!outputs')" ]; then
    echo "clean_container: the checkout has uncommitted changes; the run would" >&2
    echo "not test what is committed. Commit or stash first." >&2
    exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git -C "$ROOT" archive --format=tar -o "$WORK/src.tar" HEAD
git -C "$ROOT/vendor/heteropilot" archive --format=tar -o "$WORK/heteropilot.tar" HEAD
SHA="$(git -C "$ROOT" rev-parse HEAD)"
HP_SHA="$(git -C "$ROOT/vendor/heteropilot" rev-parse HEAD)"
DIGEST="$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE" 2>/dev/null || echo "$IMAGE")"

mkdir -p "$(dirname "$LOG")"
{
    echo "# clean-container reproduction, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "graphsearch commit : $SHA"
    echo "heteropilot commit : $HP_SHA"
    echo "image              : $DIGEST"
    echo
    docker run --rm --network host -v "$WORK:/in:ro" "$IMAGE" bash -euo pipefail -c '
        pip install -q --root-user-action=ignore uv >/dev/null
        uv python install -q 3.10
        mkdir -p /w/vendor/heteropilot && cd /w
        tar -xf /in/src.tar
        tar -xf /in/heteropilot.tar -C vendor/heteropilot
        uv venv -q --python 3.10 .venv
        uv pip install -q --python .venv/bin/python -r requirements.txt
        echo "python             : $(.venv/bin/python --version)"
        echo "networkx           : $(.venv/bin/python -c "import networkx; print(networkx.__version__)")"
        echo "untracked outputs/ : $(ls outputs 2>/dev/null | wc -l) entries"
        echo
        export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
        cp experiments/results/e_g1_toy_pilot.md /tmp/committed.md
        start=$(date +%s)
        .venv/bin/python experiments/scripts/e_g1_toy_pilot.py \
            --out experiments/results/e_g1_toy_pilot.md
        echo "regenerated in $(( $(date +%s) - start )) s"
        if cmp -s /tmp/committed.md experiments/results/e_g1_toy_pilot.md; then
            echo "e_g1_toy_pilot.md  : BYTE-IDENTICAL to the committed file"
        else
            echo "e_g1_toy_pilot.md  : DIFFERS"; diff /tmp/committed.md experiments/results/e_g1_toy_pilot.md | head -40
            exit 1
        fi
        .venv/bin/python scripts/paper/md_to_tex.py \
            experiments/results/e_g1_toy_pilot.md --out-dir /tmp/tables >/dev/null
        sha256sum /tmp/tables/e_g1_toy_pilot.tex | sed "s|/tmp/tables/||"
    '
} 2>&1 | tee "$LOG"
status=${PIPESTATUS[0]}

# The table the container made must be the one this checkout makes.
HOST_TEX="$(mktemp -d)"
"$ROOT/.venv/bin/python" "$ROOT/scripts/paper/md_to_tex.py" \
    "$ROOT/experiments/results/e_g1_toy_pilot.md" --out-dir "$HOST_TEX" >/dev/null
HOST_SUM="$(cd "$HOST_TEX" && sha256sum e_g1_toy_pilot.tex)"
if grep -qF "$HOST_SUM" "$LOG"; then
    echo "e_g1_toy_pilot.tex : BYTE-IDENTICAL to this checkout's (sha256 above)" | tee -a "$LOG"
else
    echo "e_g1_toy_pilot.tex : DIFFERS from this checkout's ($HOST_SUM)" | tee -a "$LOG"
    status=1
fi
rm -rf "$HOST_TEX"
exit "$status"
