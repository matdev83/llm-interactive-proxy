from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_service_interface import ICommandService

CommandServiceHandler = Callable[[list[Any], str], Awaitable[ProcessedResult]]


class FunctionCommandService(ICommandService):
    """Adapter that turns a coroutine function into an ``ICommandService``."""

    def __init__(self, handler: CommandServiceHandler):
        if handler is None:
            raise ValueError(
                "A handler callable must be provided for the command service."
            )
        if not callable(handler):
            raise TypeError("The command service handler must be callable.")
        self._handler = handler

    async def process_commands(
        self, messages: list[Any], session_id: str
    ) -> ProcessedResult:
        return await self._handler(messages, session_id)


def ensure_command_service(
    service: ICommandService | CommandServiceHandler | None,
) -> ICommandService:
    """Validate or adapt a command service value.

    Args:
        service: Either an ``ICommandService`` instance, an async handler callable,
            or ``None``.

    Returns:
        A concrete ``ICommandService`` implementation.

    Raises:
        ValueError: If ``service`` is ``None``.
        TypeError: If ``service`` is not an ``ICommandService`` or a valid handler.
    """

    if service is None:
        raise ValueError("A command service instance is required.")

    if isinstance(service, ICommandService):
        return service

    if callable(service):
        return FunctionCommandService(service)  # type: ignore[arg-type]

    raise TypeError("The provided command service is not valid.")


__all__ = ["FunctionCommandService", "ensure_command_service"]
