# findings (samples in ~/Nextcloud/projekte/pazufa/problempdfs-by, 8 files) -- NOT copied into repo
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
