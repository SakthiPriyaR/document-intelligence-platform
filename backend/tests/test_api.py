"""
Basic API-flow tests using FastAPI's TestClient against an isolated,
temporary SQLite database. The extraction/OCR pipeline is monkeypatched so
this test suite runs without network access or an ANTHROPIC_API_KEY.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test_api.db")
    from app.core.config import get_settings
    get_settings.cache_clear()

    from app.main import app
    from app.core.database import init_db
    init_db()

    from app.services import ocr_service, extraction_service

    class DummyOCRResult:
        ocr_used = True
        full_text = "[PAGE 1]\nInvoice Total Amount Due: USD 100.00"

    monkeypatch.setattr(ocr_service, "extract_text", lambda *a, **kw: DummyOCRResult())
    monkeypatch.setattr(
        extraction_service,
        "run_extraction",
        lambda document_type, ocr_result: {
            "total_amount": {"value": 100.0, "evidence": {"source_text": "USD 100.00", "page_number": 1}}
        },
    )

    return TestClient(app)


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color="white").save(buf, format="PNG")
    return buf.getvalue()


def test_health_check(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_process_then_get_by_name_and_list(client):
    files = {"file": ("sample_invoice.png", _png_bytes(), "image/png")}
    data = {"document_type": "invoice"}
    resp = client.post("/api/v1/documents/process", files=files, data=data)
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_name"] == "sample_invoice.png"
    assert body["processing_status"] in ("PASS", "FAILED")

    get_resp = client.get("/api/v1/documents/sample_invoice.png")
    assert get_resp.status_code == 200
    assert get_resp.json()["document_name"] == "sample_invoice.png"

    list_resp = client.get("/api/v1/documents")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1


def test_get_unknown_document_returns_404(client):
    resp = client.get("/api/v1/documents/does_not_exist.pdf")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_unsupported_file_type_returns_controlled_error(client):
    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    data = {"document_type": "invoice"}
    resp = client.post("/api/v1/documents/process", files=files, data=data)
    # Controlled failure -> stored as FAILED with 200, per spec's PASS/FAILED status model.
    assert resp.status_code == 200
    body = resp.json()
    assert body["processing_status"] == "FAILED"
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
