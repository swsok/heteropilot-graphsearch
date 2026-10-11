"""The paper's rules that only the compiled PDF can check (revision R1.3).

`check.py` reads the sources and never compiles them, so a table set 660 pt
wider than its column, or a citation that resolves to nothing, passed it. This
reads what the build produced:

1. **Overfull boxes** in `main.log` wider than `OVERFULL_LIMIT_PT` fail, with
   their source line. Smaller ones are reported and allowed -- a word a few
   points past the margin is typesetting, not a missing column.
2. **Undefined references and citations** in `main.log` fail.
3. **Pages before the references** above `PAGE_LIMIT` fail. The references
   start where `main.tex` writes the `sec:refs` label into `main.aux`; with
   no bibliography yet the whole PDF counts.
4. **Anonymity patterns** in the PDF's text fail: what a double-blind
   reviewer reads is the PDF, not the source.

    python scripts/paper/check_pdf.py            # after `make -C paper pdf`

Exit 0 when everything passes; 1 with every failure listed; 2 when there is no
PDF to check, which means `make pdf` was not run.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Run as a script, this directory is sys.path[0], and its `numbers.py` (the
# macro generator) then shadows the standard library's `numbers` -- which
# `decimal`, and so pypdf, import. Drop it; nothing here imports a sibling.
if sys.path and Path(sys.path[0] or ".").resolve() == Path(__file__).resolve().parent:
    sys.path.pop(0)

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"

#: ISPASS 2026's limit, provisionally for 2027 (paper/VENUE.md).
PAGE_LIMIT = 9
OVERFULL_LIMIT_PT = 20.0

#: What a double-blind PDF must not contain (revision rule 0.4): the account
#: name, a repository host, a deviation number of the extended planner, or a
#: decision number of this repository. Decision numbers stay in the results
#: files and CLAIMS.md, which are not part of the submission.
ANONYMITY_PATTERNS = {
    "account name": re.compile(r"swsok", re.IGNORECASE),
    "repository URL": re.compile(r"github\.com/", re.IGNORECASE),
    "deviation number": re.compile(r"\bD1[0-9]{2}\b"),
    "decision number": re.compile(r"\bGS-[0-9]+\b"),
}

_OVERFULL = re.compile(
    r"Overfull \\hbox \((?P<pt>[0-9.]+)pt too wide\)(?P<where>[^\n]*)"
)
_UNDEFINED = re.compile(
    r"(Reference|Citation) [`'](?P<key>[^']+)' on page \d+ undefined"
)
_REFS_LABEL = re.compile(r"\\newlabel\{sec:refs\}\{\{[^}]*\}\{(?P<page>\d+)\}")


@dataclass
class Report:
    pages: int = 0
    content_pages: int = 0
    overfull: list[tuple[float, str]] = field(default_factory=list)
    undefined: list[str] = field(default_factory=list)
    anonymity: list[tuple[str, str]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    #: Room left where the content ends (`CONTENT-END` in the log), in pt and
    #: in lines of body text. Reported, not judged: a margin of zero passes
    #: here and fails on an installation that breaks one line differently.
    margin_pt: float | None = None
    margin_lines: float | None = None
    margin_where: str = ""


def final_pass(log: str) -> str:
    """The last TeX pass of a log that may hold several.

    Tectonic reruns TeX until the auxiliary files settle and keeps every
    pass's messages in one log; an undefined reference on the first pass is
    normal and resolved by the second. Only the last pass describes the PDF.
    """
    marker = "Rerunning TeX"
    return log.rsplit(marker, 1)[-1] if marker in log else log


_CONTENT_END = re.compile(
    r"CONTENT-END: page (?P<page>\d+), column (?P<col>[12]),\s*remaining "
    r"(?P<rem>-?[0-9.]+)pt of (?P<goal>[0-9.]+)pt,\s*baselineskip (?P<bl>[0-9.]+)pt")


def check_margin(log: str, report: Report) -> None:
    """The space left in the column where the content ends; an empty
    right-hand column is added when the content ends in the left one."""
    # TeX wraps its log at a fixed width, mid-token if need be; the wrap
    # inserts a newline and nothing else, so removing newlines undoes it.
    found = list(_CONTENT_END.finditer(final_pass(log).replace("\n", "")))
    if not found:
        return
    m = found[-1]
    goal, rem, bl = float(m["goal"]), float(m["rem"]), float(m["bl"])
    if goal >= 16000:          # \maxdimen: the content ended exactly on a page break
        rem = 0.0
    if m["col"] == "1":
        rem += goal
    report.margin_pt = rem
    report.margin_lines = rem / bl if bl else None
    report.margin_where = f"page {m['page']}, column {m['col']}"


def check_log(log: str, report: Report) -> None:
    last = final_pass(log)
    for match in _OVERFULL.finditer(last):
        report.overfull.append((float(match["pt"]), match["where"].strip()))
    for pt, where in report.overfull:
        if pt > OVERFULL_LIMIT_PT:
            report.failures.append(f"overfull hbox {pt:.1f} pt > {OVERFULL_LIMIT_PT:g} pt {where}")
    report.undefined = sorted({f"{m[1].lower()} {m['key']}" for m in _UNDEFINED.finditer(last)})
    for entry in report.undefined:
        report.failures.append(f"undefined {entry}")
    if (re.search(r"There were undefined (references|citations)", last)
            and not report.undefined):
        report.failures.append("LaTeX reports undefined references")


def references_start(aux: str) -> int | None:
    """The page `sec:refs` was written on, or None when there is no bibliography."""
    match = _REFS_LABEL.search(aux)
    return int(match["page"]) if match else None


def check_pages(pages: int, refs_page: int | None, report: Report) -> None:
    report.pages = pages
    # The references' first page may still carry body text above them, so
    # that page counts as content: a paper whose references start halfway
    # down page 10 has ten pages of content, not nine.
    report.content_pages = pages if refs_page is None else refs_page
    if report.content_pages > PAGE_LIMIT:
        report.failures.append(
            f"{report.content_pages} pages before the references > {PAGE_LIMIT}"
        )


def check_text(text: str, report: Report) -> None:
    for name, pattern in ANONYMITY_PATTERNS.items():
        for match in pattern.finditer(text):
            start = max(0, match.start() - 30)
            context = " ".join(text[start:match.end() + 20].split())
            report.anonymity.append((name, context))
    for name, context in report.anonymity:
        report.failures.append(f"anonymity: {name} in PDF text: ...{context}...")


def pdf_pages_and_text(pdf: Path) -> tuple[int, str]:
    from pypdf import PdfReader

    reader = PdfReader(pdf)
    return len(reader.pages), "\n".join(page.extract_text() or "" for page in reader.pages)


def run(paper: Path) -> tuple[Report, int]:
    pdf, log, aux = paper / "main.pdf", paper / "main.log", paper / "main.aux"
    report = Report()
    if not pdf.exists() or not log.exists():
        report.failures.append("no main.pdf / main.log: run `make -C paper pdf` first")
        return report, 2
    check_log(log.read_text(errors="replace"), report)
    check_margin(log.read_text(errors="replace"), report)
    pages, text = pdf_pages_and_text(pdf)
    check_pages(pages, references_start(aux.read_text(errors="replace")) if aux.exists() else None,
                report)
    check_text(text, report)
    return report, 1 if report.failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--paper", type=Path, default=PAPER)
    args = parser.parse_args(argv)

    report, status = run(args.paper)
    if status == 2:
        print(f"check-pdf: {report.failures[0]}", file=sys.stderr)
        return 2
    print(f"pages: {report.content_pages} before the references "
          f"(limit {PAGE_LIMIT}), {report.pages} in all")
    if report.margin_pt is not None:
        print(f"room before the references: {report.margin_pt:.1f} pt, about "
              f"{report.margin_lines:.1f} lines ({report.margin_where})")
    else:
        print("room before the references: unknown (no CONTENT-END in main.log)")
    print(f"overfull boxes: {len(report.overfull)} "
          f"({sum(pt > OVERFULL_LIMIT_PT for pt, _ in report.overfull)} over "
          f"{OVERFULL_LIMIT_PT:g} pt)")
    for pt, where in report.overfull:
        print(f"  {pt:7.1f} pt {where}")
    print(f"undefined references/citations: {len(report.undefined)}")
    print(f"anonymity hits: {len(report.anonymity)}")
    if report.failures:
        print("\ncheck-pdf FAILED:")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print("\ncheck-pdf passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
