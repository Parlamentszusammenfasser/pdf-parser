"""The public API: exactly the names in __all__, typed for strict consumers."""

import subprocess
import sys
from pathlib import Path

import pytest

import pazufa_pdf_parser


def test_all_is_the_public_api():
    assert sorted(pazufa_pdf_parser.__all__) == sorted(
        [
            "parse",
            "ParseOptions",
            "OcrMode",
            "Ocr",
            "PdfDocument",
            "Page",
            "Block",
            "BlockKind",
            "PageSource",
            "Metadata",
            "Report",
            "PageReport",
            "Issue",
            "Severity",
            "render",
            "PazufaError",
            "PdfOpenError",
            "OcrUnavailableError",
            "StepError",
            "UnknownFormatError",
        ]
    )


def test_strict_consumer_type_checks():
    pytest.importorskip("mypy")
    # without py.typed mypy sees the package as untyped and this fails
    consumer = Path(__file__).with_name("public_api_consumer.py")
    cmd = [sys.executable, "-m", "mypy", "--strict", "--config-file", "", str(consumer)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
