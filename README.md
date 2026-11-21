# pdf-parser

Turns PDFs of German legal and administrative documents (letters, printed
e-mails, Drucksachen and synopses, plenary protocols, statutes, court
decisions, contracts) into clean text and layout. Works on born-digital PDFs
and scans (OCR via tesseract).

- page headers, footers, page numbers and margin notes removed
- columns and synopses in reading order
- hyphenation fixed, paragraphs re-joined across page and column breaks
- every block kept with its kind (heading, paragraph, footnote, …) and position

## Quick start

```sh
uv add git+https://github.com/Parlamentszusammenfasser/pdf-parser --tag <release>
```

```python
from pazufa_pdf_parser import parse, render

doc = parse("drucksache.pdf")      # path, bytes or binary file object
doc.text()                         # clean body text
render(doc, "html")                # or "txt", "raw", "json"
```

```sh
pazufa-pdf-parser drucksache.pdf   # clean text to stdout
```

Requires Python ≥ 3.12. Use a
[release](https://github.com/Parlamentszusammenfasser/pdf-parser/releases) tag
for `<release>`; each release carries the wheel and sdist with a
build-provenance attestation. For scans, install `tesseract` with German data
(`apt install tesseract-ocr tesseract-ocr-deu`); without it, pages that need
OCR stay empty and the report says why.

## How it works

`parse()` runs these steps:

1. **extract**: characters from the PDF text layer; pages without a usable one are OCRed
2. **layout**: lines, columns, blocks, headings, lists, footnotes; headers and footers repeated across pages
3. **garbled**: text in broken fonts that OCR did not replace becomes noise (`drop_garbled_text`)
4. **furniture**: footers repetition misses, e.g. on the first page only
5. **page_numbers**: the number printed on each page
6. **sanitize**: hyphenation, whitespace, OCR noise
7. **flow**: paragraphs that continue on the next page or column

If a step after layout fails, the document is still returned and the failure is
recorded in its report. Details: [docs/architecture.md](docs/architecture.md).

## Library

### Options

```python
from pazufa_pdf_parser import Ocr, OcrMode, ParseOptions, parse

parse(data, ParseOptions(ocr=OcrMode.NEVER))                   # AUTO (default) | ALWAYS | NEVER
parse(data, ParseOptions(first_page=2, last_page=5, password="…"))
parse(data, ParseOptions(max_ocr_pages=500))                   # more pages to OCR: OCR none, warn
parse(data, ParseOptions(drop_garbled_text=False))             # keep garbled text OCR did not replace in txt/html
parse(data, ParseOptions(strict=True))                         # raise instead of recording problems
```

Tesseract settings live in one `Ocr` object per process. Its `max_parallel`
caps the tesseract processes of all `parse()` calls sharing it, also across
threads. The default `Ocr()` is German, 300 dpi, up to 4 processes.

```python
OCR = Ocr(languages=("deu", "eng"), dpi=400, max_parallel=2)   # once per process
parse(data, ParseOptions(ocr_engine=OCR))
```

### The result

`parse()` returns an immutable `PdfDocument`:

```
PdfDocument
├── sha256              hash of the PDF
├── metadata            title, author, created, modified, page_count
├── pages[]             number, source (text | ocr | empty), blocks, text(), furniture_text(), printed_page
├── blocks              all blocks: page, kind, text, bbox, level
├── text(pages=None)    body text, optionally of some pages, e.g. pages=[2, 3]
└── report              parser_version, pages[] (ocr_reason, ocr_confidence), issues[]
```

`paragraph`, `heading`, `list_item` and `footnote` blocks make up the text;
`header`, `footer`, `page_number`, `marginal` and `noise` blocks are kept but
left out of it; `page.furniture_text()` joins the header, footer and page-number
blocks. `printed_page` is the number printed on the page ("259", "II"), or `None`
when none was found. `bbox` is in points, origin top left, page rotation applied. A
paragraph that continues across a page break belongs to the page it starts on.

`parse()` does not raise on recoverable problems; it records them as issues:

```python
from pazufa_pdf_parser import Severity

for issue in doc.report.issues:
    if issue.severity >= Severity.WARNING:
        print(issue.page, issue.step, issue.message)
```

`issue.step` (`extract`, `ocr`, `layout`, `garbled`, `furniture`, `page_numbers`, `sanitize`, `flow`) and
`severity` are stable; `message` is for people.

### Output formats

| `render(doc, …)` | content |
|---|---|
| `"txt"` | clean running text |
| `"raw"` | every block in reading order, including headers, footers, page numbers, margin notes and noise; pages separated by form feeds |
| `"html"` | headings, paragraphs, lists and footnotes in reading order |
| `"json"` | the whole `PdfDocument`, same as `doc.to_json()` |

### Errors

All subclass `PazufaError`:

- `PdfOpenError`: not a readable PDF (corrupt, wrong password)
- `StepError`: `extract` or `layout` failed, or any step with `strict=True`; `e.step`, `e.cause`
- `OcrUnavailableError`: `strict=True` and OCR needed, but no tesseract
- `UnknownFormatError`: unknown `render` format
- `SchemaVersionError`: `from_json` got JSON from a newer version

### Caching

```python
cached = doc.to_json()
doc = PdfDocument.from_json(cached)
```

Key the cache by `doc.sha256` and the options you parsed with. `from_json`
reads JSON from older versions; JSON from newer ones raises
`SchemaVersionError`, so parse the PDF again. To pick up parser improvements,
drop entries whose `doc.report.parser_version` differs from
`pazufa_pdf_parser.__version__`.

### Stability

The public API is `__all__` plus `__version__`; it is typed (`py.typed`).
Underscored modules such as `pazufa_pdf_parser._pipeline` are internal.
Breaking changes are marked in the release notes.

## Command line

```sh
pazufa-pdf-parser letter.pdf -f json               # pages and blocks with geometry
pazufa-pdf-parser in/ -r -f txt,json -o out/       # a folder, several formats
```

Common options: `--ocr auto|always|never`, `--lang deu+eng`, `--pages 2-5`,
`--password`, `--strict`, `-v` (print issues); all in `pazufa-pdf-parser
extract --help`. A broken input never stops a batch; the exit code is `1` if
any input failed.

## Known limitations

- Two signatures side by side on a scan are read as one line.
- Letterheads are only removed when they repeat.
- No handwriting recognition.

## Development

```sh
uv sync
uv run ruff format && uv run ruff check && uv run mypy && uv run pytest
```

See [docs/architecture.md](docs/architecture.md) and [CLAUDE.md](CLAUDE.md).
