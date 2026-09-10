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
        f"Document text (page-tagged, extracted via OCR/text-layer parsing; an image is attached for image uploads):\n"
        f"-----\n{ocr_result.full_text}\n-----\n\n"
        f"Return the JSON object described in the system prompt now."
    )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json_response(raw_response: str) -> dict:
    """Parse strict JSON plus common model wrappers around a JSON object."""
    cleaned = _strip_code_fences(raw_response).lstrip("\ufeff").strip()
    if cleaned.lower().startswith("json\n"):
        cleaned = cleaned[5:].lstrip()
    candidates = [cleaned]
    start = cleaned.find("{")
    if start >= 0:
        end = cleaned.rfind("}")
        if end > start:
            candidates.append(cleaned[start:end + 1])
        candidates.append(cleaned[start:])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate, strict=False)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                parsed = json.loads(repaired, strict=False)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    logger.error("LLM returned non-JSON output: %s", cleaned[:500])
    raise ExtractionError("The AI extraction service returned an unparseable response.")


def _response_text(response) -> str:
    """Return visible model text across SDK response variants."""
    try:
        parsed = getattr(response, "parsed", None)
    except Exception:
        parsed = None
    if parsed is not None:
        if hasattr(parsed, "model_dump"):
            parsed = parsed.model_dump()
        return json.dumps(parsed)

    try:
        text = getattr(response, "text", None)
    except Exception:
        text = None
    if text:
        return text

    # Some multimodal responses expose text only through candidate parts.
    visible_parts = []
    all_parts = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                all_parts.append(part_text)
                if not getattr(part, "thought", False):
                    visible_parts.append(part_text)
    return "\n".join(visible_parts or all_parts)


def _call_gemini(system_prompt: str, user_prompt: str, image_bytes: bytes | None = None) -> str:
    """Call Gemini using Google's current ``google-genai`` SDK.

    The old ``google-generativeai`` SDK exposed a different response/config
    surface and is no longer the recommended path for current Gemini models.
    Keeping the client local to this function also means the app can still
    start when Gemini is not configured and return a useful configuration
    error only when extraction is requested.
    """
    from google import genai
    from google.genai import types

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise ExtractionError(
            "GEMINI_API_KEY is not configured on the server. "
            "Set it as an environment variable to enable AI extraction."
        )

    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS * 1000,
        ),
    )
    active_model = settings.GEMINI_MODEL

    def _status_code(exc: Exception) -> int | None:
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if isinstance(code, int):
            return code
        match = re.search(r"\b(4\d\d|5\d\d)\b", str(exc))
        return int(match.group(1)) if match else None

    last_exc: Exception | None = None
    for attempt in range(1, settings.LLM_MAX_RETRIES + 2):
        try:
            config_kwargs = {
                "system_instruction": system_prompt,
                "temperature": 0,
                "response_mime_type": "application/json",
                "max_output_tokens": 4000,
            }
            # Gemini 3 models can spend the entire small output budget on
            # hidden reasoning before producing the JSON answer. Minimal
            # thinking keeps extraction fast and leaves room for the result.
            if active_model.startswith("gemini-3"):
                thinking_type = getattr(types, "ThinkingConfig", None)
                thinking_fields = getattr(thinking_type, "model_fields", {})
                if thinking_type and "thinking_level" in thinking_fields:
                    config_kwargs["thinking_config"] = thinking_type(
                        thinking_level="minimal"
                    )
                else:
                    # Older google-genai releases do not know the Gemini 3
                    # thinking_level field. Leave it unset rather than
                    # sending a config that the installed SDK rejects.
                    logger.info("Gemini SDK lacks thinking_level; using default thinking configuration")
            config = types.GenerateContentConfig(
                **config_kwargs,
            )
            if image_bytes:
                image = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                response = client.models.generate_content(
                    model=active_model,
                    contents=[user_prompt, image],
                    config=config,
                )
            else:
                response = client.models.generate_content(
                    model=active_model,
                    contents=user_prompt,
                    config=config,
                )
            return _response_text(response)
        except Exception as exc:  # network / rate-limit / API errors
            last_exc = exc
            logger.warning("LLM call attempt %d failed: %s", attempt, exc)
            status_code = _status_code(exc)
            if status_code in (404, 429, 500, 502, 503, 504) and active_model != "gemini-3.6-flash":
                active_model = "gemini-3.6-flash"
                logger.info(
                    "Gemini model unavailable (status=%s); retrying with fallback model=%s",
                    status_code,
                    active_model,
                )
                continue
            if status_code in (400, 401, 403):
                break

    detail = str(last_exc or "unknown error").replace(settings.GEMINI_API_KEY or "", "[redacted]")
    raise ExtractionError(f"The AI extraction service failed: {detail[:300]}") from last_exc


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

    if settings.LLM_PROVIDER == "gemini":
        raw_response = _call_gemini(_SYSTEM_PROMPT, user_prompt, getattr(ocr_result, "image_bytes", None))
    elif settings.LLM_PROVIDER == "anthropic":
        raw_response = _call_anthropic(_SYSTEM_PROMPT, user_prompt)
    else:
        raise ExtractionError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")

    try:
        parsed = _parse_json_response(raw_response)
    except ExtractionError:
        # A constrained second pass handles occasional model wrappers or
        # partially formatted output without weakening the schema contract.
        retry_prompt = user_prompt + "\nReturn ONLY one valid JSON object. Do not add markdown, labels, or commentary."
        if settings.LLM_PROVIDER == "gemini":
            parsed = _parse_json_response(
                _call_gemini(_SYSTEM_PROMPT, retry_prompt, getattr(ocr_result, "image_bytes", None))
            )
        else:
            raise

    extracted_data = parsed.get("extracted_data")
    if not isinstance(extracted_data, dict):
        raise ExtractionError("The AI extraction service returned an unexpected response shape.")

    return extracted_data
