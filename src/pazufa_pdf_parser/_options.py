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
        _require_whole("max_parallel", self.max_parallel, 1)  # a fractional slot count never blocks
        _require_whole("dpi", self.dpi, 1)
        # 0 would fail every page, after rendering it
        if type(self.timeout) not in (int, float) or not self.timeout > 0:
            raise ValueError(f"timeout must be above 0 seconds, got {self.timeout!r}")
        self._slots  # create now: threads creating it lazily at the same time would each get their own limit

    @cached_property
    def _slots(self) -> _Slots:  # not a dataclass field, so asdict() and repr() leave it out
        return _Slots(self.max_parallel)

    def __reduce__(self) -> tuple[Any, ...]:
        # the limit is per process: a pickled copy (e.g. sent to a ProcessPoolExecutor) gets its own slots
        return partial(type(self), **{f.name: getattr(self, f.name) for f in fields(self) if f.init}), ()

    def __copy__(self) -> Ocr:
        return self  # copies of options must keep sharing the limit

    def __deepcopy__(self, memo: dict[int, Any]) -> Ocr:
        return self


def _require_whole(name: str, value: object, minimum: int) -> None:
    """A bool is no number of pages."""
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be a whole number of at least {minimum}, got {value!r}")


DEFAULT_OCR = Ocr()


@dataclass(frozen=True, slots=True, kw_only=True)
class ParseOptions:
    ocr: OcrMode = OcrMode.AUTO
    #: shared Tesseract settings and parallelism limit
    ocr_engine: Ocr = DEFAULT_OCR
    #: raise StepError when a step fails or an issue of severity ERROR comes up, instead of recording it
    strict: bool = False
    #: left out of repr(), so logged options don't leak it, and of ==, as it changes no output
    password: str | None = field(default=None, repr=False, compare=False)
    #: on a page whose garbled text layer OCR did not replace, text in the garbled fonts becomes noise
    #: (only in ``raw`` output) instead of body or furniture
    drop_garbled_text: bool = True
    #: limit pages (1-based, inclusive); None = all
    first_page: int | None = None
    last_page: int | None = None
    #: a PDF with more pages to OCR than this is not OCR'd at all, as OCR time grows with pages
    #: (0.76 s each single-threaded on BW 17/1104); None = no limit
    max_ocr_pages: int | None = None

    def __post_init__(self) -> None:
        # a negative limit would silently turn OCR off for every scan, page 0 read as "all pages"; None: no limit
        for name, minimum in (("max_ocr_pages", 0), ("first_page", 1), ("last_page", 1)):
            if (value := getattr(self, name)) is not None:
                _require_whole(name, value, minimum)
        if self.first_page and self.last_page and self.first_page > self.last_page:
            raise ValueError(f"first_page {self.first_page} is after last_page {self.last_page}")
        # ParseOptions(ocr="never") would otherwise be silently treated as "auto" by the identity checks
        object.__setattr__(self, "ocr", OcrMode(self.ocr))
