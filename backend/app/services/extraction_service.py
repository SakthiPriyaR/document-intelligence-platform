"""
AI-based field & table extraction.

Takes the OCR'd/parsed page text for a document and asks an LLM (Anthropic
Claude by default) to return ALL meaningful fields it can see, as strict
JSON, with per-field evidence (source text + page number) and without
inventing values that aren't actually present in the document.

The provider is isolated behind `run_extraction()` so a different
model/provider can be swapped in by changing this module only.
"""
import json
import re

from app.core.config import get_settings
from app.core.exceptions import ExtractionError
from app.core.logging import get_logger
from app.services.ocr_service import OCRResult

logger = get_logger(__name__)

_MINIMUM_FIELDS = {
    "invoice": [
        "invoice_number", "invoice_date", "vendor_name", "customer_name", "currency",
        "subtotal", "tax_amount", "discount", "total_amount",
    ],
    "balance_sheet": ["total_assets", "total_liabilities", "total_equity"],
    "profit_and_loss": [
        "revenue", "cost_of_sales", "gross_profit", "operating_expenses",
        "operating_profit", "tax", "net_profit",
    ],
    "cash_flow_statement": [
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
        "opening_cash", "net_change_in_cash", "closing_cash",
    ],
}

_SYSTEM_PROMPT = """You are a meticulous financial document data-extraction engine.

Rules you MUST follow:
1. Extract EVERY meaningful field, label, date, party name, currency, monetary
   amount, and table/line-item you can actually see in the provided document
   text - not just a fixed minimum list. Include header info, comparative
   period values, subtotals, and every line item in any table.
2. Only report a value if it is genuinely present in the document text you were
   given. If a field is not present, set its value to null. NEVER invent,
   guess, or infer a value that is not supported by the source text.
3. For every field, include the exact short snippet of source text that
   supports the value (evidence.source_text) and the page number it came from
   (evidence.page_number), taken from the "[PAGE n]" markers in the input.
4. Numbers must be returned as plain numeric JSON values (no currency symbols
   or thousands separators). Preserve negative values (including values shown
   in parentheses/brackets, which represent negative numbers).
5. If the document shows the SAME line item across multiple comparative
   periods/years (e.g. "Current Year" vs "Previous Year", or "2025" vs
   "2024"), encode each period as its own field named
   "<field_name>__<period_label>" (double underscore), where period_label is
   the year/period exactly as labelled in the document (e.g.
   "total_assets__2025", "total_assets__2024"). If there is only one period,
   you do not need a suffix.
6. Respond with STRICT JSON only - no markdown code fences, no commentary,
   no explanation before or after the JSON.

Output JSON shape:
{
  "extracted_data": {
    "<field_name>": {"value": <string|number|null>, "evidence": {"source_text": <string|null>, "page_number": <int|null>}},
    ...
    "line_items": [ {"<column>": <value>, ...}, ... ]   // include only if a table/line-items exist
  }
}
"""


def _build_user_prompt(document_type: str, ocr_result: OCRResult) -> str:
    min_fields = _MINIMUM_FIELDS.get(document_type, [])
    return (
        f"Document type: {document_type}\n"
        f"At minimum, look for (but do not limit yourself to) these fields where present: "
        f"{', '.join(min_fields)}.\n\n"
        f"Document text (page-tagged, extracted via OCR/text-layer parsing):\n"
        f"-----\n{ocr_result.full_text}\n-----\n\n"
        f"Return the JSON object described in the system prompt now."
    )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    import anthropic

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        raise ExtractionError(
            "ANTHROPIC_API_KEY is not configured on the server. "
            "Set it as an environment variable to enable AI extraction."
        )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS)

    last_exc: Exception | None = None
    for attempt in range(1, settings.LLM_MAX_RETRIES + 2):
        try:
            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=4000,
                temperature=0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return "".join(block.text for block in response.content if block.type == "text")
        except Exception as exc:  # network / rate-limit / API errors
            last_exc = exc
            logger.warning("LLM call attempt %d failed: %s", attempt, exc)

    raise ExtractionError("The AI extraction service failed after retries.") from last_exc


def run_extraction(document_type: str, ocr_result: OCRResult) -> dict:
    settings = get_settings()
    logger.info("Running LLM extraction provider=%s document_type=%s", settings.LLM_PROVIDER, document_type)

    user_prompt = _build_user_prompt(document_type, ocr_result)

    if settings.LLM_PROVIDER == "anthropic":
        raw_response = _call_anthropic(_SYSTEM_PROMPT, user_prompt)
    else:
        raise ExtractionError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")

    cleaned = _strip_code_fences(raw_response)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("LLM returned non-JSON output: %s", raw_response[:500])
        raise ExtractionError("The AI extraction service returned an unparseable response.") from exc

    extracted_data = parsed.get("extracted_data")
    if not isinstance(extracted_data, dict):
        raise ExtractionError("The AI extraction service returned an unexpected response shape.")

    return extracted_data
