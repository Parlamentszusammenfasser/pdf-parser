# BW samples (Landtag von Baden-Württemberg)

Real PDFs that broke scraper-bw's text extraction (issue #6, scraper-bw DD-015 and issue #27). All are public Landtag documents. Senders in the annexes are associations and authorities.
"Observed" is what `pazufa-pdf-parser` produces on 9b65f0f (OCR auto, tesseract `deu`). Source = first 8 hex chars of the original file's sha256.

| File | Case | Observed | Source |
|---|---|---|---|
| drs-17-0273-clean.pdf | clean Gesetzentwurf, 4 p (scraper-bw `tests/fixtures/pdf/17_0273_D.pdf`) | all pages text; running header removed; page-1 footer (with the "Ausgegeben" date and page number 1) is furniture, its two columns read one after the other | ed90aa28 |
| drs-17-1201-ascii-shift.pdf | Änderungsanträge, 5 p: p. 1 clean, pp. 2–5 font shifted by ASCII +29 with C1 controls ("6WlGWHWDJ" = "Städtetag") | pp. 2–5 OCR'd; each page's own number "17/1201-N" recovered; the printed page number tesseract drops is kept from the text layer | c91ba7ad |
| drs-17-1104-garbled-146p.pdf | Beschlussempfehlung, 146 p, 131 pages with the ASCII +29 font | 131 pages OCR'd, 15 text, ~27 s; no control characters left | 4d96800f |
| drs-17-6014-garbled-annex.pdf | Gesetzentwurf trimmed to pp. 1, 14, 19 of 24: annexed statements with the ASCII +29 font (p. 14) and Latin-Extended mojibake ("ĞĂŵƚĞŶ", p. 19) | both annex pages OCR'd and readable | 3942fdea |
| plpr-18-10.pdf | Plenarprotokoll 18/10, 49 p, printed page numbers 259–305 | speeches read well; ToC entries split at line ends (#24) | f5e5aea3 |
| to-18-14-speaking-times.pdf | Tagesordnung 18/14 with a speaking-time column (scraper-bw `tests/fixtures/tagesordnung/`) | speaking times read before the items (#8) | b8023617 |
| gbl-2026-12.pdf | Gesetzblatt 2026 Nr. 12, 2 p: law on p. 1, signatures on p. 2 (scraper-bw #27 kept only p. 2) | p. 1 complete; p. 2 header in body, signature columns right first (#23) | e2f199fd |

Considered and left out: Drs. 17/4341 (a third mojibake variant; 91 % garbage, far above the OCR threshold) and 17/1001 (ASCII +29 again).
