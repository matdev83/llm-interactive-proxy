"""Unit tests for CLI parameter blocking functionality."""

import os
import pytest
from unittest.mock import MagicMock

from src.core.commands.handlers.reasoning_handlers import (
    ReasoningEffortHandler,
    ThinkingBudgetHandler,
    _is_cli_thinking_budget_enabled,
)
from src.core.domain.session import SessionState


class TestCLIParameterBlocking:
    """Test suite for CLI parameter blocking of interactive commands."""

    def setup_method(self):
        """Set up test environment."""
        # Save original environment
        self.original_thinking_budget = os.environ.get("THINKING_BUDGET")
        
    def teardown_method(self):
        """Clean up test environment."""
        # Restore original environment
        if self.original_thinking_budget is not None:
            os.environ["THINKING_BUDGET"] = self.original_thinking_budget
        elif "THINKING_BUDGET" in os.environ:
            del os.environ["THINKING_BUDGET"]

    def test_cli_thinking_budget_detection_works(self):
        """Test that CLI thinking budget detection works correctly."""
        # Test with no CLI flag
        if "THINKING_BUDGET" in os.environ:
            del os.environ["THINKING_BUDGET"]
        assert not _is_cli_thinking_budget_enabled()
        
        # Test with CLI flag set
        os.environ["THINKING_BUDGET"] = "8192"
        assert _is_cli_thinking_budget_enabled()
        
        # Test with empty string
        os.environ["THINKING_BUDGET"] = ""
        assert not _is_cli_thinking_budget_enabled()
        
        # Test with whitespace only
        os.environ["THINKING_BUDGET"] = "   "
        assert not _is_cli_thinking_budget_enabled()

    def test_reasoning_effort_handler_blocks_when_cli_thinking_budget_set(self):
        """Test that reasoning effort handler blocks changes when CLI thinking budget is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = ReasoningEffortHandler()
        state = SessionState()
        
        result = handler.handle("high", state)
        
        assert not result.success
        assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message
        assert "CLI settings take priority over interactive commands" in result.message

    def test_reasoning_effort_handler_works_normally_when_cli_thinking_budget_not_set(self):
        """Test that reasoning effort handler works normally when CLI thinking budget is not set."""
        # Ensure CLI thinking budget is disabled
        if "THINKING_BUDGET" in os.environ:
            del os.environ["THINKING_BUDGET"]
        
        handler = ReasoningEffortHandler()
        state = SessionState()
        
        result = handler.handle("high", state)
        
        # Should succeed when CLI thinking budget is disabled
        assert result.success
        assert "Reasoning effort set to high" in result.message
        assert result.new_state is not None

    def test_thinking_budget_handler_blocks_when_cli_thinking_budget_set(self):
        """Test that thinking budget handler blocks changes when CLI thinking budget is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = ThinkingBudgetHandler()
        state = SessionState()
        
        result = handler.handle("4096", state)
        
        assert not result.success
        assert "Cannot change thinking budget when --thinking-budget CLI parameter is set" in result.message
        assert "CLI settings take priority over interactive commands" in result.message

    def test_thinking_budget_handler_works_normally_when_cli_thinking_budget_not_set(self):
        """Test that thinking budget handler works normally when CLI thinking budget is not set."""
        # Ensure CLI thinking budget is disabled
        if "THINKING_BUDGET" in os.environ:
            del os.environ["THINKING_BUDGET"]
        
        handler = ThinkingBudgetHandler()
        state = SessionState()
        
        result = handler.handle("2048", state)
        
        # Should succeed when CLI thinking budget is disabled
        assert result.success
        assert "Thinking budget set to 2048" in result.message
        assert result.new_state is not None

    def test_thinking_budget_handler_still_validates_when_cli_thinking_budget_set(self):
        """Test that thinking budget handler still validates input even when CLI is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = ThinkingBudgetHandler()
        state = SessionState()
        
        # Should block first, before even getting to validation
        result = handler.handle("invalid", state)
        
        assert not result.success
        assert "Cannot change thinking budget when --thinking-budget CLI parameter is set" in result.message

    def test_reasoning_effort_handler_still_validates_when_cli_thinking_budget_set(self):
        """Test that reasoning effort handler still validates input even when CLI is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = ReasoningEffortHandler()
        state = SessionState()
        
        # Should block first, before even getting to validation
        result = handler.handle("invalid_level", state)
        
        assert not result.success
        assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message

    def test_handlers_allow_empty_values_when_cli_thinking_budget_set(self):
        """Test that handlers still handle empty/None values correctly when CLI is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        # Test reasoning effort handler with None
        handler = ReasoningEffortHandler()
        state = SessionState()
        
        result = handler.handle(None, state)
        
        # Should block with CLI message first, not the validation message
        assert not result.success
        assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message
        
        # Test thinking budget handler with empty string
        budget_handler = ThinkingBudgetHandler()
        
        result = budget_handler.handle("", state)
        
        # Should block with CLI message first, not the validation message
        assert not result.success
        assert "Cannot change thinking budget when --thinking-budget CLI parameter is set" in result.message

    @pytest.mark.parametrize("cli_value", ["8192", "4096", "1024", "-1", "0"])
    def test_reasoning_effort_blocked_for_various_cli_values(self, cli_value):
        """Test that reasoning effort is blocked for various CLI thinking budget values."""
        os.environ["THINKING_BUDGET"] = cli_value
        
        handler = ReasoningEffortHandler()
        state = SessionState()
        
        result = handler.handle("medium", state)
        
        assert not result.success
        assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message

    @pytest.mark.parametrize("cli_value", ["8192", "4096", "1024", "-1", "0"])
    def test_thinking_budget_blocked_for_various_cli_values(self, cli_value):
        """Test that thinking budget is blocked for various CLI thinking budget values."""
        os.environ["THINKING_BUDGET"] = cli_value
        
        handler = ThinkingBudgetHandler()
        state = SessionState()
        
        result = handler.handle("2048", state)
        
        assert not result.success
        assert "Cannot change thinking budget when --thinking-budget CLI parameter is set" in result.message
