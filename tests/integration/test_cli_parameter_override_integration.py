"""Integration tests for CLI parameter override functionality."""

import os
import pytest
from unittest.mock import MagicMock, AsyncMock

from src.core.commands.handlers.set_command_handler import SetCommandHandler
from src.core.commands.command import Command
from src.core.domain.session import Session, SessionState


class TestCLIParameterOverrideIntegration:
    """Integration tests for CLI parameter override protection."""

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

    @pytest.mark.asyncio
    async def test_set_command_with_reasoning_effort_blocked_by_cli_thinking_budget(self):
        """Test that set command blocks reasoning effort when CLI thinking budget is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"reasoning-effort": "high"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message

    @pytest.mark.asyncio
    async def test_set_command_with_thinking_budget_blocked_by_cli_thinking_budget(self):
        """Test that set command blocks thinking budget when CLI thinking budget is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"thinking-budget": "4096"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change thinking budget when --thinking-budget CLI parameter is set" in result.message

    @pytest.mark.asyncio
    async def test_set_command_with_multiple_reasoning_params_blocked_by_cli_thinking_budget(self):
        """Test that set command blocks multiple reasoning parameters when CLI thinking budget is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"reasoning-effort": "high", "thinking-budget": "4096"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message

    @pytest.mark.asyncio
    async def test_set_command_with_non_reasoning_params_works_with_cli_thinking_budget(self):
        """Test that set command allows non-reasoning parameters even when CLI thinking budget is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"temperature": "0.7"})
        
        result = await handler.handle(command, session)
        
        # Should succeed since temperature is not a reasoning parameter
        assert result.success
        assert "Settings updated" in result.message

    @pytest.mark.asyncio
    async def test_set_command_with_mixed_params_blocks_reasoning_only(self):
        """Test that set command blocks only reasoning parameters in mixed requests."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"temperature": "0.7", "reasoning-effort": "high"})
        
        result = await handler.handle(command, session)
        
        # Should fail because reasoning-effort is blocked
        assert not result.success
        assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message

    @pytest.mark.asyncio
    async def test_set_command_with_reasoning_aliases_blocked_by_cli_thinking_budget(self):
        """Test that set command blocks reasoning parameter aliases when CLI thinking budget is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        
        # Test various aliases for reasoning effort
        for param_name in ["reasoning_effort", "reasoning"]:
            command = Command(name="set", args={param_name: "medium"})
            
            result = await handler.handle(command, session)
            
            assert not result.success
            assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message

    @pytest.mark.asyncio
    async def test_set_command_with_thinking_budget_aliases_blocked_by_cli_thinking_budget(self):
        """Test that set command blocks thinking budget parameter aliases when CLI thinking budget is set."""
        # Enable CLI thinking budget
        os.environ["THINKING_BUDGET"] = "8192"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        
        # Test various aliases for thinking budget
        for param_name in ["thinking_budget", "budget"]:
            command = Command(name="set", args={param_name: "2048"})
            
            result = await handler.handle(command, session)
            
            assert not result.success
            assert "Cannot change thinking budget when --thinking-budget CLI parameter is set" in result.message

    @pytest.mark.asyncio
    async def test_all_reasoning_parameters_work_normally_without_cli_thinking_budget(self):
        """Test that all reasoning parameters work normally when CLI thinking budget is not set."""
        # Ensure CLI thinking budget is disabled
        if "THINKING_BUDGET" in os.environ:
            del os.environ["THINKING_BUDGET"]
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        
        # Test all reasoning parameters
        reasoning_params = [
            ("reasoning-effort", "high"),
            ("reasoning_effort", "medium"),
            ("reasoning", "low"),
            ("thinking-budget", "1024"),
            ("thinking_budget", "2048"),
            ("budget", "4096"),
        ]
        
        for param_name, param_value in reasoning_params:
            command = Command(name="set", args={param_name: param_value})
            
            result = await handler.handle(command, session)
            
            # Should succeed when CLI thinking budget is disabled
            assert result.success, f"Failed for {param_name}={param_value}: {result.message}"



    @pytest.mark.parametrize("cli_value", ["-1", "0", "512", "1024", "2048", "4096", "8192", "16384", "32768"])
    async def test_various_cli_thinking_budget_values_block_interactive_commands(self, cli_value):
        """Test that various CLI thinking budget values block interactive commands."""
        os.environ["THINKING_BUDGET"] = cli_value
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"reasoning-effort": "high"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change reasoning effort when --thinking-budget CLI parameter is set" in result.message
