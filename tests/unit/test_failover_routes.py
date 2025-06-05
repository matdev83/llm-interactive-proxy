import pytest
from src.proxy_logic import ProxyState, CommandParser
from unittest.mock import Mock

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
        mock_app_state.functional_backends = {"openrouter", "gemini"} # Add functional backends
        
        self.mock_app = Mock()
        self.mock_app.state = mock_app_state

    def test_create_route_enables_interactive(self):
        state = ProxyState()
        parser = CommandParser(state, self.mock_app, command_prefix="!/")
        parser.process_text("!/create-failover-route(name=foo,policy=k)")
        assert state.interactive_mode is True
        assert "foo" in state.failover_routes
        assert state.failover_routes["foo"]["policy"] == "k"


    def test_route_append_and_list(self):
        state = ProxyState(interactive_mode=True)
        parser = CommandParser(state, self.mock_app, command_prefix="!/")
        parser.process_text("!/create-failover-route(name=bar,policy=m)")
        parser.process_text("!/route-append(name=bar,openrouter:model-a)")
        parser.process_text("!/route-prepend(name=bar,gemini:model-b)")
        parser.process_text("!/route-clear(name=bar)")
        assert state.list_route("bar") == []
        parser.process_text("!/route-append(name=bar,gemini:model-c)")
        parser.process_text("!/route-list(name=bar)")
        assert state.list_route("bar") == ["gemini:model-c"]
