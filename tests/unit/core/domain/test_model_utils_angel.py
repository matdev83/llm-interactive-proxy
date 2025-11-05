from __future__ import annotations

from src.core.domain.model_utils import parse_model_with_params


def test_parse_angel_model_simple() -> None:
    backend, model, params = parse_model_with_params(
        "anthropic:claude-3-5-sonnet", default_backend="openai"
    )
    assert backend == "anthropic"
    assert model == "claude-3-5-sonnet"
    assert params == {}


def test_parse_angel_model_with_params() -> None:
    backend, model, params = parse_model_with_params(
        "openai:gpt-4o-mini?temperature=1&reasoning_effort=high",
        default_backend="openai",
    )
    assert backend == "openai"
    assert model == "gpt-4o-mini"
    assert params["temperature"] == "1"
    assert params["reasoning_effort"] == "high"


def test_parse_angel_model_default_backend() -> None:
    backend, model, params = parse_model_with_params(
        "gpt-4o-mini?temperature=0.5", default_backend="openai"
    )
    assert backend == "openai"
    assert model == "gpt-4o-mini"
    assert params["temperature"] == "0.5"
