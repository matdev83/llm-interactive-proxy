from __future__ import annotations

from src.core.domain.model_utils import parse_model_with_params


def test_parse_quality_verifier_model_simple() -> None:
    result = parse_model_with_params(
        "anthropic:claude-3-5-sonnet", default_backend="openai"
    )
    assert result.backend_type == "anthropic"
    assert result.model_name == "claude-3-5-sonnet"
    assert result.uri_params == {}


def test_parse_quality_verifier_model_with_params() -> None:
    result = parse_model_with_params(
        "openai:gpt-4o-mini?temperature=1&reasoning_effort=high",
        default_backend="openai",
    )
    assert result.backend_type == "openai"
    assert result.model_name == "gpt-4o-mini"
    assert result.uri_params["temperature"] == "1"
    assert result.uri_params["reasoning_effort"] == "high"


def test_parse_quality_verifier_model_default_backend() -> None:
    result = parse_model_with_params(
        "gpt-4o-mini?temperature=0.5", default_backend="openai"
    )
    assert result.backend_type == "openai"
    assert result.model_name == "gpt-4o-mini"
    assert result.uri_params["temperature"] == "0.5"
