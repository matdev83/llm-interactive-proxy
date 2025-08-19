from unittest.mock import Mock

import pytest
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import BackendConfiguration, SessionState


# Helper function to run a command against a given state
async def run_command(command_string: str, state: SessionState) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = state
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    # Manually register all failover commands for the test
    from src.core.domain.commands.failover_commands import (
        CreateFailoverRouteCommand,
        DeleteFailoverRouteCommand,
        ListFailoverRoutesCommand,
        RouteAppendCommand,
        RouteClearCommand,
        RouteListCommand,
        RoutePrependCommand,
    )
    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {
        "create-failover-route": CreateFailoverRouteCommand(),
        "delete-failover-route": DeleteFailoverRouteCommand(),
        "list-failover-routes": ListFailoverRoutesCommand(),
        "route-append": RouteAppendCommand(),
        "route-clear": RouteClearCommand(),
        "route-list": RouteListCommand(),
        "route-prepend": RoutePrependCommand(),
    }
    
    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_failover_commands_lifecycle(snapshot):
    """Snapshot test for the full lifecycle of failover route commands."""
    
    state = SessionState(backend_config=BackendConfiguration())
    results = []

    # 1. Create a route
    results.append(await run_command("!/create-failover-route(name=myroute,policy=k)", state))
    
    # 2. Append an element
    results.append(await run_command("!/route-append(name=myroute,element=openai:gpt-4)", state))

    # 3. List the route
    results.append(await run_command("!/route-list(name=myroute)", state))

    # 4. List all routes
    results.append(await run_command("!/list-failover-routes", state))

    # 5. Clear the route
    results.append(await run_command("!/route-clear(name=myroute)", state))

    # 6. Delete the route
    results.append(await run_command("!/delete-failover-route(name=myroute)", state))

    # 7. Try to delete a non-existent route
    results.append(await run_command("!/delete-failover-route(name=nonexistent)", state))

    # Assert all results against a single snapshot
    assert "\n---\n".join(results) == snapshot
