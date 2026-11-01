"""Rule-based document classification.

Each :class:`Rule` contributes a weighted score to one :class:`DocType` when it
matches in its scope (``head`` = first page incl. furniture, ``all`` = whole
text, ``tail`` = last page). Rules are data: applications can add their own via
``Classifier(extra_rules=...)``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Literal

from .model import Classification, DocType, Document, PageSource, RegionKind

Scope = Literal["head", "all", "tail", "first_lines"]
_M = re.M
_MI = re.M | re.I


@dataclass(frozen=True)
class Rule:
    doc_type: DocType
    name: str
    weight: float
    pattern: re.Pattern[str] | None = None
    scope: Scope = "all"
    max_hits: int = 1  # matches counted at most this often (each adds weight * decay**i)
    predicate: Callable[[ClassifierInput], bool] | None = None

    def score(self, inp: ClassifierInput) -> tuple[float, str | None]:
        if self.predicate is not None:
            return (self.weight, self.name) if self.predicate(inp) else (0.0, None)
        assert self.pattern is not None
        text = inp.scope(self.scope)
        hits = 0
        first = None
        for m in self.pattern.finditer(text):
            hits += 1
            if first is None:
                first = m.group(0)[:60]
            if hits >= self.max_hits:
                break
        if not hits:
            return 0.0, None
        total = sum(self.weight * (0.7**i) for i in range(hits))
        return total, f"{self.name}: {first!r}" + (f" (x{hits})" if hits > 1 else "")


@dataclass
class ClassifierInput:
    head: str
    all: str
    tail: str
    first_lines: str
    features: dict = field(default_factory=dict)

    def scope(self, name: Scope) -> str:
        return getattr(self, name)

    @classmethod
    def from_document(cls, doc: Document) -> ClassifierInput:
        def page_text(p) -> str:
            return "\n".join(b.raw_text for b in p.all_blocks if b.kind.is_body or b.kind.is_furniture)

        pages = doc.pages
        head = page_text(pages[0]) if pages else ""
        all_text = "\n".join(page_text(p) for p in pages)
        tail = page_text(pages[-1]) if pages else ""
        body_lines = [ln.text for b in (pages[0].blocks if pages else []) for ln in b.lines]
        first_lines = "\n".join(body_lines[:20])
        feats = {
            "pages": len(pages),
            "ocr_pages": sum(1 for p in pages if p.source is PageSource.OCR),
            "empty_pages": sum(1 for p in pages if p.source is PageSource.EMPTY),
            "has_synopsis": any(r.synopsis for p in pages if p.layout for r in p.layout.iter_regions()),
            "first_page_columns": bool(
                pages and pages[0].layout and any(r.kind is RegionKind.COLUMNS for r in pages[0].layout.iter_regions())
            ),
            "chars": len(all_text),
        }
        feats["scanned"] = feats["ocr_pages"] > 0 and feats["ocr_pages"] >= feats["pages"] / 2
        feats["language"] = guess_language(all_text)
        return cls(head=head, all=all_text, tail=tail, first_lines=first_lines, features=feats)


_DE_STOP = {"der", "die", "das", "und", "nicht", "mit", "für", "von", "auf", "ist", "den", "des", "zu", "im", "wird"}
_EN_STOP = {"the", "and", "of", "to", "is", "in", "for", "that", "with", "on", "be", "this", "are", "by"}


def guess_language(text: str) -> str:
    words = re.findall(r"[a-zäöüß]+", text.lower()[:20000])
    de = sum(1 for w in words if w in _DE_STOP)
    en = sum(1 for w in words if w in _EN_STOP)
    if de == en == 0:
        return "und"
    return "de" if de >= en else "en"


_EMAIL_KEYS = re.compile(r"^(Von|From|An|To|Cc|CC|Bcc|Betreff|Subject|Gesendet|Sent|Datum|Date|Anlagen|Attachments|Wichtigkeit|Importance)\s*:", _M)


def _email_header_count(inp: ClassifierInput) -> int:
    keys = {m.group(1).lower() for m in _EMAIL_KEYS.finditer(inp.first_lines)}
    groups = [{"von", "from"}, {"an", "to"}, {"betreff", "subject"}, {"gesendet", "sent", "datum", "date"}, {"cc", "bcc"}, {"anlagen", "attachments"}]
    return sum(1 for g in groups if keys & g)


T = DocType

DEFAULT_RULES: list[Rule] = [
    # ---- e-mail printouts
    Rule(T.EMAIL, "email headers (>=3)", 7.0, predicate=lambda i: _email_header_count(i) >= 3),
    Rule(T.EMAIL, "email headers (2)", 2.0, predicate=lambda i: _email_header_count(i) == 2),
    Rule(T.EMAIL, "forwarded/reply marker", 0.8, re.compile(r"^(WG|AW|Fwd?|Re|RE|FW):", _M), "first_lines"),
    Rule(T.EMAIL, "original message", 1.0, re.compile(r"-{3,}\s*(Ursprüngliche Nachricht|Original Message)", _MI)),
    # ---- letters
    Rule(T.LETTER, "salutation", 3.0, re.compile(r"^\s*(Sehr geehrte[rs]?|Liebe[rs]?|Guten Tag|Dear)\b", _MI)),
    Rule(T.LETTER, "closing", 2.5, re.compile(r"(Mit freundlichen Grüßen|Freundliche Grüße|Mit besten Grüßen|Hochachtungsvoll|Viele Grüße|Kind regards|Yours sincerely|Best regards)", re.I)),
    Rule(T.LETTER, "postal code line", 1.5, re.compile(r"^\s*(D-?\s?)?\d{5}\s+[A-ZÄÖÜ][\wäöüß\-. ]+$", _M), "head"),
    Rule(T.LETTER, "standalone date", 1.0, re.compile(r"^\s*([A-ZÄÖÜ][\wäöüß\- ]+,\s*(den\s*)?)?\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}\s*$", _M), "head"),
    Rule(T.LETTER, "reference fields", 1.0, re.compile(r"(Ihr Zeichen|Unser Zeichen|Ihre Nachricht vom|Geschäftszeichen|Aktenzeichen|Az\.:?|Ansprechpartner(in)?)", re.I), "head"),
    Rule(T.LETTER, "contact block", 0.6, re.compile(r"^\s*(Telefon|Tel\.?|Fax|E-Mail)\b", _MI), "head"),
    Rule(T.LETTER, "letter layout (sidebar)", 0.5, predicate=lambda i: i.features.get("first_page_columns") and not i.features.get("has_synopsis")),
    Rule(T.LETTER, "statement", 0.5, re.compile(r"\bStellungnahme\b"), "head"),
    # ---- parliamentary prints
    Rule(T.PARLIAMENTARY_PRINT, "Drucksache number", 4.0, re.compile(r"Drucksache\s*\d{1,2}\s*/\s*\d+", re.I), "head"),
    Rule(T.PARLIAMENTARY_PRINT, "Wahlperiode", 1.5, re.compile(r"\d{1,2}\.\s*Wahlperiode", re.I), "head"),
    Rule(T.PARLIAMENTARY_PRINT, "parliament", 1.0, re.compile(r"(Landtag|Bundestag|Bundesrat|Bürgerschaft|Abgeordnetenhaus)", re.I), "head"),
    Rule(T.PARLIAMENTARY_PRINT, "print kind", 1.5, re.compile(r"^\s*(Gesetzentwurf|Antrag|Dringlichkeitsantrag|Änderungsantrag|Beschlussempfehlung|Bericht und Beschlussempfehlung|Kleine Anfrage|Große Anfrage|Schriftliche Anfrage|Anfragen zum Plenum|Antwort|Unterrichtung|Entschließungsantrag)\b", _M), "head"),
    Rule(T.PARLIAMENTARY_PRINT, "A) Problem", 1.5, re.compile(r"^\s*A\)?\s*(Problem|Problem und Ziel)\b", _M)),
    Rule(T.PARLIAMENTARY_PRINT, "B) Lösung", 1.0, re.compile(r"^\s*B\)?\s*Lösung\b", _M)),
    # ---- plenary protocols
    Rule(T.PLENARY_PROTOCOL, "protocol title", 4.0, re.compile(r"\b(Plenarprotokoll|Protokollauszug|Stenografischer Bericht|Stenographischer Bericht|Plenarsitzung)\b", re.I), "all", max_hits=1),
    Rule(T.PLENARY_PROTOCOL, "session", 1.0, re.compile(r"\d+\.\s*(Plenum|Plenarsitzung|Sitzung des (Landtags|Bundestages|Bundesrates))\b"), "head"),
    Rule(
        T.PLENARY_PROTOCOL,
        "speaker turns",
        0.8,
        re.compile(
            r"^\s*((Erste[rn]?\s|Zweite[rn]?\s|Dritte[rn]?\s)?(Vize)?[Pp]räsident(in)?|Abg\.|Staatsminister(in)?|Staatssekretär(in)?|Ministerpräsident(in)?|Bundesminister(in)?|[A-ZÄÖÜ][\w\-]+ [A-ZÄÖÜ][\w\-]+ \((CSU|SPD|AfD|GRÜNE|BÜNDNIS 90/DIE GRÜNEN|FREIE WÄHLER|FDP|CDU|CDU/CSU|DIE LINKE|Die Linke|BSW|SSW|fraktionslos)\))[^:\n]{0,80}:\s",
            _M,
        ),
        max_hits=8,
    ),
    Rule(T.PLENARY_PROTOCOL, "applause", 0.4, re.compile(r"\((Beifall|Zuruf|Heiterkeit|Lachen|Widerspruch)\b"), max_hits=4),
    Rule(T.PLENARY_PROTOCOL, "agenda item", 1.0, re.compile(r"Tagesordnungspunkt", re.I)),
    # ---- statutes / regulations
    Rule(T.STATUTE, "§ headings", 0.8, re.compile(r"^\s*§\s*\d+[a-z]?\s*$|^\s*§\s*\d+[a-z]?\s+[A-ZÄÖÜ][^.\n]{2,80}$", _M), max_hits=6),
    Rule(T.STATUTE, "article headings", 0.7, re.compile(r"^\s*Artikel\s+\d+[a-z]?\s*$", _M), max_hits=4),
    Rule(T.STATUTE, "entry into force", 1.0, re.compile(r"tritt\s.{0,60}\sin\s+Kraft", re.I | re.S)),
    Rule(T.STATUTE, "law title", 1.0, re.compile(r"^\s*(Gesetz|Verordnung|Satzung|Bekanntmachung)\s+(über|zur|zum|des|der|für)\b", _M), "head"),
    Rule(T.STATUTE, "table of contents", 0.8, re.compile(r"^\s*(Inhaltsübersicht|Inhaltsverzeichnis)\s*$", _M)),
    Rule(T.STATUTE, "gazette", 1.0, re.compile(r"(BGBl\.|GVBl\.|GVOBl\.|GBl\.|Bundesgesetzblatt|Gesetz- und Verordnungsblatt)"), "head"),
    Rule(T.STATUTE, "enactment formula", 1.5, re.compile(r"(hat das folgende Gesetz beschlossen|verordnet:|wird verordnet|erlässt .{0,80}folgende Satzung)", re.I)),
    # ---- court decisions
    Rule(T.COURT_DECISION, "Im Namen des Volkes", 4.0, re.compile(r"Im\s+Namen\s+des\s+Volkes", re.I)),
    Rule(T.COURT_DECISION, "decision title", 1.5, re.compile(r"^\s*(Urteil|Beschluss|Gerichtsbescheid|Versäumnisurteil|Endurteil|Teilurteil)\s*$", _M), "head"),
    Rule(T.COURT_DECISION, "Tenor", 2.0, re.compile(r"^\s*(Tenor|Leitsätze?|Leitsatz)\s*:?\s*$", _M)),
    Rule(T.COURT_DECISION, "Tatbestand", 2.0, re.compile(r"^\s*Tatbestand\s*:?\s*$", _M)),
    Rule(T.COURT_DECISION, "Entscheidungsgründe", 2.0, re.compile(r"^\s*(Entscheidungsgründe|Gründe)\s*:?\s*$", _M)),
    Rule(T.COURT_DECISION, "court", 1.5, re.compile(r"(Verwaltungsgericht|Landgericht|Amtsgericht|Oberlandesgericht|Bundesgerichtshof|Bundesverfassungsgericht|Verfassungsgerichtshof|Sozialgericht|Landessozialgericht|Bundessozialgericht|Finanzgericht|Bundesfinanzhof|Arbeitsgericht|Landesarbeitsgericht|Bundesarbeitsgericht|Bundesverwaltungsgericht|Verwaltungsgerichtshof|Oberverwaltungsgericht|Kammergericht)"), "head"),
    Rule(T.COURT_DECISION, "parties", 1.0, re.compile(r"(in der Verwaltungsstreitsache|in dem Rechtsstreit|in der Strafsache|in dem Verfahren|Kläger(in)?\b|Beklagte[rn]?\b|Antragsteller(in)?\b|Antragsgegner(in)?\b)", re.I), "head"),
    Rule(T.COURT_DECISION, "Rechtsmittelbelehrung", 1.5, re.compile(r"(Rechtsmittelbelehrung|Rechtsbehelfsbelehrung)", re.I)),
    Rule(T.COURT_DECISION, "file number", 1.0, re.compile(r"\b\d{1,2}\s?(BvR|BvL|BvF|BvE|C|K|KR|S|O|U|W|ZR|StR|AZR|B|L|N|Ws|Ss)\s?\d+/\d{2}\b"), "head"),
    # ---- contracts
    Rule(T.CONTRACT, "contract title", 1.5, re.compile(r"^\s*([\wäöüß\-]*vertrag|Vereinbarung|Vertrag|Kooperationsvereinbarung|Rahmenvereinbarung)\b", _MI), "head"),
    Rule(T.CONTRACT, "between ... and", 1.0, re.compile(r"^\s*zwischen\s*$|\bzwischen\b.{0,200}\bund\b", _MI | re.S), "head"),
    Rule(T.CONTRACT, "party designation", 2.0, re.compile(r"(nachfolgend|im Folgenden|nachstehend)\s+[„\"»]?[\wäöüß\- ]{2,40}[“\"«]?\s+genannt", re.I)),
    Rule(T.CONTRACT, "contract parties", 1.0, re.compile(r"(Vertragsparteien|Vertragspartner|Auftraggeber|Auftragnehmer|Vermieter|Mieter|Arbeitgeber|Arbeitnehmer)", re.I), max_hits=2),
    Rule(T.CONTRACT, "contract clauses", 1.5, re.compile(r"§\s*\d+\s+(Vertragsgegenstand|Gegenstand des Vertrages|Laufzeit|Kündigung|Vergütung|Vertragsdauer|Gewährleistung|Haftung|Schlussbestimmungen)", re.I), max_hits=3),
    Rule(T.CONTRACT, "signature place", 1.0, re.compile(r"(Ort,\s*Datum|Unterschrift)", re.I), "tail"),
]

SUBTYPES: dict[DocType, list[tuple[str, re.Pattern[str]]]] = {
    T.PARLIAMENTARY_PRINT: [
        ("bill", re.compile(r"\b(Gesetzentwurf|Entwurf eines (\w+ )?Gesetzes)\b")),
        ("report", re.compile(r"\b(Beschlussempfehlung|Bericht)\b")),
        ("amendment", re.compile(r"\bÄnderungsantrag\b")),
        ("motion", re.compile(r"\b(Dringlichkeitsantrag|Entschließungsantrag|Antrag)\b")),
        ("inquiry", re.compile(r"\b(Kleine Anfrage|Große Anfrage|Schriftliche Anfrage|Anfragen zum Plenum|Anfrage)\b")),
        ("answer", re.compile(r"\bAntwort\b")),
        ("notice", re.compile(r"\b(Unterrichtung|Mitteilung)\b")),
    ],
    T.LETTER: [
        ("statement", re.compile(r"\bStellungnahme\b")),
        ("administrative_decision", re.compile(r"\bBescheid\b")),
        ("objection", re.compile(r"\bWiderspruch\b")),
        ("invoice", re.compile(r"\bRechnung(snummer)?\b")),
        ("reminder", re.compile(r"\bMahnung\b")),
        ("termination", re.compile(r"\bKündigung\b")),
    ],
    T.COURT_DECISION: [
        ("judgment", re.compile(r"\b(Urteil|Endurteil|Teilurteil|Versäumnisurteil)\b")),
        ("order", re.compile(r"\b(Beschluss|Gerichtsbescheid)\b")),
    ],
    T.STATUTE: [
        ("regulation", re.compile(r"\bVerordnung\b")),
        ("bylaw", re.compile(r"\bSatzung\b")),
        ("act", re.compile(r"\bGesetz\b")),
    ],
    T.PLENARY_PROTOCOL: [
        ("excerpt", re.compile(r"\bProtokollauszug\b")),
        ("full", re.compile(r"\b(Plenarprotokoll|Stenografischer Bericht)\b")),
    ],
}

MIN_SCORE = 2.5


class Classifier:
    def __init__(self, rules: list[Rule] | None = None, extra_rules: list[Rule] | None = None):
        self.rules = list(rules if rules is not None else DEFAULT_RULES) + list(extra_rules or [])

    def classify_input(self, inp: ClassifierInput) -> Classification:
        scores: dict[str, float] = {t.value: 0.0 for t in DocType if t is not DocType.GENERIC}
        evidence: dict[str, list[str]] = {}
        for rule in self.rules:
            s, why = rule.score(inp)
            if s:
                scores[rule.doc_type.value] = scores.get(rule.doc_type.value, 0.0) + s
                evidence.setdefault(rule.doc_type.value, []).append(why or rule.name)
        # an e-mail printout of a letter is an e-mail; a print containing a law is a print
        if scores.get(T.EMAIL.value, 0) >= 7:
            scores[T.LETTER.value] *= 0.5
        if scores.get(T.PARLIAMENTARY_PRINT.value, 0) >= 5.5:
            scores[T.STATUTE.value] *= 0.6
        if scores.get(T.PLENARY_PROTOCOL.value, 0) >= 5:
            scores[T.PARLIAMENTARY_PRINT.value] *= 0.5
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best, best_score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_score < MIN_SCORE:
            doc_type = DocType.GENERIC
            confidence = round(1 - best_score / MIN_SCORE, 3) if best_score else 0.5
        else:
            doc_type = DocType(best)
            margin = (best_score - second) / best_score
            strength = 1 - math.exp(-best_score / 4)
            confidence = round(max(0.05, min(0.99, 0.5 * margin + 0.5 * strength)), 3)
        subtype = self._subtype(doc_type, inp)
        return Classification(
            doc_type=doc_type,
            subtype=subtype,
            confidence=confidence,
            scores={k: round(v, 2) for k, v in ranked},
            evidence=evidence,
            features=inp.features,
        )

    def classify(self, doc: Document) -> Classification:
        return self.classify_input(ClassifierInput.from_document(doc))

    @staticmethod
    def _subtype(doc_type: DocType, inp: ClassifierInput) -> str | None:
        options = SUBTYPES.get(doc_type)
        if not options:
            return None
        texts = [inp.first_lines + "\n" + inp.head]
        if doc_type is DocType.PLENARY_PROTOCOL:
            texts.append(inp.all[:20000])  # "Protokollauszug" often only in running headers
        for text in texts:
            best: tuple[int, str] | None = None
            for name, rx in options:
                m = rx.search(text)
                if m and (best is None or m.start() < best[0]):
                    best = (m.start(), name)
            if best:
                return best[1]
        return None
