"""Exception hierarchy."""

from typing import Any


class PazufaError(Exception):
    """Base class for all errors raised by pazufa_pdf_parser."""


class PdfOpenError(PazufaError):
    """The input could not be opened as a PDF (corrupt, wrong password, not a PDF)."""


class OcrUnavailableError(PazufaError):
    """OCR was required but no working tesseract installation was found."""


class StepError(PazufaError):
    """A pipeline step failed (only raised in strict mode)."""

    def __init__(self, step: str, cause: BaseException):
        super().__init__(f"step {step!r} failed: {cause!r}")
        self.step = step
        self.cause = cause

    def __reduce__(self) -> tuple[Any, ...]:
        # pickle rebuilds an exception from its message alone; a process pool must get step and cause back
        return StepError, (self.step, self.cause)


class SchemaVersionError(PazufaError):
    """The JSON was written with a newer schema than this parser reads; parse the PDF again."""


class UnknownFormatError(PazufaError, ValueError):
    """Requested output format is not registered."""
