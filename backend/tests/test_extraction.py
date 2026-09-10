from app.services.extraction_service import _parse_json_response


def test_parse_json_response_accepts_markdown_wrapped_json():
    result = _parse_json_response('Here is the result:\n```json\n{"extracted_data": {}}\n```')
    assert result == {"extracted_data": {}}
