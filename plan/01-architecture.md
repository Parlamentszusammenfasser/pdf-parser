# architecture
deps runtime: pypdfium2 (Apache/BSD; extraction+render, avoid AGPL pymupdf), pillow. tesseract via subprocess TSV (optional at runtime).
deps dev: pytest, lxml (XSD validation of AKN output; schema vendored tests/schemas/akomantoso30.xsd + xml.xsd, OASIS)

pkg src/pazufa_parser/
  model.py        BBox Word Line Block Region Page Document Classification LegalNode Issue ; to_dict()
  errors.py       PazufaError, PdfOpenError, OcrUnavailable
  options.py      ParseOptions (ocr mode auto|always|never, langs, dpi, jobs, strict, password, min_text_chars...)
  source.py       open pdf (path/bytes/fileobj), sha256, info dict, password, repair-free
  extract/pdf.py  pdfium chars -> words (font size,bold,italic,invisible,unicode_err) ; rotation transform to view space top-left
  extract/ocr.py  render page (pdfium) -> tesseract tsv -> words w/ conf ; OSD rotation ; thread pool
  probe.py        per-page decision text|ocr|hybrid (chars, garbage ratio, image coverage)
  layout/lines.py words->lines (baseline clustering), gaps -> tabs
  layout/furniture.py header/footer/page numbers across pages (digit-normalized fuzzy repeat + patterns)
  layout/segment.py  XY-cut w/ gutter-compatible strip merging -> Region tree (stack|columns|leaf), keyvalue guard
  layout/blocks.py   leaf lines -> blocks (gap, font, indent, list markers), heading detection by font stats
  sanitize.py     unicode cleanup, ligatures, cid, PUA bullets, soft hyphen, letterspacing, dehyphenate, unwrap, ocr junk lines
  classify.py     rule scoring -> DocType {letter,email,parliamentary_print(bill/report/motion/...),plenary_protocol,statute,court_decision,contract,generic}; subtype; features (synopsis, scanned)
  extract_fields/ common(entities: dates, emails, phones, iban, urls, refs § Art Drs, az) letter email parliament protocol court legal_structure
  pipeline.py     Step protocol(name, applies(ctx), run(ctx)); Context; Pipeline(steps, insert/replace/remove); stage physical then classify then dispatch logical; per-step error capture -> Issue (strict re-raises)
  render/         raw txt html legalxml(AKN 3.0) json ; registry register_renderer()
  api.py          parse(src, options) -> Document ; render(doc, fmt) ; convert(src, fmt)
  cli.py          pazufa-parser [extract] in... -f fmt[,fmt] -o dir|- --ocr --lang --dpi --jobs --strict --json-log; classify; formats
coords: view space, points, top-left origin, after /Rotate.
formats: raw = all text incl furniture/rotated/lowconf, reading order, lines as-is, \f between pages
         txt = body only, sanitized, dehyphenated, paragraphs reflowed, blank line between blocks
         html = semantic, columns as css grid, headings, meta dl, synopsis as 2-col grid
         legalxml = AKN 3.0: bill/act (body hierarchy), debate(speech), judgment, doc(name=letter|email|report|...)
         json = structured info (classification, fields, entities, outline, pages stats, issues)
