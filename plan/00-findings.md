# findings: the first problem PDFs (now in tests/samples/by and tests/samples/sh under descriptive names, see their READMEs)
0000000003.pdf  scan Canon, 2p, letter DIN5008, sidebar right, Stellungnahme FreieWohlfahrtspflege -> needs OCR
0000000041.pdf  scan, 3p, /Rotate 270 (mediabox landscape, view portrait), letter Handwerkstag, footer logo
0000010143.pdf  scan, 2p, letter ASB, sidebar right, footer Landesvorstand
0000010184.pdf  scan, 3p, letter (page2 continuation w/ page number "2" top)
0000005048.pdf  Word, 1p, Bayern Drucksache 19/7613 Beschlussempfehlung+Bericht; letter-spaced "A b l e h n u n g"; key-value "Berichterstatter:   X"; footer note
0000010201.pdf  Outlook print, 2p, email (Von/An/Betreff/Datum/Anlagen), forwarded email inline, signature block
041_PL_004..pdf AntennaHouse, 24p, Plenarprotokoll-Auszug; speaker list p1; header "Protokollauszug / 41. Plenum, 04.02.2025 ... 1" every page; hyphenation; 1.5 spacing
drucksache-20-03769.pdf LibreOffice 6p SH Drucksache 20/3769 Bericht+Beschlussempfehlung + SYNOPSIS two columns (Gesetzentwurf | Ausschussvorschlag), alternating header even/odd, page num bottom center
tools: pdftotext/qpdf/tesseract(deu,eng,osd) present; no mutool/ocrmypdf. python 3.14, uv.
pdfium: charbox (pdf space, bottom-left, unrotated), fontsize, fontname, weight, IsGenerated, IsHyphen, HasUnicodeMapError, angle; page.get_size() is rotated view.

# BY samples in tests/samples/by (23 files, 5.7 MB, issue #7)
Picked from all 1352 PDFs of the 19th Wahlperiode (`pdfs-by-2026-11-14`, 497 MB) by covering every producer / document kind / OCR case, then reviewed by hand; per-file case and today's output defects in `tests/samples/by/README.md`. The full corpus stays outside git (GitHub LFS is unavailable: public fork of an archived repo).

Personal-data check (body text and PDF metadata).
- Problem PDFs added later (scan-statement-sidebar, scan-rotate-270-footer-logo, scan-letter-continuation-page, drs-beschlussempfehlung-ablehnung, protokollauszug-24p): association addresses and office holders signing in role, MdL. Keep.
- email-outlook-forwarded, email-attached-letter-ligatures: work e-mail addresses of association staff (Bauindustrie, GEW) and ministry desks, acting in role; metadata Author of the GEW mail names association staff. Keep. All documents are published Landtag/government documents or association statements from a public Verbandsanhörung; no private individuals.
- Landtag/GVBl prints (drs-*, ausschuss-tagesordnung, plenum-tagesordnung, protokollauszug, plenarprotokoll-page, gvbl-landscape-tables): MdL and office holders only. Metadata Author of the two agendas names Landtagsamt staff (role: author of an official document). Keep.
- letter-clean, statement-page-break, statement-toc-dot-leaders, scan-letter, scan-reading-order, scan-rotate-270, scan-garbled-font: association addresses, office holders signing in role. Keep.
- email-forwarded-with-statement, email-multiline-subject: names and work e-mail addresses of association staff and ministry desks, acting in role. Keep.
- letter-sidebar, statement-ti-ligature-mixed-scan: staff contact name in sidebar / metadata Author. Keep.
- scan-rotate-90, letter-image-letterhead-ocr-merge: staff contact name, phone, work e-mail. Keep.
- Dropped fe90d97d (and its duplicate 7651b07e): letter from a local chapter with the sender's private home address; replaced by 569a98e0 (letter-image-letterhead-ocr-merge, same OCR-merge case).

# BW samples in tests/samples/bw (7 files, 5.4 MB, issue #6)
The five PDFs from #6 plus Gesetzblatt 2026 Nr. 12 (scraper-bw #27) and Drs. 17/6014 trimmed to pp. 1, 14, 19 (Latin-Extended mojibake next to the ASCII +29 shift); per-file case in `tests/samples/bw/README.md`. All public Landtag/Gesetzblatt documents; the 17/6014 annexes are association statements (functional addresses only); metadata holds no names. Defects found and filed: #22 (page-1 footer columns interleaved), #23 (Gesetzblatt page 2), #24 (protocol ToC split); #8 covers the agenda. Each has a strict `xfail` test.
