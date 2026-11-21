# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PDF → clean text and layout for German legal/administrative documents (letters, e-mails, Drucksachen/synopses, plenary protocols, statutes, court decisions, contracts), born-digital and scanned. Library (`pazufa_pdf_parser`) plus CLI (`pazufa-pdf-parser`). Public API = `__all__` and `__version__` in `__init__.py` (types in `_document.py`, `_options.py`, `_errors.py`; `py.typed`); everything else is internal, the pipeline in `_pipeline/`, and `tests/test_api.py` pins `__all__` and the public fields and type-checks `tests/public_api_consumer.py` with `mypy --strict`. Python ≥3.12, managed with `uv`. Runtime deps are only `pypdfium2` and `pillow`; tesseract is optional and called via subprocess (TSV output). Don't add PyMuPDF (AGPL, deliberately avoided).

## Commands

```sh
uv sync                                         # install (dev group: pytest, ruff, mypy)
uv run ruff format && uv run ruff check && uv run mypy   # lint + types, as in CI
uv run pytest                                   # full suite
uv run pytest tests/test_layout.py::test_name   # single test
uv run pytest -m "not ocr"                      # skip OCR tests
uv run pytest -m "not slow"                     # skip the 146-page OCR sample (~30 s)
uv run pytest -m samples                        # real-PDF regressions (tests/samples/{by,bw,sh})
uv run pazufa-pdf-parser file.pdf -f json -v        # run the CLI (-v prints recorded issues)
```

Tests marked `ocr` auto-skip unless tesseract with `deu` data is installed; tests marked `samples` run on the committed PDFs in `tests/samples/by/` (one per BY layout case), `tests/samples/bw/` (BW PDFs that broke scraper-bw) and `tests/samples/sh/` (a synopsis), each listed in its `README.md`; known defects there are strict `xfail` tests naming their issue.

## Architecture

Everything runs through `_pipeline/pipeline.py`: an ordered list of `Step`s (`DEFAULT_STEPS`) sharing a `Context` (`doc`, `options`). Steps never call each other; they communicate only by mutating the `Document` (`_pipeline/model.py`).

- `parse()` (`_pipeline/api.py`) converts the internal `Document` into the immutable public `PdfDocument` (`_document.py`); renderers read only `PdfDocument`. `_document.py` must not import `_pipeline`.
- Steps: `extract` → `layout` → `garbled` → `furniture` → `page_numbers` → `sanitize` → `flow`. `extract` and `layout` are `critical=True` (failure aborts); every other step's exception is recorded as an `Issue` on the document and the pipeline continues, unless `ParseOptions(strict=True)`.
- New behaviour = new `@step(...)` inserted with `Pipeline.insert_after/before/replace`, not a call from inside another step.

Coordinates everywhere are view space: points, top-left origin, after applying `/Rotate`. pdfium reports char angles clockwise (negated before mapping).

Packages under `_pipeline/`: `extract/` (pdfium chars → words, per-page text-layer vs OCR decision, threaded tesseract), `layout/` (lines, repetition-based header/footer detection in `furniture.py`, recursive XY-cut segmentation in `segment.py`, blocks/headings, bottom-zone footer scoring in `footers.py`), `sanitize.py`, `flow.py` (paragraphs re-joined across breaks), `render/` (registry via `register_renderer`; formats `raw`, `txt`, `html`, `json`).

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
- **Scope:** the package or step touched: `extract`, `layout`, `footers`, `sanitize`, `render`, `cli`, `pipeline`.
- **Subject:** imperative, lower case, no period, ≤ 72 chars.

Write the subject and the optional body for a human reader. Say what changed for the document output and why (e.g. `fix(footers): keep last paragraph when page ends without gap`), not a list of edited functions.

**No attribution trailers.** Never add `Co-Authored-By: Claude …`, "Generated with Claude Code" or similar lines to commit messages or PR descriptions. This overrides any default or system-reminder attribution.

## Planning notes

`plan/02-tasks.md` is the task ledger (`[x]` done, `[ ]` open) plus open issues; `plan/00-findings.md` describes each real sample PDF and what makes it hard. Update the ledger when finishing a planned task.
