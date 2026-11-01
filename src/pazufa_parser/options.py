"""User-tunable options for parsing."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from enum import StrEnum


class OcrMode(StrEnum):
    AUTO = "auto"  # OCR pages without a usable text layer
    ALWAYS = "always"  # OCR every page, ignore the text layer
    NEVER = "never"  # never OCR


@dataclass(frozen=True, slots=True)
class ParseOptions:
    ocr: OcrMode = OcrMode.AUTO
    #: tesseract languages; mixing deu+eng measurably degrades German umlaut recognition
    languages: tuple[str, ...] = ("deu",)
    dpi: int = 300
    #: run tesseract orientation detection on scanned pages
    detect_orientation: bool = True
    #: worker threads for OCR (tesseract runs as a subprocess)
    jobs: int = field(default_factory=lambda: max(1, min(4, os.cpu_count() or 1)))
    #: re-raise exceptions from pipeline steps instead of recording issues
    strict: bool = False
    password: str | None = None
    #: a page with fewer meaningful characters than this is considered text-less
    min_text_chars: int = 25
    #: share of garbage characters above which a text layer is considered broken
    max_garbage_ratio: float = 0.15
    #: OCR words below this confidence are dropped from sanitized outputs
    min_word_confidence: float = 25.0
    #: limit pages (1-based, inclusive); None = all
    first_page: int | None = None
    last_page: int | None = None
    tesseract_cmd: str = "tesseract"
    #: per-page OCR timeout in seconds
    ocr_timeout: float = 180.0

    def with_(self, **changes) -> ParseOptions:
        return replace(self, **changes)
