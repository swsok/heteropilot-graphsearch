"""Derive the registered real-lab holdout fixture from the committed real one.

Preregistration E-G7, holdout 2: "the P3 hardware fixture with exactly one
change: the uplink reservation on one node altered from its measured value.
The variant is derived mechanically from the committed real fixture; the change
is a single field, recorded in the result file, so that what is being held out
is the *topology condition* and not a different cluster."

Mechanical means this script: it edits one scalar and refuses to run if the
file it is pointed at does not have exactly the shape it expects. Anything
else -- a hand edit, a second field, a different node -- would make the holdout
a different cluster, which the registration names as the thing to avoid.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

#: The port to alter. It has to be one the candidates under test actually
#: cross, or the holdout tests nothing: `gpu0-gpu2` (T2's PCIe path) declares
#: `shared_resource: port-gpu0`, while `gpu0-gpu1` (T1's NVLink path) declares
#: none, so this single field separates the two placements rather than moving
#: both or neither.
PORT = "port-gpu0"

#: 60 % of the measured 25.12 GB/s capacity, the same fraction E-G4's
#: background generator held. Not a measurement: see the result file.
RESERVED = 15.07


def derive(source: pathlib.Path, out: pathlib.Path) -> str:
    text = source.read_text()
    block = re.search(
        rf"^- id: {re.escape(PORT)}\n((?:  .*\n)+)", text, re.M
    )
    if block is None:
        raise SystemExit(f"{source}: no shared resource '{PORT}'")
    body = block.group(1)
    if not re.search(r"^  reserved: 0\.0$", body, re.M):
        raise SystemExit(
            f"{source}: '{PORT}' does not have 'reserved: 0.0'; this script "
            "changes exactly one scalar and will not guess which"
        )
    new_body = re.sub(r"^  reserved: 0\.0$", f"  reserved: {RESERVED}", body, count=1, flags=re.M)
    patched = text[: block.start(1)] + new_body + text[block.end(1) :]
    if patched.count(f"reserved: {RESERVED}") != 1:
        raise SystemExit("refusing to write: more than one field changed")

    header = (
        "# DERIVED FIXTURE -- do not hand-edit. Regenerate with\n"
        "#   python experiments/scripts/make_holdout_fixture.py\n"
        "#\n"
        f"# Source: {source.name}\n"
        f"# Change: shared_resources[{PORT}].reserved 0.0 -> {RESERVED} (GB/s)\n"
        "#\n"
        "# This is the registered E-G7 holdout 2. The reservation is NOT a\n"
        "# measurement: E-G4 showed this node's PCIe ports are not physically\n"
        "# shared, so it is a variation of the topology ASSUMPTION the search\n"
        "# must respond to, not a claim about the hardware. Every other field,\n"
        "# including every `source:` tag, is inherited unchanged from the\n"
        "# source fixture and keeps whatever provenance it had there.\n"
    )
    out.write_text(header + patched)
    return f"{PORT}.reserved 0.0 -> {RESERVED}"


def main(argv: list[str] | None = None) -> int:
    root = pathlib.Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=pathlib.Path,
                    default=root / "fixtures" / "clusters" / "real-a40x8.v2.yaml")
    ap.add_argument("--out", type=pathlib.Path,
                    default=root / "fixtures" / "clusters" / "real-lab-holdout.v2.yaml")
    args = ap.parse_args(argv)
    change = derive(args.source, args.out)
    print(f"wrote {args.out} ({change})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
