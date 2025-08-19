from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.commands.handlers.base_handler import ICommandHandler
    from src.core.commands.handlers.command_handler import ILegacyCommandHandler


class CommandHandlerFactory:
    """Factory for creating command handlers."""

    def create_handlers(self) -> list[ICommandHandler | ILegacyCommandHandler]:
        """Create and return all available command handlers.

        Returns:
            List of command handlers
        """
        handlers: list[ICommandHandler | ILegacyCommandHandler] = []

        # Import handlers here to avoid circular imports
        # Backend handlers
        from src.core.commands.handlers.backend_handlers import (
            BackendHandler,
            ModelHandler,
            OpenAIUrlHandler,
        )

        handlers.extend(
            [
                BackendHandler(),
                ModelHandler(),
                OpenAIUrlHandler(),
            ]
        )

        # Loop detection handlers
        from src.core.commands.handlers.loop_detection_handlers import (
            LoopDetectionHandler,
            ToolLoopDetectionHandler,
            ToolLoopMaxRepeatsHandler,
            ToolLoopModeHandler,
            ToolLoopTTLHandler,
        )

        handlers.extend(
            [
                LoopDetectionHandler(),
                ToolLoopDetectionHandler(),
                ToolLoopMaxRepeatsHandler(),
                ToolLoopTTLHandler(),
                ToolLoopModeHandler(),
            ]
        )

        # Reasoning handlers
        from src.core.commands.handlers.command_handler import (
            TemperatureCommandHandler,
        )
        from src.core.commands.handlers.reasoning_handlers import (
            GeminiGenerationConfigHandler,
            ReasoningEffortHandler,
            ThinkingBudgetHandler,
        )

        handlers.extend(
            [
                TemperatureCommandHandler(),
                ReasoningEffortHandler(),
                ThinkingBudgetHandler(),
                GeminiGenerationConfigHandler(),
            ]
        )

        # Project handlers
        from src.core.commands.handlers.project_dir_handler import (
            ProjectDirCommandHandler,
        )
        from src.core.commands.handlers.project_handler import ProjectCommandHandler

        handlers.extend(
            [
                ProjectCommandHandler(),
                ProjectDirCommandHandler(),
            ]
        )

        # Oneoff handler
        from src.core.commands.handlers.oneoff_handler import OneOffCommandHandler

        handlers.append(OneOffCommandHandler())

        # Failover handlers
        from src.core.commands.handlers.failover_handlers import (
            CreateFailoverRouteHandler,
            DeleteFailoverRouteHandler,
            ListFailoverRoutesHandler,
            RouteAppendHandler,
            RouteClearHandler,
            RouteListHandler,
            RoutePrependHandler,
        )

        handlers.extend(
            [
                CreateFailoverRouteHandler(),
                DeleteFailoverRouteHandler(),
                RouteListHandler(),
                RouteAppendHandler(),
                RoutePrependHandler(),
                RouteClearHandler(),
                ListFailoverRoutesHandler(),
            ]
        )

        # PWD handler
        from src.core.commands.handlers.pwd_handler import PwdCommandHandler

        handlers.append(PwdCommandHandler())

        return handlers
