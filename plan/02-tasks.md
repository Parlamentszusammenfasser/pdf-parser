# tasks  [ ] todo [x] done [~] partial
[x] T01 model/errors/options
[x] T02 source + pdf extractor (rotation via FPDF_PageToDevice affine; ligature components share box -> no dedupe within same text obj; \x02 soft hyphen -> "-")
[x] T03 ocr extractor + probe (deu only default: deu+eng loses umlauts 37->13 on sample; OSD only on low conf)
[x] T04 lines + furniture
[x] T05 segment (xycut + strip grouping by gutter intersection; reject narrow/label columns; aside_first for sidebars) + blocks (pitch-based)
[x] T06 sanitize (+ocr § fixes, label/postal lines keep breaks)
[x] T07 classify
[x] T08 field extractors
[x] T09 pipeline + dispatch + api
[x] T10 renderers raw txt html json legalxml (all 9 samples XSD-valid)
[x] T11 cli
[x] T12 tests (216 incl. 23 sample regression, OCR, XSD validation, CLI)
[x] T13 iterate on samples (new sample 0000010446 appeared mid-session: email + attached letter, ligature fonts)
[x] T14 README
# open issues / ideas
- multi-signatory side-by-side signatures merged in one line (scans)
- footnote markers detached ("auf. 1 Hinzu") -> could map small raised digits to superscripts
- pdfium char angle is CLOCKWISE (verified) -> negate before mapping
- AKN: narrative/scene are inline-only; docCourt not in AKN3 -> courtType
[x] T15 footer pass: step `furniture` (layout/footers.py) between layout and sanitize; `flow` split out of sanitize;
     BlockKind.FOOTNOTE; plausible_size() fixes "1 Tf"+matrix sizes (Outlook). Sample leaks fixed: 041/10184/10143 p1, 5048, 0003 p2
[x] T17 public immutable `PdfDocument` (#11); renderers read it, html linear, raw = all blocks sanitized (#15)
[x] T18 `PdfDocument.to_json`/`from_json` with `schema_version` (#13); 17/1104: 0.50 MB JSON
[x] T19 shared `Ocr` engine object in `ParseOptions(ocr_engine=…)`, process-wide `max_parallel` (#9)
[x] T20 public API = `__all__`, internals in `_pipeline/`, `py.typed`, strict-typed consumer test (#16)
[x] T21 `ParseOptions.max_ocr_pages`: over the limit no OCR, text layer kept, WARNING issue (ERROR if forced) (#10)
[x] T22 `Page.furniture_text()` and `Page.printed_page`, step `page_numbers` (page-number line, "Seite N", or header
     number the next page continues; numbers the neighbour repeats are rejected); page-1 Drucksache/Plenarprotokoll
     masthead is furniture also on single pages; band holds 5 lines for "1 von 3" above a four-line footer (#12;
     missed page-1 numbers and OCR-dropped lone numbers → #34)
[x] T23 BW page-1 footer is furniture (#22): a strip whose own two-column gutter the group's margin gutter misses starts new columns; a bottom zone holding the page number (lone, or tab-set beside text) scores +1 and takes the number along; no page "0"
[x] T24 printed page numbers beside text (#34): a page number closing a band line ("Bayerisches<tab>177", footer
     "…<tab>I") becomes its own page-number block when the neighbour page continues it; on OCR pages a lone
     text-layer number tesseract missed is kept
[x] T25 Gesetzblatt page 2 (#23): its one-off running header is furniture as the page's first line; two
     columns that pair up line for line (signature lists) are no sidebar and read left first
[x] T26 protocol ToC (#24): a word hyphenated across two lines keeps them in one block despite a bold/size change
[x] T27 `ParseOptions.drop_garbled_text` (#33, on by default): on a page whose garbled text layer OCR did not
     replace, blocks set mostly in a garbled font become noise (raw only); scraper-bw's paragraph scorer is not
     ported, on parser output it only hit real text (uppercase titles, Czech, tables)
[x] T28 whole-repo review fixes: emoji (surrogate pairs) no longer break every output; flow works for page ranges
     not starting at 1; text outside the CropBox is dropped; invalid page ranges, dpi and timeout are rejected;
     sha256 of the input as given; huge pages OCRed at a lower dpi; CLI survives unwritable outputs and same-named
     inputs
[x] T29 interface review: `Page` carries width/height, `needs_ocr`, `ocr_reason`, `ocr_confidence` (no more
     `PageReport`); `Issue.code`; `Block.continues` keeps a paragraph's halves on their pages; tuning thresholds
     are constants; `strict` raises at the first ERROR issue; password out of repr/==; schema 2 with a readable
     set; pdfium lock per page; cross-step values typed (`Page.garbage_ratio`, `Document.body_size`)
[x] T30 internal cleanup: `merge_flow` in `flow.py`; one synopsis helper on `Page`; `rotate_words` in the model;
     block text normalised in sanitize; dead code removed (column, area, contains_point, media_type, tesseract_available, sanitize_text, ...)
[x] T31 ruled tables (#47): extract keeps thin paths as `Page.rules`; rules that meet in a grid with an inner border
     cut the page at row borders (unless text runs on across one: merged cells, text beside) and rows at column
     borders, so cells read whole and in column order; one-line rows stay one line; flow never joins table rows.
[x] T32 sideways pages (#47): on a page turned upright, lines upright on the paper beyond the body are header,
     footer or page number (BW Drs. 18/623 pp. 64–65, BY GVBl pp. 193–195 now get their printed page)
[-] T16 type-aware `letter_footer` step after classify: dropped, classification and fields removed (#14)
