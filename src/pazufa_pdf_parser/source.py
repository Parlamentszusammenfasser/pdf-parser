"""Opening PDF inputs (path, bytes or binary file object)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

import pypdfium2 as pdfium

from .errors import PdfOpenError

Source = str | os.PathLike[str] | bytes | bytearray | memoryview | IO[bytes]

# pdfium is not thread safe; every call into it must hold this lock.
PDFIUM_LOCK = threading.RLock()

_INFO_KEYS = ("Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate", "ModDate")


@dataclass
class OpenedPdf:
    pdf: pdfium.PdfDocument
    data: bytes
    name: str | None
    sha256: str
    info: dict[str, Any] = field(default_factory=dict)

    def close(self) -> None:
        with PDFIUM_LOCK:
            with contextlib.suppress(Exception):  # pragma: no cover - best effort
                self.pdf.close()

    def __enter__(self) -> OpenedPdf:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_source(src: Source) -> tuple[bytes, str | None]:
    if isinstance(src, (bytes, bytearray, memoryview)):
        return bytes(src), None
    if isinstance(src, (str, os.PathLike)):
        p = Path(src)
        try:
            return p.read_bytes(), str(p)
        except OSError as e:
            raise PdfOpenError(f"cannot read {p}: {e.strerror or e}") from e
    if hasattr(src, "read"):
        data = src.read()
        if not isinstance(data, (bytes, bytearray)):
            raise PdfOpenError("file object must be opened in binary mode")
        return bytes(data), getattr(src, "name", None) if isinstance(getattr(src, "name", None), str) else None
    raise TypeError(f"unsupported source type: {type(src).__name__}")


def open_pdf(src: Source, password: str | None = None) -> OpenedPdf:
    data, name = read_source(src)
    if not data:
        raise PdfOpenError(f"{name or 'input'} is empty")
    # tolerate leading garbage before the header (mail gateways, broken uploads)
    head = data.find(b"%PDF-", 0, 1024)
    if head < 0:
        raise PdfOpenError(f"{name or 'input'} is not a PDF (no %PDF- header)")
    if head > 0:
        data = data[head:]
    sha = hashlib.sha256(data).hexdigest()
    with PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(data, password=password)
        except pdfium.PdfiumError as e:
            msg = str(e)
            if "password" in msg.lower():
                raise PdfOpenError(f"{name or 'input'} is encrypted; a (correct) password is required") from e
            raise PdfOpenError(f"{name or 'input'} could not be parsed: {msg}") from e
        info: dict[str, Any] = {}
        # broken metadata or version info must not reject an otherwise readable PDF
        with contextlib.suppress(Exception):
            meta = pdf.get_metadata_dict(skip_empty=True)
            info = {k: v for k, v in meta.items() if k in _INFO_KEYS}
        with contextlib.suppress(Exception):
            info["page_count"] = len(pdf)
            info["pdf_version"] = pdf.get_version()
        if info.get("page_count", 0) == 0:
            pdf.close()
            raise PdfOpenError(f"{name or 'input'} has no pages")
    return OpenedPdf(pdf=pdf, data=data, name=name, sha256=sha, info=info)
