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
from app.core.database import SessionLocal
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


def _response_from_record(record: ProcessedDocument) -> DocumentProcessResponse:
    return DocumentProcessResponse(
        document_id=record.id, document_name=record.document_name, document_type=record.document_type,
        processing_status=record.processing_status, overall_confidence=record.overall_confidence,
        file_validation=FileValidationResult(**record.file_validation), extracted_data=record.extracted_data,
        validation=ValidationResult(**record.validation) if record.validation else None,
        processing_metadata=ProcessingMetadata(**record.processing_metadata),
        error=ErrorDetail(**record.error) if record.error else None,
    )


def process_document(db: Session, document_name: str, document_type: str, raw: bytes, record: ProcessedDocument | None = None) -> DocumentProcessResponse:
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

        record = record or ProcessedDocument(document_name=document_name, document_type=document_type)
        record.processing_status = processing_status
        record.overall_confidence = overall_confidence
        record.file_type = file_validation.file_type
        record.page_count = file_validation.page_count
        record.file_validation = file_validation.model_dump()
        record.extracted_data = extracted_data
        record.validation = validation_result.model_dump()
        record.processing_metadata = metadata.model_dump(mode="json")
        record.error = None
        (document_repository.update if record.id else document_repository.create)(db, record)
        return _response_from_record(record)

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
        record = record or ProcessedDocument(document_name=document_name, document_type=document_type)
        record.processing_status = "FAILED"
        record.overall_confidence = None
        record.file_type = fv.file_type
        record.page_count = fv.page_count
        record.file_validation = fv.model_dump()
        record.extracted_data = {}
        record.validation = {}
        record.processing_metadata = metadata.model_dump(mode="json")
        record.error = {"code": exc.code, "message": exc.message}
        (document_repository.update if record.id else document_repository.create)(db, record)
        return _response_from_record(record)


def queue_document(db: Session, document_name: str, document_type: str, raw: bytes) -> DocumentProcessResponse:
    """Validate and persist a fast PROCESSING record before starting the slow pipeline."""
    try:
        file_validation = validate_uploaded_file(document_name, raw)
    except AppError:
        return process_document(db, document_name, document_type, raw)

    settings = get_settings()
    metadata = ProcessingMetadata(
        ocr_used=False, llm_provider=settings.LLM_PROVIDER, llm_model=settings.active_llm_model,
        processed_at=datetime.now(timezone.utc), processing_time_ms=0,
    )
    record = ProcessedDocument(
        document_name=document_name, document_type=document_type, processing_status="PROCESSING",
        overall_confidence=None, file_type=file_validation.file_type, page_count=file_validation.page_count,
        file_validation=file_validation.model_dump(), extracted_data={}, validation={},
        processing_metadata=metadata.model_dump(mode="json"), error=None,
    )
    document_repository.create(db, record)
    return _response_from_record(record)


def process_document_in_background(document_id: str, document_name: str, document_type: str, raw: bytes) -> None:
    db = SessionLocal()
    try:
        record = document_repository.get_by_id(db, document_id)
        if record is not None:
            process_document(db, document_name, document_type, raw, record=record)
    except Exception:
        logger.exception("Background processing failed for document_id=%s", document_id)
    finally:
        db.close()
