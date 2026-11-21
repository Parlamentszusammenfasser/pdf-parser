# Architecture

The public API is what `__init__.py` exports: `__all__` and `__version__`. Its
types live in `_document.py`, `_options.py` and `_errors.py`; other names there,
and the whole `_pipeline/` package, are internal.

Everything runs through `_pipeline/pipeline.py`: an ordered list of steps sharing one
`Context` (`doc`, `options`). Steps never call each other; they only read and
modify the `Document`.

```mermaid
flowchart LR
    extract --> layout --> garbled --> furniture --> page_numbers --> sanitize --> flow
```

A failure in `extract` or `layout` aborts; any other step's exception is
recorded in `doc.issues` and the pipeline continues (unless `strict=True`).

Coordinates are in view space everywhere: points, top-left origin, page
rotation applied.

## Steps

**Extract** (`_pipeline/extract/`). pdfium gives characters with font, size, weight and
angle. They are rebuilt into words (ligatures kept, fake-bold duplicates
dropped, sideways pages turned upright). Per page, the text layer is used
unless it is missing, garbled, or a large image with sparse text; then the
page is OCRed with tesseract (TSV output; the shared `Ocr` object caps how many
run at once across all parses). Orientation
detection only runs when the first pass looks bad.

**Layout** (`_pipeline/layout/`). Words become lines. Running headers, footers and page
numbers are found by fuzzy repetition across pages (`furniture.py`). Each page
is split by a recursive XY-cut (`segment.py`), which handles letter sidebars,
multi-column text and two-column synopses without splitting tables or list
markers into columns. Lines become blocks on changes in pitch, font,
indentation, list markers and bold run-in labels; headings come from font
statistics.

**Garbled** (`drop_garbled` in `_pipeline/sanitize.py`). On a page whose garbled text layer OCR did
not replace (OCR off, unavailable or over `max_ocr_pages`), blocks set mostly in a font whose
characters the PDF cannot map become `noise`, kept in `raw` output only. `drop_garbled_text=False`
keeps them.

**Furniture** (`_pipeline/layout/footers.py`). Catches footers that repetition misses:
first-page-only letter footers, single-page documents, logos OCR reads
differently on each page. Blocks below a clear gap at the page bottom are
scored on small font, footer vocabulary (register court, bank, contact data),
OCR noise, repetition and gap size. Numbered notes become `footnote` blocks
that stay in the text.

**Sanitize / flow** (`_pipeline/sanitize.py`). Removes soft hyphens, private-use glyphs
and OCR junk, collapses letter-spacing, de-hyphenates, then re-joins
paragraphs across column breaks. Across a page break each page keeps its half
and the first is marked `continues`, so page citations stay right.

**Result** (`_document.py`). `parse()` (`_pipeline/api.py`) turns the internal
`Document` into the immutable `PdfDocument` (pages, blocks, metadata, report), which round-trips
through JSON (`to_json`/`from_json`, `SCHEMA_VERSION`). Renderers
(`_pipeline/render/`) read only `PdfDocument`; formats register via `register_renderer`:
`raw`, `txt`, `html`, `json`.

## Extending

Add behaviour as a new step, never as a call from inside another step. The
pipeline is internal: this is for working on the parser, not for its users.

```python
from pazufa_pdf_parser._pipeline.pipeline import Pipeline, step
from pazufa_pdf_parser._pipeline.render import register_renderer

@step("word_count")
def word_count(ctx):
    ctx.doc.stats["words"] = len(ctx.doc.body_text().split())

pipe = Pipeline().insert_after("flow", word_count)   # also insert_before / replace / remove / append
doc = pipe.run("file.pdf")                           # the internal Document

register_renderer("upper", lambda d: d.text().upper(), "up.txt")   # d is a PdfDocument
```

## Tests

```sh
uv run pytest                     # synthetic PDFs; OCR tests run if tesseract + deu is installed
uv run pytest -m samples          # real sample PDFs in tests/samples/{by,bw,sh}
uv run pytest -m "not slow"       # skip the 146-page OCR sample
```

`tests/pdfgen.py` writes PDFs with exactly known layouts. `tests/conftest.py`
defines synthetic documents (letter, bill, e-mail, protocol, judgment, contract,
synopsis, two columns). To reproduce a layout bug, add a
synthetic page there rather than committing a PDF.
