"""
Tests for Reasoning Command Handlers.

This module tests the reasoning-related command handlers including
reasoning effort, thinking budget, and Gemini configuration.
"""

import json
from unittest.mock import Mock

import pytest
from src.core.commands.handlers.base_handler import CommandHandlerResult
from src.core.commands.handlers.reasoning_handlers import (
    GeminiGenerationConfigHandler,
    ReasoningEffortHandler,
    ThinkingBudgetHandler,
)
from src.core.interfaces.domain_entities_interface import ISessionState


class TestReasoningEffortHandler:
    """Tests for ReasoningEffortHandler class."""

    @pytest.fixture
    def handler(self) -> ReasoningEffortHandler:
        """Create a ReasoningEffortHandler instance."""
        return ReasoningEffortHandler()

    @pytest.fixture
    def mock_state(self) -> ISessionState:
        """Create a mock session state."""
        state = Mock(spec=ISessionState)
        state.reasoning_config = Mock()
        state.with_reasoning_config = Mock(return_value=state)
        return state

    def test_handler_properties(self, handler: ReasoningEffortHandler) -> None:
        """Test handler properties."""
        assert handler.name == "reasoning-effort"
        assert handler.aliases == ["reasoning_effort", "reasoning"]
        assert handler.description == "Set the reasoning effort level (low, medium, high, maximum)"
        assert handler.examples == [
            "!/set(reasoning-effort=low)",
            "!/set(reasoning-effort=medium)",
            "!/set(reasoning-effort=high)",
            "!/set(reasoning-effort=maximum)",
        ]

    def test_can_handle_reasoning_effort_variations(self, handler: ReasoningEffortHandler) -> None:
        """Test can_handle with various reasoning effort parameter names."""
        # Exact matches
        assert handler.can_handle("reasoning-effort") is True
        assert handler.can_handle("reasoning_effort") is True
        assert handler.can_handle("reasoning effort") is True

        # Alias matches
        assert handler.can_handle("reasoning") is True

        # Case insensitive
        assert handler.can_handle("REASONING-EFFORT") is True
        assert handler.can_handle("Reasoning-Effort") is True

        # No matches
        assert handler.can_handle("effort") is False
        assert handler.can_handle("reasoning-effort-level") is False
        assert handler.can_handle("other") is False

    @pytest.mark.asyncio
    async def test_handle_with_valid_effort_level(
        self, handler: ReasoningEffortHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with valid reasoning effort level."""
        mock_state.reasoning_config.with_reasoning_effort = Mock(return_value=mock_state.reasoning_config)

        result = handler.handle("high", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == "Reasoning effort set to high"
        assert result.new_state is mock_state

        # Verify the reasoning config was updated
        mock_state.reasoning_config.with_reasoning_effort.assert_called_once_with("high")
        mock_state.with_reasoning_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_with_invalid_effort_level(
        self, handler: ReasoningEffortHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with invalid reasoning effort level."""
        result = handler.handle("invalid", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Invalid reasoning effort: invalid. Use low, medium, high, or maximum."
        assert result.new_state is None

        # Verify the state was not updated
        mock_state.reasoning_config.with_reasoning_effort.assert_not_called()
        mock_state.with_reasoning_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_with_none_value(
        self, handler: ReasoningEffortHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with None value."""
        result = handler.handle(None, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Reasoning effort level must be specified"
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_empty_string(
        self, handler: ReasoningEffortHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with empty string."""
        result = handler.handle("", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Reasoning effort level must be specified"
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_all_valid_effort_levels(
        self, handler: ReasoningEffortHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with all valid reasoning effort levels."""
        valid_levels = ["low", "medium", "high", "maximum"]

        for level in valid_levels:
            mock_state.reasoning_config.with_reasoning_effort = Mock(return_value=mock_state.reasoning_config)
            mock_state.with_reasoning_config = Mock(return_value=mock_state)

            result = handler.handle(level, mock_state)

            assert isinstance(result, CommandHandlerResult)
            assert result.success is True
            assert result.message == f"Reasoning effort set to {level}"
            assert result.new_state is mock_state

    @pytest.mark.asyncio
    async def test_handle_with_case_insensitive_effort_levels(
        self, handler: ReasoningEffortHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with case insensitive effort levels."""
        mock_state.reasoning_config.with_reasoning_effort = Mock(return_value=mock_state.reasoning_config)

        result = handler.handle("HIGH", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == "Reasoning effort set to high"
        assert result.new_state is mock_state


class TestThinkingBudgetHandler:
    """Tests for ThinkingBudgetHandler class."""

    @pytest.fixture
    def handler(self) -> ThinkingBudgetHandler:
        """Create a ThinkingBudgetHandler instance."""
        return ThinkingBudgetHandler()

    @pytest.fixture
    def mock_state(self) -> ISessionState:
        """Create a mock session state."""
        state = Mock(spec=ISessionState)
        state.reasoning_config = Mock()
        state.with_reasoning_config = Mock(return_value=state)
        return state

    def test_handler_properties(self, handler: ThinkingBudgetHandler) -> None:
        """Test handler properties."""
        assert handler.name == "thinking-budget"
        assert handler.aliases == ["thinking_budget", "budget"]
        assert handler.description == "Set the thinking budget in tokens (128-32768)"
        assert handler.examples == ["!/set(thinking-budget=1024)", "!/set(thinking-budget=2048)"]

    def test_can_handle_thinking_budget_variations(self, handler: ThinkingBudgetHandler) -> None:
        """Test can_handle with various thinking budget parameter names."""
        # Exact matches
        assert handler.can_handle("thinking-budget") is True
        assert handler.can_handle("thinking_budget") is True
        assert handler.can_handle("thinking budget") is True

        # Alias matches
        assert handler.can_handle("budget") is True

        # Case insensitive
        assert handler.can_handle("THINKING-BUDGET") is True
        assert handler.can_handle("Thinking-Budget") is True

        # No matches
        assert handler.can_handle("thinking") is False  # Partial match doesn't work
        assert handler.can_handle("budget-limit") is False
        assert handler.can_handle("other") is False

    @pytest.mark.asyncio
    async def test_handle_with_valid_budget(
        self, handler: ThinkingBudgetHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with valid thinking budget."""
        mock_state.reasoning_config.with_thinking_budget = Mock(return_value=mock_state.reasoning_config)

        result = handler.handle("1024", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == "Thinking budget set to 1024"
        assert result.new_state is mock_state

        # Verify the reasoning config was updated
        mock_state.reasoning_config.with_thinking_budget.assert_called_once_with(1024)
        mock_state.with_reasoning_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_with_boundary_values(
        self, handler: ThinkingBudgetHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with boundary values."""
        mock_state.reasoning_config.with_thinking_budget = Mock(return_value=mock_state.reasoning_config)

        # Test minimum valid value
        result = handler.handle("128", mock_state)
        assert result.success is True
        assert result.message == "Thinking budget set to 128"

        # Test maximum valid value
        result = handler.handle("32768", mock_state)
        assert result.success is True
        assert result.message == "Thinking budget set to 32768"

    @pytest.mark.asyncio
    async def test_handle_with_invalid_budget_too_low(
        self, handler: ThinkingBudgetHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with budget too low."""
        result = handler.handle("127", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Thinking budget must be between 128 and 32768 tokens"
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_invalid_budget_too_high(
        self, handler: ThinkingBudgetHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with budget too high."""
        result = handler.handle("32769", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Thinking budget must be between 128 and 32768 tokens"
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_invalid_number_format(
        self, handler: ThinkingBudgetHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with invalid number format."""
        result = handler.handle("not-a-number", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Invalid thinking budget: not-a-number. Must be an integer."
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_none_value(
        self, handler: ThinkingBudgetHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with None value."""
        result = handler.handle(None, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Thinking budget must be specified"
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_empty_string(
        self, handler: ThinkingBudgetHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with empty string."""
        result = handler.handle("", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Thinking budget must be specified"
        assert result.new_state is None


class TestGeminiGenerationConfigHandler:
    """Tests for GeminiGenerationConfigHandler class."""

    @pytest.fixture
    def handler(self) -> GeminiGenerationConfigHandler:
        """Create a GeminiGenerationConfigHandler instance."""
        return GeminiGenerationConfigHandler()

    @pytest.fixture
    def mock_state(self) -> ISessionState:
        """Create a mock session state."""
        state = Mock(spec=ISessionState)
        state.reasoning_config = Mock()
        state.with_reasoning_config = Mock(return_value=state)
        return state

    def test_handler_properties(self, handler: GeminiGenerationConfigHandler) -> None:
        """Test handler properties."""
        assert handler.name == "gemini-generation-config"
        assert handler.aliases == ["gemini_generation_config", "gemini_config"]
        assert handler.description == "Set the Gemini generation config as a JSON object"
        assert handler.examples == [
            "!/set(gemini-generation-config={'thinkingConfig': {'thinkingBudget': 1024}})"
        ]

    def test_can_handle_gemini_config_variations(self, handler: GeminiGenerationConfigHandler) -> None:
        """Test can_handle with various Gemini config parameter names."""
        # Exact matches
        assert handler.can_handle("gemini-generation-config") is True
        assert handler.can_handle("gemini_generation_config") is True
        assert handler.can_handle("gemini generation config") is True

        # Alias matches
        assert handler.can_handle("gemini_config") is False  # Uses underscore, not dash

        # Case insensitive
        assert handler.can_handle("GEMINI-GENERATION-CONFIG") is True
        assert handler.can_handle("Gemini-Generation-Config") is True

        # No matches
        assert handler.can_handle("gemini") is False
        assert handler.can_handle("generation-config") is False
        assert handler.can_handle("other") is False

    @pytest.mark.asyncio
    async def test_handle_with_valid_json_string(
        self, handler: GeminiGenerationConfigHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with valid JSON string."""
        config_json = '{"thinkingConfig": {"thinkingBudget": 1024}}'
        mock_state.reasoning_config.with_gemini_generation_config = Mock(return_value=mock_state.reasoning_config)

        result = handler.handle(config_json, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == f"Gemini generation config set to {json.loads(config_json)}"
        assert result.new_state is mock_state

        # Verify the reasoning config was updated
        expected_config = {"thinkingConfig": {"thinkingBudget": 1024}}
        mock_state.reasoning_config.with_gemini_generation_config.assert_called_once_with(expected_config)
        mock_state.with_reasoning_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_with_valid_dict(
        self, handler: GeminiGenerationConfigHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with valid dictionary."""
        config_dict = {"thinkingConfig": {"thinkingBudget": 1024}}
        mock_state.reasoning_config.with_gemini_generation_config = Mock(return_value=mock_state.reasoning_config)

        result = handler.handle(config_dict, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == f"Gemini generation config set to {config_dict}"
        assert result.new_state is mock_state

        # Verify the reasoning config was updated
        mock_state.reasoning_config.with_gemini_generation_config.assert_called_once_with(config_dict)

    @pytest.mark.asyncio
    async def test_handle_with_invalid_json_string(
        self, handler: GeminiGenerationConfigHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with invalid JSON string."""
        invalid_json = '{"thinkingConfig": {"thinkingBudget": 1024'  # Missing closing brace

        result = handler.handle(invalid_json, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert "Invalid JSON:" in result.message
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_non_dict_json(
        self, handler: GeminiGenerationConfigHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with JSON that doesn't parse to a dictionary."""
        json_string = '["not", "a", "dict"]'

        result = handler.handle(json_string, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Invalid Gemini generation config: must be a JSON object"
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_none_value(
        self, handler: GeminiGenerationConfigHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with None value."""
        result = handler.handle(None, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Gemini generation config must be specified"
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_empty_string(
        self, handler: GeminiGenerationConfigHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with empty string."""
        result = handler.handle("", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == "Gemini generation config must be specified"
        assert result.new_state is None

    @pytest.mark.asyncio
    async def test_handle_with_complex_config(
        self, handler: GeminiGenerationConfigHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with complex Gemini configuration."""
        complex_config = {
            "thinkingConfig": {
                "thinkingBudget": 2048,
                "includeThoughts": True
            },
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.9,
                "topK": 40,
                "maxOutputTokens": 1024
            }
        }
        mock_state.reasoning_config.with_gemini_generation_config = Mock(return_value=mock_state.reasoning_config)

        result = handler.handle(complex_config, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == f"Gemini generation config set to {complex_config}"
        assert result.new_state is mock_state

        # Verify the reasoning config was updated
        mock_state.reasoning_config.with_gemini_generation_config.assert_called_once_with(complex_config)
