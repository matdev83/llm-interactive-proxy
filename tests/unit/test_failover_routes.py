from unittest.mock import Mock

import pytest

from src.command_parser import CommandParser, CommandParserConfig
from src.models import ChatMessage
from src.proxy_logic import ProxyState


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
        state = ProxyState()
        config = CommandParserConfig(
            proxy_state=state,
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser = CommandParser(config, command_prefix="!/")
        parser.process_messages([ChatMessage(role="user", content="!/create-failover-route(name=foo,policy=k)")])
        assert state.interactive_mode is True
        assert "foo" in state.failover_routes
        assert state.failover_routes["foo"]["policy"] == "k"

    def test_route_append_and_list(self):
        state = ProxyState(interactive_mode=True)
        config = CommandParserConfig(
            proxy_state=state,
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser = CommandParser(config, command_prefix="!/")
        parser.process_messages([ChatMessage(role="user", content="!/create-failover-route(name=bar,policy=m)")])
        parser.process_messages([ChatMessage(role="user", content="!/route-append(name=bar,openrouter:model-a)")])
        parser.process_messages([ChatMessage(role="user", content="!/route-prepend(name=bar,gemini:model-b)")])
        parser.process_messages([ChatMessage(role="user", content="!/route-clear(name=bar)")])
        assert state.list_route("bar") == []
        parser.process_messages([ChatMessage(role="user", content="!/route-append(name=bar,gemini:model-c)")])
        parser.process_messages([ChatMessage(role="user", content="!/route-list(name=bar)")])
        assert state.list_route("bar") == ["gemini:model-c"]

    def test_routes_are_server_wide(self):
        shared = {}
        state1 = ProxyState(failover_routes=shared)
        config1 = CommandParserConfig(
            proxy_state=state1,
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser1 = CommandParser(config1, command_prefix="!/")
        parser1.process_messages([ChatMessage(role="user", content="!/create-failover-route(name=r,policy=k)")])
        parser1.process_messages([ChatMessage(role="user", content="!/route-append(name=r,openrouter:model-a)")])

        state2 = ProxyState(interactive_mode=True, failover_routes=shared)
        config2 = CommandParserConfig(
            proxy_state=state2,
            app=self.mock_app,
            functional_backends=self.mock_app.state.functional_backends,
            preserve_unknown=True,
        )
        parser2 = CommandParser(config2, command_prefix="!/")
        assert state2.list_route("r") == ["openrouter:model-a"]
        parser2.process_messages([ChatMessage(role="user", content="!/route-append(name=r,gemini:model-b)")])
        assert state1.list_route("r") == ["openrouter:model-a", "gemini:model-b"]
