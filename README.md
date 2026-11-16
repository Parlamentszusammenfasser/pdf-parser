# pdf-parser

Turns PDFs of German legal and administrative documents (letters, printed
e-mails, Drucksachen and synopses, plenary protocols, statutes, court
decisions, contracts) into clean text: page headers, footers and page numbers
removed, columns in reading order, paragraphs re-joined across page breaks.
Works on born-digital PDFs and scans (OCR via tesseract).

## Install

```sh
uv add git+https://github.com/Parlamentszusammenfasser/pdf-parser --tag 0.1.0
```

Pin a [release](https://github.com/Parlamentszusammenfasser/pdf-parser/releases)
tag. Each release also carries the wheel and sdist with a build-provenance
attestation (`gh attestation verify <file> -R Parlamentszusammenfasser/pdf-parser`).

The repo is `pdf-parser`; the package is `pazufa-pdf-parser`
(`import pazufa_pdf_parser`), and the CLI command is `pazufa-pdf-parser`.

Requires Python ≥ 3.12. Optional, for scans: `tesseract` with German data
(`apt install tesseract-ocr tesseract-ocr-deu`).

## Library

```python
from pazufa_pdf_parser import parse, render

doc = parse("statement.pdf")          # path, bytes or binary file object
doc.text()                            # clean body text
doc.text(pages=[2, 3])                # only these pages (1-based)
render(doc, "html")                   # also "txt", "raw", "json"
```

Options are keyword arguments (or a `ParseOptions` object):

```python
parse(data, ocr="never")              # "auto" (default) | "always" | "never"
parse(data, first_page=2, last_page=5, password="…")
```

Tesseract settings live in one `Ocr` object per process. Its `max_parallel`
caps the Tesseract processes of every `parse()` sharing it, also across
threads; pages with a text layer never wait. By default all calls share
`Ocr()`: German, 300 dpi, up to 4 processes.

```python
OCR = Ocr(languages=("deu", "eng"), dpi=400, max_parallel=2)   # once per process
parse(data, ParseOptions(ocr_engine=OCR))
```

`parse` does not raise on recoverable problems. It records them in
`doc.report.issues` and carries on; pass `strict=True` to raise instead. Unreadable
PDFs raise `PdfOpenError` (all errors subclass `PazufaError`).

### What you get

`parse` returns an immutable `PdfDocument`:

| attribute | content |
|---|---|
| `doc.pages` | per page: `number`, `source` (`text`/`ocr`/`empty`), `text` (body text), `blocks` |
| `doc.blocks` | every block of every page with `page`, `kind`, `text`, `bbox` (points, top-left origin), `level` (headings). `paragraph`, `heading`, `list_item` and `footnote` make up the text; `header`, `footer`, `page_number`, `marginal` and `noise` are left out of it |
| `doc.metadata` | `title`, `author`, `created`, `modified` (`datetime` or `None`), `page_count` |
| `doc.sha256` | content hash of the PDF |
| `doc.report` | `parser_version`; per page why it was or was not OCRed and the OCR confidence; `issues` |

A paragraph that continues across a page break belongs to the page it starts
on. `doc.to_json()` serialises the whole result (the `json` format).

## Command line

```sh
pazufa-pdf-parser letter.pdf                        # clean text to stdout
pazufa-pdf-parser letter.pdf -f json                # pages and blocks with geometry
pazufa-pdf-parser in/ -r -f txt,json -o out/        # batch, several formats
```

Common options: `--ocr auto|always|never`, `--lang deu+eng`, `--pages 2-5`,
`--password`, `--strict`, `-v` (print recorded issues). A broken input never
stops a batch; exit code is `1` if any input failed.

## Output formats

| format | content |
|---|---|
| `txt` | clean running text: no headers/footers/page numbers, de-hyphenated, paragraphs re-joined across page and column breaks |
| `raw` | every block in reading order, including headers, footers, page numbers, margin notes and OCR noise; pages separated by form feeds. Not the untouched PDF text: each block is sanitized (and paragraphs re-joined) as in `txt` |
| `html` | headings, paragraphs, lists and footnotes in reading order (columns and synopses are read one after the other, not laid out side by side) |
| `json` | the whole `PdfDocument`: pages, blocks with kind, text and geometry, metadata and report |

## Known limitations

- Two signatures side by side on a scan are read as one line.
- Letterheads at the top of the page are only removed when they repeat.
- No handwriting recognition.

## More

- [docs/architecture.md](docs/architecture.md): pipeline, extending, tests
- `plan/`: task ledger and notes on the real sample PDFs
