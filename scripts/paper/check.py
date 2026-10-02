#!/usr/bin/env python
"""The draft's own rules, enforced. `make check` runs this.

Four checks, each for a failure that is invisible on a casual read:

1. **No numeric literal in a body section, in digits or in words.** A number
   typed into prose is a number whose provenance was dropped on the way in, and
   it goes stale silently the next time an experiment re-runs. Spelling it out
   does not help: "six to eight per cent" stood in this draft while the
   fixtures measured 4.5, 6.2 and 21, and the digit rule could not see it.
2. **No forbidden phrasing.** The research design names two claims this work
   may not make: that it is the first to represent a cluster as a graph, and
   that a top-K procedure guarantees a global optimum.
3. **A paragraph may assert only what `CLAIMS.md` calls `Established`.** Each
   paragraph carries `% claim: C<n>`. Two other statuses may be cited, and each
   needs its own deliberate marker, because they are not the same situation:
   `Pending` needs `% pending` (the result is not in), and `Not established`
   needs `% not-established` (the result IS in and it contradicts the claim --
   `CLAIMS.md` requires the paper to say so, in the indicative). Conflating
   them would let a negative result be written as though it were still
   awaited.
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

#: **A measured quantity spelled out in words.** The digit rule cannot see
#: these, and one got through: "six to eight per cent of placements never
#: simulate" stood in the draft while the fixtures measured 4.5 %, 6.2 % and
#: 21 % -- a figure that was wrong, inherited from an earlier result file, and
#: invisible to a checker looking for digits.
#:
#: Only patterns that name a QUANTITY are listed. Ordinary prose uses number
#: words constantly ("one of the five conditions", "two reasons"), and a rule
#: that flagged those would be turned off within a day.
WORDED = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)"
    r"(?:[\s-]+(?:to|and|or)[\s-]+\w+)?[\s-]+(?:per\s+cent|percent|"
    r"times|fold|milliseconds?|seconds?|gigabytes?|GB/s|Gbit/s|rps)\b",
    re.I,
)

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
    out, claims, pending, negative, body, start = [], [], False, False, [], 0
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
        if stripped.startswith("% not-established"):
            negative = True
            start = start or number
            continue
        if not stripped:
            if body:
                out.append((start or number, claims, pending, negative,
                            "\n".join(body)))
            claims, pending, negative, body, start = [], False, False, [], 0
            continue
        start = start or number
        body.append(line)
    if body:
        out.append((start, claims, pending, negative, "\n".join(body)))
    return out


def _anonymity_patterns() -> dict:
    """The one list, from `check_pdf.py`: the source and the PDF are held to
    the same identifying strings (revision rule 0.4)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_pdf", Path(__file__).resolve().parent / "check_pdf.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_pdf", module)
    spec.loader.exec_module(module)
    return module.ANONYMITY_PATTERNS


#: Hand-written LaTeX outside `sections/` that reaches the PDF. Generated
#: tables come from results files, which may name decision numbers; what they
#: print is held by `check_pdf.py` on the PDF itself.
HANDWRITTEN = (ROOT / "paper" / "main.tex", ROOT / "paper" / "tables" / "reuse.tex",
               ROOT / "paper" / "figures" / "concept_sec9.tex")


def anonymity_failures(paths) -> list[str]:
    """Identifying strings in prose a reviewer reads, comments excluded.

    Comments are the repository's own notes and never reach the PDF; a
    decision number there is how the source cites its record.
    """
    patterns = _anonymity_patterns()
    out = []
    for path in paths:
        text = re.sub(r"(?<!\\)%.*$", "", path.read_text(), flags=re.M)
        rel = path.relative_to(ROOT) if ROOT in path.parents else path
        for name, pattern in patterns.items():
            for match in pattern.finditer(text):
                out.append(f"{rel}: {name} {match.group(0)!r} -- the submission "
                           f"is double-blind (revision rule 0.4)")
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
            for match in WORDED.finditer(prose):
                failures.append(
                    f"{rel}: measured quantity spelled out as "
                    f"{match.group(0)!r}. Spelling a number does not give it "
                    f"provenance -- cite the macro."
                )

        failures += anonymity_failures([path])

        flat = re.sub(r"\s+", " ", prose)
        for pattern, why in FORBIDDEN:
            if re.search(pattern, flat, re.I):
                failures.append(f"{rel}: {why}")

        for number, claims, pending, negative, _body in paragraphs(raw):
            for cid in claims:
                state = status.get(cid)
                if state is None:
                    failures.append(f"{rel}:{number}: unknown claim {cid}")
                    continue
                if state.startswith("Established"):
                    continue
                bare = state.strip("*").split(",")[0].strip()
                if bare.lower().startswith("not established"):
                    if not negative:
                        failures.append(
                            f"{rel}:{number}: cites {cid}, which is "
                            f"`Not established` -- the experiment ran and "
                            f"contradicted it -- without a `% not-established` "
                            f"marker. CLAIMS.md requires the paper to say so; "
                            f"the marker is how you confirm the paragraph does."
                        )
                elif not pending:
                    failures.append(
                        f"{rel}:{number}: cites {cid}, which is {bare!r}, "
                        f"without a `% pending` marker. A claim that is not "
                        f"Established is written in a form that does not "
                        f"change when the result arrives."
                    )

        for match in re.finditer(r"\\pending\{([^}]*)\}", raw):
            line = raw[: match.start()].count("\n") + 1
            pendings.append(f"  {rel}:{line}  {match.group(1)}")

    if args.sections == SECTIONS:
        failures += anonymity_failures(HANDWRITTEN)

    print(f"pending placeholders: {len(pendings)}")
    for item in pendings:
        print(item)

    if failures:
        print(f"\ncheck FAILED: {len(failures)} problem(s)", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("\ncheck passed: no numeric literals, no forbidden claims, every "
          "cited claim Established, or marked pending, or marked "
          "not-established")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
