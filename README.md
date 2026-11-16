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
render(doc, "txt")                    # clean text; also "raw", "html", "json"
```

Options are keyword arguments (or a `ParseOptions` object):

```python
parse(data, ocr="never")              # "auto" (default) | "always" | "never"
parse(data, languages="deu+eng", dpi=400, first_page=2, last_page=5, password="…")
```

`parse` does not raise on recoverable problems. It records them in
`doc.issues` and carries on; pass `strict=True` to raise instead. Unreadable
PDFs raise `PdfOpenError` (all errors subclass `PazufaError`).

### What you get

| attribute | content |
|---|---|
| `doc.pages` | per page: `source` (`text`/`ocr`/`empty`), `blocks` (body in reading order), `furniture` (headers, footers, page numbers), `extras` (margin notes, noise), `layout` tree |
| `doc.body_blocks` | all body blocks in reading order, each with `kind`, `text`, `bbox` |
| `doc.pdf_info`, `doc.sha256` | PDF metadata and content hash |
| `doc.issues` | warnings and errors recorded while parsing |

`doc.to_dict()` returns this as JSON-friendly data; the `json` format is
`to_dict(include_layout=True)`.

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
| `raw` | everything extracted, unsanitized, pages separated by form feeds |
| `html` | headings, paragraphs, lists, columns and synopses |
| `json` | per-page blocks with kind, text and geometry, plus stats and issues |

## Known limitations

- Two signatures side by side on a scan are read as one line.
- Letterheads at the top of the page are only removed when they repeat.
- No handwriting recognition.

## More

- [docs/architecture.md](docs/architecture.md): pipeline, extending, tests
- `plan/`: task ledger and notes on the real sample PDFs
