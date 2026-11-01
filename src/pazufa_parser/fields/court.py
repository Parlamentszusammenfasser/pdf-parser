"""Court decisions (Urteile, Beschlüsse) and contracts."""

from __future__ import annotations

import re

from ..model import Block, Document
from .common import find_dates

COURT_RE = re.compile(
    r"((?:Bayerisches |Hessisches |Sächsisches |Schleswig-Holsteinisches |Niedersächsisches |Hamburgisches )?"
    r"(?:Bundesverfassungsgericht|Bundesgerichtshof|Bundesverwaltungsgericht|Bundessozialgericht|Bundesarbeitsgericht|Bundesfinanzhof|"
    r"Verfassungsgerichtshof|Verwaltungsgerichtshof|Oberverwaltungsgericht|Oberlandesgericht|Landessozialgericht|Landesarbeitsgericht|"
    r"Verwaltungsgericht|Landgericht|Amtsgericht|Sozialgericht|Finanzgericht|Arbeitsgericht|Kammergericht)"
    r"(?:\s+(?:für\s+)?[A-ZÄÖÜ][\wäöüß\-]+(?:\s+(?:am|an der|in der)\s+[A-ZÄÖÜ][\wäöüß\-]+)?)?)"
)
FILE_NO_RE = re.compile(
    r"(?:Az\.?|Aktenzeichen|Geschäftsnummer|Gz\.?)\s*:?\s*([\w][\w .\-/]{2,30}\d)"
    r"|\b(\d{1,2}\s?(?:BvR|BvL|BvF|BvE|BvQ|ZR|StR|AZR|C|K|KR|S|O|U|W|B|L|N|Ws|Ss|CS|ZB|Sa|Ta)\s?\d{1,5}[./]\d{2,4})\b"
)
DECISION_TYPE_RE = re.compile(r"^\s*(Urteil|Endurteil|Teilurteil|Versäumnisurteil|Anerkenntnisurteil|Beschluss|Gerichtsbescheid)\s*$", re.M)
SECTION_RES = {
    "tenor": re.compile(r"^\s*(Tenor|für Recht erkannt|beschlossen|hat .{0,120}(für Recht erkannt|beschlossen))\s*:?\s*$", re.I),
    "guiding_principles": re.compile(r"^\s*(Leitsätze?|Leitsatz|Orientierungssatz)\s*:?\s*$", re.I),
    "facts": re.compile(r"^\s*Tatbestand\s*:?\s*$", re.I),
    "reasons": re.compile(r"^\s*(Entscheidungsgründe|Gründe)\s*:?\s*$", re.I),
    "remedies": re.compile(r"^\s*(Rechtsmittelbelehrung|Rechtsbehelfsbelehrung(?:\s*:)?)\b.*$", re.I),
}
PARTY_ROLE_RE = re.compile(r"[-–]\s*(Kläger(?:in)?|Beklagte[rn]?|Antragsteller(?:in)?|Antragsgegner(?:in)?|Beschwerdeführer(?:in)?|Beigeladene[rn]?|Berufungskläger(?:in)?|Revisionskläger(?:in)?|Beteiligte[rn]?)\s*[-–]")
SUBJECT_RE = re.compile(r"^\s*wegen\s+(.{3,200}?)\s*$", re.M | re.I)


def _t(b: Block) -> str:
    return (b.text or b.raw_text).strip()


def court_sections(blocks: list[Block]) -> list[tuple[str, int]]:
    """Return (section_name, block_index) for each section heading found."""
    out = []
    for i, b in enumerate(blocks):
        t = _t(b)
        if len(t) > 160:
            continue
        for name, rx in SECTION_RES.items():
            if rx.match(t.split("\n")[0]):
                out.append((name, i))
                b.labels.add(f"section:{name}")
                break
    return out


def extract_court_fields(doc: Document) -> dict:
    blocks = doc.body_blocks
    # raw lines keep "wegen ..." / "- Kläger -" at line starts
    head = "\n".join(" ".join(ln.split()) for b in (doc.pages[0].all_blocks if doc.pages else []) for ln in b.raw_text.split("\n"))
    full = "\n".join(_t(b) for b in blocks)
    fields: dict = {}
    m = COURT_RE.search(head)
    if m:
        fields["court"] = " ".join(m.group(1).split())
    m = FILE_NO_RE.search(head)
    if m:
        fields["file_number"] = " ".join((m.group(1) or m.group(2)).split())
    m = DECISION_TYPE_RE.search(head)
    if m:
        fields["decision_type"] = m.group(1)
    dm = re.search(r"\b(?:vom|am|verkündet am|Datum)\s*:?\s*(\d{1,2}\.\s?(?:\d{1,2}\.|[A-Za-zäÄ]+)\s?\d{4})", head)
    d = find_dates(dm.group(1)) if dm else find_dates(head)
    if d:
        fields["date"] = d[0]["iso"]
    if re.search(r"Im\s+Namen\s+des\s+Volkes", head, re.I):
        fields["in_the_name_of_the_people"] = True
    parties = []
    for pm in PARTY_ROLE_RE.finditer(head):
        before = head[: pm.start()].rstrip().split("\n")
        name = before[-1].strip(" ,") if before else ""
        # walk up to the first line that looks like the name
        k = len(before) - 1
        while k > 0 and (not name or name.lower().startswith(("vertreten", "bevollmächtigt", "prozessbevollmächtigt"))):
            k -= 1
            name = before[k].strip(" ,")
        parties.append({"role": pm.group(1), "name": name})
    if parties:
        fields["parties"] = parties
    m = SUBJECT_RE.search(head)
    if m:
        fields["subject"] = m.group(1).strip()
    secs = court_sections(blocks)
    if secs:
        fields["sections"] = [name for name, _ in secs]
    judges = re.findall(r"^\s*((?:Vorsitzende[r]?\s+)?Richter(?:in)?\s+(?:am\s+\w+\s+)?[A-ZÄÖÜ][\wäöüß\-]+)\s*$", full, re.M)
    if judges:
        fields["judges"] = judges[:7]
    return fields


# --------------------------------------------------------------------------- contracts

CONTRACT_TITLE_RE = re.compile(r"^\s*([\wÄÖÜäöüß\-]*(?:[Vv]ertrag|[Vv]ereinbarung))\b[^\n]{0,80}$", re.M)
DESIGNATION_RE = re.compile(r"(?:nachfolgend|im Folgenden|nachstehend)\s+(?:kurz\s+)?[„\"»]?([\wÄÖÜäöüß\- ]{2,40}?)[“\"«]?\s+genannt", re.I)


def extract_contract_fields(doc: Document) -> dict:
    blocks = doc.body_blocks
    head = "\n".join(_t(b) for b in blocks[:25])
    fields: dict = {}
    m = CONTRACT_TITLE_RE.search(head)
    if m:
        fields["title"] = m.group(0).strip()
    parties: list[dict] = []
    m = re.search(r"\bzwischen\b(.{3,600}?)\bund\b(.{3,600}?)(?:\n\s*\n|wird folgende|wird nachstehende|schließen folgende|$)", head, re.S | re.I)
    seg = m.group(0) if m else head
    for dm in DESIGNATION_RE.finditer(seg):
        before = seg[: dm.start()].rstrip(" ,–-(\n")
        lines = [ln.strip(" ,") for ln in before.split("\n") if ln.strip(" ,")]
        name = ""
        for ln in reversed(lines):
            if ln.lower() in ("zwischen", "und") or ln.lower().startswith(("vertreten durch", "-", "–")):
                continue
            name = re.sub(r"^(zwischen|und)\s+", "", ln, flags=re.I)
            break
        parties.append({"role": dm.group(1).strip(), "name": name})
    if parties:
        fields["parties"] = parties
    tail = "\n".join(_t(b) for b in blocks[-10:])
    places = re.findall(r"^\s*([A-ZÄÖÜ][\wäöüß\-]+),\s*(?:den\s+)?(\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4})", tail, re.M)
    if places:
        fields["signed"] = [{"place": p, "date": (find_dates(d) or [{"iso": None}])[0]["iso"]} for p, d in places]
    return fields
