#!/usr/bin/env python
"""Turn a results markdown table into a LaTeX table that still says where it came from.

Every file under `experiments/results/` is headed by a provenance banner -- one
of MOCK, REAL SIM or REAL HARDWARE -- and the work order's rule 3 says the
paper's tables carry that banner, as a tag in the caption. This script is the mechanism for
that rule rather than a reminder of it: a markdown file whose banner cannot be
classified produces no table at all and a non-zero exit.

That refusal is the point. A number that reaches a paper without its provenance
is indistinguishable from a measurement, and the banner is the only thing
standing between a mock figure and a performance claim.

What it does NOT do: compute, round or reformat a value. A cell is copied
through with TeX's special characters escaped and nothing else.

What it MAY do, and only as `scripts/paper/tables.yaml` says (revision R1.1):
choose which columns of a table the paper shows and in what order, rename their
headers, take a column from another table of the same file matched on the first
column, set two cells side by side as `a / b`, and set the float's width and
type size. A results file carries every column an experiment produced; a
two-column page cannot, and a table squeezed to fit was a table whose
correctness columns nobody could read. Every cell that appears is still the
markdown's own text.

Usage:
    python scripts/paper/md_to_tex.py --out-dir paper/tables experiments/results/*.md
    python scripts/paper/md_to_tex.py --out-dir paper/tables --all
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
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

#: The short form that goes in every caption. Since revision R1.2 it is the
#: only provenance a table carries: the long sentences below are said once,
#: in the evaluation's "Provenance tags" paragraph, instead of under each of
#: three MOCK tables. A table without its tag is still impossible -- a file
#: whose banner cannot be classified produces no table at all.
TAGS: dict[str, str] = {
    "mock": "MOCK",
    "real-sim": "REAL SIM",
    "hardware": "REAL HARDWARE",
}

#: What each tag means, per provenance kind. Deliberately not parameterised by
#: the markdown's own wording: two files phrasing the same banner differently
#: must still mean the same thing in the paper. The paper states these once
#: (`paper/sections/eval.tex`, "Provenance tags"), and a test holds the two
#: to the same words. `note=` puts one back under a table for a standalone use.
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


TABLES_YAML = REPO_ROOT / "scripts" / "paper" / "tables.yaml"

#: An unmapped table with more columns than this gets a warning: it is set
#: whole, and a reader of a two-column page will not see much of it.
MANY_COLUMNS = 7


class TableSpecError(ValueError):
    """`tables.yaml` names a column, a join or a size the table does not have."""


@dataclass
class TableSpec:
    columns: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)
    joins: list = field(default_factory=list)
    width: str = "column"
    size: str = "small"


_SIZES = ("small", "footnotesize", "scriptsize")


def load_specs(path: Path = TABLES_YAML) -> dict[str, TableSpec]:
    """`tables.yaml`, keyed by the label stem a table is written under."""
    if not path.exists():
        return {}
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs = {}
    for key, entry in raw.items():
        spec = TableSpec(
            columns=list(entry.get("columns", [])),
            labels={str(k): str(v) for k, v in (entry.get("labels") or {}).items()},
            joins=list(entry.get("join", [])),
            width=entry.get("width", "column"),
            size=entry.get("size", "small"),
        )
        if spec.width not in ("column", "page"):
            raise TableSpecError(f"{key}: width must be column or page, not {spec.width!r}")
        if spec.size not in _SIZES:
            raise TableSpecError(f"{key}: size must be one of {_SIZES}, not {spec.size!r}")
        specs[str(key)] = spec
    return specs


def _find(tables, names: list[str], key: str):
    for header, rows in tables:
        if all(name in header for name in names):
            return header, rows
    raise TableSpecError(f"{key}: no table in the file has every header of {names}")


def apply_spec(key: str, header: list[str], rows: list[list[str]], spec: TableSpec,
               tables) -> tuple[list[str], list[list[str]]]:
    """The columns `spec` names, in its order, under its labels.

    A join adds columns from another table of the same file, matched on the
    first column (a fixture, a placement); a missing match is `-`, never a
    guess. A composite column is `{name:, cells: [a, b], sep:}` and sets the
    two cells side by side. A column the table does not have is an error,
    so a renamed column in a results script cannot silently drop out.
    """
    width = len(header)
    records = [dict(zip(header, (row + [""] * width)[:width], strict=True)) for row in rows]
    for join in spec.joins:
        other_header, other_rows = _find(tables, join["find"], key)
        n = len(other_header)
        index = {row[0]: dict(zip(other_header, (row + [""] * n)[:n], strict=True))
                 for row in other_rows}
        for record in records:
            match = index.get(record[header[0]], {})
            for column in join["columns"]:
                record[column] = match.get(column, "-")
    available = set(header) | {c for join in spec.joins for c in join["columns"]}
    out_header, getters = [], []
    for column in spec.columns:
        if isinstance(column, dict):
            for cell in column["cells"]:
                if cell not in available:
                    raise TableSpecError(
                        f"{key}: composite column names {cell!r}, not in the table")
            sep = column.get("sep", " / ")
            getters.append(lambda r, cells=column["cells"], sep=sep: sep.join(r[c] for c in cells))
            out_header.append(spec.labels.get(column["name"], column["name"]))
        else:
            if column not in available:
                raise TableSpecError(f"{key}: column {column!r} is not in the table "
                                     f"(has {sorted(available)})")
            getters.append(lambda r, c=column: r[c])
            out_header.append(spec.labels.get(column, column))
    return out_header, [[get(r) for get in getters] for r in records]


#: A table with more columns than this spans both columns of the page. The
#: venue is two-column (IEEE conference, ISPASS); a twelve-column table set in
#: one column is either 2x too wide or unreadably small.
WIDE_COLUMNS = 6


def render(
    header: list[str],
    rows: list[list[str]],
    *,
    caption: str,
    label: str,
    note: str | None = None,
    source: str,
    kind: str,
    width: str | None = None,
    size: str = "small",
) -> str:
    """One `table` float: `booktabs` rules, the provenance tag in the caption,
    and a note underneath only when one is passed."""
    spec = column_spec(header, rows)
    # Wide tables span the page; either kind is shrunk only if it still does
    # not fit (`max width`), never enlarged, so a narrow table keeps its size.
    # `tables.yaml` says which, when it maps the table.
    wide = len(header) > WIDE_COLUMNS if width is None else width == "page"
    env = "table*" if wide else "table"
    width = "\\textwidth" if wide else "\\columnwidth"
    body = [
        f"%% Generated by scripts/paper/md_to_tex.py from {source}.",
        "%% Do not edit: `make tables` overwrites it. Edit the experiment script.",
        f"\\begin{{{env}}}[t]",
        # The banner goes in the CAPTION. A reader skimming the list of
        # tables, or glancing at one out of context, sees the provenance
        # without having to find a footnote -- and a mock figure read as a
        # measurement is the one mistake this whole mechanism exists to
        # prevent.
        f"  \\caption{{{escape_tex(caption)}~\\sourcetag{{{TAGS[kind]}}}}}",
        f"  \\label{{{label}}}",
        f"  \\{size}",
        f"  \\begin{{adjustbox}}{{max width={width}}}",
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
        "  \\end{adjustbox}",
    ]
    if note is not None:
        # adjustbox leaves TeX in horizontal mode; without the paragraph
        # break the note is set beside a narrow table, not under it.
        body += ["  \\par", "  \\vspace{2pt}", f"  \\footnotesize {note}"]
    body += [
        f"\\end{{{env}}}",
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
    specs = load_specs()
    for position, (header, rows) in enumerate(tables, start=1):
        suffix = "" if position == 1 else f"_{position}"
        key = f"{path.stem}{suffix}"
        target = out_dir / f"{key}.tex"
        spec = specs.get(key)
        width, size = None, "small"
        if spec is not None:
            header, rows = apply_spec(key, header, rows, spec, tables)
            width, size = spec.width, spec.size
        elif len(header) > MANY_COLUMNS:
            print(f"md_to_tex: {key} has {len(header)} columns and no entry in "
                  f"tables.yaml; set whole", file=sys.stderr)
        target.write_text(
            render(
                header,
                rows,
                width=width,
                size=size,
                caption=caption if position == 1 else f"{caption} (continued)",
                label=f"tab:{path.stem}{suffix}",
                source=source,
                kind=kind,
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
