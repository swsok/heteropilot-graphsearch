#!/usr/bin/env bash
# The gitignored outputs a reproduction needs, packed with a checksum manifest.
#
# `outputs/` is ignored on purpose -- most of it is simulator scratch (several
# GB) -- but a handful of files are inputs to a re-render or a cache-only run
# and cannot be regenerated without hours of simulation. They are listed here,
# once, so REPRODUCE.md and the archive cannot disagree.
#
#     bash scripts/reproduce/archive_outputs.sh            # writes outputs-archive.tar.gz
#     bash scripts/reproduce/archive_outputs.sh --verify   # checks an unpacked archive
#
# Where the archive is hosted (a release asset, Zenodo) is decided at
# submission; REPRODUCE.md names it then.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

FILES=(
    outputs/eg3.json              # E-G3 re-render (--from-json); cold timings
    outputs/eg3-cache.json        # E-G3 cache-check section (P1.4)
    outputs/cache-eg3             # E-G3 envelope cache: correctness columns in minutes
    outputs/e_g6/scale.json       # E-G6 re-render and the scale figures
    outputs/e_g5/cache            # E-G5 registered predictions, low/knee (floor diagnosis)
    outputs/cache-eg5-high        # E-G5 exhaustive high scope (row 8), floor diagnosis
    outputs/cache-eg5-gs38        # E-G5 post-hoc re-prediction (GS-38)
)

if [ "${1:-}" = --verify ]; then
    sha256sum -c outputs-archive.sha256
    exit
fi

for f in "${FILES[@]}"; do
    [ -e "$f" ] || { echo "archive_outputs: $f is missing" >&2; exit 1; }
done
find "${FILES[@]}" -type f | LC_ALL=C sort > outputs-archive.list
xargs -a outputs-archive.list sha256sum > outputs-archive.sha256
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -czf outputs-archive.tar.gz -T outputs-archive.list outputs-archive.sha256
rm outputs-archive.list
echo "outputs-archive.tar.gz: $(du -h outputs-archive.tar.gz | cut -f1), $(wc -l < outputs-archive.sha256) files"
