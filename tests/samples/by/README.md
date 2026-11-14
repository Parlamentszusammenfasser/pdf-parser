# BY samples (19. Wahlperiode)

Picked from 1352 PDFs (`pdfs-by-2026-11-14`, 497 MB): one file per layout case, then each output reviewed by hand.
"Observed" is what `pazufa-pdf-parser` @ f9ab601 produces today (OCR auto, tesseract `deu`).
Source = sha256 file name in the full corpus.

| File | Case | Observed on f9ab601 | Source |
|---|---|---|---|
| drs-clean.pdf | best case: Word Drucksache (Beschluss with law text), 3 p | correct: running header and footer removed, paragraphs joined across page breaks, no artefacts; must stay that way | 89e1fa04 |
| drs-beschluss.pdf | Beschluss, most common Drucksache (176×), 1 p | header split: "Beschluss des Bayerischen Landtags" comes before date and number | 561f127c |
| drs-beschlussempfehlung-letterspaced.pdf | Beschlussempfehlung und Bericht, Berichterstatter key-values | letter-spaced word collapsed wrong: "einst im m i g" | 625dee2e |
| drs-gesetzentwurf-blank-page.pdf | Gesetzentwurf with blank p2 | Drucksache number only in furniture; p3 header half in body ("Bayerischer Landtag", date); author list split mid-name ("Maximilian" / "Deisenhofer") | 29ee5c3b |
| drs-staatsvertrag-bilingual-rotated-maps.pdf | Antrag der Staatsregierung, trimmed to pp. 1–3, 319–320, 326–327 of 328 | DE/CZ parallel columns; `/Rotate 90` map pages OCR'd to noise ("] =yg"); "Bundes - republik", "vollzieh enden" | 8c75ed85 |
| ausschuss-tagesordnung.pdf | committee agenda, 2 p | running header "Ausschuss … Seite 2" left in body | 4c1864bf |
| plenum-tagesordnung.pdf | plenary agenda, 23 p | time column ("anschließend ohne Aussprache", "Beratungszeit") read before/among the items, BY variant of #8 | 87ed7f58 |
| protokollauszug.pdf | Protokollauszug, most common type (291×), 2 p | speaker list p1; "Protokollauszug 16. Plenum …" header stays in body | c4b4aba1 |
| plenarprotokoll-page.pdf | full plenary protocol page | running header "Protokoll 19/49 … 5513" stays in body | 57ae5ac1 |
| gvbl-landscape-tables.pdf | GVBl (InDesign), ToC, landscape pp. 17–19 | landscape pages auto-rotated; table headers scrambled ("2. Se- 3. Se- … mester mester"); no furniture on rotated pages | 5bd18ddb |
| email-forwarded-with-statement.pdf | forwarded e-mail + attached statement (PDF24), mixed page sizes | reads well; flagged as synopsis (false positive) | 2d7fc202 |
| email-multiline-subject.pdf | e-mail print (Qt) | multi-line Betreff: value lands after "Gesendet am", label "Betreff:" alone | c2ba1ec5 |
| letter-clean.pdf | plain Word letter (PDF-XChange) | clean; control sample | 2b066f03 |
| letter-sidebar.pdf | Word letter with right sidebar | sidebar interleaved between address and subject | ff2a2aae |
| statement-page-break.pdf | statement (PDFMaker) | paragraphs not re-joined across page break ("Art." / "105 Abs.", "höchstrichterlichen" / "Rechtsprechung") | c06a6e5c |
| statement-toc-dot-leaders.pdf | statement with dot-leader ToC | ToC entries merged into one line | 6ae6db5b |
| statement-ti-ligature-mixed-scan.pdf | text pages + one scanned page, `/Rotate` 0/270 | "ti" ligature → U+FFFD ("Ar�kel", 14×) | 74519dfa |
| scan-garbled-font.pdf | garbled font (100 % garbage), trimmed to p. 1 | OCR fallback works; fax cover with handwriting | e05d2704 |
| scan-letter.pdf | full scan (Konica), 1 p | sidebar before body; OK | 20f02e0d |
| scan-reading-order.pdf | full scan (Canon) | margin text inserted mid-paragraph ("Wir / insbesondere im / wissen …") | 04b6ed7d |
| scan-rotate-270.pdf | scan with `/Rotate 270` (Ricoh) | OK | 132eebbe |
| scan-rotate-90.pdf | scan with `/Rotate 90` | OK | 24b86a86 |
| letter-image-letterhead-ocr-merge.pdf | image letterhead + sparse text layer (OCR merge path) | OCR errors in letterhead ("Barn", "Telefan") | 569a98e0 |

## Personal data
Checked per file in `plan/00-findings.md`.
