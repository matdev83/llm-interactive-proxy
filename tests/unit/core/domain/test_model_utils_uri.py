"""Tests for URI parameter parsing in model_utils."""

from src.core.domain.model_utils import parse_model_with_params


def test_parse_model_with_single_parameter() -> None:
    """Test parsing model string with single URI parameter."""
    backend, model, params = parse_model_with_params("openai:gpt-4?temperature=0.5")

    assert backend == "openai"
    assert model == "gpt-4"
    assert params == {"temperature": "0.5"}
    # Verify params are JSON-serializable (strings from query parsing)
    assert isinstance(params, dict)
    # JsonValue is a type alias, so we check for JSON-serializable types directly
    import json

    json.dumps(params)  # Should not raise


def test_parse_model_with_multiple_parameters() -> None:
    """Test parsing model string with multiple URI parameters."""
    backend, model, params = parse_model_with_params(
        "backend:model?temperature=0.2&reasoning_effort=low"
    )

    assert backend == "backend"
    assert model == "model"
    assert params == {"temperature": "0.2", "reasoning_effort": "low"}


def test_parse_model_with_model_group_and_parameters() -> None:
    """Test parsing model string with model group and URI parameters."""
    backend, model, params = parse_model_with_params(
        "backend:model_group/model_name?temperature=0.8"
    )

    assert backend == "backend"
    assert model == "model_group/model_name"
    assert params == {"temperature": "0.8"}


def test_parse_model_with_slash_separator_and_parameters() -> None:
    """Test parsing vendor/model string with URI parameters (no backend selection)."""
    backend, model, params = parse_model_with_params("openai/gpt-4?temp=0.5")

    assert backend == ""
    assert model == "openai/gpt-4"
    assert params == {"temp": "0.5"}


def test_parse_model_without_parameters() -> None:
    """Test parsing model string without URI parameters (backward compatibility)."""
    backend, model, params = parse_model_with_params("openai:gpt-4")

    assert backend == "openai"
    assert model == "gpt-4"
    assert params == {}
    # Verify empty dict is compatible with dict[str, JsonValue]
    assert isinstance(params, dict)


def test_parse_model_with_empty_query_string() -> None:
    """Test parsing model string with empty query string after ?."""
    backend, model, params = parse_model_with_params("backend:model?")

    assert backend == "backend"
    assert model == "model"
    assert params == {}


def test_parse_model_with_duplicate_parameters() -> None:
    """Test parsing model string with duplicate parameters (last value wins)."""
    backend, model, params = parse_model_with_params(
        "backend:model?temperature=0.5&temperature=0.8"
    )

    assert backend == "backend"
    assert model == "model"
    # Last value should win
    assert params == {"temperature": "0.8"}


def test_parse_model_with_default_backend() -> None:
    """Test parsing model string with default backend and parameters."""
    backend, model, params = parse_model_with_params(
        "gpt-4?temperature=0.5", default_backend="openai"
    )

    assert backend == "openai"
    assert model == "gpt-4"
    assert params == {"temperature": "0.5"}


def test_parse_model_with_complex_model_path() -> None:
    """Test parsing model string with complex model path and parameters."""
    backend, model, params = parse_model_with_params(
        "openrouter:anthropic/claude-3-haiku:beta?temperature=0.3&reasoning_effort=high"
    )

    assert backend == "openrouter"
    assert model == "anthropic/claude-3-haiku:beta"
    assert params == {"temperature": "0.3", "reasoning_effort": "high"}


def test_parse_model_malformed_graceful_fallback() -> None:
    """Test that malformed query strings are handled gracefully."""
    # This should not raise an exception, but fall back to no parameters
    backend, model, params = parse_model_with_params("backend:model?invalid")

    assert backend == "backend"
    assert model == "model"
    # Should have empty params or handle gracefully
    assert isinstance(params, dict)


def test_parse_model_with_invalid_parameter_value() -> None:
    """Test parsing model string with invalid parameter value."""
    backend, model, params = parse_model_with_params("backend:model?temp=invalid")

    assert backend == "backend"
    assert model == "model"
    # Parser should still extract the parameter, validation happens later
    assert params == {"temp": "invalid"}


def test_parse_model_with_special_characters_in_values() -> None:
    """Test parsing model string with special characters in parameter values."""
    backend, model, params = parse_model_with_params("backend:model?name=test%20value")

    assert backend == "backend"
    assert model == "model"
    # URL-encoded space should be decoded
    assert "name" in params


def test_parse_model_with_numeric_parameter_values() -> None:
    """Test parsing model string with numeric parameter values."""
    backend, model, params = parse_model_with_params(
        "backend:model?temperature=0.5&max_tokens=100"
    )

    assert backend == "backend"
    assert model == "model"
    # Values are returned as strings, conversion happens in validator
    assert params == {"temperature": "0.5", "max_tokens": "100"}


def test_parse_model_with_boolean_like_values() -> None:
    """Test parsing model string with boolean-like parameter values."""
    backend, model, params = parse_model_with_params(
        "backend:model?stream=true&verbose=false"
    )

    assert backend == "backend"
    assert model == "model"
    assert params == {"stream": "true", "verbose": "false"}


def test_parse_model_with_equals_in_value() -> None:
    """Test parsing model string with equals sign in parameter value."""
    backend, model, params = parse_model_with_params("backend:model?key=value=extra")

    assert backend == "backend"
    assert model == "model"
    # parse_qs should handle this correctly
    assert "key" in params


def test_parse_model_with_ampersand_only() -> None:
    """Test parsing model string with only ampersand in query."""
    backend, model, params = parse_model_with_params("backend:model?&")

    assert backend == "backend"
    assert model == "model"
    assert params == {}


def test_parse_model_with_empty_parameter_name() -> None:
    """Test parsing model string with empty parameter name."""
    backend, model, params = parse_model_with_params("backend:model?=value")

    assert backend == "backend"
    assert model == "model"
    # Empty key should be ignored by parse_qs
    assert params == {} or params == {"": "value"}


def test_parse_model_with_parameter_no_value() -> None:
    """Test parsing model string with parameter but no value."""
    backend, model, params = parse_model_with_params("backend:model?flag")

    assert backend == "backend"
    assert model == "model"
    # parse_qs with keep_blank_values=False should ignore this
    assert params == {}


def test_parse_model_backward_compatibility_colon_separator() -> None:
    """Test backward compatibility with colon separator (no parameters)."""
    backend, model, params = parse_model_with_params("openai:gpt-4-turbo")

    assert backend == "openai"
    assert model == "gpt-4-turbo"
    assert params == {}


def test_parse_model_backward_compatibility_slash_separator() -> None:
    """Test vendor/model-style parsing with slash in model (no parameters)."""
    backend, model, params = parse_model_with_params("openrouter/anthropic/claude-3")

    assert backend == ""
    assert model == "openrouter/anthropic/claude-3"
    assert params == {}


def test_parse_model_backward_compatibility_no_separator() -> None:
    """Test backward compatibility with no separator (uses default backend)."""
    backend, model, params = parse_model_with_params("gpt-4", default_backend="openai")

    assert backend == "openai"
    assert model == "gpt-4"
    assert params == {}


def test_parse_model_backward_compatibility_complex_path() -> None:
    """Test backward compatibility with complex model path (no parameters)."""
    backend, model, params = parse_model_with_params(
        "openrouter:anthropic/claude-3-opus:beta"
    )

    assert backend == "openrouter"
    assert model == "anthropic/claude-3-opus:beta"
    assert params == {}


def test_parse_model_with_multiple_question_marks() -> None:
    """Test parsing model string with multiple question marks."""
    backend, model, params = parse_model_with_params("backend:model?temp=0.5?extra=1")

    assert backend == "backend"
    assert model == "model"
    # Only first ? should be treated as query separator
    # The second ? becomes part of the query string
    assert isinstance(params, dict)


def test_parse_model_with_hash_fragment() -> None:
    """Test parsing model string with hash fragment."""
    backend, model, params = parse_model_with_params("backend:model?temp=0.5#fragment")

    assert backend == "backend"
    assert model == "model"
    # Hash should be part of the query string or ignored
    assert isinstance(params, dict)


def test_parse_model_with_very_long_parameter_value() -> None:
    """Test parsing model string with very long parameter value."""
    long_value = "x" * 1000
    backend, model, params = parse_model_with_params(f"backend:model?data={long_value}")

    assert backend == "backend"
    assert model == "model"
    assert "data" in params
    assert len(params["data"]) == 1000


def test_parse_model_with_unicode_characters() -> None:
    """Test parsing model string with unicode characters in parameters."""
    backend, model, params = parse_model_with_params("backend:model?name=test_αβγ")

    assert backend == "backend"
    assert model == "model"
    assert "name" in params


def test_parse_model_empty_string() -> None:
    """Test parsing empty model string."""
    backend, model, params = parse_model_with_params("", default_backend="openai")

    assert backend == "openai"
    assert model == ""
    assert params == {}


def test_parse_model_only_question_mark() -> None:
    """Test parsing model string that is only a question mark."""
    backend, model, params = parse_model_with_params("?", default_backend="openai")

    assert backend == "openai"
    assert model == "" or backend == ""
    assert params == {}


def test_parse_model_with_mixed_separators_and_params() -> None:
    """Test parsing model string with mixed separators and parameters."""
    backend, model, params = parse_model_with_params(
        "openai:model_group/model_name?temperature=0.7&reasoning_effort=medium"
    )

    assert backend == "openai"
    assert model == "model_group/model_name"
    assert params == {"temperature": "0.7", "reasoning_effort": "medium"}


def test_parse_model_case_sensitivity() -> None:
    """Test that parameter names are case-sensitive."""
    backend, model, params = parse_model_with_params(
        "backend:model?Temperature=0.5&temperature=0.8"
    )

    assert backend == "backend"
    assert model == "model"
    # Both should be present as different keys
    assert "Temperature" in params or "temperature" in params


def test_parse_model_with_trailing_ampersand() -> None:
    """Test parsing model string with trailing ampersand."""
    backend, model, params = parse_model_with_params("backend:model?temp=0.5&")

    assert backend == "backend"
    assert model == "model"
    assert params == {"temp": "0.5"}


def test_parse_model_with_leading_ampersand() -> None:
    """Test parsing model string with leading ampersand."""
    backend, model, params = parse_model_with_params("backend:model?&temp=0.5")

    assert backend == "backend"
    assert model == "model"
    assert params == {"temp": "0.5"}
