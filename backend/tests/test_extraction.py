from app.services.extraction_service import _parse_json_response


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
