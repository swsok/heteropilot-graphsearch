#!/usr/bin/env python
"""Turn a results markdown table into a LaTeX table that still says where it came from.

Every file under `experiments/results/` is headed by a provenance banner -- one
of MOCK, REAL SIM or REAL HARDWARE -- and the work order's rule 3 says the
paper's tables carry that banner as a note. This script is the mechanism for
that rule rather than a reminder of it: a markdown file whose banner cannot be
classified produces no table at all and a non-zero exit.

That refusal is the point. A number that reaches a paper without its provenance
is indistinguishable from a measurement, and the banner is the only thing
standing between a mock figure and a performance claim.

What it does NOT do: compute, round, reorder or reformat a value. A cell is
copied through with TeX's special characters escaped and nothing else. If a
table needs a different shape in the paper, the experiment script that writes
the markdown is what changes, so the markdown and the paper cannot disagree.

Usage:
    python scripts/paper/md_to_tex.py --out-dir paper/tables experiments/results/*.md
    python scripts/paper/md_to_tex.py --out-dir paper/tables --all
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: Where `--all` looks. Relative to the repository root, which is this file's
#: great-grandparent: scripts/paper/md_to_tex.py -> scripts/paper -> scripts -> root.
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "experiments" / "results"

#: The three banners rule 3 allows, most specific first. "REAL SIM" has to be
#: tested before "MOCK" would ever match, and "REAL HARDWARE" before "REAL SIM",
#: because a hardware banner naming its simulator cache would otherwise be
#: filed as a simulation.
BANNERS: tuple[tuple[str, str], ...] = (
    ("REAL HARDWARE", "hardware"),
    ("REAL SIM", "real-sim"),
    ("MOCK", "mock"),
)

#: What the note under each table says, per provenance kind. Deliberately not
#: parameterised by the markdown's own wording: two files phrasing the same
#: banner differently must still produce the same claim in the paper.
NOTES: dict[str, str] = {
    "mock": (
        "Mock predictor. \\textbf{These are not performance numbers.} The mock obeys the "
        "same physics as the elimination bounds, which is what makes a disagreement with "
        "the oracle meaningful, but no figure here is a measurement or a simulation of "
        "any hardware."
    ),
    "real-sim": (
        "LLMServingSim. \\textbf{Simulated, not measured.} Figures are the simulator's "
        "output under the cache named in the source file; no hardware was run."
    ),
    "hardware": (
        "Measured on hardware. The node serials are named in the source file. Percentiles "
        "are the median of the repetitions with the range reported; a single trial is not "
        "reported as a measurement."
    ),
}

#: Characters TeX would otherwise read as markup. Ordered dict semantics matter:
#: the backslash has to be replaced first or it would escape the escapes.
_TEX_ESCAPES: tuple[tuple[str, str], ...] = (
    ("\\", "\\textbackslash{}"),
    ("&", "\\&"),
    ("%", "\\%"),
    ("$", "\\$"),
    ("#", "\\#"),
    ("_", "\\_"),
    ("{", "\\{"),
    ("}", "\\}"),
    ("~", "\\textasciitilde{}"),
    ("^", "\\textasciicircum{}"),
)

#: A markdown table's separator row: |---|:---:|---:| and so on.
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")

#: `**bold**` and `` `code` `` are the only inline markup the results files use.
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")

#: A cell that is a bare number, possibly signed, possibly with a percent sign.
#: Used only to choose a column's alignment, never to reinterpret a value.
_NUMERIC = re.compile(r"^[-+]?\d+(\.\d+)?\s*%?$")


class BannerError(Exception):
    """A results file whose provenance cannot be read. Never recoverable here."""


def classify_banner(text: str) -> tuple[str, str]:
    """Return (kind, the banner line) for a results markdown file.

    Only the first 20 lines are considered: a banner is a header, and a file
    that mentions "REAL HARDWARE" halfway down in prose is discussing hardware,
    not claiming to be it.
    """
    head = text.splitlines()[:20]
    for line in head:
        upper = line.upper()
        for marker, kind in BANNERS:
            if marker in upper:
                return kind, line.strip().lstrip("> ").strip()
    raise BannerError(
        "no provenance banner in the first 20 lines; expected one of "
        + ", ".join(marker for marker, _ in BANNERS)
    )


def escape_tex(text: str) -> str:
    """Escape TeX specials, after unwrapping the inline markdown the results use."""
    text = _BOLD.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    for char, replacement in _TEX_ESCAPES:
        text = text.replace(char, replacement)
    return text


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def find_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Every GFM table in the file, in order, as (header, rows).

    A table is a header line, a separator line, and the body rows that follow
    it unbroken. Anything else is prose and is not this script's business.
    """
    lines = text.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index < len(lines) - 1:
        if "|" in lines[index] and _SEPARATOR.match(lines[index + 1]):
            header = _split_row(lines[index])
            rows: list[list[str]] = []
            cursor = index + 2
            while cursor < len(lines) and "|" in lines[cursor]:
                rows.append(_split_row(lines[cursor]))
                cursor += 1
            tables.append((header, rows))
            index = cursor
        else:
            index += 1
    return tables


def column_spec(header: list[str], rows: list[list[str]]) -> str:
    """`l` for the first column, `r` for a column whose every cell is a number.

    Alignment is the only formatting decision this script makes, and it is made
    from the data rather than by hand so that a regenerated table cannot drift
    from the markdown it came from.
    """
    spec = ["l"]
    for position in range(1, len(header)):
        cells = [row[position] for row in rows if position < len(row)]
        numeric = bool(cells) and all(_NUMERIC.match(cell) for cell in cells)
        spec.append("r" if numeric else "l")
    return "".join(spec)


def title_of(text: str) -> str:
    """The file's `# ` heading, or an empty string. Becomes the caption."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def render(
    header: list[str],
    rows: list[list[str]],
    *,
    caption: str,
    label: str,
    note: str,
    source: str,
) -> str:
    """One `table` float. `booktabs` rules, and the provenance note underneath."""
    spec = column_spec(header, rows)
    body = [
        f"%% Generated by scripts/paper/md_to_tex.py from {source}.",
        "%% Do not edit: `make tables` overwrites it. Edit the experiment script.",
        "\\begin{table}[t]",
        f"  \\caption{{{escape_tex(caption)}}}",
        f"  \\label{{{label}}}",
        "  \\small",
        f"  \\begin{{tabular}}{{{spec}}}",
        "    \\toprule",
        "    " + " & ".join(escape_tex(cell) for cell in header) + " \\\\",
        "    \\midrule",
    ]
    for row in rows:
        padded = (row + [""] * len(header))[: len(header)]
        body.append("    " + " & ".join(escape_tex(cell) for cell in padded) + " \\\\")
    body += [
        "    \\bottomrule",
        "  \\end{tabular}",
        "  \\vspace{2pt}",
        f"  \\footnotesize {note}",
        "\\end{table}",
        "",
    ]
    return "\n".join(body)


def convert(path: Path, out_dir: Path) -> list[Path]:
    """Convert one results file. Returns the paths written, in order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8")
    kind, _banner = classify_banner(text)
    tables = find_tables(text)
    if not tables:
        raise BannerError(f"{path}: banner is {kind}, but the file has no table")

    caption = title_of(path.read_text(encoding="utf-8")) or path.stem
    source = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
    written: list[Path] = []
    for position, (header, rows) in enumerate(tables, start=1):
        suffix = "" if position == 1 else f"_{position}"
        target = out_dir / f"{path.stem}{suffix}.tex"
        target.write_text(
            render(
                header,
                rows,
                caption=caption if position == 1 else f"{caption} (continued)",
                label=f"tab:{path.stem}{suffix}",
                note=NOTES[kind],
                source=source,
            ),
            encoding="utf-8",
        )
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="md_to_tex.py",
        description="Results markdown tables to LaTeX, provenance banner included.",
    )
    parser.add_argument("inputs", nargs="*", type=Path, help="results markdown files")
    parser.add_argument(
        "--all", action="store_true", help=f"convert every .md under {RESULTS_DIR}"
    )
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "paper" / "tables")
    args = parser.parse_args(argv)

    inputs = sorted(args.inputs)
    if args.all:
        inputs = sorted(RESULTS_DIR.glob("*.md"))
    if not inputs:
        print("md_to_tex: nothing to convert", file=sys.stderr)
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for path in inputs:
        try:
            for target in convert(path, args.out_dir):
                print(f"{path} -> {target}")
        except BannerError as exc:
            print(f"md_to_tex: REFUSED {path}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
