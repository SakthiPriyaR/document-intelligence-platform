# Document Intelligence Platform
##  Case Study

End-to-end document extraction, validation and reconciliation

Live application: https://document-intelligence-platform-kace.onrender.com/
API documentation: https://document-intelligence-platform-kace.onrender.com/docs

---

# 1. Problem and objective

- Accept invoices, balance sheets, profit and loss statements, and cash-flow statements.
- Extract every meaningful field and table value from PDF, JPG, and PNG documents.
- Preserve evidence with source text and page number for traceability.
- Validate the document's own arithmetic without inventing missing values.
- Return a structured result through an API and a usable review dashboard.

---

# 2. Supported scope

| Area | Implementation |
|---|---|
| Document types | Invoice, balance sheet, profit and loss, cash flow statement |
| Uploads | PDF, JPG/JPEG, PNG; maximum 3 pages and 15 MB |
| Processing | FastAPI queue response followed by background extraction |
| Result states | PROCESSING, PASS, FAILED |
| Evidence | Source snippet and page number per extracted field |
| Persistence | SQLAlchemy with SQLite default; Postgres-ready configuration |

---

# 3. Architecture

Browser dashboard -> FastAPI REST API -> validation -> OCR/text extraction -> Gemini vision
-> financial validation -> repository -> SQLite or Postgres -> dashboard and API response

Key modules:

- `document_validation_service.py`: file type, integrity, readability, and page checks.
- `ocr_service.py`: PDF text layer, PyMuPDF rasterization, and Tesseract fallback.
- `extraction_service.py`: evidence-backed structured JSON through `google-genai`.
- `financial_validation_service.py`: document-type formula checks and tolerance handling.
- `document_repository.py`: persisted processed-document records.

See `docs/architecture.png` and `docs/architecture.pdf` for the exported diagram.

---

# 4. Input validation and OCR

Validation runs before OCR or AI:

- Detects supported content from file bytes, not only the browser MIME type.
- Rejects unsupported, empty, corrupt, unreadable, and over-limit uploads.
- Uses native `pdfplumber` text when a PDF has a usable text layer.
- Uses PyMuPDF plus Tesseract for scanned PDF pages.
- Sends normalized JPG/PNG images to Gemini vision for layout-aware extraction.

This keeps invalid documents cheap to reject and preserves page-level provenance.

---

# 5. AI extraction contract

Gemini receives the page-tagged source text and, for image uploads, the normalized page image.

- Extracts all visible meaningful fields and line items, not only a fixed list.
- Returns `null` when a value is absent or unreadable.
- Does not infer unsupported values.
- Uses strict JSON with a stable `extracted_data` envelope.
- Attaches `evidence.source_text` and `evidence.page_number`.
- Supports comparative periods using `field__period` keys.
- Handles current Gemini response variants, model fallback, empty output, and larger JSON payloads.

No API key is committed to source control.

---

# 6. Financial validation

Each document type has explicit checks with operands, formula, calculated value, reported value,
variance, and status.

| Type | Example check |
|---|---|
| Invoice | subtotal + tax - discount versus total |
| Balance sheet | liabilities + equity versus assets |
| Profit and loss | revenue - cost of sales versus gross profit |
| Cash flow | operating + investing + financing + FX versus net change |

Tolerance handles ordinary rounding. Missing operands produce `NOT_APPLICABLE`, never a guessed
`PASS` or `FAIL`.

---

# 7. Product experience and API

- Responsive Ledger dashboard with upload dropzone and processing workflow.
- Search, status/type filters, summary statistics, and refresh control.
- Centered document workspace with Fields, Validation, and Raw JSON tabs.
- Missing and low-confidence values are visually marked.
- Background jobs are polled automatically until PASS or FAILED.

Mandatory endpoints:

`POST /api/v1/documents/process` | `GET /api/v1/documents/{document_name}`

`GET /api/v1/documents` | `GET /api/v1/health`

---

# 8. Verification and deployment

- Public Render deployment is live.
- `/api/v1/health` reports the service and Gemini configuration status.
- Swagger/OpenAPI is available at `/docs`.
- Fresh live invoice verification returned file validation `PASS` and processing status `PASS`.
- The live test returned 43 extracted field entries and 6 line items.
- Automated suite: 25 tests passing without a network call or API key.
- Sample JSON fixtures cover all four document types, scanned/OCR failure, and unsupported input.

Repository: https://github.com/SakthiPriyaR/document-intelligence-platform

---

# 9. Deployment and submission links

| Required item | Submission value |
|---|---|
| Deployed Backend API URL (working health check) | https://document-intelligence-platform-kace.onrender.com/api/v1/health |
| Deployed Frontend URL | https://document-intelligence-platform-kace.onrender.com/ |
| Deployment Platform Used | Render (Docker web service) |
| Public GitHub repository | https://github.com/SakthiPriyaR/document-intelligence-platform |
| Version-controlled PPTX | https://github.com/SakthiPriyaR/document-intelligence-platform/blob/main/docs/solution_presentation.pptx |

For the required Google Drive share URL: upload `docs/solution_presentation.pptx` to the project
owner's Google Drive, set **General access** to **Anyone with the link - Viewer**, and paste the
resulting share URL in the application form. A Drive link cannot be created without access to the
owner's Google account.

---

# 10. Limitations and production plan

- Render Free local SQLite storage is ephemeral; managed Postgres is required for durable history.
- No authentication or rate limiting in this evaluation deployment.
- Large, dense documents may need chunked extraction and an async job queue.
- Confidence is model-reported and not independently calibrated.
- Production plan: auth, tenant isolation, Postgres/object storage, durable worker queue,
  observability, golden-document evaluations, and expanded reconciliation.

---

# 11. Delivery quality and submission materials

The solution uses modular service boundaries, controlled error handling, automated tests,
documented deployment steps, and environment-based configuration. Gemini is used at runtime only
for evidence-backed document field extraction after explicit configuration through `GEMINI_API_KEY`.

## Submission deliverables

- Public GitHub repository
- Live frontend and API
- Swagger/OpenAPI documentation
- README with setup, architecture, validation, and limitations
- Architecture diagram exports
- This solution presentation

---


