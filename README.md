# pdf-parser

Turns PDFs of German legal and administrative documents into clean text and
structured fields. Works on born-digital PDFs and scans (OCR via tesseract).

Supported document types: letters and statements, printed e-mails,
parliamentary prints (Drucksachen, synopses), plenary protocols, statutes,
court decisions, contracts. Anything else comes back as `generic` with text
and entities.

## Install

```sh
uv add git+https://github.com/Parlamentszusammenfasser/pdf-parser
```

The repo is `pdf-parser`; the package is `pazufa-pdf-parser`
(`import pazufa_pdf_parser`), and the CLI command is `pazufa-pdf-parser`.

Requires Python ≥ 3.12. Optional, for scans: `tesseract` with German data
(`apt install tesseract-ocr tesseract-ocr-deu`).

## Library

```python
from pazufa_pdf_parser import parse, render

doc = parse("statement.pdf")          # path, bytes or binary file object

doc.doc_type                          # DocType.LETTER
doc.classification.subtype            # "statement"
doc.fields["title"]                   # "Stellungnahme zum Entwurf eines Testgesetzes"
doc.fields["date"]                    # "2024-07-16"
doc.fields["letter"]["recipient"]     # {"name": ..., "street": ..., "city": ..., "lines": [...]}
doc.entities["legal_references"]      # ["§ 3 Abs. 2 Satz 1 BayBO", ...]

render(doc, "txt")                    # clean text; also "raw", "html", "legalxml", "json"
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
| `doc.classification` | `doc_type`, `subtype`, `confidence` (0–1), `scores` and `evidence` per type |
| `doc.fields["title"]`, `["date"]`, `["language"]` | document-level summary, date as ISO string |
| `doc.fields[<family>]` | type-specific fields, see below |
| `doc.entities` | `dates`, `emails`, `urls`, `phones`, `ibans` (checksum-validated), `bics`, `file_numbers`, `printed_matter`, `legal_references` (only non-empty keys) |
| `doc.legal` | `LegalNode` tree of statutes/bills/contracts (Artikel, §, Absatz, Nummer, Buchstabe) |
| `doc.speeches` | plenary protocol speeches (`speaker`, `role`, `party`, `paragraphs`) |
| `doc.synopsis` | aligned rows of a two-column synopsis: `[{"left": [...], "right": [...]}]` |
| `doc.issues` | warnings and errors recorded while parsing |

Type-specific fields:

| `doc_type` | `fields` key | main fields |
|---|---|---|
| `letter` | `letter` | `sender`, `recipient`, `return_address`, `date`, `place`, `subject`, `salutation`, `closing`, `signatory` |
| `email` | `email` | `from`, `to`, `cc`, `date`, `subject`, `thread`, `attachments`, `attached_letter` |
| `parliamentary_print` | `print` | `parliament`, `period`, `number`, `kind`, `originator`, `committee`, `date`, `title` |
| `plenary_protocol` | `protocol` | `parliament`, `period`, `session`, `date`, `agenda_items`, `speakers`, `referenced_prints` |
| `court_decision` | `court` | `court`, `decision_type`, `file_number`, `date`, `parties`, `sections` |
| `contract` | `contract` | `title`, `parties`, `signed` |

`doc.to_dict()` returns all of this as JSON-friendly data; the `json` format is
`to_dict(include_layout=True)`.

## Command line

```sh
pazufa-pdf-parser letter.pdf                        # clean text to stdout
pazufa-pdf-parser letter.pdf -f json                # structured fields
pazufa-pdf-parser in/ -r -f txt,json -o out/        # batch, several formats
pazufa-pdf-parser classify in/                      # file, type, confidence, title (TSV; --json for all scores)
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
| `legalxml` | Akoma Ntoso 3.0, schema-valid; fields embedded in `meta/proprietary` |
| `json` | all of the above as data, plus per-page blocks with geometry |

## Known limitations

- Two signatures side by side on a scan are read as one line.
- Letterheads at the top of the page are only removed when they repeat.
- Footer contents (register court, bank details) are not parsed into fields.
- No handwriting recognition.

## More

- [docs/architecture.md](docs/architecture.md): pipeline, extending, tests
- `plan/`: task ledger and notes on the real sample PDFs
