import pytest
from src.proxy_logic import ProxyState, CommandParser


def test_create_route_enables_interactive():
    state = ProxyState()
    parser = CommandParser(state, command_prefix="!/")
    parser.process_text("!/create-failover-route(name=foo,policy=k)")
    assert state.interactive_mode is True
    assert "foo" in state.failover_routes
    assert state.failover_routes["foo"]["policy"] == "k"


def test_route_append_and_list():
    state = ProxyState(interactive_mode=True)
    parser = CommandParser(state, command_prefix="!/")
    parser.process_text("!/create-failover-route(name=bar,policy=m)")
    parser.process_text("!/route-append(name=bar,openrouter:model-a)")
    parser.process_text("!/route-prepend(name=bar,gemini:model-b)")
    parser.process_text("!/route-clear(name=bar)")
    assert state.list_route("bar") == []
    parser.process_text("!/route-append(name=bar,gemini:model-c)")
    parser.process_text("!/route-list(name=bar)")
    assert state.list_route("bar") == ["gemini:model-c"]
