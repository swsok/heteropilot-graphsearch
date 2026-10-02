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
