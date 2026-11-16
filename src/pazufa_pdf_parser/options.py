"""User-tunable options for parsing."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field, replace
from enum import StrEnum


class OcrMode(StrEnum):
    AUTO = "auto"  # OCR pages without a usable text layer
    ALWAYS = "always"  # OCR every page, ignore the text layer
    NEVER = "never"  # never OCR


@dataclass(frozen=True, slots=True, eq=False)
class Ocr:
    """Tesseract settings; create one per process and share it between parse() calls.

    ``max_parallel`` caps the Tesseract processes of all parse() calls using this
    object, also across threads. Pages with a usable text layer never wait.
    """

    #: tesseract languages; mixing deu+eng measurably degrades German umlaut recognition
    languages: tuple[str, ...] = ("deu",)
    dpi: int = 300
    max_parallel: int = field(default_factory=lambda: min(4, os.cpu_count() or 1))
    #: per-page timeout in seconds
    timeout: float = 180.0
    tesseract_cmd: str = "tesseract"
    #: run tesseract orientation detection on scanned pages
    detect_orientation: bool = True
    _slots: threading.BoundedSemaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_parallel < 1:
            raise ValueError(f"max_parallel must be at least 1, got {self.max_parallel}")
        object.__setattr__(self, "_slots", threading.BoundedSemaphore(self.max_parallel))


DEFAULT_OCR = Ocr()


@dataclass(frozen=True, slots=True)
class ParseOptions:
    ocr: OcrMode = OcrMode.AUTO
    #: shared Tesseract settings and parallelism limit
    ocr_engine: Ocr = DEFAULT_OCR
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

    def with_(self, **changes) -> ParseOptions:
        return replace(self, **changes)
