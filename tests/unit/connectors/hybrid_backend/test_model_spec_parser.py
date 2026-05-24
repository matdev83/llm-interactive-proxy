"""Unit tests for ModelSpecParser service.

Tests cover parsing of hybrid model specification strings in the format:
hybrid:[reasoning-backend:reasoning-model?params,execution-backend:execution-model?params]

Requirements satisfied:
- Req 2.1: ModelSpecParser extraction
- Req 11: Test-preserving migration
"""

import pytest
from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec
from src.connectors.hybrid_backend.protocols import IModelSpecParser


class TestModelSpecParser:
    """Test ModelSpecParser service implementation."""

    @pytest.fixture
    def parser(self):
        """Create a ModelSpecParser instance for testing."""
        from src.connectors.hybrid_backend.services.model_spec_parser import (
            ModelSpecParser,
        )

        return ModelSpecParser()

    def test_parser_implements_protocol(self, parser):
        """Verify parser implements IModelSpecParser protocol."""
        assert isinstance(parser, IModelSpecParser)

    def test_valid_format_basic(self, parser):
        """Test valid format: hybrid:[backend:model,backend:model]."""
        model_spec = "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]"

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "openai"
        assert spec.execution_model == "gpt-3.5-turbo"
        assert spec.execution_params == {}

    def test_valid_format_without_hybrid_prefix(self, parser):
        """Test valid format without 'hybrid:' prefix."""
        model_spec = "[openai:gpt-4,anthropic:claude-3]"

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"
        assert spec.execution_params == {}

    def test_valid_example_minimax_qwen(self, parser):
        """Test valid example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]."""
        model_spec = "hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "minimax"
        assert spec.reasoning_model == "MiniMax-M2"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "qwen-oauth"
        assert spec.execution_model == "qwen3-coder-plus"
        assert spec.execution_params == {}

    def test_valid_format_with_whitespace(self, parser):
        """Test valid format with whitespace around components."""
        model_spec = "hybrid:[ openai : gpt-4 , anthropic : claude-3 ]"

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.reasoning_params == {}
        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"
        assert spec.execution_params == {}

    def test_valid_format_with_uri_params(self, parser):
        """Test valid format with URI parameters."""
        model_spec = (
            "hybrid:[minimax:MiniMax-M2?temperature=0.8,"
            "qwen-oauth:qwen3-coder-plus?temperature=0.3]"
        )

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "minimax"
        assert spec.reasoning_model == "MiniMax-M2"
        assert spec.reasoning_params == {"temperature": "0.8"}
        assert spec.execution_backend == "qwen-oauth"
        assert spec.execution_model == "qwen3-coder-plus"
        assert spec.execution_params == {"temperature": "0.3"}

    def test_valid_format_with_multiple_uri_params(self, parser):
        """Test valid format with multiple URI parameters."""
        model_spec = (
            "hybrid:[openai:gpt-4?temperature=0.7&max_tokens=1000,"
            "anthropic:claude-3?temperature=0.5&max_tokens=2000]"
        )

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.reasoning_params["temperature"] == "0.7"
        assert spec.reasoning_params["max_tokens"] == "1000"
        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"
        assert spec.execution_params["temperature"] == "0.5"
        assert spec.execution_params["max_tokens"] == "2000"

    def test_valid_format_with_url_encoded_params(self, parser):
        """Test valid format with URL-encoded parameters."""
        model_spec = (
            "hybrid:[openai:gpt-4?param1=value%20with%20spaces,"
            "anthropic:claude-3?param2=value%2Bplus]"
        )

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        # URL decoding is handled by parse_model_with_params
        assert "param1" in spec.reasoning_params
        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"
        assert "param2" in spec.execution_params

    def test_valid_format_with_special_characters_in_model_name(self, parser):
        """Test valid format with special characters in model names."""
        model_spec = (
            "hybrid:[openai:gpt-4-turbo-preview,anthropic:claude-3-opus-20240229]"
        )

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4-turbo-preview"
        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3-opus-20240229"

    def test_invalid_format_missing_brackets(self, parser):
        """Test invalid format: missing brackets."""
        model_spec = "hybrid:openai:gpt-4,anthropic:claude-3"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Invalid hybrid model format" in str(exc_info.value)
        assert (
            "Expected: hybrid:[reasoning-backend:reasoning-model,execution-backend:execution-model]"
            in str(exc_info.value)
        )

    def test_invalid_format_missing_opening_bracket(self, parser):
        """Test invalid format: missing opening bracket."""
        model_spec = "hybrid:openai:gpt-4,anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Invalid hybrid model format" in str(exc_info.value)

    def test_invalid_format_missing_closing_bracket(self, parser):
        """Test invalid format: missing closing bracket."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:claude-3"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Invalid hybrid model format" in str(exc_info.value)

    def test_invalid_format_empty_string(self, parser):
        """Test invalid format: empty string."""
        model_spec = ""

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Invalid hybrid model format" in str(exc_info.value)

    def test_invalid_format_single_model(self, parser):
        """Test invalid format: only one model specified."""
        model_spec = "hybrid:[openai:gpt-4]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Expected exactly 2 models" in str(exc_info.value)
        assert "got 1" in str(exc_info.value)

    def test_invalid_format_three_models(self, parser):
        """Test invalid format: three models specified."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:claude-3,openai:gpt-3.5-turbo]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Expected exactly 2 models" in str(exc_info.value)
        assert "got 3" in str(exc_info.value)

    def test_invalid_format_missing_colon(self, parser):
        """Test invalid format: missing colon in reasoning model."""
        model_spec = "hybrid:[openai,anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        # When missing colon, the splitter doesn't find 2 parts
        assert "Invalid hybrid model format" in str(exc_info.value)
        assert "Expected exactly 2 models" in str(exc_info.value)

    def test_invalid_format_missing_execution_colon(self, parser):
        """Test invalid format: missing colon in execution model."""
        model_spec = "hybrid:[openai:gpt-4,anthropic]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        # When missing colon in execution, parse_model_with_params returns empty model
        assert "Incomplete execution model specification" in str(exc_info.value)

    def test_invalid_format_empty_reasoning_backend(self, parser):
        """Test invalid format: empty reasoning backend."""
        model_spec = "hybrid:[:gpt-4,anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Incomplete reasoning model specification" in str(exc_info.value)

    def test_invalid_format_empty_reasoning_model(self, parser):
        """Test invalid format: empty reasoning model."""
        model_spec = "hybrid:[openai:,anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Incomplete reasoning model specification" in str(exc_info.value)

    def test_invalid_format_empty_execution_backend(self, parser):
        """Test invalid format: empty execution backend."""
        model_spec = "hybrid:[openai:gpt-4,:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Incomplete execution model specification" in str(exc_info.value)

    def test_invalid_format_empty_execution_model(self, parser):
        """Test invalid format: empty execution model."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:]"

        with pytest.raises(ValueError) as exc_info:
            parser.parse(model_spec)

        assert "Incomplete execution model specification" in str(exc_info.value)

    def test_invalid_format_malformed_uri_params(self, parser):
        """Test invalid format: malformed URI parameters."""
        model_spec = "hybrid:[openai:gpt-4?invalid=,anthropic:claude-3]"

        # This might pass parsing but params will be empty or malformed
        # The exact behavior depends on parse_model_with_params implementation
        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"

    def test_comma_in_uri_params_preserved(self, parser):
        """Test that commas in URI parameters don't split models incorrectly."""
        model_spec = (
            "hybrid:[openai:gpt-4?param=value1,value2," "anthropic:claude-3?other=test]"
        )

        spec = parser.parse(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"

    def test_return_type_is_hybrid_model_spec(self, parser):
        """Test that parse returns HybridModelSpec instance."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:claude-3]"

        spec = parser.parse(model_spec)

        assert isinstance(spec, HybridModelSpec)

    def test_spec_is_frozen(self, parser):
        """Test that returned HybridModelSpec is frozen (immutable)."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:claude-3]"

        spec = parser.parse(model_spec)

        # Attempting to modify should raise FrozenInstanceError
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            spec.reasoning_backend = "modified"
