"""
Data-access layer for processed documents. Keeps the API/service layer free
of raw SQL/ORM queries.
"""
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.exceptions import DatabaseError, DocumentNotFoundError
from app.core.logging import get_logger
from app.models.document import ProcessedDocument

logger = get_logger(__name__)


def create(db: Session, record: ProcessedDocument) -> ProcessedDocument:
    try:
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to persist processed document: %s", exc)
        raise DatabaseError("Failed to store the processed document result.") from exc


def get_latest_by_name(db: Session, document_name: str) -> ProcessedDocument:
    record = (
        db.query(ProcessedDocument)
        .filter(ProcessedDocument.document_name == document_name)
        .order_by(desc(ProcessedDocument.created_at))
        .first()
    )
    if record is None:
        raise DocumentNotFoundError(f"No processed document found with name '{document_name}'.")
    return record


def list_all(db: Session, limit: int = 200) -> list[ProcessedDocument]:
    return (
        db.query(ProcessedDocument)
        .order_by(desc(ProcessedDocument.created_at))
        .limit(limit)
        .all()
    )
