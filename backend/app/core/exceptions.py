"""
Application-specific exceptions and a single FastAPI exception handler that
converts them (and any unhandled exception) into a consistent, safe JSON
error response - never leaking stack traces or secrets to the client.
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for all controlled application errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APPLICATION_ERROR"

    def __init__(self, message: str, code: str | None = None, status_code: int | None = None):
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        super().__init__(message)


class UnsupportedFileTypeError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "UNSUPPORTED_FILE_TYPE"


class EmptyFileError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "EMPTY_FILE"


class CorruptedFileError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "CORRUPTED_FILE"


class PageLimitExceededError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "PAGE_LIMIT_EXCEEDED"


class DocumentNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "DOCUMENT_NOT_FOUND"


class OCRProcessingError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "OCR_PROCESSING_FAILED"


class ExtractionError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "EXTRACTION_FAILED"


class DatabaseError(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "DATABASE_ERROR"


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("Handled AppError code=%s path=%s message=%s", exc.code, request.url.path, exc.message)
    return _error_response(exc.code, exc.message, exc.status_code)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never expose the raw exception / stack trace to the client.
    logger.exception("Unhandled exception on path=%s: %s", request.url.path, exc)
    return _error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred while processing the request.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
