# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PDF → structured fields + clean text for German legal/administrative documents (letters, e-mails, Drucksachen/synopses, plenary protocols, statutes, court decisions, contracts), born-digital and scanned. Library (`pazufa_pdf_parser`) plus CLI (`pazufa-pdf-parser`). Python ≥3.12, managed with `uv`. Runtime deps are only `pypdfium2` and `pillow`; tesseract is optional and called via subprocess (TSV output). Don't add PyMuPDF (AGPL, deliberately avoided).

## Commands

```sh
uv sync                                         # install (dev group: pytest, lxml, ruff, mypy)
uv run ruff format && uv run ruff check && uv run mypy   # lint + types, as in CI
uv run pytest                                   # full suite
uv run pytest tests/test_layout.py::test_name   # single test
uv run pytest -m "not ocr"                      # skip OCR tests
PAZUFA_SAMPLES_DIR=~/Nextcloud/projekte/pazufa/problempdfs-by uv run pytest -m samples   # real-PDF regressions
uv run pazufa-pdf-parser file.pdf -f json -v        # run the CLI (-v prints recorded issues)
uv run pazufa-pdf-parser classify in/ --json
```

Tests marked `ocr` auto-skip unless tesseract with `deu` data is installed; tests marked `samples` auto-skip unless `PAZUFA_SAMPLES_DIR` is set (sample PDFs are not in the repo; `tests/test_samples.py` pins the expected type/subtype per file).

## Architecture

Everything runs through `pipeline.py`: an ordered list of `Step`s (`DEFAULT_STEPS`) sharing a `Context` (`doc`, `options`, `classifier`, `scratch`). Steps never call each other; they communicate only by mutating the `Document` (`model.py`).

- **Physical stage** (always runs): `extract` → `layout` → `furniture` → `sanitize` → `flow`. `extract` and `layout` are `critical=True` (failure aborts); every other step's exception is recorded as an `Issue` on the document and the pipeline continues, unless `ParseOptions(strict=True)`.
- **Logical stage**: `classify` sets `doc.classification`; type-specific steps (`email`, `letter`, `parliamentary_print`, `plenary_protocol`, `court_decision`, `contract`, `legal_structure`) declare `doc_types=[...]` and are dispatched only when the type matches. `synopsis` runs via a `when=` predicate. `summary` fills document-level `fields["title"]`/`["date"]`.
- Order matters: footers are removed (`furniture`) and paragraphs re-joined across page/column breaks (`flow`) *before* `classify`, so page furniture doesn't skew classification or entities.
- New behaviour = new `@step(...)` inserted with `Pipeline.insert_after/before/replace`, not a call from inside another step.

Coordinates everywhere are view space: points, top-left origin, after applying `/Rotate`. pdfium reports char angles clockwise (negated before mapping).

Packages: `extract/` (pdfium chars → words, per-page text-layer vs OCR decision, threaded tesseract), `layout/` (lines, repetition-based header/footer detection in `furniture.py`, recursive XY-cut segmentation in `segment.py`, blocks/headings, bottom-zone footer scoring in `footers.py`), `sanitize.py`, `classify.py` (transparent weighted `Rule`s, every decision carries evidence), `fields/` (one module per document family plus `common.py` entities), `render/` (registry via `register_renderer`; formats `raw`, `txt`, `html`, `legalxml`, `json`).

`legalxml` emits Akoma Ntoso 3.0; tests validate every output against the vendored OASIS XSD in `tests/schemas/`, so keep renderer changes schema-valid.

## Tests

`tests/pdfgen.py` is a tiny dependency-free PDF writer: describe pages as lists of `T(x, y, text, size, bold, ...)` (y measured from the page top) and `make_pdf(...)` builds the bytes; `make_scanned_pdf` renders fake scans for OCR tests. `conftest.py` defines synthetic documents for each type and a session fixture `parsed` that parses them all once with `ocr="never"`. Reproduce a layout bug by adding a synthetic page here rather than committing a PDF.

## Coding guidelines

**Comments** state the domain reason a reader can't get from the code: which document quirk, sample PDF or German convention forces this rule (e.g. `# Outlook prints set "1 Tf" and scale via the matrix`). One line, plain language a colleague understands without context. Never narrate what the code does.

**Size.** Solve the case at hand with the least code. No options, hooks, base classes or generalisations until a second real use exists. If a heuristic grows a special case, check whether an existing step or helper already covers it before adding a branch.

**Leave touched code better.** This overrides the workspace "surgical changes" rule for this repo. When you edit a function, also fix what makes it hard to read: unclear names, long functions, duplicated logic, magic thresholds without a named constant or reason. Stay within the functions and tests you are changing. Don't sweep unrelated modules, and keep refactors behaviour-neutral (tests green before and after).

**Tests.** Every heuristic change needs tests for:
- the intended case,
- the boundary where it must *not* fire (the false positive it could cause on another document type),
- malformed or empty input.

Before adding a test, look for an existing one covering the same behaviour and extend it. Fold near-identical tests into one `@pytest.mark.parametrize` table with `ids=`. Delete tests that only re-assert what another test already checks.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): subject`.
- **Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`, `build`. On `main`, `feat` cuts a minor release, `fix`/`perf` a patch (CI, python-semantic-release); the rest release nothing.
- **PR titles** follow the same format (CI checks it): PRs are squash-merged, so the title becomes the commit that decides the release.
- **Scope:** the package or step touched: `extract`, `layout`, `footers`, `sanitize`, `classify`, `fields`, `render`, `cli`, `pipeline`.
- **Subject:** imperative, lower case, no period, ≤ 72 chars.

Write the subject and the optional body for a human reader. Say what changed for the document output and why (e.g. `fix(footers): keep last paragraph when page ends without gap`), not a list of edited functions.

## Planning notes

`plan/02-tasks.md` is the task ledger (`[x]` done, `[ ]` open, e.g. T16: type-aware `letter_footer` step after `classify`) plus open issues; `plan/00-findings.md` describes each real sample PDF and what makes it hard. Update the ledger when finishing a planned task.
