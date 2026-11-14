"""OCR backend: render with pdfium, recognise with the tesseract CLI (TSV output)."""

from __future__ import annotations

import csv
import functools
import io
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageOps

from ..errors import OcrUnavailableError
from ..model import BBox, TextSource, Word


@dataclass(slots=True)
class OcrResult:
    words: list[Word]
    width: float  # page size in points after orientation correction
    height: float
    rotation: int = 0  # clockwise degrees applied to make the page upright
    mean_confidence: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)


@functools.lru_cache(maxsize=8)
def tesseract_languages(cmd: str = "tesseract") -> frozenset[str]:
    """Installed tesseract languages; raises OcrUnavailableError if tesseract is missing."""
    exe = shutil.which(cmd)
    if not exe:
        raise OcrUnavailableError(f"tesseract executable {cmd!r} not found on PATH")
    try:
        r = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OcrUnavailableError(f"tesseract not usable: {e}") from e
    out = (r.stdout + r.stderr).decode("utf-8", "replace").splitlines()
    return frozenset(line.strip() for line in out[1:] if line.strip() and " " not in line.strip())


def tesseract_available(cmd: str = "tesseract") -> bool:
    try:
        return bool(tesseract_languages(cmd))
    except OcrUnavailableError:
        return False


def resolve_languages(requested: tuple[str, ...], cmd: str = "tesseract") -> tuple[str, list[str]]:
    """Return a tesseract ``-l`` argument and the list of requested-but-missing languages."""
    have = tesseract_languages(cmd)
    use = [lang for lang in requested if lang in have]
    missing = [lang for lang in requested if lang not in have]
    if not use:
        use = ["eng"] if "eng" in have else sorted(have - {"osd"})[:1]
    if not use:
        raise OcrUnavailableError("no tesseract language data installed")
    return "+".join(use), missing


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def detect_rotation(img: Image.Image, dpi: int, cmd: str = "tesseract", timeout: float = 60) -> tuple[int, float]:
    """Clockwise rotation needed to make the image upright, and its confidence."""
    try:
        r = subprocess.run(
            [cmd, "stdin", "stdout", "--psm", "0", "--dpi", str(dpi)],
            input=_png(img),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0, 0.0
    text = r.stdout.decode("utf-8", "replace")
    m_rot = re.search(r"Rotate:\s*(\d+)", text)
    m_conf = re.search(r"Orientation confidence:\s*([\d.]+)", text)
    if not m_rot:
        return 0, 0.0
    return int(m_rot.group(1)) % 360, float(m_conf.group(1)) if m_conf else 0.0


def run_tesseract_tsv(
    img: Image.Image, lang: str, dpi: int, cmd: str = "tesseract", psm: int = 3, timeout: float = 180
) -> str:
    try:
        r = subprocess.run(
            [
                cmd,
                "stdin",
                "stdout",
                "-l",
                lang,
                "--psm",
                str(psm),
                "--dpi",
                str(dpi),
                "-c",
                "preserve_interword_spaces=0",
                "tsv",
            ],
            input=_png(img),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise OcrUnavailableError(f"tesseract executable {cmd!r} not found") from e
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(f"tesseract timed out after {timeout}s") from e
    if r.returncode != 0:
        raise RuntimeError(f"tesseract failed ({r.returncode}): {r.stderr.decode('utf-8', 'replace')[-300:]}")
    return r.stdout.decode("utf-8", "replace")


def parse_tsv(tsv: str, scale: float) -> list[Word]:
    """Parse tesseract TSV into words. ``scale`` converts pixels to points."""
    reader = csv.reader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    header = next(reader, None)
    if not header or "text" not in header:
        return []
    idx = {name: i for i, name in enumerate(header)}
    rows: dict[tuple[int, int, int, int], list[tuple[str, float, int, int, int, int]]] = {}
    for row in reader:
        if len(row) < len(header):
            continue
        try:
            if int(row[idx["level"]]) != 5:
                continue
            conf = float(row[idx["conf"]])
            left, top = int(row[idx["left"]]), int(row[idx["top"]])
            width, height = int(row[idx["width"]]), int(row[idx["height"]])
            key = (
                int(row[idx["page_num"]]),
                int(row[idx["block_num"]]),
                int(row[idx["par_num"]]),
                int(row[idx["line_num"]]),
            )
        except ValueError:
            continue
        text = row[idx["text"]].strip()
        if not text or conf < 0:
            continue
        rows.setdefault(key, []).append((text, conf, left, top, width, height))
    words: list[Word] = []
    for items in rows.values():
        heights = sorted(it[5] for it in items if len(it[0]) > 1) or sorted(it[5] for it in items)
        # words with ascender+descender span ~0.95em; the 80th percentile word height is a
        # stable estimate because most lines contain such a word
        size = heights[min(len(heights) - 1, int(len(heights) * 0.8))] / 0.95 * scale
        for text, conf, left, top, width, height in items:
            words.append(
                Word(
                    text=text,
                    bbox=BBox(left * scale, top * scale, (left + width) * scale, (top + height) * scale),
                    size=round(size, 2),
                    source=TextSource.OCR,
                    confidence=conf,
                )
            )
    return words


def preprocess(img: Image.Image) -> Image.Image:
    g = img.convert("L")
    # stretch contrast for faint scans; cheap and safe
    return ImageOps.autocontrast(g, cutoff=1)


def ocr_image(
    img: Image.Image,
    dpi: int,
    lang: str,
    *,
    detect_orientation: bool = True,
    cmd: str = "tesseract",
    timeout: float = 180,
) -> OcrResult:
    """OCR a rendered page image. Orientation is only probed when the first pass looks bad."""
    img = preprocess(img)
    scale = 72.0 / dpi

    def attempt(im: Image.Image, rotation: int) -> OcrResult:
        words = parse_tsv(run_tesseract_tsv(im, lang, dpi, cmd, timeout=timeout), scale)
        confs = [w.confidence for w in words if w.confidence is not None]
        mean = sum(confs) / len(confs) if confs else 0.0
        return OcrResult(words, im.width * scale, im.height * scale, rotation, mean, {"ocr_words": len(words)})

    res = attempt(img, 0)
    if detect_orientation and (res.mean_confidence < 60 or len(res.words) < 15):
        rot, conf = detect_rotation(img, dpi, cmd)
        res.stats["osd_rotation"], res.stats["osd_confidence"] = rot, conf
        if rot and conf >= 1.5:
            alt = attempt(img.rotate(-rot, expand=True), rot)
            if alt.mean_confidence * max(len(alt.words), 1) > res.mean_confidence * max(len(res.words), 1):
                alt.stats.update(res.stats)
                res = alt
    res.stats["ocr_mean_confidence"] = round(res.mean_confidence, 2)
    return res
