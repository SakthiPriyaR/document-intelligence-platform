"""
Orchestrates the full processing pipeline for a single uploaded document:

  validate -> OCR/text extraction -> AI field extraction -> financial
  validation -> persist -> build API response.

Every stage is wrapped so that a failure produces a controlled FAILED
result (stored and returned) instead of an unhandled 500, except for
programming errors which still bubble up to the global exception handler.
"""
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.models.document import ProcessedDocument
from app.repositories import document_repository
from app.schemas.document import (
    DocumentProcessResponse,
    ErrorDetail,
    FileValidationResult,
    ProcessingMetadata,
    ValidationResult,
)
from app.services import extraction_service, financial_validation_service, ocr_service
from app.services.document_validation_service import validate_uploaded_file

logger = get_logger(__name__)


def _compute_overall_confidence(extracted_data: dict) -> float | None:
    scores = [
        field.get("confidence")
        for field in extracted_data.values()
        if isinstance(field, dict) and isinstance(field.get("confidence"), (int, float))
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def process_document(db: Session, document_name: str, document_type: str, raw: bytes) -> DocumentProcessResponse:
    settings = get_settings()
    start = time.monotonic()
    logger.info("Processing document name=%s type=%s", document_name, document_type)

    file_validation: FileValidationResult | None = None
    try:
        file_validation = validate_uploaded_file(document_name, raw)

        ocr_result = ocr_service.extract_text(file_validation.file_type, raw)
        extracted_data = extraction_service.run_extraction(document_type, ocr_result)
        validation_result: ValidationResult = financial_validation_service.run_financial_validation(
            document_type, extracted_data
        )

        overall_confidence = _compute_overall_confidence(extracted_data)
        processing_status = "PASS" if validation_result.overall_status != "FAIL" else "FAILED"

        metadata = ProcessingMetadata(
            ocr_used=ocr_result.ocr_used,
            llm_provider=settings.LLM_PROVIDER,
            llm_model=settings.active_llm_model,
            processed_at=datetime.now(timezone.utc),
            processing_time_ms=int((time.monotonic() - start) * 1000),
        )

        record = ProcessedDocument(
            document_name=document_name,
            document_type=document_type,
            processing_status=processing_status,
            overall_confidence=overall_confidence,
            file_type=file_validation.file_type,
            page_count=file_validation.page_count,
            file_validation=file_validation.model_dump(),
            extracted_data=extracted_data,
            validation=validation_result.model_dump(),
            processing_metadata=metadata.model_dump(mode="json"),
            error=None,
        )
        document_repository.create(db, record)

        return DocumentProcessResponse(
            document_id=record.id,
            document_name=document_name,
            document_type=document_type,
            processing_status=processing_status,
            overall_confidence=overall_confidence,
            file_validation=file_validation,
            extracted_data=extracted_data,
            validation=validation_result,
            processing_metadata=metadata,
            error=None,
        )

    except AppError as exc:
        logger.warning("Controlled failure while processing document=%s: %s", document_name, exc.message)
        metadata = ProcessingMetadata(
            ocr_used=False,
            llm_provider=None,
            llm_model=None,
            processed_at=datetime.now(timezone.utc),
            processing_time_ms=int((time.monotonic() - start) * 1000),
        )
        fv = file_validation or FileValidationResult(
            file_type="unknown", is_supported=False, is_readable=False, page_count=None,
            status="FAILED", reason=exc.message,
        )
        record = ProcessedDocument(
            document_name=document_name,
            document_type=document_type,
            processing_status="FAILED",
            overall_confidence=None,
            file_type=fv.file_type,
            page_count=fv.page_count,
            file_validation=fv.model_dump(),
            extracted_data={},
            validation={},
            processing_metadata=metadata.model_dump(mode="json"),
            error={"code": exc.code, "message": exc.message},
        )
        document_repository.create(db, record)

        return DocumentProcessResponse(
            document_id=record.id,
            document_name=document_name,
            document_type=document_type,
            processing_status="FAILED",
            overall_confidence=None,
            file_validation=fv,
            extracted_data={},
            validation=None,
            processing_metadata=metadata,
            error=ErrorDetail(code=exc.code, message=exc.message),
        )
