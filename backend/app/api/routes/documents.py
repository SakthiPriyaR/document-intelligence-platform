"""
REST API routes for document processing, retrieval and dashboard listing.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories import document_repository
from app.schemas.document import (
    DocumentListItem,
    DocumentListResponse,
    DocumentProcessResponse,
    DocumentType,
    ErrorDetail,
    FileValidationResult,
    HealthResponse,
    ProcessingMetadata,
    ValidationResult,
)
from app.services.document_service import process_document_in_background, queue_document

logger = get_logger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Return a concise readiness response without exposing provider configuration."""
    settings = get_settings()
    database_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - depends on deployment infrastructure
        logger.exception("Health check database probe failed")
        database_status = "unavailable"

    processing_ready = bool(
        settings.GEMINI_API_KEY if settings.LLM_PROVIDER == "gemini" else settings.ANTHROPIC_API_KEY
    )
    status = "ok" if database_status == "connected" and processing_ready else "degraded"
    return HealthResponse(
        status=status,
        service="document-intelligence-platform",
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        checks={
            "api": "operational",
            "database": database_status,
            "document_processing": "ready" if processing_ready else "configuration_required",
        },
    )


@router.post("/documents/process", response_model=DocumentProcessResponse, tags=["documents"])
async def process_document_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    db: Session = Depends(get_db),
) -> DocumentProcessResponse:
    raw = await file.read()
    logger.info("Received upload filename=%s document_type=%s", file.filename, document_type.value)
    response = queue_document(
        db, document_name=file.filename or "unnamed_document",
        document_type=document_type.value, raw=raw,
    )
    if response.processing_status == "PROCESSING":
        background_tasks.add_task(
            process_document_in_background, response.document_id,
            response.document_name, response.document_type, raw,
        )
    return response


@router.get("/documents/{document_name}", response_model=DocumentProcessResponse, tags=["documents"])
def get_document_by_name(document_name: str, db: Session = Depends(get_db)) -> DocumentProcessResponse:
    record = document_repository.get_latest_by_name(db, document_name)
    return DocumentProcessResponse(
        document_id=record.id,
        document_name=record.document_name,
        document_type=record.document_type,
        processing_status=record.processing_status,
        overall_confidence=record.overall_confidence,
        file_validation=FileValidationResult(**record.file_validation),
        extracted_data=record.extracted_data,
        validation=ValidationResult(**record.validation) if record.validation else None,
        processing_metadata=ProcessingMetadata(**record.processing_metadata),
        error=ErrorDetail(**record.error) if record.error else None,
    )


@router.get("/documents", response_model=DocumentListResponse, tags=["documents"])
def list_documents(db: Session = Depends(get_db)) -> DocumentListResponse:
    records = document_repository.list_all(db)
    items = [
        DocumentListItem(
            document_id=r.id,
            document_name=r.document_name,
            document_type=r.document_type,
            processing_status=r.processing_status,
            overall_confidence=r.overall_confidence,
            processed_at=r.processing_metadata.get("processed_at") or r.created_at,
        )
        for r in records
    ]
    return DocumentListResponse(total=len(items), documents=items)
