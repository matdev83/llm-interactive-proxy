"""Tests for URI parameter parsing in `src.core.domain.model_utils`."""

from __future__ import annotations

import json

from src.core.domain.model_utils import (
    RESOLVED_URI_PARAMS_EXTRA_BODY_KEY,
    has_explicit_backend_selector,
    parse_model_backend,
    parse_model_with_params,
)


def test_parse_model_with_single_parameter() -> None:
    result = parse_model_with_params("openai:gpt-4?temperature=0.5")

    assert result.backend_type == "openai"
    assert result.model_name == "gpt-4"
    assert result.uri_params == {"temperature": "0.5"}
    json.dumps(result.uri_params)


def test_parse_model_with_multiple_parameters() -> None:
    result = parse_model_with_params(
        "backend:model?temperature=0.2&reasoning_effort=low"
    )

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"temperature": "0.2", "reasoning_effort": "low"}


def test_parse_model_with_model_group_and_parameters() -> None:
    result = parse_model_with_params("backend:model_group/model_name?temperature=0.8")

    assert result.backend_type == "backend"
    assert result.model_name == "model_group/model_name"
    assert result.uri_params == {"temperature": "0.8"}


def test_parse_model_with_slash_separator_and_parameters() -> None:
    result = parse_model_with_params("openai/gpt-4?temp=0.5")

    assert result.backend_type == ""
    assert result.model_name == "openai/gpt-4"
    assert result.uri_params == {"temp": "0.5"}


def test_parse_model_without_parameters() -> None:
    result = parse_model_with_params("openai:gpt-4")

    assert result.backend_type == "openai"
    assert result.model_name == "gpt-4"
    assert result.uri_params == {}
    assert isinstance(result.uri_params, dict)


def test_parse_model_with_empty_query_string() -> None:
    result = parse_model_with_params("backend:model?")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {}


def test_parse_model_with_duplicate_parameters() -> None:
    result = parse_model_with_params("backend:model?temperature=0.5&temperature=0.8")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"temperature": "0.8"}


def test_parse_model_with_default_backend() -> None:
    result = parse_model_with_params("gpt-4?temperature=0.5", default_backend="openai")

    assert result.backend_type == "openai"
    assert result.model_name == "gpt-4"
    assert result.uri_params == {"temperature": "0.5"}


def test_parse_model_with_complex_model_path() -> None:
    result = parse_model_with_params(
        "openrouter:anthropic/claude-3-haiku:beta?temperature=0.3&reasoning_effort=high"
    )

    assert result.backend_type == "openrouter"
    assert result.model_name == "anthropic/claude-3-haiku:beta"
    assert result.uri_params == {"temperature": "0.3", "reasoning_effort": "high"}


def test_parse_model_malformed_graceful_fallback() -> None:
    result = parse_model_with_params("backend:model?invalid")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {}


def test_parse_model_with_invalid_parameter_value() -> None:
    result = parse_model_with_params("backend:model?temp=invalid")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"temp": "invalid"}


def test_parse_model_with_special_characters_in_values() -> None:
    result = parse_model_with_params("backend:model?name=test%20value")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"name": "test value"}


def test_parse_model_with_numeric_parameter_values() -> None:
    result = parse_model_with_params("backend:model?temperature=0.5&max_tokens=100")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"temperature": "0.5", "max_tokens": "100"}


def test_parse_model_with_boolean_like_values() -> None:
    result = parse_model_with_params("backend:model?stream=true&verbose=false")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"stream": "true", "verbose": "false"}


def test_parse_model_with_equals_in_value() -> None:
    result = parse_model_with_params("backend:model?key=value=extra")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"key": "value=extra"}


def test_parse_model_with_ampersand_only() -> None:
    result = parse_model_with_params("backend:model?&")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {}


def test_parse_model_with_empty_parameter_name() -> None:
    result = parse_model_with_params("backend:model?=value")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params in ({}, {"": "value"})


def test_parse_model_with_parameter_no_value() -> None:
    result = parse_model_with_params("backend:model?flag")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {}


def test_parse_model_backward_compatibility_colon_separator() -> None:
    result = parse_model_with_params("openai:gpt-4-turbo")

    assert result.backend_type == "openai"
    assert result.model_name == "gpt-4-turbo"
    assert result.uri_params == {}


def test_parse_model_backward_compatibility_slash_separator() -> None:
    result = parse_model_with_params("openrouter/anthropic/claude-3")

    assert result.backend_type == ""
    assert result.model_name == "openrouter/anthropic/claude-3"
    assert result.uri_params == {}


def test_reserved_alias_namespace_is_not_treated_as_backend_selector() -> None:
    assert has_explicit_backend_selector("alias:oss-code-medium") is False

    parsed = parse_model_backend("alias:oss-code-medium", default_backend="openai")

    assert parsed.backend_type == "openai"
    assert parsed.model_name == "alias:oss-code-medium"


def test_reserved_auto_namespace_is_not_treated_as_backend_selector() -> None:
    assert has_explicit_backend_selector("auto:oss-code-medium") is False

    parsed = parse_model_backend("auto:oss-code-medium", default_backend="openai")

    assert parsed.backend_type == "openai"
    assert parsed.model_name == "auto:oss-code-medium"


def test_parse_model_backward_compatibility_no_separator() -> None:
    result = parse_model_with_params("gpt-4", default_backend="openai")

    assert result.backend_type == "openai"
    assert result.model_name == "gpt-4"
    assert result.uri_params == {}


def test_parse_model_backward_compatibility_complex_path() -> None:
    result = parse_model_with_params("openrouter:anthropic/claude-3-opus:beta")

    assert result.backend_type == "openrouter"
    assert result.model_name == "anthropic/claude-3-opus:beta"
    assert result.uri_params == {}


def test_parse_model_with_multiple_question_marks() -> None:
    result = parse_model_with_params("backend:model?temp=0.5?extra=1")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"temp": "0.5?extra=1"}


def test_parse_model_with_hash_fragment() -> None:
    result = parse_model_with_params("backend:model?temp=0.5#fragment")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"temp": "0.5#fragment"}


def test_parse_model_with_very_long_parameter_value() -> None:
    long_value = "x" * 1000
    result = parse_model_with_params(f"backend:model?data={long_value}")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params["data"] == long_value


def test_parse_model_with_unicode_characters() -> None:
    result = parse_model_with_params("backend:model?name=test_?á?")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params["name"] == "test_?á?"


def test_parse_model_empty_string() -> None:
    result = parse_model_with_params("", default_backend="openai")

    assert result.backend_type == "openai"
    assert result.model_name == ""
    assert result.uri_params == {}


def test_parse_model_only_question_mark() -> None:
    result = parse_model_with_params("?", default_backend="openai")

    assert result.backend_type == "openai"
    assert result.model_name == ""
    assert result.uri_params == {}


def test_parse_model_with_mixed_separators_and_params() -> None:
    result = parse_model_with_params(
        "openai:model_group/model_name?temperature=0.7&reasoning_effort=medium"
    )

    assert result.backend_type == "openai"
    assert result.model_name == "model_group/model_name"
    assert result.uri_params == {"temperature": "0.7", "reasoning_effort": "medium"}


def test_parse_vendor_model_suffix_with_colon_stays_model_only() -> None:
    result = parse_model_with_params("openrouter/anthropic/claude-3-haiku:free")

    assert result.backend_type == ""
    assert result.model_name == "openrouter/anthropic/claude-3-haiku:free"
    assert result.uri_params == {}


def test_parse_vendor_model_suffix_with_colon_and_query_stays_model_only() -> None:
    result = parse_model_with_params(
        "openrouter/anthropic/claude-3-haiku:free?temperature=0.5"
    )

    assert result.backend_type == ""
    assert result.model_name == "openrouter/anthropic/claude-3-haiku:free"
    assert result.uri_params == {"temperature": "0.5"}


def test_parse_backend_prefix_with_colon_in_tail_keeps_tail_intact() -> None:
    result = parse_model_with_params("openrouter:anthropic/claude-3-haiku:free")

    assert result.backend_type == "openrouter"
    assert result.model_name == "anthropic/claude-3-haiku:free"
    assert result.uri_params == {}


def test_parse_backend_prefix_with_colon_in_tail_and_query_keeps_tail_intact() -> None:
    result = parse_model_with_params(
        "openrouter:anthropic/claude-3-haiku:free?temperature=0.5&top_p=0.7"
    )

    assert result.backend_type == "openrouter"
    assert result.model_name == "anthropic/claude-3-haiku:free"
    assert result.uri_params == {"temperature": "0.5", "top_p": "0.7"}


def test_has_explicit_backend_selector_uses_colon_before_slash_rule() -> None:
    assert has_explicit_backend_selector("openrouter:anthropic/claude-3-haiku:free")
    assert not has_explicit_backend_selector("openrouter/anthropic/claude-3-haiku:free")


def test_parse_model_backend_colon_after_slash_uses_default_backend() -> None:
    parsed = parse_model_backend(
        "openrouter/anthropic/claude-3-haiku:free", default_backend="openai"
    )

    assert parsed.backend_type == "openai"
    assert parsed.model_name == "openrouter/anthropic/claude-3-haiku:free"


def test_parse_model_case_sensitivity() -> None:
    result = parse_model_with_params("backend:model?Temperature=0.5&temperature=0.8")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"Temperature": "0.5", "temperature": "0.8"}


def test_parse_model_with_trailing_ampersand() -> None:
    result = parse_model_with_params("backend:model?temp=0.5&")

    assert result.backend_type == "backend"
    assert result.model_name == "model"
    assert result.uri_params == {"temp": "0.5"}


def test_parse_model_with_leading_ampersand() -> None:
    result = parse_model_with_params("backend:model?&temp=0.5")

    assert result.backend_type == "backend"
    assert result.model_name == "model"


def test_resolved_uri_params_extra_body_key_value() -> None:
    assert RESOLVED_URI_PARAMS_EXTRA_BODY_KEY == "_resolved_uri_params"
    assert isinstance(RESOLVED_URI_PARAMS_EXTRA_BODY_KEY, str)
    assert RESOLVED_URI_PARAMS_EXTRA_BODY_KEY.startswith("_")
