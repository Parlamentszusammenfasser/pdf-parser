"""Text-layer extraction with pdfium: characters -> words in view space."""

from __future__ import annotations

import ctypes
import math
import unicodedata
from dataclasses import dataclass
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as R

from ..model import BBox, TextSource, Word
from ..source import PDFIUM_LOCK

_ITALIC_FLAG = 1 << 6
_FORCE_BOLD_FLAG = 1 << 18
_BOLD_NAME_HINTS = ("bold", "black", "heavy", "semibold", "demibold", "extrabold", "fett")
_ITALIC_NAME_HINTS = ("italic", "oblique", "kursiv")


class Affine:
    """Maps PDF user space (y up, unrotated) to view space (y down, rotated)."""

    __slots__ = ("a", "b", "c", "d", "e", "f")

    def __init__(self, a: float, b: float, c: float, d: float, e: float, f: float):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f

    def box(self, left: float, bottom: float, right: float, top: float) -> BBox:
        pts = [self.apply(left, bottom), self.apply(right, bottom), self.apply(left, top), self.apply(right, top)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return BBox(min(xs), min(ys), max(xs), max(ys))

    def direction_angle(self, radians: float) -> int:
        """View-space reading direction (0, 90, 180, 270) of text whose pdfium char angle is ``radians``.

        pdfium reports the angle clockwise, i.e. the user-space direction is ``-radians``.
        """
        dx, dy = math.cos(-radians), math.sin(-radians)
        vx = self.a * dx + self.c * dy
        vy = self.b * dx + self.d * dy
        deg = math.degrees(math.atan2(-vy, vx)) % 360
        return int(round(deg / 90.0)) % 4 * 90


def page_affine(page: pdfium.PdfPage) -> Affine:
    """Derive the user->view transform from pdfium (includes /Rotate and mediabox origin)."""
    w, h = page.get_size()
    scale = 1000
    sx, sy = int(round(w * scale)), int(round(h * scale))
    out_x, out_y = ctypes.c_int(), ctypes.c_int()

    def dev(px: float, py: float) -> tuple[float, float]:
        R.FPDF_PageToDevice(page.raw, 0, 0, sx, sy, 0, px, py, ctypes.byref(out_x), ctypes.byref(out_y))
        return out_x.value / scale, out_y.value / scale

    unit = 100.0
    ex, ey = dev(0.0, 0.0)
    ax, ay = dev(unit, 0.0)
    cx, cy = dev(0.0, unit)
    return Affine((ax - ex) / unit, (ay - ey) / unit, (cx - ex) / unit, (cy - ey) / unit, ex, ey)


@dataclass(slots=True)
class _Char:
    ch: str
    box: BBox
    size: float
    font: str
    bold: bool
    italic: bool
    angle: int
    invisible: bool
    hyphen: bool
    obj: int = 0  # text object handle (ligature components share it)


@dataclass(slots=True)
class PageText:
    words: list[Word]
    stats: dict[str, Any]


def _suspect(c: _Char) -> bool:
    """Counts toward the page's garbage ratio, which decides OCR; symbol-font glyphs without ToUnicode
    land in the private use area and say the text layer cannot be read either."""
    return _unmapped(c) or unicodedata.category(c.ch) == "Co"


def _unmapped(c: _Char) -> bool:
    """A character the font's encoding could not map. Unlike private-use symbols (bullets, digits of
    symbol fonts) these mark the font itself as broken."""
    return c.ch.startswith("\x00") or _is_garbage(c.ch)


def _is_garbage(ch: str) -> bool:
    return ch == "�" or unicodedata.category(ch) in ("Cc", "Cs", "Cn") and ch not in "\t\n\r"


# loose char boxes span ascent..descent, roughly 1.15 em for common fonts
_LOOSE_BOX_EM = 1.15


def plausible_size(reported: float, box: BBox, angle: int) -> float:
    """Font size as seen on the page.

    pdfium reports the nominal ``Tf`` size; producers that draw with ``1 Tf`` and
    scale via the text matrix (e.g. Outlook printouts) yield sizes around 1. If the
    reported size disagrees with the glyph box by more than 2x, the size measured
    from the box is used instead.
    """
    extent = box.height if angle in (0, 180) else box.width
    measured = extent / _LOOSE_BOX_EM
    if measured <= 0:
        return reported
    if reported < 2.0 or not (0.5 * measured <= reported <= 2.0 * measured):
        return round(measured, 2)
    return reported


def extract_page_words(page: pdfium.PdfPage, rotation_aware: bool = True) -> PageText:
    """Extract words with font attributes from one page's text layer.

    Must be called with ``PDFIUM_LOCK`` held (or from a single thread).
    """
    affine = page_affine(page)
    textpage = page.get_textpage()
    try:
        chars = _read_chars(textpage, affine)
    finally:
        textpage.close()
    total = sum(1 for c in chars if not c.ch.isspace())
    garbage = sum(1 for c in chars if _suspect(c))
    invisible = sum(1 for c in chars if c.invisible)
    words = _chars_to_words(chars)
    stats = {
        "chars": total,
        "garbage_chars": garbage,
        "invisible_chars": invisible,
        "garbage_ratio": (garbage / total) if total else 0.0,
    }
    return PageText(words=words, stats=stats)


def _read_chars(textpage: pdfium.PdfTextPage, affine: Affine) -> list[_Char]:
    tp = textpage.raw
    n = R.FPDFText_CountChars(tp)
    out: list[_Char] = []
    rect = R.FS_RECTF()
    left, right, bottom, top = ctypes.c_double(), ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
    font_cache: dict[int, tuple[str, bool, bool, bool]] = {}
    name_buf = ctypes.create_string_buffer(256)
    flags = ctypes.c_int()
    prev: _Char | None = None
    for i in range(n):
        cp = R.FPDFText_GetUnicode(tp, i)
        if cp == 0:
            continue
        try:
            ch = chr(cp)
        except ValueError:
            ch = "�"
        generated = bool(R.FPDFText_IsGenerated(tp, i))
        if ch.isspace() or generated and ch in " \r\n":
            out.append(_Char(" ", BBox(0, 0, 0, 0), 0, "", False, False, 0, False, False))
            prev = None
            continue
        if ch == "\x02":
            ch = "-"  # pdfium reports soft hyphens at line ends as STX
        if R.FPDFText_HasUnicodeMapError(tp, i) == 1:
            ch = "\x00" + ch  # marked as garbage, stripped later
        if R.FPDFText_GetLooseCharBox(tp, i, rect):
            box = affine.box(rect.left, rect.bottom, rect.right, rect.top)
        elif R.FPDFText_GetCharBox(
            tp, i, ctypes.byref(left), ctypes.byref(right), ctypes.byref(bottom), ctypes.byref(top)
        ):
            box = affine.box(left.value, bottom.value, right.value, top.value)
        else:
            continue
        size = R.FPDFText_GetFontSize(tp, i)
        obj = R.FPDFText_GetTextObject(tp, i)
        key = ctypes.cast(obj, ctypes.c_void_p).value or 0
        fi = font_cache.get(key)
        if fi is None:
            n_name = R.FPDFText_GetFontInfo(tp, i, name_buf, len(name_buf), ctypes.byref(flags))
            fname = name_buf.value.decode("utf-8", "replace") if n_name else ""
            weight = R.FPDFText_GetFontWeight(tp, i)
            lname = fname.lower()
            bold = weight >= 600 or bool(flags.value & _FORCE_BOLD_FLAG) or any(h in lname for h in _BOLD_NAME_HINTS)
            italic = bool(flags.value & _ITALIC_FLAG) or any(h in lname for h in _ITALIC_NAME_HINTS)
            invisible = bool(obj) and R.FPDFTextObj_GetTextRenderMode(obj) == R.FPDF_TEXTRENDERMODE_INVISIBLE
            fi = (fname, bold, italic, invisible)
            font_cache[key] = fi
        fname, bold, italic, invisible = fi
        angle = affine.direction_angle(R.FPDFText_GetCharAngle(tp, i))
        size = plausible_size(size, box, angle)
        c = _Char(ch, box, size, fname, bold, italic, angle, invisible, bool(R.FPDFText_IsHyphen(tp, i)), key)
        # drop "fake bold" duplicates: identical glyph drawn again at (almost) the same spot by
        # another text object (ligatures like "tt" share one box within the same object)
        if (
            prev is not None
            and prev.obj != c.obj
            and prev.ch == c.ch
            and abs(prev.box.x0 - c.box.x0) < 0.3
            and abs(prev.box.y0 - c.box.y0) < 0.3
        ):
            prev.bold = True
            continue
        out.append(c)
        prev = c
    return out


def _chars_to_words(chars: list[_Char]) -> list[Word]:
    words: list[Word] = []
    cur: list[_Char] = []

    def flush() -> None:
        if not cur:
            return
        text = "".join(c.ch for c in cur)
        bold_chars = sum(1 for c in cur if c.bold)
        sizes = sorted(c.size for c in cur)
        words.append(
            Word(
                text=text,
                bbox=BBox.enclosing(c.box for c in cur),
                size=sizes[len(sizes) // 2],
                bold=bold_chars * 2 > len(cur),
                italic=sum(1 for c in cur if c.italic) * 2 > len(cur),
                font=cur[0].font,
                source=TextSource.PDF,
                angle=cur[0].angle,
                invisible=all(c.invisible for c in cur),
                garbage=sum(1 for c in cur if _unmapped(c)),
            )
        )
        cur.clear()

    for c in chars:
        if c.ch == " ":
            flush()
            continue
        if cur:
            p = cur[-1]
            size = max(p.size, c.size, 1.0)
            if c.angle != p.angle:
                flush()
            elif c.angle == 0:
                same_line = abs(c.box.cy - p.box.cy) < 0.45 * max(p.box.height, c.box.height, 1.0)
                gap = c.box.x0 - p.box.x1
                backwards = c.box.x0 < p.box.x0 - 0.1 * size
                if not same_line or gap > 0.22 * size or (gap < -0.6 * size and backwards):
                    flush()
            else:
                # rotated text: split on large jumps only
                d = math.hypot(c.box.cx - p.box.cx, c.box.cy - p.box.cy)
                if d > 1.6 * size:
                    flush()
        cur.append(c)
    flush()
    # strip the garbage marker but keep text so that raw output shows everything
    for w in words:
        if "\x00" in w.text:
            w.text = w.text.replace("\x00", "")
    return [w for w in words if w.text.strip()]


def image_coverage(page: pdfium.PdfPage) -> float:
    """Fraction of the page area covered by image objects (0..1+)."""
    w, h = page.get_size()
    if w <= 0 or h <= 0:
        return 0.0
    total = 0.0
    try:
        for obj in page.get_objects(filter=[R.FPDF_PAGEOBJ_IMAGE], max_depth=4):
            left, bottom, right, top = obj.get_bounds()
            total += max(0.0, right - left) * max(0.0, top - bottom)
    except Exception:
        return 0.0
    return min(total / (w * h), 1.0)


def page_has_vector_glyphs(page: pdfium.PdfPage) -> int:
    """Number of path objects (outlined text shows up as many paths)."""
    try:
        return sum(1 for _ in page.get_objects(filter=[R.FPDF_PAGEOBJ_PATH], max_depth=4))
    except Exception:
        return 0


__all__ = ["PageText", "extract_page_words", "image_coverage", "page_has_vector_glyphs", "PDFIUM_LOCK"]
