"""Text sanitation: artifact removal, de-hyphenation and paragraph reflow."""

from __future__ import annotations

import re
import unicodedata

from .model import Block, BlockKind, Line

LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    "Ĳ": "IJ",
    "ĳ": "ij",
    "Œ": "OE",
    "œ": "oe",
}

# characters that are pure artifacts in running text
_DROP = dict.fromkeys(map(ord, "­​‌‍⁠﻿‎‏‪‫‬‭‮￼\x00"))
_SPACES = dict.fromkeys(map(ord, "              　"), " ")
_BULLETS = dict.fromkeys(map(ord, "▪●■∙‣⁃◦○□➢►"), "•")

_CID_RE = re.compile(r"\(cid:\d+\)")
_PUA_RE = re.compile(r"[-]")
_CTRL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")
# "A b l e h n u n g" -> "Ablehnung" (>= 4 single letters separated by single spaces)
_LETTERSPACED_RE = re.compile(r"(?<!\S)((?:[^\W\d_] ){3,}[^\W\d_])(?!\S)")
_JUNK_LINE_RE = re.compile(r"^[\W_]{1,}$")
# compound continuation: keep hyphen ("Aus- und Fortbildung")
_KEEP_HYPHEN_NEXT = {"und", "oder", "bzw", "bzw.", "sowie", "als", "bis", "noch", "wie", "&", "u.", "or", "and"}

_FIELD_LINE_RE = re.compile(
    r"^(Von|An|Cc|CC|Bcc|Betreff|Gesendet( am)?|Datum|Anlagen?|From|To|Subject|Sent|Date|Tel(efon)?\.?|Fax|Mobil|E-?Mail|eMail|Web|Internet|www|Az\.?|Ihr Zeichen|Unser Zeichen|Aktenzeichen)\s*:",
    re.I,
)

# "CSU: Ablehnung", "Berichterstatter: Name" - consecutive label lines form a table
_LABEL_LINE_RE = re.compile(r"^[\w ÄÖÜäöüß/.\-()]{1,40}:\s+\S")
_POSTAL_LINE_RE = re.compile(r"^(D-?\s?)?\d{5}\s+[A-ZÄÖÜ][\wäöüß.\- ]{1,40}$")

# hyphen-like characters at line end that indicate word division
_HYPHENS = "-‐‑­"


def clean_chars(text: str) -> str:
    """Normalise unicode and remove invisible / private-use artifacts. Keeps line breaks."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    for k, v in LIGATURES.items():
        if k in text:
            text = text.replace(k, v)
    text = text.translate(_BULLETS).translate(_DROP).translate(_SPACES)
    text = _CID_RE.sub("", text)
    text = _PUA_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def collapse_letterspacing(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return m.group(1).replace(" ", "")

    return _LETTERSPACED_RE.sub(repl, text)


def normalize_spaces(text: str) -> str:
    text = text.replace("\t", " ")
    text = _MULTISPACE_RE.sub(" ", text)
    # no space before punctuation that OCR sometimes inserts
    text = re.sub(r" +([,;!?)\]])", r"\1", text)
    text = re.sub(r" +([.:])(?=\s|$)", r"\1", text)
    text = re.sub(r"([(\[„]) +", r"\1", text)
    return text.strip()


def is_junk_line(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if _JUNK_LINE_RE.match(t):
        # keep meaningful single symbols / dividers carrying content
        return t not in {"§", "•", "*"}
    return False


def join_hyphenated(first: str, second: str) -> str | None:
    """Join two line fragments if ``first`` ends with a word-division hyphen.

    Returns the joined text, or None if no de-hyphenation applies.
    """
    a = first.rstrip()
    if len(a) < 2 or a[-1] not in _HYPHENS or not a[-2].isalpha():
        return None
    b = second.lstrip()
    if not b:
        return None
    nxt_word = b.split(maxsplit=1)[0]
    if nxt_word.lower().rstrip(",.;") in _KEEP_HYPHEN_NEXT:
        return a + " " + b  # "Aus- und Fortbildung"
    if b[0].islower():
        return a[:-1] + b  # "Parlaments-" + "fragen"
    # "CDU-" + "Fraktion", "E-" + "Mail": keep the hyphen, no space
    return a + b


def is_line_structured(lines: list[str]) -> bool:
    """Addresses, signatures, contact blocks: short lines whose breaks carry meaning."""
    ls = [ln.strip() for ln in lines if ln.strip()]
    if len(ls) < 2 or len(ls) > 10:
        return False
    if any(_POSTAL_LINE_RE.match(ln) for ln in ls) and len(ls) <= 8:
        return True
    if any(len(ln) > 1 and ln[-1] in _HYPHENS and ln[-2].isalpha() for ln in ls):
        return False  # word divided at line end -> running text
    return all(len(ln) <= 60 for ln in ls) and not ls[-1].endswith((".", ";", ":", "!", "?", ",")) and len(ls) <= 6


def reflow_lines(lines: list[str], widths: list[float] | None = None, full_width: float | None = None) -> str:
    """Join wrapped lines of one paragraph into running text.

    Lines that are clearly shorter than the paragraph width (address lines,
    signature lines) keep their line break unless the following line continues
    a hyphenated word. Line-structured blocks keep all breaks.
    """
    if is_line_structured(lines):
        return "\n".join(ln.strip() for ln in lines if ln.strip())
    out = ""
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
            continue
        joined = join_hyphenated(out, line)
        if joined is not None:
            out = joined
            continue
        prev_short = False
        if widths is not None and full_width:
            prev_short = widths[i - 1] < 0.72 * full_width
        prev_line = lines[i - 1].strip()
        if (
            _FIELD_LINE_RE.match(line)
            or (_FIELD_LINE_RE.match(prev_line) and prev_short)
            or (_LABEL_LINE_RE.match(line) and _LABEL_LINE_RE.match(prev_line))
            or _POSTAL_LINE_RE.match(line)
        ):
            out += "\n" + line  # "Key: value" lines (mail headers, contact data) stay separate
        elif prev_short and not out.rstrip().endswith((",",)) and not line[:1].islower():
            out += "\n" + line
        else:
            out += " " + line
    return out


_OCR_FIXES: list[tuple[re.Pattern[str], str]] = [
    # tesseract frequently reads "§" as "8"
    (re.compile(r"(?<=\b[Zz]u )8 (\d{1,3}[a-z]?)\b"), r"§ \1"),
    (re.compile(r"(?<=\b[Zz]u )8(\d{1,3}[a-z]?) (?=(Abs\.|Absatz|Satz|Nr\.)\s)"), r"§ \1 "),
    (re.compile(r"\b8 (\d{1,3}[a-z]?) (?=(Abs\.|Absatz|Satz|Nr\.|S\.)\s)"), r"§ \1 "),
    (
        re.compile(
            r"\b(nach|gemäß|gem\.|des|dem|den|vgl\.|siehe|i\.V\.m\.) 8 (\d{1,3}[a-z]?)(?= (Abs|Satz|Nr|S)\.?\b)"
        ),
        r"\1 § \2",
    ),
    (re.compile(r"\b88 (\d{1,3}[a-z]?)( (und|bis|,) \d)"), r"§§ \1\2"),
    # superscript ² read as "?"
    (re.compile(r"(\d) ?m\?(?=[\s.,;)]|$)"), r"\1 m²"),
    (re.compile(r"—-|-—|--"), "–"),
    # stray quote/apostrophe glued into names: "Wilfried’Mück"
    (re.compile(r"(?<=[a-zäöüß])[’'`](?=[A-ZÄÖÜ][a-zäöüß])"), " "),
]


def fix_ocr_text(text: str) -> str:
    """Conservative corrections for frequent OCR confusions in German legal text."""
    for rx, rep in _OCR_FIXES:
        text = rx.sub(rep, text)
    return text


def sanitize_text(text: str) -> str:
    """Sanitize a free text (no layout info): clean, de-hyphenate, normalise whitespace."""
    text = clean_chars(text)
    paras = re.split(r"\n\s*\n", text)
    out = []
    for p in paras:
        lines = [collapse_letterspacing(normalize_spaces(ln)) for ln in p.split("\n")]
        lines = [ln for ln in lines if not is_junk_line(ln)]
        if lines:
            out.append(reflow_lines(lines))
    return "\n\n".join(out)


def line_text(line: Line, min_conf: float | None = None) -> str:
    """Text of a line with low-confidence OCR words removed."""
    if min_conf is None or all(w.confidence is None for w in line.words):
        return line.text
    words = [w for w in line.words if w.confidence is None or w.confidence >= min_conf]
    return " ".join(w.text for w in words)


def sanitize_block(block: Block, min_conf: float | None = None) -> str:
    texts: list[str] = []
    widths: list[float] = []
    for ln in block.lines:
        t = normalize_spaces(collapse_letterspacing(clean_chars(line_text(ln, min_conf))))
        if is_junk_line(t):
            continue
        texts.append(t)
        widths.append(ln.bbox.width)
    if not texts:
        return ""
    full = max(widths) if widths else None
    if block.kind is BlockKind.HEADING:
        out = reflow_lines(texts)
    else:
        out = reflow_lines(texts, widths, full)
    if any(w.confidence is not None for ln in block.lines for w in ln.words):
        out = fix_ocr_text(out)
    return out


_OCR_GARBAGE_WORD_RE = re.compile(r"^[^\w§€$%&@]{2,}$")


def block_is_noise(block: Block) -> bool:
    """OCR blocks consisting mostly of symbol soup or very low confidence words."""
    text = " ".join(ln.text for ln in block.lines)
    stripped = text.replace(" ", "")
    if not stripped:
        return True
    alnum = sum(ch.isalnum() for ch in stripped)
    conf = block.confidence
    if alnum / len(stripped) < 0.4 and len(stripped) < 80:
        return True
    if conf is not None and conf < 35 and len(stripped) < 40:
        return True
    words = text.split()
    if words and sum(1 for w in words if _OCR_GARBAGE_WORD_RE.match(w)) / len(words) > 0.6:
        return True
    return False
