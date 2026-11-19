"""User-tunable options for parsing."""

from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass, field, fields
from enum import StrEnum
from functools import cached_property, partial
from typing import Any


class OcrMode(StrEnum):
    AUTO = "auto"  # OCR pages without a usable text layer
    ALWAYS = "always"  # OCR every page, ignore the text layer
    NEVER = "never"  # never OCR


class _Slots:
    """First come, first served. threading.Semaphore lets the thread that just released a slot take
    it again ahead of the waiting ones, so one long scan kept every other parse waiting until it was done."""

    def __init__(self, n: int) -> None:
        self._free = n
        self._lock = threading.Lock()
        self._waiting: deque[threading.Lock] = deque()

    def __enter__(self) -> None:
        with self._lock:
            if self._free and not self._waiting:
                self._free -= 1
                return
            turn = threading.Lock()
            turn.acquire()
            self._waiting.append(turn)
        turn.acquire()  # __exit__ of another thread hands its slot over by releasing this

    def __exit__(self, *exc: object) -> None:
        with self._lock:
            if self._waiting:
                self._waiting.popleft().release()
            else:
                self._free += 1


@dataclass(frozen=True, eq=False, kw_only=True)
class Ocr:
    """Tesseract settings; create one per process and share it between parse() calls.

    ``max_parallel`` caps the Tesseract processes of all parse() calls using this
    object, also across threads; pages wait their turn in order. A PDF without
    pages to OCR never waits.
    """

    #: tesseract languages, also "deu+eng"; mixing deu+eng measurably degrades German umlaut recognition
    languages: tuple[str, ...] = ("deu",)
    dpi: int = 300
    max_parallel: int = field(default_factory=lambda: min(4, os.cpu_count() or 1))
    #: seconds for each tesseract run (a page needs up to three: OCR, orientation check, rotated OCR)
    timeout: float = 180.0
    tesseract_cmd: str = "tesseract"
    #: run tesseract orientation detection on scanned pages
    detect_orientation: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.languages, str):
            object.__setattr__(self, "languages", tuple(x for x in self.languages.replace(",", "+").split("+") if x))
        # a float would make the slot count fractional, which never blocks
        if not isinstance(self.max_parallel, int) or self.max_parallel < 1:
            raise ValueError(f"max_parallel must be a whole number of at least 1, got {self.max_parallel!r}")
        self._slots  # create now: threads creating it lazily at the same time would each get their own limit

    @cached_property
    def _slots(self) -> _Slots:  # not a dataclass field, so asdict() and repr() leave it out
        return _Slots(self.max_parallel)

    def __reduce__(self) -> tuple[Any, ...]:
        # the limit is per process: a pickled copy (e.g. sent to a ProcessPoolExecutor) gets its own slots
        return partial(Ocr, **{f.name: getattr(self, f.name) for f in fields(self)}), ()

    def __deepcopy__(self, memo: dict[int, Any]) -> Ocr:
        return self  # copies of options must keep sharing the limit


DEFAULT_OCR = Ocr()


@dataclass(frozen=True, slots=True, kw_only=True)
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
    #: a PDF with more pages to OCR than this is not OCR'd at all, as OCR time grows with pages
    #: (0.76 s each single-threaded on BW 17/1104); None = no limit
    max_ocr_pages: int | None = None

    def __post_init__(self) -> None:
        # a negative limit would silently turn OCR off for every scan
        if self.max_ocr_pages is not None and (type(self.max_ocr_pages) is not int or self.max_ocr_pages < 0):
            raise ValueError(f"max_ocr_pages must be a whole number of at least 0, got {self.max_ocr_pages!r}")
        # ParseOptions(ocr="never") would otherwise be silently treated as "auto" by the identity checks
        object.__setattr__(self, "ocr", OcrMode(self.ocr))
