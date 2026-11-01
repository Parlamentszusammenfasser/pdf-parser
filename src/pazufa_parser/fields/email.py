"""Field extraction for printed e-mails (Outlook / Thunderbird / webmail printouts)."""

from __future__ import annotations

import re

from ..model import Block, Document
from .common import EMAIL_RE, find_dates

KEYS = {
    "von": "from", "from": "from", "absender": "from",
    "an": "to", "to": "to", "empfänger": "to",
    "cc": "cc", "bcc": "bcc", "kopie": "cc",
    "betreff": "subject", "subject": "subject",
    "gesendet": "date", "gesendet am": "date", "sent": "date", "datum": "date", "date": "date",
    "anlagen": "attachments", "attachments": "attachments", "anhang": "attachments", "anhänge": "attachments",
    "wichtigkeit": "importance", "importance": "importance",
}  # fmt: skip
HEADER_RE = re.compile(r"^\s*(" + "|".join(sorted(KEYS, key=len, reverse=True)) + r")\s*:\s*(.*)$", re.I)
LIST_KEYS = {"to", "cc", "bcc"}


_NAME_ADDR_RE = re.compile(r"([^<>;]*?)\s*<([^<>\s]+@[^<>\s]+)>")


def _split_addresses(value: str) -> list[dict]:
    """'A <a@x.de>; B <b@x.de>', 'a@x.de, b@x.de', 'Name only' -> [{name, email}]."""
    out: list[dict] = []
    value = re.sub(r"\[mailto:[^\]]*\]", "", value)
    pairs = list(_NAME_ADDR_RE.finditer(value))
    if pairs:
        for m in pairs:
            name = m.group(1).strip(" ;,'\"")
            out.append({k: v for k, v in (("name", name), ("email", m.group(2))) if v})
        rest = _NAME_ADDR_RE.sub(";", value)
    else:
        rest = value
    for part in re.split(r"[;,]", rest):
        part = part.strip(" '\"")
        if not part:
            continue
        m = EMAIL_RE.search(part)
        if m:
            name = part.replace(m.group(0), "").strip(" <>'\"")
            out.append({k: v for k, v in (("name", name), ("email", m.group(0))) if v})
        elif not pairs:
            out.append({"name": part})
    return out


def parse_header_lines(lines: list[str], groups: list[int] | None = None) -> tuple[dict, int]:
    """Parse header lines from the top. Returns (fields, number of consumed lines).

    ``groups`` optionally gives a layout-block id per line; continuation lines are
    only accepted within the block of the header line they continue.
    """
    fields: dict = {}
    last: str | None = None
    last_group = None
    consumed = 0
    for i, raw in enumerate(lines):
        line = raw.replace("\t", " ").rstrip()
        group = groups[i] if groups else None
        m = HEADER_RE.match(line)
        if m:
            key = KEYS[m.group(1).lower()]
            if key in fields and key != "attachments":
                break  # next message header block starts
            value = m.group(2).strip()
            if key == "attachments":
                fields.setdefault(key, [])
                if value:
                    fields[key].append(value)
            else:
                fields[key] = value
            last, last_group = key, group
            consumed = i + 1
            continue
        if last and line.strip() and group == last_group and _continuation(raw, last):
            if last == "attachments":
                fields[last].append(line.strip())
            else:
                fields[last] = (fields[last] + " " + line.strip()).strip()
            consumed = i + 1
            continue
        break
    return fields, consumed


def _continuation(raw: str, last: str) -> bool:
    s = raw.strip()
    if not s or HEADER_RE.match(s):
        return False
    if last == "attachments":
        return bool(re.search(r"\.\w{2,5}$", s))
    if last in ("to", "cc", "bcc", "from"):
        return "@" in s or s.rstrip().endswith(";")
    # wrapped subject lines: no salutation, no sentence end
    return last == "subject" and not re.match(r"(Sehr geehrte|Liebe|Hallo|Guten Tag)", s) and len(s) < 140


def _finalize(h: dict) -> dict:
    out = dict(h)
    for k in LIST_KEYS:
        if k in out:
            out[k] = _split_addresses(out[k])
    if "from" in out:
        addrs = _split_addresses(out["from"])
        out["from"] = addrs[0] if addrs else {"name": out["from"]}
    if "date" in out:
        out["date_text"] = out["date"]
        d = find_dates(out["date"])
        out["date"] = d[0]["iso"] if d else None
        tm = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", out["date_text"])
        if tm and out["date"]:
            out["datetime"] = f"{out['date']}T{int(tm.group(1)):02d}:{tm.group(2)}:{tm.group(3) or '00'}"
    if "subject" in out:
        subj = out["subject"]
        prefixes = []
        while True:
            m = re.match(r"^\s*(WG|AW|Fwd?|Re|RE|FW|Wtr|SV|VS)\s*:\s*", subj, re.I)
            if not m:
                break
            prefixes.append(m.group(1).upper())
            subj = subj[m.end() :]
        if prefixes:
            out["subject_prefixes"] = prefixes
            out["forwarded"] = any(p in ("WG", "FW", "FWD", "WTR", "VS") for p in prefixes)
            out["reply"] = any(p in ("AW", "RE", "SV") for p in prefixes)
        out["subject_clean"] = subj.strip()
    return out


def extract_email_fields(doc: Document) -> dict:
    blocks: list[Block] = [b for p in doc.pages for b in p.blocks]
    lines: list[tuple[Block, str]] = [(b, ln.text) for b in blocks for ln in b.lines]
    texts = [t for _, t in lines]
    groups = [id(b) for b, _ in lines]
    fields: dict = {}
    headers, n = parse_header_lines(texts, groups)
    if headers:
        fields.update(_finalize(headers))
        for b, _ in lines[:n]:
            b.labels.add("email_header")
    # embedded (quoted / forwarded) messages
    thread = []
    i = n
    while i < len(texts):
        m = HEADER_RE.match(texts[i].replace("\t", " "))
        if m and KEYS[m.group(1).lower()] == "from":
            h, k = parse_header_lines(texts[i:], groups[i:])
            if len(h) >= 3:
                thread.append(_finalize(h))
                for b, _ in lines[i : i + k]:
                    b.labels.add("email_header")
                i += k
                continue
        i += 1
    if thread:
        fields["thread"] = thread
    return fields
