from unittest.mock import Mock

import pytest
from src.command_parser import CommandParser, CommandParserConfig
from src.core.domain.session import Session, SessionStateAdapter
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

    def test_create_route_enables_interactive(self):
        session = Session(session_id="test_session")
        state = session.state
        config = CommandParserConfig(
            proxy_state=SessionStateAdapter(state),
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser = CommandParser(config, command_prefix="!/")
        parser.process_messages(
            [
                ChatMessage(
                    role="user", content="!/create-failover-route(name=foo,policy=k)"
                )
            ]
        )
        assert session.state.interactive_just_enabled is True
        assert "foo" in session.state.backend_config.failover_routes
        assert session.state.backend_config.failover_routes["foo"]["policy"] == "k"

    def test_route_append_and_list(self):
        session = Session(session_id="test_session")
        state = session.state
        config = CommandParserConfig(
            proxy_state=SessionStateAdapter(state),
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser = CommandParser(config, command_prefix="!/")
        parser.process_messages(
            [
                ChatMessage(
                    role="user", content="!/create-failover-route(name=foo,policy=k)"
                ),
                ChatMessage(
                    role="user", content="!/route-append(name=foo,element=bar)"
                ),
                ChatMessage(
                    role="user", content="!/route-append(name=foo,element=baz:qux)"
                ),
            ]
        )
        assert session.state.backend_config.failover_routes["foo"]["policy"] == "k"
        elements = session.state.backend_config.get_route_elements("foo")
        assert len(elements) == 2
        assert "bar" in elements
        assert "baz:qux" in elements

    def test_routes_are_server_wide(self):
        session1 = Session(session_id="session1")
        state1 = session1.state
        config1 = CommandParserConfig(
            proxy_state=SessionStateAdapter(state1),
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser1 = CommandParser(config1, command_prefix="!/")

        session2 = Session(session_id="session2")
        state2 = session2.state
        config2 = CommandParserConfig(
            proxy_state=SessionStateAdapter(state2),
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        # parser2 is unused - removed to fix F841

        # Create a route in session1
        parser1.process_messages(
            [
                ChatMessage(
                    role="user", content="!/create-failover-route(name=test,policy=m)"
                )
            ]
        )

        # Verify the route exists in session1
        assert "test" in session1.state.backend_config.failover_routes

        # Verify the route also exists in session2 (server-wide)
        assert "test" in session2.state.backend_config.failover_routes
