from __future__ import annotations

from src.core.domain.translation_utils.processed_response_usage import (
    usage_summary_from_processed_response,
)
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse


def test_usage_summary_prefers_chunk_usage_over_content_dict() -> None:
    from_chunk = UsageSummary.from_dict(
        {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
    )
    chunk = ProcessedResponse(
        content={
            "usage": {
                "prompt_tokens": 99,
                "completion_tokens": 99,
                "total_tokens": 198,
            },
        },
        usage=from_chunk,
    )
    assert usage_summary_from_processed_response(chunk) == from_chunk


def test_usage_summary_from_content_when_chunk_usage_none() -> None:
    chunk = ProcessedResponse(
        content={
            "id": "chatcmpl-1",
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        },
        usage=None,
    )
    got = usage_summary_from_processed_response(chunk)
    assert got is not None
    assert got.prompt_tokens == 10
    assert got.completion_tokens == 4
    assert got.total_tokens == 14


def test_usage_summary_codex_style_input_output_tokens() -> None:
    chunk = ProcessedResponse(
        content={
            "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
        },
        usage=None,
    )
    got = usage_summary_from_processed_response(chunk)
    assert got is not None
    assert got.prompt_tokens == 5
    assert got.completion_tokens == 7
    assert got.total_tokens == 12


def test_usage_summary_returns_none_for_non_dict_content() -> None:
    chunk = ProcessedResponse(content=b"not-json", usage=None)
    assert usage_summary_from_processed_response(chunk) is None


def test_usage_summary_returns_none_when_no_usage_key() -> None:
    chunk = ProcessedResponse(content={"choices": []}, usage=None)
    assert usage_summary_from_processed_response(chunk) is None


def test_usage_summary_ignores_non_dict_usage_value() -> None:
    chunk = ProcessedResponse(content={"usage": "invalid"}, usage=None)
    assert usage_summary_from_processed_response(chunk) is None
