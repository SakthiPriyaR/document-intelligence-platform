# Presentation Talk Track

Use this as speaker notes for the accompanying `solution_presentation.pptx`.
It is designed for a six to eight minute internship-case-study presentation.

## Slide 1 — Introduction (30 seconds)

“This is Ledger, a document intelligence platform for financial documents. It turns invoices and financial statements into structured, evidence-backed data and checks the document’s arithmetic. The live application is deployed on Render and uses FastAPI with Google Gemini vision.”

## Slide 2 — Objective and scope (35 seconds)

“The solution supports invoices, balance sheets, profit and loss statements, and cash-flow statements. It accepts PDF, JPG, and PNG files. The goal is not only extraction: every extracted value remains traceable to its source page, and financial totals are checked.”

## Slide 3 — Architecture (45 seconds)

“The browser calls a FastAPI API. Before anything expensive happens, the backend validates the file. It extracts text through native PDF text or OCR, sends normalized information to Gemini for structured extraction, runs financial validation, and persists the result. The dashboard and API both read the same result.”

## Slide 4 — Validation and OCR (35 seconds)

“File validation happens first. The service checks the actual file bytes, integrity, size, page count, and readability. For text PDFs it uses the text layer; for scanned pages it falls back to PyMuPDF and Tesseract. This prevents invalid files from reaching the AI step.”

## Slide 5 — AI extraction (45 seconds)

“Gemini is used only to read and structure the supplied document. It returns fields, line items, evidence, and confidence. The contract explicitly says not to invent values: missing or unreadable values are null. I also added handling for current Gemini response formats and model fallback.”

## Slide 6 — Financial validation (45 seconds)

“After extraction, the app checks formulas appropriate to the selected document type. For an invoice, for example, it compares subtotal plus tax minus discount with the total. Each check reports its inputs, calculation, variance, and PASS, FAIL, or NOT_APPLICABLE status.”

## Slide 7 — Dashboard and API (40 seconds)

“The dashboard is for human review: upload, search, filters, and a detailed workspace. A record opens into Fields, Validation, and Raw JSON tabs. The same capability is exposed through the mandatory REST endpoints, with Swagger documentation at `/docs`.”

## Slide 8 — Verification (35 seconds)

“I verified the solution with 25 automated tests and a fresh live invoice upload. The live result passed file validation and processing, extracted 43 field entries and 6 line items. The frontend, health endpoint, API, and Swagger are publicly reachable.”

## Slide 9 — Deployment links (20 seconds)

“This slide contains the exact submission links: the deployed API base, live frontend, Render as the platform, and the public GitHub repository. The PPTX is version-controlled in the repository. For the form’s Google Drive field, I upload this same PPTX to Drive and share it as view-only.”

## Slide 10 — Limitations and roadmap (30 seconds)

“The main evaluation limitation is that free Render local SQLite storage is not durable across restarts. A production version would use managed Postgres, object storage, a durable worker queue, authentication, and monitoring. I call this out clearly rather than hiding it.”

## Slide 11 — AI usage and deliverables (20 seconds)

“AI coding assistance helped with scaffolding and iteration, but the source was reviewed and test-verified. Gemini at runtime is explicitly configured and is used only for evidence-backed extraction. The repository includes the code, documentation, tests, samples, architecture, and presentation files.”

## Slide 12 — Live demo flow (45 seconds)

“I will now show the app: select a document type, upload a file, explain validation, wait for the processing status, then open the result. I will point to the evidence, line items, validation checks, and raw JSON. I finish by returning to the deployment and test evidence.”

## Before presenting

- Open the live frontend 1–2 minutes early to wake the Render Free service.
- Keep one completed document visible in the ledger as a backup demonstration.
- Keep the API docs open in a separate browser tab.
- Upload `docs/solution_presentation.pptx` to Google Drive and set it to **Anyone with the link - Viewer** before submitting.
