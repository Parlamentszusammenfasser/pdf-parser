"""Parliamentary prints (Drucksachen) and plenary protocols."""

from __future__ import annotations

import re

from ..model import Block, BlockKind, Document, Speech
from .common import DRUCKSACHE_RE, find_dates

PARLIAMENT_RE = re.compile(
    r"((?:[A-ZÄÖÜ][\wäöüß\-]+\s)?(?:Landtag|LANDTAG|Bundestag|BUNDESTAG|Bundesrat|BUNDESRAT|Bürgerschaft|BÜRGERSCHAFT|Abgeordnetenhaus|ABGEORDNETENHAUS)(?:\s(?:von|des|der)\s[A-ZÄÖÜ][\wäöüß\-]+)?)"
)
PERIOD_RE = re.compile(r"(\d{1,2})\.\s*Wahlperiode", re.I)
PRINT_NO_RE = re.compile(r"Drucksache\s*(\d{1,2})\s*/\s*(\d{1,6})", re.I)
KIND_RE = re.compile(
    r"^\s*(Gesetzentwurf|Antrag|Dringlichkeitsantrag|Änderungsantrag|Entschließungsantrag|Beschlussempfehlung und Bericht|Bericht und Beschlussempfehlung|Beschlussempfehlung|Bericht|Kleine Anfrage|Große Anfrage|Schriftliche Anfrage|Anfragen zum Plenum|Antwort|Unterrichtung|Mitteilung)\b",
    re.M,
)
ORIGINATOR_RE = re.compile(r"^\s*(?:Gesetzentwurf|Antrag|Dringlichkeitsantrag|Änderungsantrag|Kleine Anfrage|Schriftliche Anfrage|Antwort)\s+(der|des)\s+(.+?)(?:\n|$)", re.M)
COMMITTEE_RE = re.compile(r"\b(?:des|der)\s+((?:Innen-\s+und\s+)?(?:[\wäöüß\-]+)?[Aa]usschuss(?:es)?\b[^\n]*)")
RECOMMENDATION_RE = re.compile(r"Beschlussempfehlung\s*:?\s*\n?\s*([A-ZÄÖÜ][^\n]{2,60})")
RAPPORTEUR_RE = re.compile(r"^\s*(Mitberichterstatter(?:in)?|Berichterstatter(?:in)?)\s*:\s*(.+)$", re.M)
VOTE_RE = re.compile(r"^[ \t]*([A-ZÄÖÜ][\wÄÖÜäöü/ .\-]{1,30}?)[ \t]*:[ \t]*(Zustimmung|Ablehnung|Enthaltung|Annahme|Zustimmung mit Änderungen)[ \t]*$", re.M)
CHAIR_RE = re.compile(r"^\s*([A-ZÄÖÜ][\wäöüß.\- ]{3,60})\s*\n\s*(Vorsitzende[r]?|Präsident(?:in)?|Stellv\. Vorsitzende[r]?)\s*$", re.M)

SESSION_RE = re.compile(r"(\d+)\.\s*(Plenum|Sitzung|Plenarsitzung)\b")
AGENDA_RE = re.compile(r"Tagesordnungspunkt(?:e)?\s+(\d+(?:\s?[a-z]\b)?(?:\s*(?:und|bis)\s*\d+(?:\s?[a-z]\b)?)?)", re.I)

ROLE_WORDS = (
    "Präsident",
    "Präsidentin",
    "Vizepräsident",
    "Vizepräsidentin",
    "Alterspräsident",
    "Staatsminister",
    "Staatsministerin",
    "Staatssekretär",
    "Staatssekretärin",
    "Ministerpräsident",
    "Ministerpräsidentin",
    "Minister",
    "Ministerin",
    "Bundesminister",
    "Bundesministerin",
    "Abg.",
    "Senator",
    "Senatorin",
)
SPEAKER_RE = re.compile(r"^\s*(?P<head>[^:()\n]{3,90}?)(?:\s\((?P<paren>[^)]{1,80})\))?\s*:\s+(?P<rest>.*)$", re.S)
INTERJECTION_RE = re.compile(r"^\s*\((?:[^()]|\([^()]*\))+\)\s*$", re.S)
PARTIES = ("CSU", "CDU", "SPD", "AfD", "GRÜNE", "BÜNDNIS 90/DIE GRÜNEN", "FREIE WÄHLER", "FDP", "DIE LINKE", "Die Linke", "BSW", "SSW", "fraktionslos", "CDU/CSU")


def _text(b: Block) -> str:
    return b.text or b.raw_text


def _title_case(s: str) -> str:
    return " ".join(w if not w.isupper() or len(w) <= 3 else "-".join(p.capitalize() for p in w.split("-")) for w in s.split())


def extract_print_fields(doc: Document) -> dict:
    page1 = doc.pages[0] if doc.pages else None
    if page1 is None:
        return {}
    head_blocks = [b for b in page1.all_blocks if b.kind.is_body or b.kind.is_furniture]
    head = "\n".join(_text(b) for b in head_blocks)
    body = "\n".join(_text(b) for b in page1.blocks)
    fields: dict = {}
    m = PRINT_NO_RE.search(head)
    if m:
        fields["number"] = f"{m.group(1)}/{m.group(2)}"
        fields["period"] = int(m.group(1))
    m = PERIOD_RE.search(head)
    if m:
        fields["period"] = int(m.group(1))
    m = PARLIAMENT_RE.search(head)
    if m:
        name = " ".join(m.group(1).split())
        fields["parliament"] = _title_case(name) if name.isupper() else name
    dates = find_dates(head[:600]) or find_dates(head)
    if dates:
        fields["date"] = dates[0]["iso"]
    m = KIND_RE.search(body)
    if m:
        fields["kind"] = m.group(1)
        title = _print_title(page1.blocks, m.group(1))
        if title:
            fields["title"] = title
    m = ORIGINATOR_RE.search(body)
    if m:
        orig = re.split(r"\s+(?:Drs\.|Drucksache)\s*\d", m.group(2).strip())[0]
        orig = re.split(r"\s+(?=(?:zur|zum|über|betreffend)\s)", orig)[0]
        fields["originator"] = orig.strip()
    m = COMMITTEE_RE.search(body)
    if m and "kind" in fields and re.search(r"Bericht|Beschlussempfehlung", fields["kind"]):
        fields["committee"] = " ".join(m.group(1).split()).rstrip(",.")
    full = doc.body_text()
    m = RECOMMENDATION_RE.search(full)
    if m:
        fields["recommendation"] = m.group(1).strip()
    rap = [{"role": r.group(1), "name": r.group(2).strip()} for r in RAPPORTEUR_RE.finditer(full)]
    if rap:
        fields["rapporteurs"] = rap
    votes = _votes(full)
    if votes:
        fields["votes"] = votes
    m = CHAIR_RE.search(full)
    if m:
        fields["signatory"] = {"name": m.group(1).strip(), "role": m.group(2)}
    refs = [f"{a}/{b}" for a, b in DRUCKSACHE_RE.findall(full)]
    refs = [r for r in dict.fromkeys(refs) if r != fields.get("number")]
    if refs:
        fields["referenced_prints"] = refs
    return fields


_TITLE_SKIP = re.compile(
    r"^(des|der)\s.*(Ausschuss|ausschusses)\b|^(Gesetzentwurf|Antrag|Dringlichkeitsantrag|Änderungsantrag)\s+(der|des)\s|^(Drs\.|Drucksache)\s*\d|^\d{1,2}\.\s?\w+\s\d{4}$|^\d{1,2}\.\d{1,2}\.\d{2,4}$|^\d+\.\s*Wahlperiode",
    re.I,
)
_TITLE_START = re.compile(r"^(Entwurf eines|Gesetz|Verordnung|zur|zum|über|betreffend|für|zu)\b")


def _print_title(blocks: list[Block], kind: str) -> str | None:
    """Title of a print: the subject following the kind line (skipping committee,
    originator, number and date lines)."""
    start = next((i for i, b in enumerate(blocks) if _text(b).lstrip().startswith(kind)), None)
    if start is None:
        return None
    rest = " ".join(_text(blocks[start]).split())[len(kind) :].strip(" :")
    candidates = []
    if rest and not _TITLE_SKIP.match(rest):
        candidates.append(rest)
    for b in blocks[start + 1 : start + 8]:
        t = " ".join(_text(b).split())
        if not t:
            continue
        if _TITLE_SKIP.match(t):
            continue
        if len(t) > 250 or (b.kind is not BlockKind.HEADING and t.endswith(".") and not _TITLE_START.match(t)):
            break
        candidates.append(t)
    # "der Staatsregierung zur Änderung ..." -> drop the originator part
    split = []
    for c in candidates:
        m = re.match(r"^(der|des)\s.+?\s(?=(zur|zum|über|betreffend|für|eines)\b)", c)
        split.append(c[m.end() :] if m else c)
    candidates = split
    # prefer an explicit subject line ("Entwurf eines Gesetzes ...", "zur Änderung ...")
    for c in candidates:
        if _TITLE_START.match(c):
            return c
    return candidates[0] if candidates else None


def _votes(text: str) -> list[dict]:
    """Group consecutive 'PARTY: Zustimmung' lines into vote tables."""
    tables: list[dict] = []
    cur: dict[str, str] = {}
    last_end = -1
    for m in VOTE_RE.finditer(text):
        if cur and m.start() - last_end > 3:
            tables.append({"results": cur})
            cur = {}
        cur[" ".join(m.group(1).split())] = m.group(2)
        last_end = m.end()
    if cur:
        tables.append({"results": cur})
    return tables


# --------------------------------------------------------------------------- protocols


def _speaker_from(b: Block) -> tuple[str, str, str, str] | None:
    """Detect a speaker turn at the start of a block. Returns (speaker, role, party, rest)."""
    text = _text(b)
    m = SPEAKER_RE.match(text)
    if not m:
        return None
    head = " ".join(m.group("head").split())
    paren = (m.group("paren") or "").strip()
    first_line = b.lines[0] if b.lines else None
    bold_prefix = False
    if first_line is not None:
        words = first_line.words
        n = 0
        for w in words:
            if not w.bold:
                break
            n += 1
            if w.text.endswith(":") or w.text.endswith("):"):
                bold_prefix = True
                break
    role = next((r for r in ROLE_WORDS if re.search(rf"(^|\s){re.escape(r)}(\s|$)", head)), "")
    party = paren if any(p in paren for p in PARTIES) else ""
    if not (bold_prefix or role or party):
        return None
    if len(head.split()) > 8:
        return None
    name = head
    if role:
        idx = head.find(role)
        name = head[idx + len(role) :].strip()
        role = head[: idx + len(role)].strip()
    ministry = paren if paren and not party else ""
    if ministry:
        role = f"{role} ({ministry})" if role else ministry
    return name or head, role, party, m.group("rest").strip()


def extract_protocol(doc: Document) -> tuple[dict, list[Speech]]:
    fields: dict = {}
    head = "\n".join(b.raw_text for b in doc.pages[0].all_blocks) if doc.pages else ""
    full_with_furniture = "\n".join(_text(b) for p in doc.pages[:3] for b in p.all_blocks)
    m = SESSION_RE.search(full_with_furniture)
    if m:
        fields["session"] = int(m.group(1))
    dates = find_dates(full_with_furniture)
    if dates:
        fields["date"] = dates[0]["iso"]
    m = PARLIAMENT_RE.search(full_with_furniture)
    if m:
        fields["parliament"] = " ".join(m.group(1).split())
    m = PERIOD_RE.search(full_with_furniture)
    if m:
        fields["period"] = int(m.group(1))
    body = doc.body_text()
    agenda = list(dict.fromkeys(m.group(1) for m in AGENDA_RE.finditer(body)))
    if agenda:
        fields["agenda_items"] = agenda
    refs = list(dict.fromkeys(f"{a}/{b}" for a, b in DRUCKSACHE_RE.findall(body)))
    if refs:
        fields["referenced_prints"] = refs
    # speaker list on a cover page ("Redner zu nachfolgendem Tagesordnungspunkt")
    m = re.search(r"Redner(?:innen)?(?: und Rednerinnen)? zu[^\n]*\n((?:[^\n]+\n?){1,40})", head)
    if m:
        fields["speaker_list"] = [ln.strip() for ln in m.group(1).split("\n") if ln.strip()]

    speeches: list[Speech] = []
    cur: Speech | None = None
    for b in doc.body_blocks:
        if b.kind not in (BlockKind.PARAGRAPH, BlockKind.HEADING, BlockKind.LIST_ITEM):
            continue
        text = _text(b).strip()
        if not text:
            continue
        if INTERJECTION_RE.match(text):
            b.labels.add("interjection")
            if cur is not None:
                cur.paragraphs.append(text)
            continue
        sp = _speaker_from(b)
        if sp is not None:
            name, role, party, rest = sp
            cur = Speech(speaker=name, role=role, party=party, paragraphs=[rest] if rest else [], page=b.page)
            speeches.append(cur)
            b.labels.add("speaker_turn")
            continue
        if cur is not None:
            cur.paragraphs.append(text)
    if speeches:
        seen: dict[str, dict] = {}
        for s in speeches:
            key = s.speaker
            if key not in seen:
                seen[key] = {"name": s.speaker, "role": s.role, "party": s.party, "turns": 0}
            seen[key]["turns"] += 1
        fields["speakers"] = list(seen.values())
    # title: agenda item heading text (first blocks after the first speaker turn opening the item)
    m = re.search(r"(Gesetzentwurf|Antrag|Dringlichkeitsantrag)\s+(der|des)\s+[\s\S]{3,400}?\(Drs\.\s*\d+/\d+\)", body)
    if m:
        fields["topic"] = " ".join((m.group(0)).split())
    return fields, speeches
