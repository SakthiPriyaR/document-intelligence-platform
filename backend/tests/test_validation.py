"""
Tests for file validation and financial calculation validation.
These do not require any external API keys.
"""
import io

import pytest
from PIL import Image

from app.core.exceptions import CorruptedFileError, EmptyFileError, PageLimitExceededError, UnsupportedFileTypeError
from app.services.document_validation_service import validate_uploaded_file
from app.services.financial_validation_service import run_financial_validation


def _make_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color="white").save(buf, format="PNG")
    return buf.getvalue()


def _make_pdf_bytes(num_pages: int = 1) -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# --- File validation ---------------------------------------------------

def test_empty_file_rejected():
    with pytest.raises(EmptyFileError):
        validate_uploaded_file("empty.pdf", b"")


def test_unsupported_file_type_rejected():
    with pytest.raises(UnsupportedFileTypeError):
        validate_uploaded_file("notes.txt", b"just some plain text, not a real document")


def test_corrupted_pdf_rejected():
    with pytest.raises(CorruptedFileError):
        validate_uploaded_file("broken.pdf", b"%PDF-1.4\n%%not really a valid pdf body")


def test_valid_png_passes():
    result = validate_uploaded_file("scan.png", _make_png_bytes())
    assert result.status == "PASS"
    assert result.file_type == "image/png"
    assert result.page_count == 1


def test_pdf_page_limit_exceeded():
    with pytest.raises(PageLimitExceededError):
        validate_uploaded_file("big.pdf", _make_pdf_bytes(num_pages=5))


def test_pdf_within_page_limit_passes():
    result = validate_uploaded_file("ok.pdf", _make_pdf_bytes(num_pages=2))
    assert result.status == "PASS"
    assert result.page_count == 2


# --- Financial validation -----------------------------------------------

def _field(value):
    return {"value": value, "evidence": {"source_text": str(value), "page_number": 1}}


def test_invoice_total_check_pass():
    extracted = {
        "subtotal": _field(12500.00),
        "tax_amount": _field(625.00),
        "discount": _field(0.00),
        "total_amount": _field(13125.00),
    }
    result = run_financial_validation("invoice", extracted)
    check = next(c for c in result.checks if c.name == "invoice_total_check")
    assert check.status == "PASS"
    assert result.overall_status == "PASS"


def test_invoice_total_check_fail():
    extracted = {
        "subtotal": _field(12500.00),
        "tax_amount": _field(625.00),
        "discount": _field(0.00),
        "total_amount": _field(20000.00),
    }
    result = run_financial_validation("invoice", extracted)
    check = next(c for c in result.checks if c.name == "invoice_total_check")
    assert check.status == "FAIL"
    assert result.overall_status == "FAIL"


def test_invoice_missing_fields_not_applicable():
    extracted = {"total_amount": _field(13125.00)}
    result = run_financial_validation("invoice", extracted)
    check = next(c for c in result.checks if c.name == "invoice_total_check")
    assert check.status == "NOT_APPLICABLE"


def test_balance_sheet_equation_multi_period():
    extracted = {
        "total_liabilities__2025": _field(40000),
        "total_equity__2025": _field(60000),
        "total_assets__2025": _field(100000),
        "total_liabilities__2024": _field(30000),
        "total_equity__2024": _field(50000),
        "total_assets__2024": _field(80000),
    }
    result = run_financial_validation("balance_sheet", extracted)
    assert len(result.checks) == 2
    assert result.overall_status == "PASS"


def test_cash_flow_reconciliation():
    extracted = {
        "operating_cash_flow": _field(5000),
        "investing_cash_flow": _field(-2000),
        "financing_cash_flow": _field(-1000),
        "net_change_in_cash": _field(2000),
        "opening_cash": _field(1000),
        "closing_cash": _field(3000),
    }
    result = run_financial_validation("cash_flow_statement", extracted)
    assert result.overall_status == "PASS"


def test_parenthesised_negative_values_parsed():
    from app.services.financial_validation_service import _to_number
    assert _to_number("(1,250.50)") == -1250.50
    assert _to_number("USD 13,125.00") == 13125.00
    assert _to_number(None) is None
