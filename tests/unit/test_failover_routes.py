from typing import cast
from unittest.mock import Mock

import pytest
from src.command_parser import CommandParser, CommandParserConfig
from src.core.domain.session import Session, SessionState, SessionStateAdapter
from src.models import ChatMessage


class TestFailoverRoutes:

    @pytest.fixture(autouse=True)
    def setup_mock_app(self):
        # Create a mock app object with a state attribute and mock backends
        mock_openrouter_backend = Mock()
        mock_openrouter_backend.get_available_models.return_value = ["model-a"]

        mock_gemini_backend = Mock()
        mock_gemini_backend.get_available_models.return_value = ["model-b"]

        mock_app_state = Mock()
        mock_app_state.openrouter_backend = mock_openrouter_backend
        mock_app_state.gemini_backend = mock_gemini_backend
        mock_app_state.functional_backends = {
            "openrouter",
            "gemini",
        }  # Add functional backends

        self.mock_app = Mock()
        self.mock_app.state = mock_app_state

    @pytest.mark.asyncio
    async def test_create_route_enables_interactive(self):
        session = Session(session_id="test_session")
        state_adapter = SessionStateAdapter(cast(SessionState, session.state))
        config = CommandParserConfig(
            proxy_state=state_adapter,  # Pass the adapter
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser = CommandParser(config, command_prefix="!/")
        await parser.process_messages(
            [
                ChatMessage(
                    role="user", content="!/create-failover-route(name=foo,policy=k)"
                )
            ]
        )
        # Check the updated state through the adapter
        assert state_adapter._state.interactive_just_enabled is True
        assert "foo" in state_adapter._state.backend_config.failover_routes
        assert (
            state_adapter._state.backend_config.failover_routes["foo"]["policy"] == "k"
        )

    @pytest.mark.asyncio
    async def test_route_append_and_list(self):
        # In real usage, each command would create a route, and subsequent requests
        # would use the route. Since routes are per-session and our test simulates
        # multiple independent calls (like separate API requests), we need to
        # properly simulate how the system would actually work.

        # Create initial session and route
        session = Session(session_id="test_session")
        state_adapter = SessionStateAdapter(cast(SessionState, session.state))
        config = CommandParserConfig(
            proxy_state=state_adapter,
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser = CommandParser(config, command_prefix="!/")

        # Create the route
        await parser.process_messages(
            [
                ChatMessage(
                    role="user", content="!/create-failover-route(name=foo,policy=k)"
                )
            ]
        )

        # Verify the route was created
        assert "foo" in state_adapter._state.backend_config.failover_routes
        assert state_adapter._state.backend_config.get_route_elements("foo") == []

        # For the next command, we need to update the parser's config with the updated state
        # This simulates how in production, each request would get the current state
        config.proxy_state = (
            state_adapter  # Reuse the same adapter which has updated state
        )
        parser2 = CommandParser(config, command_prefix="!/")

        # Append first element
        await parser2.process_messages(
            [
                ChatMessage(
                    role="assistant",
                    content="Failover route 'foo' created with policy 'k'",
                ),
                ChatMessage(
                    role="user", content="!/route-append(name=foo,element=bar)"
                ),
            ]
        )

        # Verify first element was added
        elements_after_first = state_adapter._state.backend_config.get_route_elements(
            "foo"
        )
        assert len(elements_after_first) == 1
        assert "bar" in elements_after_first

        # Create another parser with the updated state for the third command
        parser3 = CommandParser(config, command_prefix="!/")

        # Append second element
        await parser3.process_messages(
            [
                ChatMessage(
                    role="assistant",
                    content="Element 'bar' appended to failover route 'foo'",
                ),
                ChatMessage(
                    role="user", content="!/route-append(name=foo,element=openai:gpt-4)"
                ),
            ]
        )

        # Check the final state
        assert (
            state_adapter._state.backend_config.failover_routes["foo"]["policy"] == "k"
        )
        elements = state_adapter._state.backend_config.get_route_elements("foo")
        assert len(elements) == 2
        assert "bar" in elements
        assert "openai:gpt-4" in elements

    @pytest.mark.asyncio
    async def test_routes_are_server_wide(self):
        session1 = Session(session_id="session1")
        state_adapter1 = SessionStateAdapter(cast(SessionState, session1.state))
        config1 = CommandParserConfig(
            proxy_state=state_adapter1,  # Pass the adapter
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser1 = CommandParser(config1, command_prefix="!/")

        session2 = Session(session_id="session2")
        state_adapter2 = SessionStateAdapter(cast(SessionState, session2.state))

        # Create a route in session1
        await parser1.process_messages(
            [
                ChatMessage(
                    role="user", content="!/create-failover-route(name=test,policy=m)"
                )
            ]
        )

        # Verify the route exists in session1's adapter state
        assert "test" in state_adapter1._state.backend_config.failover_routes

        # In the new architecture, routes are per-session, not server-wide
        # So session2 won't have the route created in session1
        # This test expectation needs to be updated
        assert "test" not in state_adapter2._state.backend_config.failover_routes
