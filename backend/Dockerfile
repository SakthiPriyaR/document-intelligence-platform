FROM python:3.12-slim

# System dependencies: Tesseract (OCR) + fonts for better OCR accuracy.
# PyMuPDF (fitz) is a self-contained wheel so no poppler system package is needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY frontend /frontend

ENV PYTHONUNBUFFERED=1 \
    UPLOAD_TMP_DIR=/tmp/doc_intel_uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
