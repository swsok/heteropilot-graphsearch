# The paper build. Run from this directory: `make -C paper paper`, or `make
# paper` with this as the working directory.
#
# `paper` depends on `tables`, always. A paper built without regenerating its
# tables is a paper whose numbers are whatever was in the tree last time, and
# that is exactly the failure the generated-tables rule exists to prevent. If
# you want to compile without touching the tables, say `make pdf` and know that
# you did.

PYTHON ?= python
ROOT   := $(abspath $(CURDIR)/..)

# Every results file, so `make tables` cannot be silently out of date because
# an experiment was added and nobody edited this file.
RESULTS := $(wildcard $(ROOT)/experiments/results/*.md)

# Figure generators live one per file here and are added by P4 and P6. The
# directory is allowed to be empty; `make figures` says how many it ran rather
# than pretending either way.
FIGURE_SCRIPTS := $(wildcard $(ROOT)/scripts/paper/figures/*.py)

.PHONY: paper pdf tables figures clean help

help:
	@echo "make tables   regenerate tables/*.tex from experiments/results/*.md"
	@echo "make figures  run every generator in scripts/paper/figures/"
	@echo "make paper    tables + figures + main.pdf"
	@echo "make pdf      main.pdf from what is already in the tree"
	@echo "make clean    remove build artefacts and generated tables"

paper: tables figures pdf

# Tectonic first, on purpose: it resolves its own package set from a pinned
# bundle, so the same source builds the same way on a machine that has no TeX
# installation and on one that has a decade of accumulated local styles. The
# other two are the fallback for a machine that has a full TeX Live and no
# network.
pdf:
	@set -e; \
	if command -v tectonic >/dev/null 2>&1; then \
	    tectonic --keep-logs --print main.tex; \
	elif command -v latexmk >/dev/null 2>&1; then \
	    latexmk -pdf -halt-on-error main.tex; \
	elif command -v pdflatex >/dev/null 2>&1; then \
	    pdflatex -halt-on-error main.tex && pdflatex -halt-on-error main.tex; \
	else \
	    echo "make pdf: no LaTeX engine found." >&2; \
	    echo "  Install one of: tectonic (a single binary, no TeX install" >&2; \
	    echo "  needed -- see https://tectonic-typesetting.github.io), or" >&2; \
	    echo "  texlive-full with latexmk." >&2; \
	    exit 1; \
	fi

# md_to_tex.py REFUSES a results file whose provenance banner it cannot read,
# and exits non-zero when it does. That failure propagates here deliberately:
# an untraceable number must stop the build, not appear in the paper with the
# banner missing.
tables: $(RESULTS)
	@mkdir -p tables
	$(PYTHON) $(ROOT)/scripts/paper/md_to_tex.py --all --out-dir $(CURDIR)/tables

figures:
	@mkdir -p figures
	@if [ -z "$(FIGURE_SCRIPTS)" ]; then \
	    echo "make figures: no generators in scripts/paper/figures/ yet (P4, P6.3)"; \
	else \
	    for script in $(FIGURE_SCRIPTS); do \
	        echo "make figures: $$script"; \
	        $(PYTHON) "$$script" --out-dir $(CURDIR)/figures || exit 1; \
	    done; \
	fi

clean:
	rm -f main.pdf main.aux main.log main.out main.bbl main.blg main.fls \
	      main.fdb_latexmk main.synctex.gz
	rm -f tables/*.tex
