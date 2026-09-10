import sys
from types import ModuleType, SimpleNamespace

from app.services.extraction_service import _parse_json_response
from app.services.extraction_service import _call_gemini


def test_parse_json_response_accepts_markdown_wrapped_json():
    result = _parse_json_response('Here is the result:\n```json\n{"extracted_data": {}}\n```')
    assert result == {"extracted_data": {}}


def test_parse_json_response_accepts_trailing_comma_and_commentary():
    result = _parse_json_response('Result: {"extracted_data": {},}')
    assert result == {"extracted_data": {}}


def test_parse_json_response_accepts_line_breaks_in_evidence_text():
    result = _parse_json_response('{"extracted_data": {"note": {"value": "line1\nline2"}}}')
    assert result["extracted_data"]["note"]["value"] == "line1\nline2"


def test_parse_json_response_ignores_trailing_commentary():
    result = _parse_json_response('{"extracted_data": {}} Thank you.')
    assert result == {"extracted_data": {}}


def test_call_gemini_uses_current_sdk_for_image(monkeypatch):
    calls = []

    class FakePart:
        @classmethod
        def from_bytes(cls, *, data, mime_type):
            return {"data": data, "mime_type": mime_type}

    class FakeConfig:
        def __init__(self, **kwargs):
            self.values = kwargs

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text='{"extracted_data": {}}')

    fake_types = ModuleType("google.genai.types")
    fake_types.Part = FakePart
    fake_types.GenerateContentConfig = FakeConfig
    fake_types.HttpOptions = lambda **kwargs: kwargs
    fake_types.ThinkingConfig = FakeConfig

    fake_genai = ModuleType("google.genai")
    fake_genai.types = fake_types
    fake_genai.Client = lambda *, api_key, http_options: SimpleNamespace(models=FakeModels())

    fake_google = ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    from app.core.config import get_settings
    get_settings.cache_clear()

    result = _call_gemini("system", "extract this", b"jpeg-bytes")

    assert result == '{"extracted_data": {}}'
    assert calls[0]["model"] == get_settings().GEMINI_MODEL
    assert calls[0]["contents"][0] == "extract this"
    assert calls[0]["contents"][1] == {"data": b"jpeg-bytes", "mime_type": "image/jpeg"}
    assert calls[0]["config"].values["system_instruction"] == "system"
    assert calls[0]["config"].values["response_mime_type"] == "application/json"


def test_call_gemini_falls_back_on_temporary_model_error(monkeypatch):
    calls = []

    class FakeError(Exception):
        code = 503

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise FakeError("temporary model outage")
            return SimpleNamespace(text='{"extracted_data": {}}')

    class FakePart:
        @classmethod
        def from_bytes(cls, *, data, mime_type):
            return {"data": data, "mime_type": mime_type}

    class FakeConfig:
        def __init__(self, **kwargs):
            self.values = kwargs

    fake_types = ModuleType("google.genai.types")
    fake_types.Part = FakePart
    fake_types.GenerateContentConfig = FakeConfig
    fake_types.HttpOptions = lambda **kwargs: kwargs
    fake_types.ThinkingConfig = FakeConfig

    fake_genai = ModuleType("google.genai")
    fake_genai.types = fake_types
    fake_genai.Client = lambda *, api_key, http_options: SimpleNamespace(models=FakeModels())

    fake_google = ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    from app.core.config import get_settings
    get_settings.cache_clear()

    result = _call_gemini("system", "extract this")

    assert result == '{"extracted_data": {}}'
    assert [call["model"] for call in calls] == ["gemini-2.5-flash", "gemini-3.6-flash"]
