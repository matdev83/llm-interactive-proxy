
from typing import Any

import pytest
from src.core.domain.session import BackendConfiguration, Session, SessionState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)


# Helper function to run a command against a given state (direct execution)
async def run_command(command_string: str, state: SessionState) -> str:
    # Build minimal Session wrapper expected by commands
    session = Session(session_id="test", state=state)

    # Minimal in-memory state service to satisfy DI for stateful commands
    class _StateService(ISecureStateAccess, ISecureStateModification):
        def __init__(self) -> None:
            self._prefix = "!/"
            self._redaction = False
            self._disabled = False
            self._routes: list[dict[str, Any]] = []

        def get_command_prefix(self) -> str | None:
            return self._prefix

        def get_api_key_redaction_enabled(self) -> bool:
            return self._redaction

        def get_disable_interactive_commands(self) -> bool:
            return self._disabled

        def get_failover_routes(self) -> list[dict[str, Any]] | None:
            return self._routes

        def update_command_prefix(self, prefix: str) -> None:
            self._prefix = prefix

        def update_api_key_redaction(self, enabled: bool) -> None:
            self._redaction = enabled

        def update_interactive_commands(self, disabled: bool) -> None:
            self._disabled = disabled

        def update_failover_routes(self, routes: list[dict[str, Any]]) -> None:
            self._routes = routes

    svc = _StateService()

    from src.core.domain.commands.failover_commands import (
        CreateFailoverRouteCommand,
        DeleteFailoverRouteCommand,
        ListFailoverRoutesCommand,
        RouteAppendCommand,
        RouteClearCommand,
        RouteListCommand,
        RoutePrependCommand,
    )

    handlers = {
        "create-failover-route": CreateFailoverRouteCommand(svc, svc),
        "delete-failover-route": DeleteFailoverRouteCommand(svc, svc),
        "list-failover-routes": ListFailoverRoutesCommand(svc, svc),
        "route-append": RouteAppendCommand(svc, svc),
        "route-clear": RouteClearCommand(svc, svc),
        "route-list": RouteListCommand(svc, svc),
        "route-prepend": RoutePrependCommand(svc, svc),
    }

    # Parse command name and arguments from command_string like !/cmd(a=b,c=d)
    assert command_string.startswith("!/")
    after = command_string[2:]
    if "(" in after and after.endswith(")"):
        name, args_str = after.split("(", 1)
        args_str = args_str[:-1]
    else:
        name, args_str = after, ""

    args: dict[str, Any] = {}
    if args_str:
        for part in args_str.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                args[k.strip()] = v.strip()
            else:
                args[part] = True

    cmd = handlers.get(name)
    if not cmd:
        return f"cmd not found: {name}"

    result = await cmd.execute(args, session)
    return getattr(result, "message", "")


@pytest.mark.asyncio
async def test_failover_commands_lifecycle(snapshot):
    """Snapshot test for the full lifecycle of failover route commands."""

    state = SessionState(backend_config=BackendConfiguration())
    results = []

    # 1. Create a route
    results.append(
        await run_command("!/create-failover-route(name=myroute,policy=k)", state)
    )

    # 2. Append an element
    results.append(
        await run_command("!/route-append(name=myroute,element=openai:gpt-4)", state)
    )

    # 3. List the route
    results.append(await run_command("!/route-list(name=myroute)", state))

    # 4. List all routes
    results.append(await run_command("!/list-failover-routes", state))

    # 5. Clear the route
    results.append(await run_command("!/route-clear(name=myroute)", state))

    # 6. Delete the route
    results.append(await run_command("!/delete-failover-route(name=myroute)", state))

    # 7. Try to delete a non-existent route
    results.append(
        await run_command("!/delete-failover-route(name=nonexistent)", state)
    )

    # Assert all results against a single snapshot
    from_str = "\n---\n".join(results)
    snapshot.assert_match(from_str, "failover_lifecycle_output")
