"""
SQLAlchemy ORM model for a processed document.

Extraction results, validation results and processing metadata are stored as
JSON blobs alongside a handful of indexed/queryable columns used by the
dashboard list view. This keeps the schema stable even though the extracted
fields vary a lot between invoices, balance sheets, P&L and cash-flow
statements.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProcessedDocument(Base):
    __tablename__ = "processed_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)

    document_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    document_type: Mapped[str] = mapped_column(String, index=True, nullable=False)

    processing_status: Mapped[str] = mapped_column(String, index=True, nullable=False)  # PASS | FAILED
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    file_type: Mapped[str] = mapped_column(String, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    file_validation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    extracted_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    processing_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
