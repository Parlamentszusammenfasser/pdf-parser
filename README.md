# pazufa-parser

Robust extraction of **structured information** and **clean full text** from PDF
documents. The parser targets German legal and administrative documents: letters
and position statements, printed e-mails, parliamentary papers (Drucksachen) and
synopses, plenary protocols, statutes, court decisions and contracts. Born-digital
PDFs and scans (via OCR) are both supported.

It ships as both a **library** (`import pazufa_parser`) and a **command-line tool**
(`pazufa-parser`).

## Install

```sh
uv sync                    # runtime: pypdfium2, pillow
# optional, for scanned documents:
pacman -S tesseract tesseract-data-deu      # or apt install tesseract-ocr tesseract-ocr-deu
```

## Command line

```sh
pazufa-parser letter.pdf                          # sanitized text to stdout
pazufa-parser letter.pdf -f json                  # structured information
pazufa-parser in/ -r -f txt,html,legalxml,raw,json -o out/   # batch, several formats
pazufa-parser classify in/ --json                 # only the classification
pazufa-parser formats                             # list output formats
```

Useful options: `--ocr auto|always|never`, `--lang deu` (`deu+eng` for mixed
documents; mixing languages measurably hurts German umlaut recognition),
`--dpi 300`, `--pages 2-5`, `--password`, `--strict`, `-v` (prints the issues
recorded during processing). Exit codes: `0` ok, `1` at least one input failed,
`2` usage error. A broken input never stops a batch.

### Output formats

| format     | extension  | content |
|------------|------------|---------|
| `raw`      | `.raw.txt` | every extracted piece of text in reading order, unsanitized: running headers and footers, page numbers, rotated margin notes, low-confidence OCR. Large gaps become tabs, and pages are separated by form feeds. |
| `txt`      | `.txt`     | sanitized running text: no page furniture, de-hyphenated, ligatures/soft hyphens/private-use glyphs/OCR junk removed, letter-spacing (`A b l e h n u n g`) collapsed, paragraphs reflowed (also across page and column breaks). Addresses and tables keep their lines. |
| `html`     | `.html`    | lightweight semantic HTML: headings, paragraphs, list items, multi-column regions as CSS grid, and synopses as row-aligned two-column grids, with a metadata header. |
| `legalxml` | `.akn.xml` | [Akoma Ntoso 3.0 / OASIS LegalDocML](https://docs.oasis-open.org/legaldocml/akn-core/v1.0/). Bills and statutes map to `bill`/`act` with an article/section/paragraph/point hierarchy, protocols to `debate` with `speech` elements, court decisions to `judgment`, and everything else to `doc`. Output validates against the official XSD (checked in the tests). All extracted fields are embedded as JSON in `meta/proprietary`. |
| `json`     | `.json`    | classification (type, subtype, confidence, evidence), document-type fields, entities, legal structure, synopsis, speeches, per-page blocks with geometry, issues and timings. |

## Library

```python
from pazufa_parser import parse, render, ParseOptions

doc = parse("statement.pdf")                     # path, bytes or binary file object
doc.classification.doc_type                      # DocType.LETTER
doc.classification.subtype                       # "statement"
doc.fields["letter"]["recipient"]["lines"]       # structured fields per type
doc.fields["title"], doc.fields["date"]          # document-level summary
doc.entities["legal_references"]                 # ["§ 3 Abs. 2 S. 1 BayBO", ...]
doc.legal                                        # LegalNode tree (Artikel/§/Absatz/Nummer/Buchstabe)
doc.issues                                       # problems recorded while processing

text = render(doc, "txt")                        # or raw / html / legalxml / json
doc = parse(data, ParseOptions(ocr="never"))     # options as object ...
doc = parse(data, ocr="always", dpi=400)         # ... or as keyword overrides
```

### Extending

The pipeline is an ordered list of steps. After the `classify` step, the steps
that apply to the detected document type are dispatched; steps declare their
target types and never call each other directly.

```python
from pazufa_parser import Pipeline, step, DocType, Classifier, Rule, register_renderer
import re

@step("invoice_numbers", doc_types=[DocType.LETTER])
def invoice_numbers(ctx):
    ctx.doc.fields["invoice"] = re.findall(r"Rechnungsnr\.?\s*(\S+)", ctx.doc.body_text())

pipe = Pipeline(classifier=Classifier(extra_rules=[
    Rule(DocType.CONTRACT, "framework agreement", 3.0, re.compile(r"Rahmenvertrag")),
]))
pipe.insert_after("letter", invoice_numbers)     # also: insert_before / replace / remove / append
doc = pipe.run("file.pdf")

register_renderer("markdown", lambda d: "\n\n".join(b.text for b in d.body_blocks), "md")
```

Lower-level building blocks (layout segmentation, sanitization, entity
extraction, the legal structure parser) are importable from
`pazufa_parser.layout`, `pazufa_parser.sanitize` and `pazufa_parser.fields`.

## Architecture

```
open (pdfium) ─► extract ─► layout ─► sanitize ─► classify ─► dispatch ──► summary
                 │           │                     │           ├ email, letter
                 │ per page: │ lines, page         │ weighted  ├ parliamentary_print
                 │ text layer│ furniture, XY-cut   │ rules     ├ plenary_protocol
                 │ or OCR    │ with gutter-        │           ├ court_decision, contract
                 │ (parallel)│ grouped strips,     │           ├ synopsis
                 │           │ blocks, headings    │           └ legal_structure
```

* **Extraction** (`extract/`): pdfium gives characters with font, size, weight,
  angle and render mode. The extractor maps them into a rotation-corrected view
  space, rebuilds words (keeping ligature components, dropping fake-bold
  duplicates, turning soft hyphens back into `-`), and turns sideways pages
  upright. Per page it decides between the text layer and OCR: no usable text,
  a garbled text layer, or a large image with sparse text. OCR runs tesseract
  via its TSV output on several threads. Orientation detection only runs when
  the first pass looks bad.
* **Layout** (`layout/`): words are clustered into lines. Running headers,
  footers and page numbers are found by fuzzy, digit-normalized repetition
  across pages. Each page is segmented by a recursive XY-cut whose horizontal
  strips are grouped by a shared vertical gutter. This handles letter
  sidebars (read first, as an aside), multi-column text and two-column
  synopses, and avoids splitting key/value tables, list markers or line
  numbers into columns. Blocks come from line pitch, font and indentation
  changes, list markers and bold run-in labels; headings come from document
  font statistics.
* **Classification** (`classify.py`): transparent weighted rules over the
  first page, the full text and the last page, combined with layout features.
  Every decision carries its evidence.
* **Fields** (`fields/`): one module per document family, plus generic
  entities: dates, e-mail addresses, phone and fax numbers, IBAN with checksum
  validation, BIC, URLs, file numbers, printed-matter references and legal
  citations.

Plans and design notes are in `plan/`.

## Tests

```sh
uv run pytest                     # synthetic PDFs generated on the fly (+ OCR tests if tesseract is installed)
PAZUFA_SAMPLES_DIR=~/path/to/problempdfs uv run pytest   # + regression tests on the real sample PDFs
```

The suite generates PDFs with exactly known layouts: letters with sidebars,
bills, e-mails, protocols, judgments, contracts, synopses, two-column pages,
rotated pages, invisible text layers, encrypted files and fake scans with noise
or rotation. It also validates every Akoma Ntoso output against the vendored
OASIS schema (`tests/schemas/`).

## Known limitations

* Side-by-side signatures of two signatories on scans are read as one line.
* Footnote markers are not mapped to superscripts (`Fachkraftquote auf. 1`).
* A footer note on a single-page document cannot be told apart from body text,
  since there is no repetition to detect.
* Handwriting is not recognized. Signature scribbles are filtered out of the
  signatory field.
