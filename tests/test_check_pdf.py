"""`scripts/paper/check_pdf.py` (revision R1.3), on fabricated logs and aux files.

The gate exists because a source-only check passed a PDF with tables 660 pt
wider than their column; these pin that each rule fails when it should and
only then.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _check_pdf():
    spec = importlib.util.spec_from_file_location(
        "check_pdf", ROOT / "scripts" / "paper" / "check_pdf.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_pdf"] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


C = _check_pdf()


def test_a_wide_overfull_box_fails_and_a_small_one_does_not() -> None:
    report = C.Report()
    C.check_log(
        "Overfull \\hbox (660.0pt too wide) in paragraph at lines 7--18\n"
        "Overfull \\hbox (3.2pt too wide) in paragraph at lines 40--41\n",
        report,
    )
    assert len(report.overfull) == 2
    assert len(report.failures) == 1 and "660.0 pt" in report.failures[0]


def test_only_the_last_pass_counts() -> None:
    report = C.Report()
    C.check_log(
        "LaTeX Warning: Reference `sec:eval' on page 1 undefined on input line 4.\n"
        "Rerunning TeX because main.aux changed\nclean second pass\n",
        report,
    )
    assert report.failures == []


def test_an_undefined_citation_fails() -> None:
    report = C.Report()
    C.check_log("LaTeX Warning: Citation `helix' on page 2 undefined on input line 9.\n",
                report)
    assert report.undefined == ["citation helix"]
    assert report.failures


def test_pages_count_up_to_the_references() -> None:
    aux = "\\relax\n\\newlabel{sec:refs}{{}{10}}\n"
    assert C.references_start(aux) == 10
    over = C.Report()
    C.check_pages(11, C.references_start(aux), over)
    assert over.content_pages == 10 and over.failures
    within = C.Report()
    C.check_pages(11, C.references_start("\\newlabel{sec:refs}{{}{9}}"), within)
    assert within.content_pages == 9 and within.failures == []
    no_bib = C.Report()
    C.check_pages(10, None, no_bib)
    assert no_bib.failures


def test_identifying_text_fails() -> None:
    report = C.Report()
    C.check_text("see github.com/someone and D127 and GS-38 and Swsok", report)
    assert {name for name, _ in report.anonymity} == {
        "account name", "repository URL", "deviation number", "decision number"}
    clean = C.Report()
    C.check_text("H4 bench prefix-caching knob; 100 GB/s; DGX-1; MD5", clean)
    assert clean.failures == []


def test_no_pdf_means_run_make_pdf_first(tmp_path: Path) -> None:
    report, status = C.run(tmp_path)
    assert status == 2 and "make -C paper pdf" in report.failures[0]


def _check_src():
    spec = importlib.util.spec_from_file_location(
        "paper_check", ROOT / "scripts" / "paper" / "check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["paper_check"] = module
    spec.loader.exec_module(module)
    return module


def test_the_source_check_holds_the_same_identifying_strings(tmp_path: Path) -> None:
    """R2.4: check.py refuses in prose what check_pdf.py refuses in the PDF,
    and leaves comments alone -- they are the repository's own notes."""
    src = _check_src()
    section = tmp_path / "x.tex"
    section.write_text(
        "%% GS-38 and D127 are how this source cites its record.\n"
        "Body text naming github.com/someone and decision GS-38.\n")
    failures = src.anonymity_failures([section])
    assert len(failures) == 2
    assert any("repository URL" in f for f in failures)
    assert any("decision number" in f for f in failures)
    assert src.anonymity_failures([ROOT / "paper" / "tables" / "reuse.tex"]) == []


def test_the_planner_is_named_and_a_pending_reference_is_counted(tmp_path: Path) -> None:
    """R2.3: one gloss is allowed, two are a planner left unnamed; and an
    entry whose arXiv number is not out yet is reported, not hidden."""
    src = _check_src()
    once = tmp_path / "a.tex"
    once.write_text("HeteroPilot, the existing planner, is cited.\n")
    twice = tmp_path / "b.tex"
    twice.write_text("The planner this work extends. %% the existing planner\n")
    assert src.unnamed_planner_failures([once]) == []
    assert src.unnamed_planner_failures([once, twice])
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{a,\n  note = {arXiv preprint, number pending}\n}\n"
                   "@article{b,\n  doi = {10.1/x}\n}\n")
    assert src.pending_references(bib) == ["a"]


def test_the_abstract_is_counted_with_a_macro_as_one_word(tmp_path: Path) -> None:
    """R3.2: at most 150 words; a macro prints one number, so it is one word."""
    src = _check_src()
    tex = tmp_path / "main.tex"
    tex.write_text("\\begin{abstract}\n%% a comment is not counted\n"
                   "Three words here, \\egfiveTtwoOverTone{}x apart, $p99$ ms.\n"
                   "\\end{abstract}\n")
    assert src.abstract_words(tex) == 7
    assert src.abstract_words() <= src.ABSTRACT_WORD_LIMIT


def test_the_room_before_the_references_is_read_through_log_wrapping() -> None:
    log = ("CONTENT-END: page 9, column 2, remaining 18.0869pt of 579.98688pt, baselineskip\n"
           " 12.0pt\n")
    report = C.Report()
    C.check_margin(log, report)
    assert round(report.margin_lines, 2) == 1.51 and report.margin_where == "page 9, column 2"
    left = C.Report()
    C.check_margin(log.replace("column 2", "column 1"), left)
    assert round(left.margin_pt, 1) == round(18.0869 + 579.98688, 1)
