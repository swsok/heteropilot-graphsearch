#!/usr/bin/env python
"""The draft's own rules, enforced. `make check` runs this.

Four checks, each for a failure that is invisible on a casual read:

1. **No numeric literal in a body section.** A number typed into prose is a
   number whose provenance was dropped on the way in, and it goes stale
   silently the next time an experiment re-runs. Every figure comes from
   `numbers.tex`, generated from named cells of named results files.
2. **No forbidden phrasing.** The research design names two claims this work
   may not make: that it is the first to represent a cluster as a graph, and
   that a top-K procedure guarantees a global optimum.
3. **A paragraph may assert only what `CLAIMS.md` calls `Established`.** Each
   paragraph carries `% claim: C<n>`; a claim that is `Pending` may still be
   cited, but the paragraph must also carry `% pending`, which is what the
   `\\pending` macro marks in the margin.
4. **Every `\\pending` is listed**, so the count is a number somebody looks at
   rather than a habit.

Exit status is non-zero if any check fails. The `\\pending` list is printed
either way -- it is the draft's own to-do, not an error.

    python scripts/paper/check.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECTIONS = ROOT / "paper" / "sections"
CLAIMS = ROOT / "paper" / "CLAIMS.md"

#: Research design section 13. Matched case-insensitively against the body with
#: comments and macros stripped, so a phrase split over two lines is still
#: found.
FORBIDDEN: tuple[tuple[str, str], ...] = (
    (r"first\s+to\s+(represent|model)\s+.{0,40}\bgraph",
     "claims to be the first graph representation of a cluster (Helix does "
     "graph-based placement already)"),
    (r"top-?\$?K\$?\s+.{0,30}\bguarantee",
     "claims a top-K procedure guarantees an optimum; it does not, and this "
     "search's contribution is that it reports what it never evaluated"),
    (r"\bguarantee[sd]?\s+.{0,20}\bglobal\s+optim",
     "claims a global optimum"),
)

#: **A decimal or a percentage**, which is what the rule names. Not every
#: numeral: `128` devices and `$K = 16$` are design constants fixed by the
#: pre-registration, and they do not go stale when an experiment re-runs --
#: which is the failure the rule exists to prevent. A measured quantity is
#: almost always a decimal or a percentage, and those must come from
#: `numbers.tex`.
LITERAL = re.compile(r"(?<![\w\\{[.])(\d+\.\d+|\d+\s*\\?%)(?![\w}\]])")

#: Sections exempt from the literal check, with the reason. Empty on purpose:
#: an exemption is a decision, and the file records who made it and why rather
#: than letting one accumulate silently.
WHITELIST: dict[str, str] = {}


def strip_tex(text: str) -> str:
    """Comments, macro NAMES and float bodies out; running prose left in.

    Table floats are `\\input` rather than written here, so anything inside a
    `table` or `figure` environment in a section is hand-written and exempt --
    `\\sourcetag{MOCK}` is not prose. `\\label`, `\\ref` and `\\pending` take
    identifiers, not numbers a reader reads.
    """
    text = re.sub(r"(?m)^\s*%.*$", "", text)
    text = re.sub(r"(?<!\\)%.*$", "", text, flags=re.M)
    text = re.sub(r"\\begin\{(table|figure)\*?\}.*?\\end\{\1\*?\}", "",
                  text, flags=re.S)
    text = re.sub(r"\\(label|ref|eqref|cite|input|pending|sourcetag)\{[^}]*\}",
                  "", text)
    # A macro invocation is a reference to numbers.tex, which is the approved
    # route; its NAME may contain digits (\egfourBusbwTwo) and must not be read
    # as a literal.
    text = re.sub(r"\\[A-Za-z@]+", " ", text)
    return text


def claim_status() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in CLAIMS.read_text().splitlines():
        m = re.match(r"^\| (C\d+) \|(.+)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) >= 3:
            out[m.group(1)] = re.sub(r"\[\^\w+\]", "", cells[-1]).strip()
    return out


def paragraphs(text: str) -> list[tuple[int, list[str], bool, str]]:
    """(line number, claim ids, is-pending, body) per paragraph.

    A paragraph is a run of lines up to a blank one. Its `% claim:` and
    `% pending` markers may sit on the lines immediately above it, which is
    where they read most naturally.
    """
    out, claims, pending, body, start = [], [], False, [], 0
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("% claim:"):
            claims += re.findall(r"C\d+", stripped)
            start = start or number
            continue
        if stripped.startswith("% pending"):
            pending = True
            start = start or number
            continue
        if not stripped:
            if body:
                out.append((start or number, claims, pending, "\n".join(body)))
            claims, pending, body, start = [], False, [], 0
            continue
        start = start or number
        body.append(line)
    if body:
        out.append((start, claims, pending, "\n".join(body)))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", type=Path, default=SECTIONS)
    args = parser.parse_args(argv)

    status = claim_status()
    if not status:
        print("check: CLAIMS.md has no id'd rows", file=sys.stderr)
        return 1

    failures: list[str] = []
    pendings: list[str] = []

    for path in sorted(args.sections.glob("*.tex")):
        raw = path.read_text()
        # `--sections` may point outside the repo (the checker's own tests
        # do), so the display path degrades to the absolute one rather
        # than raising.
        rel = path.relative_to(ROOT) if ROOT in path.parents else path
        prose = strip_tex(raw)

        if path.name not in WHITELIST:
            for match in LITERAL.finditer(prose):
                failures.append(
                    f"{rel}: numeric literal {match.group(0)!r} in prose. Add "
                    f"it to scripts/paper/numbers.yaml and cite the macro."
                )

        flat = re.sub(r"\s+", " ", prose)
        for pattern, why in FORBIDDEN:
            if re.search(pattern, flat, re.I):
                failures.append(f"{rel}: {why}")

        for number, claims, pending, _body in paragraphs(raw):
            for cid in claims:
                state = status.get(cid)
                if state is None:
                    failures.append(f"{rel}:{number}: unknown claim {cid}")
                elif not state.startswith("Established") and not pending:
                    failures.append(
                        f"{rel}:{number}: cites {cid}, which is "
                        f"{state.split(',')[0]!r}, without a `% pending` "
                        f"marker. A claim that is not Established is written "
                        f"in a form that does not change when the result "
                        f"arrives."
                    )

        for match in re.finditer(r"\\pending\{([^}]*)\}", raw):
            line = raw[: match.start()].count("\n") + 1
            pendings.append(f"  {rel}:{line}  {match.group(1)}")

    print(f"pending placeholders: {len(pendings)}")
    for item in pendings:
        print(item)

    if failures:
        print(f"\ncheck FAILED: {len(failures)} problem(s)", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("\ncheck passed: no numeric literals, no forbidden claims, every "
          "cited claim Established or marked pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
