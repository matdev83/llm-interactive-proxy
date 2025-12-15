import json

from src.core.domain.chat import ImageURL, MessageContentPartImage
from src.core.domain.translation import Translation
from src.core.domain.translation_utils import (
    content_utils,
    json_utils,
    media_utils,
    tool_utils,
    usage_utils,
)


def test_json_utils_sanitize_dict_drops_non_json_values() -> None:
    payload = {"ok": 1, "bad": object(), "nested": {"keep": True, "drop": {1, 2}}}

    expected = {"ok": 1, "nested": {"keep": True}}

    assert json_utils._sanitize_dict_for_json(payload) == expected
    assert Translation._sanitize_dict_for_json(payload) == expected


def test_json_utils_sanitize_dict_handles_cycles() -> None:
    payload: dict[str, object] = {}
    payload["self"] = payload

    assert json_utils._sanitize_dict_for_json(payload) == {"self": {}}
    assert Translation._sanitize_dict_for_json(payload) == {"self": {}}


def test_json_utils_sanitize_list_handles_cycles() -> None:
    payload: list[object] = []
    payload.append(payload)

    assert json_utils._sanitize_list_for_json(payload) == [[]]
    assert Translation._sanitize_list_for_json(payload) == [[]]


def test_tool_utils_normalize_tool_arguments_accepts_valid_json_string() -> None:
    raw = '  {"a": 1}  '
    assert tool_utils._normalize_tool_arguments(raw) == '{"a": 1}'
    assert Translation._normalize_tool_arguments(raw) == '{"a": 1}'


def test_tool_utils_normalize_tool_arguments_fixes_simple_single_quotes() -> None:
    raw = "{'a': 1}"
    normalized = tool_utils._normalize_tool_arguments(raw)
    assert json.loads(normalized) == {"a": 1}


def test_tool_utils_normalize_tool_arguments_rejects_unfixable_jsonish_strings() -> (
    None
):
    raw = "{'a': \"can't\"}"
    assert tool_utils._normalize_tool_arguments(raw) == "{}"


def test_tool_utils_process_gemini_function_call_preserves_thought_signature() -> None:
    function_call = {"id": "call_123", "name": "do_thing", "args": {"x": 1}}
    part = {"thoughtSignature": "sig_abc"}

    tool_call = tool_utils._process_gemini_function_call(function_call, part=part)
    assert tool_call.id == "call_123"
    assert tool_call.function.name == "do_thing"
    assert json.loads(tool_call.function.arguments) == {"x": 1}
    assert tool_call.extra_content == {"google": {"thought_signature": "sig_abc"}}


def test_media_utils_detect_image_mime_type_data_uri() -> None:
    assert (
        media_utils._detect_image_mime_type("data:image/png;base64,AAAA") == "image/png"
    )


def test_media_utils_process_gemini_image_part_inline_data() -> None:
    part = MessageContentPartImage(image_url=ImageURL(url="data:image/png;base64,AAAA"))
    assert media_utils._process_gemini_image_part(part) == {
        "inline_data": {"mime_type": "image/png", "data": "AAAA"}
    }


def test_media_utils_process_gemini_image_part_rejects_file_scheme_and_local_paths() -> (
    None
):
    part_file = MessageContentPartImage(image_url=ImageURL(url="file:///etc/passwd"))
    assert media_utils._process_gemini_image_part(part_file) is None

    part_local = MessageContentPartImage(image_url=ImageURL(url="C:\\\\tmp\\\\x.png"))
    assert media_utils._process_gemini_image_part(part_local) is None


def test_content_utils_coerce_reasoning_text_picks_common_keys() -> None:
    payload = {"thinking": [" one ", {"text": "two"}], "ignored": "three"}
    assert content_utils._coerce_reasoning_text(payload) == "one\ntwo"


def test_content_utils_safe_string_handles_bytes_and_none() -> None:
    assert content_utils._safe_string(None) == ""
    assert content_utils._safe_string(b"hi") == "hi"


def test_usage_utils_openai_preserves_token_details() -> None:
    usage = {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
        "prompt_tokens_details": {"cached_tokens": 2},
        "completion_tokens_details": {"reasoning_tokens": 1},
    }

    normalized = usage_utils._normalize_usage_metadata(usage, "openai")
    assert normalized["prompt_tokens"] == 3
    assert normalized["completion_tokens"] == 4
    assert normalized["total_tokens"] == 7
    assert normalized["prompt_tokens_details"] == {"cached_tokens": 2}
    assert normalized["completion_tokens_details"] == {"reasoning_tokens": 1}
