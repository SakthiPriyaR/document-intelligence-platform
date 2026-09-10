"""
Text extraction / OCR service.

Strategy:
  1. Native PDFs: try direct text-layer extraction (pdfplumber). Cheap, fast
     and far more accurate than OCR when a real text layer exists.
  2. Scanned PDFs / images, or PDF pages whose extracted text is suspiciously
     short (i.e. effectively an image with no usable text layer): rasterise
     the page with PyMuPDF and run Tesseract OCR over it.

The result is a list of per-page plain-text blocks (1-indexed page numbers)
plus a flag telling the caller whether OCR was actually used - this is
surfaced in `processing_metadata.ocr_used` in the API response.
"""
import io

from app.core.config import get_settings
from app.core.exceptions import OCRProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)

# A page's native text layer is considered "too sparse to trust" below this
# many non-whitespace characters, and we fall back to OCR for that page.
_MIN_NATIVE_TEXT_CHARS = 20


class PageText:
    def __init__(self, page_number: int, text: str, source: str):
        self.page_number = page_number
        self.text = text
        self.source = source  # "native" | "ocr"


class OCRResult:
    def __init__(self, pages: list[PageText], image_bytes: bytes | None = None):
        self.pages = pages
        self.image_bytes = image_bytes

    @property
    def ocr_used(self) -> bool:
        return any(p.source == "ocr" for p in self.pages)

    @property
    def full_text(self) -> str:
        return "\n\n".join(f"[PAGE {p.page_number}]\n{p.text}" for p in self.pages)


def _configure_tesseract():
    settings = get_settings()
    if settings.TESSERACT_CMD:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


def _ocr_image_bytes(raw: bytes) -> str:
    from PIL import Image, ImageOps
    import pytesseract

    _configure_tesseract()
    with Image.open(io.BytesIO(raw)) as img:
        # Camera invoices often rely on EXIF orientation. Apply it before OCR;
        # browsers do this automatically, Tesseract does not.
        img = ImageOps.exif_transpose(img)
        original_size = img.size
        img = img.convert("RGB")
        settings = get_settings()
        longest_side = max(img.size)
        if longest_side > settings.OCR_MAX_IMAGE_DIM:
            scale = settings.OCR_MAX_IMAGE_DIM / longest_side
            resized = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            img = img.resize(resized, Image.Resampling.LANCZOS)
            logger.info("Resized image for OCR from %sx%s to %sx%s", *original_size, *resized)
        return pytesseract.image_to_string(
            img, config="--psm 6", timeout=settings.OCR_TIMEOUT_SECONDS,
        )


def _prepare_image_for_vision(raw: bytes) -> bytes:
    """Normalize camera orientation and shrink the image before API transfer."""
    from PIL import Image, ImageOps

    settings = get_settings()
    with Image.open(io.BytesIO(raw)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        longest_side = max(image.size)
        if longest_side > settings.OCR_MAX_IMAGE_DIM:
            scale = settings.OCR_MAX_IMAGE_DIM / longest_side
            resized = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
            image = image.resize(resized, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
        prepared = output.getvalue()
    logger.info("Prepared image for vision: %d -> %d bytes", len(raw), len(prepared))
    return prepared


def _extract_native_pdf_text(raw: bytes) -> list[str]:
    import pdfplumber

    texts: list[str] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
    return texts


def _ocr_pdf_page(raw: bytes, page_index: int, dpi: int) -> str:
    import fitz  # PyMuPDF
    import pytesseract
    from PIL import Image

    _configure_tesseract()
    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        page = doc.load_page(page_index)
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(
            img, config="--psm 6", timeout=get_settings().OCR_TIMEOUT_SECONDS,
        )
    finally:
        doc.close()


def extract_text(content_type: str, raw: bytes) -> OCRResult:
    settings = get_settings()
    logger.info("Starting text extraction content_type=%s", content_type)

    try:
        if content_type in ("image/jpeg", "image/jpg", "image/png"):
            # Preserve the original image for Gemini vision. This bypasses
            # local Tesseract for camera photographs, which is substantially
            # faster and handles rotated/complex invoice layouts better.
            return OCRResult([PageText(1, "", "vision")], image_bytes=_prepare_image_for_vision(raw))

        if content_type == "application/pdf":
            native_texts = _extract_native_pdf_text(raw)
            pages: list[PageText] = []
            for idx, native_text in enumerate(native_texts):
                page_number = idx + 1
                if native_text and len(native_text.strip()) >= _MIN_NATIVE_TEXT_CHARS:
                    pages.append(PageText(page_number, native_text, "native"))
                else:
                    ocr_text = _ocr_pdf_page(raw, idx, settings.OCR_DPI)
                    pages.append(PageText(page_number, ocr_text, "ocr"))
            return OCRResult(pages)

        raise OCRProcessingError(f"Unsupported content type for text extraction: {content_type}")

    except OCRProcessingError:
        raise
    except Exception as exc:
        logger.exception("Text extraction failed: %s", exc)
        raise OCRProcessingError("Failed to extract text from the document (OCR/parsing error).") from exc
