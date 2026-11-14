"""Generic entity extraction usable for every document type."""

from __future__ import annotations

import re
from datetime import date

MONTHS = {
    "januar": 1, "jänner": 1, "jan": 1, "february": 2, "februar": 2, "feb": 2, "märz": 3, "maerz": 3, "mär": 3, "march": 3,
    "april": 4, "apr": 4, "mai": 5, "may": 5, "juni": 6, "jun": 6, "june": 6, "juli": 7, "jul": 7, "july": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "oktober": 10, "okt": 10, "october": 10,
    "november": 11, "nov": 11, "dezember": 12, "dez": 12, "december": 12, "january": 1,
}  # fmt: skip

_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_NUMERIC_RE = re.compile(r"(?<![\d.])(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}|\d{2})(?![\d])")
DATE_LONG_RE = re.compile(rf"(?<![\d.])(\d{{1,2}})\.\s?({_MONTH_NAMES})\.?\s+(\d{{4}})\b", re.I)
DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

EMAIL_RE = re.compile(r"\b[\w.+\-]+@[\w\-]+(\.[\w\-]+)*\.[a-zA-Z]{2,}\b")
URL_RE = re.compile(r"\b((https?://|www\.)[^\s<>()\"“”,;]+[^\s<>()\"“”,;.])", re.I)
PHONE_RE = re.compile(r"(?:(Tel(?:efon)?|Fon|Fax|Telefax|Mobil|Handy|T|F)\.?\s*:?\s*)(\+?\d[\d \-/().]{5,}\d)", re.I)
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?)\b")
BIC_RE = re.compile(r"\bBIC:?\s*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b")
POSTAL_RE = re.compile(r"^(?:D-?\s?)?(\d{5})\s+([A-ZÄÖÜ][\wäöüß.\- ]{1,40}?)\s*$")
DRUCKSACHE_RE = re.compile(r"\b(?:Drucksache|Drs\.|BT-Drs\.|BR-Drs\.|LT-Drs\.)\s*(\d{1,2})\s*/\s*(\d{1,6})\b")
FILE_NUMBER_RE = re.compile(r"\b(?:Az\.?|Aktenzeichen|Gz\.?|Geschäftszeichen|Unser Zeichen|Ihr Zeichen)\s*:?\s*([A-Z0-9][\w\-–/. ]{1,60}?)\s*(?:$|\n|\s{2,}|,\s|;)", re.M)

# legal references: "§ 3 Abs. 2 Satz 1 Nr. 4 BayBO", "§§ 1, 2 BGB", "Art. 57 Abs. 1 Nr. 18 BayBO", "Artikel 1 § 9 Absatz 3"
_LAW_ABBR = r"(?:[A-ZÄÖÜ][A-Za-zÄÖÜäöü]*[A-Z][A-Za-zÄÖÜäöü]*|GG|BGB|HGB|StGB|ZPO|StPO|VwGO|VwVfG|SGB\s?[IVX]+)"
_SUB = r"(?:\s+(?:Abs\.|Absatz|S\.|Satz|Nr\.|Nummer|Halbs\.|Halbsatz|Buchst\.|Buchstabe|lit\.)\s*\d+[a-z]?(?:\s*(?:und|bis|,)\s*\d+[a-z]?)*)*"
LEGAL_REF_RE = re.compile(
    rf"(?:§§?|Art\.|Artikel)\s*\d+[a-z]?(?:\s*(?:und|bis|,)\s*\d+[a-z]?)*{_SUB}(?:\s+(?:des|der)\s+[A-ZÄÖÜ][\wäöüß\-]+(?:\s+[A-ZÄÖÜ]?[\wäöüß\-]+){{0,3}}?(?=[\s,.;)]|$)|\s+{_LAW_ABBR}\b)?"
)


def to_iso(day: int, month: int, year: int) -> str | None:
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def find_dates(text: str) -> list[dict]:
    """All dates in text, as dicts {text, iso, start}. Sorted by position."""
    out: list[dict] = []
    for m in DATE_NUMERIC_RE.finditer(text):
        iso = to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            out.append({"text": m.group(0), "iso": iso, "start": m.start()})
    for m in DATE_LONG_RE.finditer(text):
        iso = to_iso(int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)))
        if iso:
            out.append({"text": m.group(0), "iso": iso, "start": m.start()})
    for m in DATE_ISO_RE.finditer(text):
        iso = to_iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if iso:
            out.append({"text": m.group(0), "iso": iso, "start": m.start()})
    out.sort(key=lambda d: d["start"])
    return out


def first_date(text: str) -> dict | None:
    d = find_dates(text)
    return d[0] if d else None


def _dedupe(items: list, key=lambda x: x) -> list:
    seen = set()
    out = []
    for it in items:
        k = key(it)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _valid_iban(iban: str) -> bool:
    s = iban.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    r = s[4:] + s[:4]
    try:
        num = int("".join(str(int(c, 36)) for c in r))
    except ValueError:
        return False
    return num % 97 == 1


def normalize_ref(ref: str) -> str:
    return " ".join(ref.replace("Artikel", "Art.").replace("Absatz", "Abs.").replace("Nummer", "Nr.").split())


def extract_entities(text: str) -> dict[str, list]:
    """Entities found anywhere in the (sanitized) text."""
    ents: dict[str, list] = {}
    ents["dates"] = _dedupe([{"text": d["text"], "iso": d["iso"]} for d in find_dates(text)], key=lambda d: d["iso"])
    ents["emails"] = _dedupe([m.group(0).rstrip(".") for m in EMAIL_RE.finditer(text)], key=str.lower)
    ents["urls"] = _dedupe(
        [m.group(1) for m in URL_RE.finditer(text) if "@" not in m.group(1)],
        key=str.lower,
    )
    phones = []
    for m in PHONE_RE.finditer(text):
        label = m.group(1).lower()
        kind = "fax" if label.startswith(("fax", "telefax")) or label == "f" else "mobile" if label in ("mobil", "handy") else "phone"
        number = " ".join(m.group(2).split())
        if sum(c.isdigit() for c in number) >= 6:
            phones.append({"type": kind, "number": number})
    ents["phones"] = _dedupe(phones, key=lambda p: (p["type"], re.sub(r"\D", "", p["number"])))
    ibans = []
    for m in IBAN_RE.finditer(text):
        cand = m.group(1)
        compact = cand.replace(" ", "")
        valid = _valid_iban(compact)
        if valid or compact[:2] in ("DE", "AT", "CH") and len(compact) in (20, 21, 22):
            ibans.append({"iban": compact, "valid": valid})
    ents["ibans"] = _dedupe(ibans, key=lambda i: i["iban"])
    ents["bics"] = _dedupe([m.group(1) for m in BIC_RE.finditer(text)])
    ents["printed_matter"] = _dedupe([f"{m.group(1)}/{m.group(2)}" for m in DRUCKSACHE_RE.finditer(text)])
    ents["file_numbers"] = _dedupe([" ".join(m.group(1).split()) for m in FILE_NUMBER_RE.finditer(text)])
    ents["legal_references"] = _dedupe([normalize_ref(m.group(0)) for m in LEGAL_REF_RE.finditer(text)])
    return {k: v for k, v in ents.items() if v}
