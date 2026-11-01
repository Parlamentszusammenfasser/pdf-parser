"""Tiny dependency-free PDF writer for tests (standard Helvetica fonts, WinAnsi).

Coordinates are given top-down (y = distance of the text top from the page top)
to match the parser's view space.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

A4 = (595.0, 842.0)


@dataclass
class T:
    x: float
    y: float  # top of the text line, measured from the page top
    text: str
    size: float = 11.0
    bold: bool = False
    angle: float = 0.0  # degrees, counter-clockwise
    invisible: bool = False
    tf_one: bool = False  # draw with "1 Tf" and scale through the text matrix (Outlook style)


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    out = bytearray()
    for b in raw:
        if b in (0x28, 0x29, 0x5C):
            out += b"\\" + bytes([b])
        elif b < 0x20 or b > 0x7E:
            out += f"\\{b:03o}".encode()
        else:
            out.append(b)
    return bytes(out)


def _content(items: list[T], height: float) -> bytes:
    ops = []
    for it in items:
        font = "/F2" if it.bold else "/F1"
        base_y = height - it.y - it.size * 0.8
        a = math.radians(it.angle)
        k = it.size if it.tf_one else 1.0
        tf = 1 if it.tf_one else it.size
        c, s = math.cos(a) * k, math.sin(a) * k
        mode = b"3 Tr " if it.invisible else b"0 Tr "
        ops.append(
            b"BT "
            + mode
            + f"{font} {tf:g} Tf {c:.4f} {s:.4f} {-s:.4f} {c:.4f} {it.x:.2f} {base_y:.2f} Tm (".encode()
            + _escape(it.text)
            + b") Tj ET"
        )
    return b"\n".join(ops)


def make_pdf(pages: list[list[T]], *, size: tuple[float, float] = A4, rotate: int = 0, title: str | None = None) -> bytes:
    w, h = size
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    catalog = add(b"")  # placeholder 1
    pages_id = add(b"")  # placeholder 2
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for items in pages:
        stream = _content(items, h)
        cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        rot = f" /Rotate {rotate}" if rotate else ""
        pid = add(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {w:g} {h:g}]{rot} "
                f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {cid} 0 R >>"
            ).encode()
        )
        kids.append(pid)
    objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objs[pages_id - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    info_id = None
    if title:
        info_id = add(b"<< /Title (" + _escape(title) + b") >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    trailer = f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R"
    if info_id:
        trailer += f" /Info {info_id} 0 R"
    out.write((trailer + f" >>\nstartxref\n{xref}\n%%EOF\n").encode())
    return out.getvalue()


def paragraph(x: float, y: float, lines: list[str], size: float = 11.0, leading: float = 1.35, bold: bool = False) -> list[T]:
    return [T(x, y + i * size * leading, ln, size, bold) for i, ln in enumerate(lines)]


FONT_CANDIDATES = [
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def find_font() -> str | None:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


def make_scanned_pdf(pages: list[list[T]], *, dpi: int = 300, rotate_image: int = 0, noise: bool = False) -> bytes:
    """Render text into images and wrap them in a PDF without text layer (a fake scan)."""
    from PIL import Image, ImageDraw, ImageFont

    font_path = find_font()
    if font_path is None:
        raise RuntimeError("no TTF font available for fake scans")
    scale = dpi / 72.0
    images = []
    for items in pages:
        img = Image.new("L", (int(A4[0] * scale), int(A4[1] * scale)), 255)
        draw = ImageDraw.Draw(img)
        for it in items:
            font = ImageFont.truetype(font_path, int(it.size * scale))
            draw.text((it.x * scale, it.y * scale), it.text, fill=0, font=font)
        if noise:
            import random

            rnd = random.Random(1)
            for _ in range(400):
                x, y = rnd.randrange(img.width), rnd.randrange(img.height)
                draw.point((x, y), fill=0)
        if rotate_image:
            img = img.rotate(rotate_image, expand=True, fillcolor=255)
        images.append(img.convert("RGB"))
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:], resolution=dpi)
    return buf.getvalue()
