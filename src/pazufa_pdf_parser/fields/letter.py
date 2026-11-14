"""Field extraction for letters (DIN 5008 style and similar)."""

from __future__ import annotations

import re

from ..model import Block, BlockKind, Document, RegionKind
from .common import EMAIL_RE, POSTAL_RE, first_date

SALUTATION_RE = re.compile(r"^\s*(Sehr geehrte[rs]?|Liebe[rs]?|Guten Tag|Hallo|Dear|Hello)\b[^\n]*", re.I)
CLOSING_RE = re.compile(
    r"(Mit freundlichen Grüßen|Mit freundlichem Gruß|Freundliche Grüße|Mit besten Grüßen|Beste Grüße|Viele Grüße|Hochachtungsvoll|Mit kollegialen Grüßen|Kind regards|Best regards|Yours sincerely|Yours faithfully|Sincerely)",
    re.I,
)
SUBJECT_PREFIX_RE = re.compile(r"^\s*(Betreff|Betr\.|Subject|Re|Az\.)\s*:\s*", re.I)
RETURN_ADDRESS_SEP_RE = re.compile(r"\s*[|·•∙]\s*|\s+[-–]\s+(?=\S)")
DATE_LINE_RE = re.compile(r"^\s*(?:(Datum|Date)\s*:?\s*)?(?:([A-ZÄÖÜ][\wäöüß\-. ]{1,30}),\s*(?:den\s+)?)?(\d{1,2}\.\s?(\d{1,2}\.|[A-Za-zäÄ]+)\s?\d{2,4})\s*$")
SIGN_PREFIX_RE = re.compile(r"^(i\.\s?A\.|i\.\s?V\.|gez\.|p\.\s?p\.|ppa\.)\s*", re.I)
ATTACHMENT_RE = re.compile(r"^\s*(Anlagen?|Anhang|Attachments?)\s*:?\s*$|^\s*(Anlagen?|Anhang)\s*:\s*(.+)$", re.I | re.M)


_CLOSINGS = ("Mit freundlichen Grüßen", "Freundliche Grüße", "Mit besten Grüßen", "Hochachtungsvoll", "Viele Grüße")


class _FuzzyMatch:
    """Minimal stand-in for re.Match used for OCR-damaged closings."""

    def __init__(self, phrase: str, end: int):
        self._phrase, self._end = phrase, end

    def group(self, n: int = 0) -> str:
        return self._phrase

    def end(self) -> int:
        return self._end


def _fuzzy_closing(text: str) -> _FuzzyMatch | None:
    """Match OCR-damaged closings ("it freuhdlichen Grüßen") on short lines."""
    from difflib import SequenceMatcher

    pos = 0
    for line in text.split("\n"):
        stripped = line.strip(" ,.")
        if 10 <= len(stripped) <= 40:
            for phrase in _CLOSINGS:
                if SequenceMatcher(None, stripped.lower(), phrase.lower()).ratio() >= 0.8:
                    return _FuzzyMatch(phrase, pos + len(line))
        pos += len(line) + 1
    return None


def _is_scribble(line: str) -> bool:
    """OCR of a handwritten signature: mostly 1-2 letter fragments."""
    toks = line.split()
    if not toks:
        return True
    short = sum(1 for t in toks if len(t.strip(".,")) <= 2)
    return len(toks) >= 2 and short / len(toks) >= 0.6 or sum(c.isalpha() for c in line) < 3


def _lines(block: Block) -> list[str]:
    return [ln for ln in (block.text or block.raw_text).split("\n") if ln.strip()]


def _block_text(block: Block) -> str:
    return block.text or block.raw_text


def _in_sidebar(doc: Document, block: Block) -> bool:
    """Block lies in a right-hand column of a columns region on its page."""
    page = doc.pages[block.page - 1]
    if page.layout is None:
        return False
    for r in page.layout.iter_regions():
        if r.kind is RegionKind.COLUMNS and not r.synopsis and len(r.children) >= 2:
            right = r.children[-1]
            if any(b is block for b in right.iter_blocks()):
                return right.bbox.x0 > page.width * 0.5 and r.bbox.y0 < page.height * 0.6
    return False


def split_return_address(line: str) -> list[str] | None:
    """'Org | Street 1 | 12345 City' -> parts, if it looks like a return address line."""
    parts = [p.strip() for p in RETURN_ADDRESS_SEP_RE.split(line) if p and p.strip()]
    if len(parts) >= 3 and any(POSTAL_RE.match(p) for p in parts):
        return parts
    return None


def extract_letter_fields(doc: Document, blocks: list[Block] | None = None, *, closing: str = "last") -> dict:
    """Extract letter fields.

    ``blocks`` restricts the extraction to a part of the document (e.g. an e-mail
    body or an attached letter); by default the whole body is used. ``closing``
    selects whether the ``"first"`` or ``"last"`` closing formula is taken.
    """
    body_all = list(blocks) if blocks is not None else [b for p in doc.pages for b in p.blocks]
    blocks = body_all
    fields: dict = {}
    if not blocks:
        return fields
    first_page = blocks[0].page

    # --- salutation
    sal_idx = None
    for i, b in enumerate(blocks):
        m = SALUTATION_RE.match(_block_text(b))
        if m:
            sal_idx = i
            fields["salutation"] = m.group(0).strip()
            b.labels.add("salutation")
            break

    # --- closing + signature
    order = range(len(body_all)) if closing == "first" else range(len(body_all) - 1, -1, -1)
    for i in order:
        b = body_all[i]
        text = _block_text(b)
        m = CLOSING_RE.search(text) or _fuzzy_closing(text)
        if not m:
            continue
        fields["closing"] = m.group(1)
        b.labels.add("closing")
        after = text[m.end() :].strip(" ,\n")
        sig_lines = [ln.strip() for ln in after.split("\n") if ln.strip()]
        j = i + 1
        while len(sig_lines) < 4 and j < len(body_all) and j <= i + 3:
            nb = body_all[j]
            lines = _lines(nb)
            page = doc.pages[nb.page - 1]
            if (
                len(lines) > 4
                or any(len(ln) > 70 for ln in lines)
                or nb.bbox.y0 > page.height * 0.88
                or nb.page != b.page
                or SALUTATION_RE.match(lines[0] if lines else "")
                or any(ln.rstrip().endswith((".", ",", ";", ":")) for ln in lines)
            ):
                break
            sig_lines.extend(lines)
            nb.labels.add("signature")
            j += 1
        sig_lines = [SIGN_PREFIX_RE.sub("", ln).strip() for ln in sig_lines]
        sig_lines = [ln for ln in sig_lines if len(ln) > 1 and not _is_scribble(ln) and not re.search(r"www\.|https?://|@", ln)]
        sig_lines = list(dict.fromkeys(sig_lines))
        if sig_lines:
            fields["signatory"] = {"name": sig_lines[0], "lines": sig_lines[:5]}
            if len(sig_lines) > 1:
                fields["signatory"]["role"] = sig_lines[1]
        break

    # --- page-1 header zone: everything before the salutation
    head = [b for b in blocks[: sal_idx if sal_idx is not None else min(len(blocks), 12)] if b.page == first_page]
    sidebar = [b for b in blocks if b.page == first_page and _in_sidebar(doc, b)]
    head += [b for b in sidebar if b not in head]
    main = [b for b in head if b not in sidebar]

    # return address line
    for b in main:
        for ln in _lines(b):
            parts = split_return_address(ln)
            if parts:
                fields["return_address"] = parts
                b.labels.add("return_address")
                break
        if "return_address" in fields:
            break

    # recipient: lines ending with a postal code line, assembled from preceding short blocks
    recipient: list[str] = []
    for idx, b in enumerate(main):
        if "return_address" in b.labels:
            continue
        lines = _lines(b)
        pi = next((k for k, ln in enumerate(lines) if POSTAL_RE.match(ln.strip())), None)
        if pi is None:
            continue
        recipient = lines[: pi + 1]
        k = idx - 1
        while k >= 0 and len(recipient) < 9:
            prev = main[k]
            pl = _lines(prev)
            if "return_address" in prev.labels or len(pl) > 4 or any(len(x) > 60 for x in pl) or DATE_LINE_RE.match(pl[0]):
                break
            if prev.bbox.y1 < b.bbox.y0 - 6 * max(b.size, 8):
                break
            recipient = pl + recipient
            prev.labels.add("recipient")
            k -= 1
        trailing = lines[pi + 1 :]
        b.labels.add("recipient")
        # "- per E-Mail -" style dispatch note
        if idx + 1 < len(main):
            nl = _lines(main[idx + 1])
            if len(nl) == 1 and re.match(r"^[-–(]?\s*(per|via|vorab per)\s+(E-Mail|Fax|Boten|Post)", nl[0], re.I):
                fields["dispatch_note"] = nl[0].strip("-–() ")
        if trailing and re.match(r"^[-–(]?\s*(per|via|vorab per)\s", trailing[0], re.I):
            fields["dispatch_note"] = trailing[0].strip("-–() ")
        break
    if recipient:
        postal = POSTAL_RE.match(recipient[-1].strip())
        fields["recipient"] = {"lines": recipient}
        if postal:
            fields["recipient"]["postal_code"] = postal.group(1)
            fields["recipient"]["city"] = postal.group(2).strip()
        if len(recipient) >= 2:
            fields["recipient"]["street"] = recipient[-2]
        fields["recipient"]["name"] = recipient[0]

    # --- date: prefer a standalone date line in the header zone (main or sidebar)
    for b in head:
        for ln in _lines(b):
            m = DATE_LINE_RE.match(ln.strip())
            if m:
                d = first_date(ln)
                if d:
                    fields["date"] = d["iso"]
                    if m.group(2):
                        fields["place"] = m.group(2).strip()
                    break
        if "date" in fields:
            break
    if "date" not in fields:
        for b in head:
            t = _block_text(b)
            if re.search(r"\b(Datum|Date)\b", t):
                d = first_date(t)
                if d:
                    fields["date"] = d["iso"]
                    break

    # --- subject: block right before the salutation that is not address/date
    if sal_idx is not None:
        for b in reversed(main):
            t = _block_text(b).strip()
            if not t or b.labels & {"recipient", "return_address"}:
                if b.labels & {"recipient"}:
                    break
                continue
            if DATE_LINE_RE.match(t.split("\n")[0]) or len(t) > 300:
                continue
            if re.search(r"\b(Datum|Telefon|E-Mail|Ansprechpartner)", t) and "\t" in b.raw_text:
                continue
            fields["subject"] = SUBJECT_PREFIX_RE.sub("", " ".join(t.split("\n"))).strip()
            b.labels.add("subject")
            break

    # --- sender: sidebar text, else return address, else letterhead / header furniture
    sender: dict = {}
    if sidebar:
        lines = [ln for b in sidebar for ln in _lines(b)]
        sender["lines"] = lines[:30]
        sender["name"] = lines[0] if lines else ""
        for b in sidebar:
            b.labels.add("sender")
    elif "return_address" in fields:
        sender["name"] = fields["return_address"][0]
        sender["lines"] = fields["return_address"]
    else:
        page = doc.pages[first_page - 1]
        heads = [b for b in page.furniture if b.kind is BlockKind.HEADER]
        top = heads or [b for b in main[:1] if b.bbox.y1 < page.height * 0.2 and "recipient" not in b.labels]
        lines = [ln for b in top for ln in _lines(b)]
        if lines:
            sender["name"] = " ".join(lines[:2]) if len(lines[0]) < 25 else lines[0]
            sender["lines"] = lines[:10]
    if sender:
        sender_text = "\n".join(sender.get("lines", []))
        emails = [m.group(0) for m in EMAIL_RE.finditer(sender_text)]
        if emails:
            sender["email"] = emails[0]
        fields["sender"] = sender

    # --- a second letter attached after this one's closing (e.g. e-mail + attached letter)
    if closing == "first" and "closing" in fields:
        ci = next((i for i, b in enumerate(body_all) if "closing" in b.labels), None)
        if ci is not None:
            rest = [b for b in body_all[ci + 1 :] if "signature" not in b.labels]
            if any(SALUTATION_RE.match(_block_text(b)) for b in rest):
                fields["attached_letter"] = extract_letter_fields(doc, rest, closing="last")

    # --- attachments ("Anlage(n): ...")
    tail_text = "\n".join(_block_text(b) for b in body_all[-6:])
    atts: list[str] = []
    for m in ATTACHMENT_RE.finditer(tail_text):
        if m.group(3):
            atts.append(m.group(3).strip())
    if atts:
        fields["attachments"] = atts
    return fields
