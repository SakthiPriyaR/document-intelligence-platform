# Document Intelligence Platform

Live deployment: https://document-intelligence-platform-kace.onrender.com/  ·  API docs: https://document-intelligence-platform-kace.onrender.com/docs

An end-to-end service that accepts invoices, balance sheets, P&L statements and cash-flow
statements (PDF/JPG/PNG), validates the upload, extracts every meaningful field via OCR + an
LLM, checks the document's own arithmetic, and exposes everything through a REST API and a
small dashboard.

> **Status of this repo**: fully implemented and unit/API-tested locally. It has **not yet been
> deployed** or run against real sample invoices/statements — do that next (see *Deployment* and
> *Testing* below) before submitting. Replace the placeholder URLs in this README once deployed.

## 1. Solution overview & architecture

```
Upload → Document Validation → OCR/Text Extraction → AI Field Extraction
       → Financial Validation → Persist (DB) → Dashboard + REST API
```

See [`docs/architecture.svg`](docs/architecture.svg) (rendered diagram) and
[`docs/architecture.mmd`](docs/architecture.mmd) (Mermaid source) for the full picture.

- **Frontend** (`frontend/`): a single static page (HTML/CSS/vanilla JS) — upload form, a ledger
  (table) of processed documents, and a slide-over detail panel with Fields / Validation / Raw
  JSON tabs. It talks only to the deployed backend's REST API.
- **Backend** (`backend/`): FastAPI application, organised by concern:
  - `app/services/document_validation_service.py` — input-control layer (file type sniffing,
    corruption/empty checks, page-count limit). Runs **before** any OCR/AI call.
  - `app/services/ocr_service.py` — native PDF text-layer extraction (pdfplumber) with a
    per-page fallback to OCR (PyMuPDF rasterisation + Tesseract) for scanned pages/images.
  - `app/services/extraction_service.py` — calls an LLM (Google Gemini by default) with a
    strict "extract everything you can see, evidence-backed, never invent" prompt and parses
    the structured JSON it returns.
  - `app/services/financial_validation_service.py` — a formula engine that runs the correct
    checks for the document type (Table 7 style formulas), tolerant of minor OCR rounding, and
    returns `NOT_APPLICABLE` rather than guessing when a required field is missing.
  - `app/services/document_service.py` — orchestrates the four stages above and turns any
    controlled failure into a `FAILED` result instead of a crash.
  - `app/repositories/document_repository.py` + `app/models/document.py` — persistence
    (SQLAlchemy; SQLite by default, swap `DATABASE_URL` for Postgres/MySQL).
  - `app/api/routes/documents.py` — the four mandatory REST endpoints.
  - `app/core/` — settings (env-var driven), logging, DB session, and the exception→JSON-error
    mapping used everywhere so nothing leaks a stack trace to the client.

## 2. Technology stack & why

| Layer | Choice | Why |
|---|---|---|
| API framework | **FastAPI** | Async, automatic Swagger/OpenAPI docs at `/docs`, first-class Pydantic validation → matches the "structured outputs" requirement directly. |
| Native PDF text | **pdfplumber** | Reliable text-layer + layout extraction for born-digital PDFs; avoids OCR cost/error when a real text layer exists. |
| PDF rasterisation | **PyMuPDF (fitz)** | Pure-wheel, no system Poppler dependency, fast page→image rendering for the OCR fallback. |
| OCR | **Tesseract** (via `pytesseract`) | Free, local, no external API needed for the assessment's 3-day scope; swappable for Google Vision/LlamaParse/etc. by editing `ocr_service.py` only. |
| Field/table extraction | **Google Gemini** (`gemini-3.6-flash`, default) | Fast multimodal extraction with a free-tier key. Isolated behind `extraction_service.run_extraction()`, with Anthropic Claude available as a drop-in alternative via `LLM_PROVIDER=anthropic`. |
| Persistence | **SQLAlchemy + SQLite** (default) | Zero-setup locally; one env-var change (`DATABASE_URL`) moves to Postgres/MySQL for deployment. |
| Frontend | **Plain HTML/CSS/JS** | Explicitly permitted by the brief; no build step, one static bundle FastAPI serves directly. |
| Testing | **pytest** + FastAPI `TestClient` | File validation and financial-formula tests need no network; API-flow tests monkeypatch OCR/LLM so the suite runs with zero external calls or API keys. |

## 3. Local setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# System dependency for OCR (already installed on most CI/deploy images):
#   Debian/Ubuntu: sudo apt-get install tesseract-ocr
#   macOS:         brew install tesseract

cp ../.env.example .env      # then fill in GEMINI_API_KEY at minimum (free, no card: aistudio.google.com/apikey)
uvicorn app.main:app --reload --port 8000
```

Open:
- Dashboard: http://localhost:8000/
- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## 4. Environment variables

See [`.env.example`](.env.example) for the full, commented list (no real secrets committed).
Key ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLite by default; point at Postgres/MySQL for deployment. |
| `GEMINI_API_KEY` | Required for AI field extraction (default provider) — read from the environment only, never hardcoded. Free tier, no card: aistudio.google.com/apikey. |
| `GEMINI_MODEL` | Defaults to `gemini-3.6-flash`; the service falls back to it when an older configured model returns 404. |
| `LLM_PROVIDER` | `gemini` (default) or `anthropic` — set `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` instead if switching. |
| `MAX_PAGE_COUNT`, `MAX_FILE_SIZE_MB` | Input-validation limits. |
| `VALIDATION_ABS_TOLERANCE`, `VALIDATION_REL_TOLERANCE` | Financial-check tolerance (see §9). |

## 5. Deployed URLs

- Frontend: https://document-intelligence-platform-kace.onrender.com/
- Backend API base: https://document-intelligence-platform-kace.onrender.com/api/v1
- Swagger/OpenAPI: https://document-intelligence-platform-kace.onrender.com/docs
- Health check: https://document-intelligence-platform-kace.onrender.com/api/v1/health
- Public GitHub repo: https://github.com/SakthiPriyaR/document-intelligence-platform

## 6. API reference

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/documents/process` | Validate and synchronously process a document (`multipart/form-data`: `file`, `document_type`), returning the persisted final result. |
| GET | `/api/v1/documents/{document_name}` | Latest structured result for that file name. |
| GET | `/api/v1/documents` | List all processed documents (dashboard feed). |
| GET | `/api/v1/health` | Health check. |

**POST /api/v1/documents/process**
```bash
curl -X POST https://YOUR-DEPLOYMENT/api/v1/documents/process \
  -F "file=@sample_invoice.pdf" \
  -F "document_type=invoice"
```

**GET by name**
```bash
curl https://YOUR-DEPLOYMENT/api/v1/documents/sample_invoice.pdf
```

**Dashboard list**
```bash
curl https://YOUR-DEPLOYMENT/api/v1/documents
```

Full request/response schemas are always up to date at `/docs` (Swagger) and `/redoc`.
Error responses are always `{"error": {"code": "...", "message": "..."}}` (see
`app/core/exceptions.py` for the full code list, e.g. `UNSUPPORTED_FILE_TYPE`,
`PAGE_LIMIT_EXCEEDED`, `CORRUPTED_FILE`, `DOCUMENT_NOT_FOUND`, `EXTRACTION_FAILED`).

## 7. Deployment

Any free-tier platform that runs a Python web service works (Render, Railway, Koyeb, Fly.io).
A `Dockerfile` is provided at `backend/Dockerfile` (installs Tesseract + Python deps, serves both
the API and the static frontend from one container on `$PORT`/8000).

1. Push this repo to a **public** GitHub repository.
2. On your platform, create a new **Web Service** from the repo, build context = repo root,
   Dockerfile = `backend/Dockerfile`.
3. Set environment variables from `.env.example` (at minimum `GEMINI_API_KEY`). The included
   Render Free does not support persistent disks, so the default SQLite file is ephemeral there.
   For durable deployment data, configure `DATABASE_URL` with a managed Postgres URL.
4. Deploy. Confirm `/api/v1/health` returns `200`, then confirm `/` (frontend) and `/docs`
   (Swagger) both load.
5. Record the resulting URLs in §5 above.

A localhost-only submission does not satisfy the assignment — the platform above must be
publicly reachable at evaluation time.

## 8. OCR / extraction / LLM details

- **OCR/parsing**: pdfplumber for native PDF text; PyMuPDF + Tesseract OCR as the fallback for
  scanned PDFs. JPG/PNG uploads are sent directly to Gemini vision to avoid slow local OCR on
  camera photographs. `processing_metadata.ocr_used` tells you whether local OCR ran.
- **LLM**: Google Gemini (`gemini-3.6-flash` by default, configurable via `GEMINI_MODEL`; swap to
  Anthropic Claude by setting `LLM_PROVIDER=anthropic`),
  called once per document with the full page-tagged text. The prompt (see
  `extraction_service.py`) requires: extract everything visible (not just the minimum field
  list), return `null` rather than invent a value, and attach `evidence.source_text` +
  `evidence.page_number` to every field.
- **Confidence scoring (optional, implemented)**: `overall_confidence` is the mean of any
  per-field confidence values the LLM chooses to report — it's descriptive of the LLM's own
  output, not a fabricated number, and the field is nullable if the model omits it.

## 9. Financial validation rules & tolerance

Implemented in `financial_validation_service.py`, one function per document type, run once per
comparative period found in the extracted data (periods are detected via a `field__period`
naming convention the extraction prompt asks the LLM to use when a document shows more than one
year/column).

| Document | Checks |
|---|---|
| Invoice | `subtotal + tax − discount ≈ total_amount`; `quantity × unit_price ≈ line amount` per line item; `Σ line amounts ≈ subtotal/total`; `cash_paid − total ≈ change` when present. |
| Balance sheet | `total_liabilities + total_equity ≈ total_assets`, per period. |
| Profit & loss | `revenue − cost_of_sales ≈ gross_profit`; `gross_profit − operating_expenses ≈ operating_profit`; `operating_profit − tax ≈ net_profit`; plus the bank-style checks from the brief (interest earned/expended, provisions, minority interest, appropriation) when those specific fields are present. |
| Cash flow | `operating + investing + financing (+ fx) ≈ net_change_in_cash`; `opening_cash + net_change (+ adjustments) ≈ closing_cash`, per period. |

A check is **PASS** if `|calculated − reported| ≤ max(VALIDATION_ABS_TOLERANCE, VALIDATION_REL_TOLERANCE × |reported|)`
(defaults: 1.0 absolute, 1% relative — tune via env vars), **FAIL** if it exceeds tolerance, and
**NOT_APPLICABLE** whenever a required operand wasn't extracted — never guessed.
Bracketed/parenthesised values (`(1,250.00)`) are parsed as negative numbers throughout.

## 10. Database / persistence

SQLAlchemy ORM, one `processed_documents` table (`app/models/document.py`). Structured blobs
(`file_validation`, `extracted_data`, `validation`, `processing_metadata`) are stored as JSON
columns so the schema stays stable across very different document types, while `document_name`,
`document_type`, `processing_status` and `created_at` are indexed for the list/lookup endpoints.
Re-processing the same `document_name` inserts a new row; `GET /documents/{name}` always returns
the most recent one, per the spec (prior versions are kept, just not surfaced by that endpoint).

The free Render deployment uses a relative SQLite file and may lose data after restarts or
redeploys. For anything beyond a demo, use managed Postgres/MySQL.

## 11. Testing

```bash
cd backend
pytest -v
```

16 tests, all passing without any network access or API key:
- `tests/test_validation.py` — file-validation edge cases (empty, unsupported, corrupted,
  page-limit) and financial-formula correctness (PASS/FAIL/NOT_APPLICABLE, multi-period balance
  sheet, parenthesised-negative parsing).
- `tests/test_api.py` — full API flow (`process` → `get by name` → `list`), a 404 on unknown
  document, and a controlled error response for an unsupported upload. OCR/LLM calls are
  monkeypatched here so the suite has no external dependency.

Sample JSON outputs covering the required demo scenarios (one per document type, a validation
FAIL, a `NOT_APPLICABLE` case, a scanned/OCR case, and an unsupported-file case) are in
[`sample_outputs/`](sample_outputs/). **These are illustrative, hand-authored examples matching
the response schema** — replace them with real output once you've run the service against the
actual sample documents provided for the assessment.

## 12. Known limitations

- No automated document-type classification (explicitly out of scope per the brief — the type
  is supplied by the caller).
- Multi-period detection relies on the LLM following the `field__period` naming convention
  requested in the prompt; unusually laid-out comparative statements may need prompt tuning.
- Sub-component reconciliation (e.g. summing individual asset line items to `total_assets`) is
  not implemented for balance sheets — only the headline equation is checked, since sub-line
  item naming varies too much to reconcile generically in the time available.
- Confidence scores, where present, reflect the LLM's own self-reported confidence, not an
  independently calibrated metric.
- Single LLM call per document; very dense 3-page statements may need a larger `max_tokens` or a
  chunked-extraction strategy if truncation is observed in practice.
- No authentication/rate-limiting — acceptable for an evaluation deployment, not for production.

## 13. What I'd change for production

- Add authentication (API keys or OAuth) and per-tenant rate limiting.
- Move file storage/OCR to an async job queue (e.g. Celery/RQ) instead of synchronous
  in-request processing, with a `PROCESSING` status and webhook/polling for completion.
- Add a real document-type classifier so the four categories don't need to be supplied manually.
- Expand automated tests to cover the extraction prompt against a golden set of real documents,
  and add contract tests for the LLM response shape.
- Add structured (JSON) log shipping to an observability platform instead of stdout text logs.
- Sub-component (line-item-to-total) reconciliation for balance sheets and P&L statements.

## 14. AI coding assistants used

This project was built with the assistance of an AI coding assistant (Claude), used for:
generating the initial FastAPI project scaffold and module boundaries, the financial-validation
formula engine, the frontend dashboard (HTML/CSS/JS), the test suite, and this README. All code
was reviewed, run, and test-verified locally as part of the same session
(`cd backend && pytest -v` → 16/16 passing) before being written to this repository.

## Project layout

```
project-root/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes/documents.py
│   │   ├── core/            (config, database, logging, exceptions)
│   │   ├── models/document.py
│   │   ├── schemas/document.py
│   │   ├── services/        (validation, ocr, extraction, financial_validation, document_service)
│   │   └── repositories/document_repository.py
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── templates/index.html
│   └── static/{css,js}
├── docs/
│   ├── architecture.svg
│   └── architecture.mmd
├── sample_outputs/*.json
├── .env.example
├── .gitignore
└── README.md
```
