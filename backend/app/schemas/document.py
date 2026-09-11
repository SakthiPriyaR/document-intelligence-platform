"""
Pydantic schemas defining the exact response contracts.

`extracted_data` is intentionally a free-form dict of
{field_name: {"value": ..., "evidence": {...}, "confidence": optional}}
because the number/names of fields differ across invoices, balance sheets,
P&L statements and cash-flow statements, and the spec requires ALL
meaningful visible fields to be returned - not a fixed subset.
"""
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    invoice = "invoice"
    balance_sheet = "balance_sheet"
    profit_and_loss = "profit_and_loss"
    cash_flow_statement = "cash_flow_statement"


class ProcessingStatus(str, Enum):
    PASS_ = "PASS"
    FAILED = "FAILED"


class FileValidationResult(BaseModel):
    file_type: str
    is_supported: bool
    is_readable: bool
    page_count: int | None = None
    status: Literal["PASS", "FAILED"]
    reason: str | None = None


class Evidence(BaseModel):
    source_text: str | None = None
    page_number: int | None = None


class ExtractedField(BaseModel):
    value: Any = None
    confidence: float | None = None
    evidence: Evidence | None = None


class ValidationCheck(BaseModel):
    name: str
    formula: str
    period: str | None = None
    operands: dict[str, Any] = Field(default_factory=dict)
    calculated_value: float | None = None
    reported_value: float | None = None
    variance: float | None = None
    status: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    message: str | None = None


class ValidationResult(BaseModel):
    checks: list[ValidationCheck] = Field(default_factory=list)
    overall_status: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    issues: list[str] = Field(default_factory=list)


class ProcessingMetadata(BaseModel):
    ocr_used: bool
    llm_provider: str | None = None
    llm_model: str | None = None
    processed_at: datetime
    processing_time_ms: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class DocumentProcessResponse(BaseModel):
    document_id: str
    document_name: str
    document_type: str
    processing_status: Literal["PROCESSING", "PASS", "FAILED"]
    overall_confidence: float | None = None
    file_validation: FileValidationResult
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResult | None = None
    processing_metadata: ProcessingMetadata
    error: ErrorDetail | None = None


class DocumentListItem(BaseModel):
    document_id: str
    document_name: str
    document_type: str
    processing_status: Literal["PROCESSING", "PASS", "FAILED"]
    overall_confidence: float | None = None
    processed_at: datetime


class DocumentListResponse(BaseModel):
    total: int
    documents: list[DocumentListItem]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    service: str
    version: str = "1.0.0"
    environment: str
    timestamp: datetime
    checks: dict[str, str]
    documentation_url: str = "/docs"
    status_page_url: str = "/status"
