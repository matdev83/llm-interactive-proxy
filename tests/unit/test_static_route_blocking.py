"""Unit tests for static route blocking functionality."""

import os
from unittest.mock import MagicMock

import pytest
from src.core.commands.command import Command
from src.core.commands.handlers.model_command_handler import ModelCommandHandler
from src.core.commands.handlers.set_command_handler import SetCommandHandler
from src.core.domain.commands.model_command import ModelCommand
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.session import Session, SessionState


class TestStaticRouteBlocking:
    """Test suite for static route blocking of interactive commands."""

    def setup_method(self):
        """Set up test environment."""
        # Save original environment
        self.original_static_route = os.environ.get("STATIC_ROUTE")
        
    def teardown_method(self):
        """Clean up test environment."""
        # Restore original environment
        if self.original_static_route is not None:
            os.environ["STATIC_ROUTE"] = self.original_static_route
        elif "STATIC_ROUTE" in os.environ:
            del os.environ["STATIC_ROUTE"]

    @pytest.mark.asyncio
    async def test_set_command_blocks_backend_when_static_route_enabled(self):
        """Test that set command blocks backend changes when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"backend": "openai"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change backend when static routing is enabled" in result.message
        assert "--static-route CLI parameter" in result.message

    @pytest.mark.asyncio
    async def test_set_command_blocks_model_when_static_route_enabled(self):
        """Test that set command blocks model changes when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"model": "gpt-4"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change model when static routing is enabled" in result.message
        assert "--static-route CLI parameter" in result.message

    @pytest.mark.asyncio
    async def test_set_command_blocks_both_backend_and_model_when_static_route_enabled(self):
        """Test that set command blocks both backend and model changes when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"backend": "openai", "model": "gpt-4"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change backend and model when static routing is enabled" in result.message
        assert "--static-route CLI parameter" in result.message

    @pytest.mark.asyncio
    async def test_set_command_allows_other_params_when_static_route_enabled(self):
        """Test that set command allows non-backend/model parameters when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"temperature": "0.7"})
        
        result = await handler.handle(command, session)
        
        # Should succeed since temperature is not backend/model
        assert result.success

    @pytest.mark.asyncio
    async def test_set_command_works_normally_when_static_route_disabled(self):
        """Test that set command works normally when static route is not enabled."""
        # Ensure static routing is disabled
        if "STATIC_ROUTE" in os.environ:
            del os.environ["STATIC_ROUTE"]
        
        handler = SetCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="set", args={"backend": "openai", "model": "gpt-4"})
        
        result = await handler.handle(command, session)
        
        # Should succeed when static routing is disabled
        assert result.success

    @pytest.mark.asyncio
    async def test_model_command_blocks_model_change_when_static_route_enabled(self):
        """Test that model command blocks model changes when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        handler = ModelCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="model", args={"name": "gpt-4"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change model when static routing is enabled" in result.message
        assert "--static-route CLI parameter" in result.message

    @pytest.mark.asyncio
    async def test_model_command_blocks_backend_model_change_when_static_route_enabled(self):
        """Test that model command blocks backend:model changes when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        handler = ModelCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="model", args={"name": "openai:gpt-4"})
        
        result = await handler.handle(command, session)
        
        assert not result.success
        assert "Cannot change model when static routing is enabled" in result.message
        assert "--static-route CLI parameter" in result.message

    @pytest.mark.asyncio
    async def test_model_command_works_normally_when_static_route_disabled(self):
        """Test that model command works normally when static route is not enabled."""
        # Ensure static routing is disabled
        if "STATIC_ROUTE" in os.environ:
            del os.environ["STATIC_ROUTE"]
        
        handler = ModelCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="model", args={"name": "gpt-4"})
        
        result = await handler.handle(command, session)
        
        # Should succeed when static routing is disabled
        assert result.success

    @pytest.mark.asyncio
    async def test_model_command_allows_unset_when_static_route_enabled(self):
        """Test that model command allows unsetting model when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        handler = ModelCommandHandler()
        session = Session(session_id="test", state=SessionState())
        command = Command(name="model", args={"name": ""})  # Empty name should unset
        
        result = await handler.handle(command, session)
        
        # Should succeed since unsetting doesn't change to a different model
        assert result.success

    @pytest.mark.asyncio
    async def test_domain_set_command_blocks_backend_model_when_static_route_enabled(self):
        """Test that domain-level set command blocks backend/model when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        # Create mock state services
        state_reader = MagicMock()
        state_modifier = MagicMock()
        
        command = SetCommand(state_reader=state_reader, state_modifier=state_modifier)
        session = Session(session_id="test", state=SessionState())
        
        # Configure the mock to return the session state
        state_reader.get_session_state.return_value = session.state
        state_modifier.update_session_state.return_value = session.state
        
        result = await command.execute({"backend": "openai"}, session)
        
        assert not result.success
        assert "Cannot change backend when static routing is enabled" in result.message
        assert "--static-route CLI parameter" in result.message

    @pytest.mark.asyncio
    async def test_domain_model_command_blocks_model_change_when_static_route_enabled(self):
        """Test that domain-level model command blocks model changes when static route is enabled."""
        # Enable static routing
        os.environ["STATIC_ROUTE"] = "gemini-cli-oauth-personal:gemini-2.5-pro"
        
        command = ModelCommand()
        session = Session(session_id="test", state=SessionState())
        
        result = await command.execute({"name": "gpt-4"}, session)
        
        assert not result.success
        assert "Cannot change model when static routing is enabled" in result.message
        assert "--static-route CLI parameter" in result.message

    def test_static_route_detection_ignores_empty_string(self):
        """Test that static route detection ignores empty strings."""
        handler = SetCommandHandler()
        
        # Set empty string
        os.environ["STATIC_ROUTE"] = ""
        assert not handler._is_static_routing_enabled()
        
        # Set to None
        os.environ["STATIC_ROUTE"] = "   "  # Whitespace only
        assert not handler._is_static_routing_enabled()
        
        # Set valid value
        os.environ["STATIC_ROUTE"] = "openai:gpt-4"
        assert handler._is_static_routing_enabled()
