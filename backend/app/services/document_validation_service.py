"""
Input-control layer: validates the uploaded file BEFORE any OCR/AI work.

This is deliberately separate from document-type classification (which is
out of scope - the document type is supplied by the caller as request
metadata).
"""
import io

from app.core.config import get_settings
from app.core.exceptions import (
    CorruptedFileError,
    EmptyFileError,
    PageLimitExceededError,
    UnsupportedFileTypeError,
)
from app.core.logging import get_logger
from app.schemas.document import FileValidationResult

logger = get_logger(__name__)

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def _sniff_content_type(raw: bytes) -> str | None:
    if raw.startswith(_PDF_MAGIC):
        return "application/pdf"
    if raw.startswith(_PNG_MAGIC):
        return "image/png"
    if raw.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    return None


def _count_pdf_pages(raw: bytes) -> int:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise CorruptedFileError("The PDF is encrypted/password-protected and cannot be read.") from exc
    return len(reader.pages)


def validate_uploaded_file(filename: str, raw: bytes) -> FileValidationResult:
    """
    Validates: file type (by content sniffing, not just extension), empty
    file, corrupted file and page-count limit. Raises a controlled AppError
    subclass on the first failure so the API can fail gracefully with a
    clear error response.
    """
    settings = get_settings()
    logger.info("Validating uploaded file name=%s size_bytes=%d", filename, len(raw) if raw else 0)

    if not raw or len(raw) == 0:
        raise EmptyFileError("The uploaded file is empty.")

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(raw) > max_bytes:
        raise UnsupportedFileTypeError(f"File exceeds the maximum allowed size of {settings.MAX_FILE_SIZE_MB}MB.")

    content_type = _sniff_content_type(raw)
    if content_type is None or content_type not in settings.allowed_content_type_list:
        raise UnsupportedFileTypeError("Only PDF / JPG / PNG documents are supported.")

    page_count = 1
    if content_type == "application/pdf":
        try:
            page_count = _count_pdf_pages(raw)
        except CorruptedFileError:
            raise
        except Exception as exc:
            raise CorruptedFileError("The PDF file could not be read; it may be corrupted.") from exc

        if page_count == 0:
            raise CorruptedFileError("The PDF contains no readable pages.")
    else:
        # Validate the image actually decodes.
        try:
            from PIL import Image

            with Image.open(io.BytesIO(raw)) as img:
                img.verify()
        except Exception as exc:
            raise CorruptedFileError("The image file could not be read; it may be corrupted.") from exc

    if page_count > settings.MAX_PAGE_COUNT:
        raise PageLimitExceededError(
            f"Document has {page_count} pages; only up to {settings.MAX_PAGE_COUNT} pages are supported."
        )

    return FileValidationResult(
        file_type=content_type,
        is_supported=True,
        is_readable=True,
        page_count=page_count,
        status="PASS",
    )
