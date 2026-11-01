"""Structured field extractors, dispatched by document type."""

from .common import extract_entities, find_dates
from .court import extract_contract_fields, extract_court_fields
from .email import extract_email_fields
from .legal import extract_legal_structure, parse_legal_texts, synopsis_columns
from .letter import extract_letter_fields
from .parliament import extract_print_fields, extract_protocol

__all__ = [
    "extract_entities",
    "find_dates",
    "extract_contract_fields",
    "extract_court_fields",
    "extract_email_fields",
    "extract_legal_structure",
    "parse_legal_texts",
    "synopsis_columns",
    "extract_letter_fields",
    "extract_print_fields",
    "extract_protocol",
]
