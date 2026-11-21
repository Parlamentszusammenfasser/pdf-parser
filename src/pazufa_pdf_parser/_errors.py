"""Exception hierarchy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._document import Issue


class PazufaError(Exception):
    """Base class for all errors raised by pazufa_pdf_parser."""


class PdfOpenError(PazufaError):
    """The input could not be opened as a PDF (corrupt, wrong password, not a PDF)."""


class OcrUnavailableError(PazufaError):
    """OCR was required but no working tesseract installation was found."""


class StepError(PazufaError):
    """A pipeline step failed: ``extract`` or ``layout``, or with ``strict=True`` any step or any issue of
    severity ERROR; ``issue`` is that issue, so strict callers can match on ``issue.code``."""

    def __init__(self, step: str, cause: BaseException, issue: Issue | None = None):
        super().__init__(f"step {step!r} failed: {cause!r}")
        self.step = step
        self.cause = cause
        self.issue = issue

    def __reduce__(self) -> tuple[Any, ...]:
        # pickle rebuilds an exception from its message alone; a process pool must get step and cause back
        return StepError, (self.step, self.cause, self.issue)


class SchemaVersionError(PazufaError):
    """The JSON was written with a schema this parser cannot read; parse the PDF again."""


class UnknownFormatError(PazufaError, ValueError):
    """Requested output format is not registered."""
