"""Unit tests for hybrid connector core functionality."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from src.connectors.hybrid import HybridConnector
from src.connectors.utils.model_capabilities import get_reasoning_tags
from src.core.common.exceptions import (
    BackendError,
    ConfigurationError,
    ServiceResolutionError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def app_config():
    """Create a basic app config for testing."""
    config = AppConfig()
    # Ensure hybrid backend is enabled by default
    if not hasattr(config, "backends"):
        from types import SimpleNamespace

        config.backends = SimpleNamespace(disable_hybrid_backend=False)
    else:
        config.backends.disable_hybrid_backend = False
    return config


@pytest.fixture
def hybrid_connector(app_config):
    """Create a hybrid connector instance for testing."""
    connector = HybridConnector(
        client=Mock(),
        config=app_config,
        translation_service=Mock(),
        backend_registry=Mock(),
    )
    return connector


class TestHybridModelSpecificationParsing:
    """Test hybrid model specification parsing (Task 8.1)."""

    def test_valid_format_basic(self, hybrid_connector):
        """Test valid format: hybrid:[backend:model,backend:model]."""
        model_spec = "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]"

        reasoning_backend, reasoning_model, execution_backend, execution_model = (
            hybrid_connector._parse_hybrid_model_spec(model_spec)
        )

        assert reasoning_backend == "openai"
        assert reasoning_model == "gpt-4"
        assert execution_backend == "openai"
        assert execution_model == "gpt-3.5-turbo"

    def test_valid_format_without_hybrid_prefix(self, hybrid_connector):
        """Test valid format without 'hybrid:' prefix."""
        model_spec = "[openai:gpt-4,anthropic:claude-3]"

        reasoning_backend, reasoning_model, execution_backend, execution_model = (
            hybrid_connector._parse_hybrid_model_spec(model_spec)
        )

        assert reasoning_backend == "openai"
        assert reasoning_model == "gpt-4"
        assert execution_backend == "anthropic"
        assert execution_model == "claude-3"

    def test_valid_example_minimax_qwen(self, hybrid_connector):
        """Test valid example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]."""
        model_spec = "hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"

        reasoning_backend, reasoning_model, execution_backend, execution_model = (
            hybrid_connector._parse_hybrid_model_spec(model_spec)
        )

        assert reasoning_backend == "minimax"
        assert reasoning_model == "MiniMax-M2"
        assert execution_backend == "qwen-oauth"
        assert execution_model == "qwen3-coder-plus"

    def test_valid_format_with_whitespace(self, hybrid_connector):
        """Test valid format with whitespace around components."""
        model_spec = "hybrid:[ openai : gpt-4 , anthropic : claude-3 ]"

        reasoning_backend, reasoning_model, execution_backend, execution_model = (
            hybrid_connector._parse_hybrid_model_spec(model_spec)
        )

        assert reasoning_backend == "openai"
        assert reasoning_model == "gpt-4"
        assert execution_backend == "anthropic"
        assert execution_model == "claude-3"

    def test_invalid_format_missing_brackets(self, hybrid_connector):
        """Test invalid format: missing brackets."""
        model_spec = "hybrid:openai:gpt-4,anthropic:claude-3"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Invalid hybrid model format" in str(exc_info.value)
        assert (
            "Expected: hybrid:[reasoning-backend:reasoning-model,execution-backend:execution-model]"
            in str(exc_info.value)
        )
        assert (
            "Example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"
            in str(exc_info.value)
        )

    def test_invalid_format_missing_opening_bracket(self, hybrid_connector):
        """Test invalid format: missing opening bracket."""
        model_spec = "hybrid:openai:gpt-4,anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Invalid hybrid model format" in str(exc_info.value)

    def test_invalid_format_missing_closing_bracket(self, hybrid_connector):
        """Test invalid format: missing closing bracket."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:claude-3"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Invalid hybrid model format" in str(exc_info.value)

    def test_invalid_format_missing_comma(self, hybrid_connector):
        """Test invalid format: missing comma separator."""
        model_spec = "hybrid:[openai:gpt-4 anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Should fail because it expects exactly 2 parts
        assert "Invalid" in str(exc_info.value)

    def test_invalid_format_extra_commas(self, hybrid_connector):
        """Test invalid format: extra commas."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:claude-3,extra:model]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Expected exactly 2 models separated by comma, got 3" in str(
            exc_info.value
        )

    def test_incomplete_spec_missing_reasoning_model(self, hybrid_connector):
        """Test incomplete spec: missing reasoning model."""
        model_spec = "hybrid:[openai:,anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Incomplete reasoning model specification" in str(exc_info.value)
        assert "Both backend and model must be non-empty" in str(exc_info.value)

    def test_incomplete_spec_missing_reasoning_backend(self, hybrid_connector):
        """Test incomplete spec: missing reasoning backend."""
        model_spec = "hybrid:[:gpt-4,anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Incomplete reasoning model specification" in str(exc_info.value)

    def test_incomplete_spec_missing_execution_model(self, hybrid_connector):
        """Test incomplete spec: missing execution model."""
        model_spec = "hybrid:[openai:gpt-4,anthropic:]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Incomplete execution model specification" in str(exc_info.value)

    def test_incomplete_spec_missing_execution_backend(self, hybrid_connector):
        """Test incomplete spec: missing execution backend."""
        model_spec = "hybrid:[openai:gpt-4,:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Incomplete execution model specification" in str(exc_info.value)

    def test_incomplete_spec_missing_colon_in_reasoning(self, hybrid_connector):
        """Test incomplete spec: missing colon in reasoning part."""
        model_spec = "hybrid:[openai-gpt-4,anthropic:claude-3]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Invalid reasoning model specification" in str(exc_info.value)
        assert "Expected format: backend:model" in str(exc_info.value)

    def test_incomplete_spec_missing_colon_in_execution(self, hybrid_connector):
        """Test incomplete spec: missing colon in execution part."""
        model_spec = "hybrid:[openai:gpt-4,anthropic-claude-3]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Invalid execution model specification" in str(exc_info.value)

    def test_edge_case_empty_string(self, hybrid_connector):
        """Test edge case: empty string."""
        model_spec = ""

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        assert "Invalid hybrid model format" in str(exc_info.value)

    def test_edge_case_only_brackets(self, hybrid_connector):
        """Test edge case: only brackets."""
        model_spec = "hybrid:[]"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        # Should fail when trying to split by comma
        assert "Invalid" in str(exc_info.value)

    def test_edge_case_special_characters_in_model_name(self, hybrid_connector):
        """Test edge case: special characters in model name."""
        model_spec = (
            "hybrid:[openai:gpt-4-turbo-preview,anthropic:claude-3-opus-20240229]"
        )

        reasoning_backend, reasoning_model, execution_backend, execution_model = (
            hybrid_connector._parse_hybrid_model_spec(model_spec)
        )

        assert reasoning_backend == "openai"
        assert reasoning_model == "gpt-4-turbo-preview"
        assert execution_backend == "anthropic"
        assert execution_model == "claude-3-opus-20240229"

    def test_error_message_includes_format_example(self, hybrid_connector):
        """Test that error messages include format examples."""
        model_spec = "invalid"

        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(model_spec)

        error_message = str(exc_info.value)
        assert (
            "Example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"
            in error_message
        )


class TestAdaptiveMessageAugmentation:
    """Test adaptive message augmentation (Task 8.2)."""

    def test_system_message_injection_for_openai(self, hybrid_connector):
        """Test system message injection for OpenAI (supports system messages)."""
        messages = [{"role": "user", "content": "Hello"}]
        reasoning_output = "This is my reasoning"

        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "openai"
        )

        # Should have system message at the beginning
        assert len(augmented) == 2
        assert augmented[0]["role"] == "system"
        assert "Consider this reasoning" in augmented[0]["content"]
        assert "<thinking>" in augmented[0]["content"]
        assert reasoning_output in augmented[0]["content"]
        assert "</thinking>" in augmented[0]["content"]

        # Original user message should be preserved
        assert augmented[1]["role"] == "user"
        assert augmented[1]["content"] == "Hello"

    def test_system_message_injection_for_anthropic(self, hybrid_connector):
        """Test system message injection for Anthropic (supports system messages)."""
        messages = [{"role": "user", "content": "Hello"}]
        reasoning_output = "This is my reasoning"

        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "anthropic"
        )

        # Should have system message at the beginning
        assert len(augmented) == 2
        assert augmented[0]["role"] == "system"
        assert reasoning_output in augmented[0]["content"]

    def test_user_message_prefix_injection_for_gemini(self, hybrid_connector):
        """Test user message prefix injection for Gemini (no system message support)."""
        messages = [{"role": "user", "content": "Hello"}]
        reasoning_output = "This is my reasoning"

        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "gemini"
        )

        # Should still have 1 message (user message modified)
        assert len(augmented) == 1
        assert augmented[0]["role"] == "user"

        # Reasoning should be prepended to user message
        assert "<reasoning>" in augmented[0]["content"]
        assert reasoning_output in augmented[0]["content"]
        assert "</reasoning>" in augmented[0]["content"]
        assert "Hello" in augmented[0]["content"]

        # Reasoning should come before original content
        content = augmented[0]["content"]
        reasoning_index = content.index(reasoning_output)
        hello_index = content.index("Hello")
        assert reasoning_index < hello_index

    def test_model_capability_detection_openai(self, hybrid_connector):
        """Test model capability detection for OpenAI."""
        assert hybrid_connector._supports_system_messages("openai") is True

    def test_model_capability_detection_anthropic(self, hybrid_connector):
        """Test model capability detection for Anthropic."""
        assert hybrid_connector._supports_system_messages("anthropic") is True

    def test_model_capability_detection_gemini(self, hybrid_connector):
        """Test model capability detection for Gemini."""
        assert hybrid_connector._supports_system_messages("gemini") is False

    def test_model_capability_detection_unknown_backend(self, hybrid_connector):
        """Test model capability detection for unknown backend (defaults to True)."""
        assert hybrid_connector._supports_system_messages("unknown-backend") is True

    def test_reasoning_format_adaptation_thinking_tags(self, hybrid_connector):
        """Test reasoning format adaptation: thinking tags for OpenAI."""
        reasoning_output = "My reasoning"
        formatted = hybrid_connector._format_reasoning_for_model(
            reasoning_output, "openai"
        )

        assert formatted.startswith("<thinking>")
        assert formatted.endswith("</thinking>")
        assert reasoning_output in formatted

    def test_reasoning_format_adaptation_think_tags_deepseek(self, hybrid_connector):
        """Test reasoning format adaptation: think tags for DeepSeek."""
        reasoning_output = "My reasoning"
        formatted = hybrid_connector._format_reasoning_for_model(
            reasoning_output, "deepseek"
        )

        assert formatted.startswith("<think>")
        assert formatted.endswith("</think>")
        assert reasoning_output in formatted

    def test_reasoning_format_adaptation_reasoning_tags_default(self, hybrid_connector):
        """Test reasoning format adaptation: reasoning tags for unknown backend."""
        reasoning_output = "My reasoning"
        formatted = hybrid_connector._format_reasoning_for_model(
            reasoning_output, "unknown"
        )

        assert formatted.startswith("<reasoning>")
        assert formatted.endswith("</reasoning>")
        assert reasoning_output in formatted

    def test_handling_existing_system_message_augment(self, hybrid_connector):
        """Test handling of existing system messages (augment existing)."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        reasoning_output = "This is my reasoning"

        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "openai"
        )

        # Should still have 2 messages
        assert len(augmented) == 2

        # System message should be augmented, not replaced
        assert augmented[0]["role"] == "system"
        assert "You are a helpful assistant" in augmented[0]["content"]
        assert "Consider this reasoning" in augmented[0]["content"]
        assert reasoning_output in augmented[0]["content"]

    def test_handling_existing_system_message_create_new(self, hybrid_connector):
        """Test creating new system message when none exists."""
        messages = [{"role": "user", "content": "Hello"}]
        reasoning_output = "This is my reasoning"

        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "openai"
        )

        # Should have new system message
        assert len(augmented) == 2
        assert augmented[0]["role"] == "system"

    def test_empty_message_list_handling(self, hybrid_connector):
        """Test handling of empty message list."""
        messages = []
        reasoning_output = "This is my reasoning"

        # Should handle gracefully and return empty list
        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "openai"
        )

        assert augmented == []

    def test_messages_with_no_user_messages(self, hybrid_connector):
        """Test messages with no user messages (only system/assistant)."""
        messages = [
            {"role": "system", "content": "System message"},
            {"role": "assistant", "content": "Assistant message"},
        ]
        reasoning_output = "This is my reasoning"

        # For system message support: should augment system message
        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "openai"
        )

        assert len(augmented) == 2
        assert augmented[0]["role"] == "system"
        assert reasoning_output in augmented[0]["content"]

    def test_messages_with_no_user_messages_gemini(self, hybrid_connector):
        """Test messages with no user messages for Gemini (no system support)."""
        messages = [{"role": "assistant", "content": "Assistant message"}]
        reasoning_output = "This is my reasoning"

        # For no system message support: should try to inject to user message
        # but if no user message exists, should return original messages
        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "gemini"
        )

        # Should return messages unchanged since no user message to inject into
        assert len(augmented) == 1
        assert augmented[0]["role"] == "assistant"

    def test_message_deep_copy_no_mutation(self, hybrid_connector):
        """Test that original messages are not mutated."""
        messages = [{"role": "user", "content": "Hello"}]
        original_content = messages[0]["content"]
        reasoning_output = "This is my reasoning"

        augmented = hybrid_connector._augment_messages(
            messages, reasoning_output, "openai"
        )

        # Original messages should not be modified
        assert messages[0]["content"] == original_content
        assert len(messages) == 1

        # Augmented messages should contain the reasoning
        assert len(augmented) > len(messages)


class TestReasoningExposure:
    """Tests for exposing reasoning output to clients."""

    def test_truncate_after_reasoning_close(self, hybrid_connector):
        raw_output = "<think>Plan</think>Final answer"

        truncated = hybrid_connector._truncate_after_reasoning_close(raw_output)

        assert truncated == "<think>Plan</think>"

    def test_format_reasoning_for_client_wraps_missing_tags(self, hybrid_connector):
        formatted = hybrid_connector._format_reasoning_for_client(
            "Consider alternatives", "minimax"
        )

        opening_tag, closing_tag = get_reasoning_tags("minimax")

        assert formatted.startswith(opening_tag)
        assert formatted.endswith(closing_tag)
        assert "Consider alternatives" in formatted

    def test_build_reasoning_stream_chunk_contains_metadata(self, hybrid_connector):
        chunk = hybrid_connector._build_reasoning_stream_chunk(
            "<think>Plan</think>", "minimax", "MiniMax-M2"
        )

        assert chunk is not None
        assert chunk.metadata == {
            "hybrid_phase": "reasoning",
            "reasoning_backend": "minimax",
            "reasoning_model": "MiniMax-M2",
        }
        assert isinstance(chunk.content, str)
        assert "MiniMax-M2" in chunk.content
        assert "<think>Plan</think>" in chunk.content

    @pytest.mark.asyncio
    async def test_prepend_reasoning_chunk_to_stream(self, hybrid_connector):
        async def original_stream():
            yield ProcessedResponse(
                content='data: {"choices": [{"delta": {"content": "Result"}}]}\n\n'
            )

        envelope = StreamingResponseEnvelope(content=original_stream())

        combined = hybrid_connector._prepend_reasoning_chunk_to_stream(
            envelope,
            "<think>Plan</think>",
            "minimax",
            "MiniMax-M2",
        )

        assert combined.content is not None

        chunks: list[ProcessedResponse] = []
        async for chunk in combined.content:
            chunks.append(chunk)
            if len(chunks) >= 2:
                break

        assert chunks
        assert "<think>Plan</think>" in str(chunks[0].content)
        assert any("Result" in str(chunk.content) for chunk in chunks[1:])

    def test_prepend_reasoning_to_non_streaming_text(self, hybrid_connector):
        combined = hybrid_connector._prepend_reasoning_to_non_streaming_content(
            "Final response.",
            "<think>Plan</think>",
            "minimax",
            "MiniMax-M2",
        )

        opening_tag, _ = get_reasoning_tags("minimax")

        assert combined.startswith(opening_tag)
        assert "Final response." in combined
        assert "<think>Plan</think>" in combined


class TestIdentityResolution:
    """Tests for backend identity resolution logic."""

    def test_backend_identity_preferred(self, hybrid_connector):
        from types import SimpleNamespace

        backend_identity = MagicMock(spec=IAppIdentityConfig)
        request_identity = MagicMock(spec=IAppIdentityConfig)

        resolved = hybrid_connector._resolve_backend_identity(
            "minimax",
            request_identity,
            SimpleNamespace(identity=backend_identity),
        )

        assert resolved is backend_identity

    def test_request_identity_fallback(self, hybrid_connector):
        from types import SimpleNamespace

        request_identity = MagicMock(spec=IAppIdentityConfig)

        resolved = hybrid_connector._resolve_backend_identity(
            "minimax",
            request_identity,
            SimpleNamespace(identity=None),
        )

        assert resolved is request_identity

    def test_app_identity_fallback(self, hybrid_connector):
        app_identity = hybrid_connector.config.identity

        resolved = hybrid_connector._resolve_backend_identity(
            "minimax",
            None,
            None,
        )

        assert resolved is app_identity


class TestReasoningParameterOverrides:
    """Test reasoning parameter overrides (Task 8.3)."""

    def test_reasoning_phase_high_effort_openai(self, hybrid_connector):
        """Test reasoning phase gets high reasoning effort for OpenAI."""
        request_data = {"model": "gpt-4", "temperature": 0.5}

        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "openai", enable_reasoning=True
        )

        assert overridden["reasoning_effort"] == "high"
        # Original data should not be mutated
        assert "reasoning_effort" not in request_data

    def test_reasoning_phase_high_thinking_budget_qwen(self, hybrid_connector):
        """Test reasoning phase gets high thinking budget for Qwen."""
        request_data = {"model": "qwen-model"}

        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "qwen", enable_reasoning=True
        )

        assert overridden["thinking_budget"] == 10000

    def test_execution_phase_low_effort_openai(self, hybrid_connector):
        """Test execution phase gets low reasoning effort for OpenAI."""
        request_data = {"model": "gpt-4"}

        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "openai", enable_reasoning=False
        )

        assert overridden["reasoning_effort"] == "low"

    def test_execution_phase_disabled_thinking_qwen(self, hybrid_connector):
        """Test execution phase gets disabled thinking for Qwen."""
        request_data = {"model": "qwen-model"}

        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "qwen", enable_reasoning=False
        )

        assert overridden["thinking_budget"] == 0

    def test_backend_specific_parameter_names_reasoning_effort(self, hybrid_connector):
        """Test backend-specific parameter names: reasoning_effort."""
        request_data = {}

        # OpenAI uses reasoning_effort
        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "openai", enable_reasoning=True
        )
        assert "reasoning_effort" in overridden

        # DeepSeek also uses reasoning_effort
        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "deepseek", enable_reasoning=True
        )
        assert "reasoning_effort" in overridden

    def test_backend_specific_parameter_names_thinking_budget(self, hybrid_connector):
        """Test backend-specific parameter names: thinking_budget."""
        request_data = {}

        # Qwen uses thinking_budget
        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "qwen", enable_reasoning=True
        )
        assert "thinking_budget" in overridden

        # Qwen-oauth also uses thinking_budget
        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "qwen-oauth", enable_reasoning=True
        )
        assert "thinking_budget" in overridden

    def test_default_parameters_for_unknown_backend(self, hybrid_connector):
        """Test default parameters for unknown backend."""
        request_data = {}

        # Unknown backend should get default parameters
        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "unknown-backend", enable_reasoning=True
        )

        # Default reasoning phase has temperature
        assert "temperature" in overridden

    def test_parameter_override_preserves_other_params(self, hybrid_connector):
        """Test that parameter override preserves other parameters."""
        request_data = {
            "model": "gpt-4",
            "temperature": 0.8,
            "max_tokens": 1000,
            "stream": True,
        }

        overridden = hybrid_connector._apply_reasoning_params(
            request_data, "openai", enable_reasoning=True
        )

        # Should preserve other parameters
        assert overridden["model"] == "gpt-4"
        assert overridden["max_tokens"] == 1000
        assert overridden["stream"] is True

        # Should add reasoning_effort
        assert overridden["reasoning_effort"] == "high"

    @patch("src.connectors.hybrid.logger")
    def test_parameter_override_logging(self, mock_logger, hybrid_connector):
        """Test parameter override logging."""
        request_data = {"reasoning_effort": "medium"}

        hybrid_connector._apply_reasoning_params(
            request_data, "openai", enable_reasoning=True
        )

        # Should log the override
        mock_logger.debug.assert_called()
        call_args = str(mock_logger.debug.call_args)
        assert "reasoning_effort" in call_args


class TestErrorHandling:
    """Test error handling (Task 8.4)."""

    def test_disabled_hybrid_backend_error(self, app_config):
        """Test disabled hybrid backend error."""
        # Configure backend as disabled
        app_config.backends.disable_hybrid_backend = True

        connector = HybridConnector(
            client=Mock(),
            config=app_config,
            translation_service=Mock(),
            backend_registry=Mock(),
        )

        # Attempt to call chat_completions
        with pytest.raises(ConfigurationError) as exc_info:
            # Use asyncio to run the async method
            import asyncio

            asyncio.run(
                connector.chat_completions(
                    request_data={"model": "hybrid:[openai:gpt-4,openai:gpt-3.5]"},
                    processed_messages=[{"role": "user", "content": "test"}],
                    effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5]",
                )
            )

        assert "Hybrid backend is disabled" in str(exc_info.value)

    def test_invalid_model_specification_error(self, hybrid_connector):
        """Test invalid model specification error."""
        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec("invalid-format")

        assert "Invalid hybrid model format" in str(exc_info.value)

    def test_incomplete_model_specification_error(self, hybrid_connector):
        """Test incomplete model specification error."""
        with pytest.raises(ValueError) as exc_info:
            hybrid_connector._parse_hybrid_model_spec(
                "hybrid:[openai:,anthropic:claude]"
            )

        assert "Incomplete" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_reasoning_phase_api_failure(self, hybrid_connector):
        """Test reasoning phase API failure."""
        # Mock backend registry to return a failing connector
        mock_backend = AsyncMock()
        mock_backend.initialize = AsyncMock()
        mock_backend.chat_completions = AsyncMock(side_effect=Exception("API Error"))

        mock_factory = Mock(return_value=mock_backend)
        hybrid_connector._backend_registry.get_backend_factory = Mock(
            return_value=mock_factory
        )

        with pytest.raises(BackendError) as exc_info:
            await hybrid_connector._execute_reasoning_phase(
                messages=[{"role": "user", "content": "test"}],
                reasoning_backend="openai",
                reasoning_model="gpt-4",
                request_data={"model": "gpt-4"},
                identity=None,
            )

        assert "reasoning" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execution_phase_api_failure(self, hybrid_connector):
        """Test execution phase API failure."""
        # Mock backend registry to return a failing connector
        mock_backend = AsyncMock()
        mock_backend.initialize = AsyncMock()
        mock_backend.chat_completions = AsyncMock(side_effect=Exception("API Error"))

        mock_factory = Mock(return_value=mock_backend)
        hybrid_connector._backend_registry.get_backend_factory = Mock(
            return_value=mock_factory
        )

        with pytest.raises(BackendError) as exc_info:
            await hybrid_connector._execute_execution_phase(
                request_data={"model": "gpt-4"},
                augmented_messages=[{"role": "user", "content": "test"}],
                execution_backend="openai",
                execution_model="gpt-4",
                identity=None,
            )

        assert "execution" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_timeout_scenario_reasoning_phase(self, hybrid_connector):
        """Test timeout scenario in reasoning phase."""
        import asyncio

        # Mock backend that takes too long
        mock_backend = AsyncMock()
        mock_backend.initialize = AsyncMock()

        async def slow_completion(*args, **kwargs):
            await asyncio.sleep(100)  # Longer than timeout
            return Mock()

        mock_backend.chat_completions = slow_completion

        mock_factory = Mock(return_value=mock_backend)
        hybrid_connector._backend_registry.get_backend_factory = Mock(
            return_value=mock_factory
        )

        with pytest.raises(BackendError) as exc_info:
            await hybrid_connector._execute_reasoning_phase(
                messages=[{"role": "user", "content": "test"}],
                reasoning_backend="openai",
                reasoning_model="gpt-4",
                request_data={"model": "gpt-4"},
                identity=None,
            )

        error_message = str(exc_info.value)
        assert (
            "timeout" in error_message.lower() or "reasoning" in error_message.lower()
        )

    def test_backend_not_found_error(self, hybrid_connector):
        """Test backend not found error."""
        with patch(
            "src.core.di.services.get_required_service",
            side_effect=ServiceResolutionError(
                "No service registered for BackendFactory",
                service_name="BackendFactory",
            ),
        ):
            import asyncio

            with pytest.raises(BackendError) as exc_info:
                asyncio.run(
                    hybrid_connector._execute_reasoning_phase(
                        messages=[{"role": "user", "content": "test"}],
                        reasoning_backend="nonexistent",
                        reasoning_model="model",
                        request_data={"model": "model"},
                        identity=None,
                    )
                )

        assert exc_info.value.code == "reasoning_backend_init_failed"
        assert "failed to initialize reasoning backend" in str(exc_info.value).lower()
