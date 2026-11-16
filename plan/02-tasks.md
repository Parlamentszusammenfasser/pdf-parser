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
[-] T16 type-aware `letter_footer` step after classify: dropped, classification and fields removed (#14)
