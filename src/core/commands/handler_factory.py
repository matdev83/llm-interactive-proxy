"""
Command handler factory.

This module provides functionality to create and register command handlers.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.command_handler import (
    BackendCommandHandler,
    HelpCommandHandler,
    ModelCommandHandler,
    TemperatureCommandHandler,
)
from src.core.commands.handlers.command_handler import (
    ILegacyCommandHandler as ICommandHandler,
)
from src.core.commands.handlers.failover_handlers import (
    CreateFailoverRouteHandler,
    DeleteFailoverRouteHandler,
    ListFailoverRoutesHandler,
    RouteAppendHandler,
    RouteClearHandler,
    RouteListHandler,
    RoutePrependHandler,
)
from src.core.commands.handlers.hello_handler import HelloCommandHandler
from src.core.commands.handlers.loop_detection_handlers import (
    LoopDetectionHandler,
    ToolLoopDetectionHandler,
    ToolLoopMaxRepeatsHandler,
    ToolLoopModeHandler,
    ToolLoopTTLHandler,
)
from src.core.commands.handlers.oneoff_handler import OneOffCommandHandler
from src.core.commands.handlers.openai_url_handler import OpenAIURLHandler
from src.core.commands.handlers.project_dir_handler import ProjectDirCommandHandler
from src.core.commands.handlers.project_handler import ProjectCommandHandler
from src.core.commands.handlers.pwd_handler import PwdCommandHandler
from src.core.commands.handlers.reasoning_handlers import (
    GeminiGenerationConfigHandler,
    ReasoningEffortHandler,
    ThinkingBudgetHandler,
)
from src.core.commands.handlers.set_handler import SetCommandHandler
from src.core.commands.handlers.unset_handler import UnsetCommandHandler
from src.core.domain.commands import CommandResult as NewResult
from src.core.services.command_service import CommandRegistry

logger = logging.getLogger(__name__)


class CommandHandlerFactory:
    """Factory for creating and registering command handlers."""

    def __init__(self) -> None:
        """Initialize the factory."""
        self._registry: CommandRegistry = CommandRegistry()
        # Allow handler classes OR zero-arg callables returning handler instances

        # Handler can be a class or a callable factory
        self._handler_classes: dict[str, Any] = {}
        self._handlers: dict[str, ICommandHandler] = {}

        # Register built-in command handlers
        self.register_handler_class(BackendCommandHandler)
        self.register_handler_class(ModelCommandHandler)
        self.register_handler_class(TemperatureCommandHandler)
        self.register_handler_class(HelpCommandHandler)
        self.register_handler_class(HelloCommandHandler)
        self.register_handler_class(OneOffCommandHandler)
        self.register_handler_class(PwdCommandHandler)
        self.register_handler_class(ProjectDirCommandHandler)
        self.register_handler_class(OpenAIURLHandler)

        project_handler = ProjectCommandHandler()
        self.register_handler_class(lambda: project_handler)

        # Project directory handler (specialized) - ensure it's attached to the
        # unified set/unset handlers so the 'set(project-dir=...)' command works.
        project_dir_handler = ProjectDirCommandHandler()

        # Register unified set and unset command handlers
        set_handler = SetCommandHandler()
        unset_handler = UnsetCommandHandler()
        self.register_handler_class(lambda: set_handler)
        self.register_handler_class(lambda: unset_handler)

        # Register reasoning handlers
        reasoning_effort_handler = ReasoningEffortHandler()
        thinking_budget_handler = ThinkingBudgetHandler()
        gemini_config_handler = GeminiGenerationConfigHandler()
        self.register_handler_class(lambda: reasoning_effort_handler)
        self.register_handler_class(lambda: thinking_budget_handler)
        self.register_handler_class(lambda: gemini_config_handler)

        # Register specialized handlers with the set and unset command handlers
        openai_url_handler = OpenAIURLHandler()
        set_handler.register_handler(project_handler)
        set_handler.register_handler(reasoning_effort_handler)
        set_handler.register_handler(thinking_budget_handler)
        set_handler.register_handler(gemini_config_handler)
        set_handler.register_handler(openai_url_handler)
        unset_handler.register_handler(project_handler)
        unset_handler.register_handler(reasoning_effort_handler)
        unset_handler.register_handler(thinking_budget_handler)
        unset_handler.register_handler(gemini_config_handler)

        # Register loop detection handlers
        loop_detection_handler = LoopDetectionHandler()
        tool_loop_detection_handler = ToolLoopDetectionHandler()
        tool_loop_max_repeats_handler = ToolLoopMaxRepeatsHandler()
        tool_loop_ttl_handler = ToolLoopTTLHandler()
        tool_loop_mode_handler = ToolLoopModeHandler()
        self.register_handler_class(lambda: loop_detection_handler)
        self.register_handler_class(lambda: tool_loop_detection_handler)
        self.register_handler_class(lambda: tool_loop_max_repeats_handler)
        self.register_handler_class(lambda: tool_loop_ttl_handler)
        self.register_handler_class(lambda: tool_loop_mode_handler)

        # Register specialized handlers with the set and unset command handlers
        set_handler.register_handler(loop_detection_handler)
        set_handler.register_handler(tool_loop_detection_handler)
        set_handler.register_handler(tool_loop_max_repeats_handler)
        set_handler.register_handler(tool_loop_ttl_handler)
        set_handler.register_handler(tool_loop_mode_handler)
        unset_handler.register_handler(loop_detection_handler)
        unset_handler.register_handler(tool_loop_detection_handler)
        unset_handler.register_handler(tool_loop_max_repeats_handler)
        unset_handler.register_handler(tool_loop_ttl_handler)
        unset_handler.register_handler(tool_loop_mode_handler)

        # Register the project_dir handler with set/unset
        set_handler.register_handler(project_dir_handler)
        unset_handler.register_handler(project_dir_handler)

        # Register failover route command handlers
        self.register_handler_class(CreateFailoverRouteHandler)
        self.register_handler_class(DeleteFailoverRouteHandler)
        self.register_handler_class(ListFailoverRoutesHandler)
        self.register_handler_class(RouteAppendHandler)
        self.register_handler_class(RouteClearHandler)
        self.register_handler_class(RouteListHandler)
        self.register_handler_class(RoutePrependHandler)

    def register_handler_class(self, handler_class: Any) -> None:
        """Register a command handler class or factory.

        Args:
            handler_class: The command handler class or zero-arg factory to register
        """
        # Create a temporary instance to get the name
        instance = handler_class() if callable(handler_class) else handler_class
        name = instance.name

        # Store the class/factory for later instantiation
        self._handler_classes[name] = handler_class
        logger.debug(f"Registered command handler class: {name}")

    def create_handlers(self) -> list[ICommandHandler]:
        """Create instances of all registered command handlers.

        Returns:
            List of command handler instances
        """
        from typing import cast

        from src.core.domain.commands import CommandResult as NewResult
        from src.core.domain.session import Session, SessionState, SessionStateAdapter

        handlers: list[ICommandHandler] = []

        # Helper: instantiate
        def _make(hctor: Any) -> Any:
            return hctor() if callable(hctor) else hctor

        # Adapter: provide async execute for handlers that only implement handle()
        class _ExecuteAdapter:
            def __init__(self, inner: Any):
                self._inner = inner
                self.name = getattr(inner, "name", "unknown")
                self._aliases = getattr(inner, "_aliases", [])

            async def execute(
                self,
                args: dict[str, str],
                session: Session | SessionStateAdapter | None,
                context: dict[str, Any] | None = None,
            ) -> NewResult:
                # Map args dict directly to handler.handle param_value
                # session may be a Session (with .state) or an ISessionState/adapter
                current_state: SessionState | SessionStateAdapter | None
                if session is None:
                    current_state = None
                elif hasattr(session, "state"):
                    current_state = cast(SessionState, session.state)
                else:
                    current_state = session
                # Many BaseCommandHandlers expect concrete SessionState; try best-effort
                param_value: Any = args if args else {}
                try:
                    result = self._inner.handle(param_value, current_state, None)
                    success: bool = getattr(result, "success", False)
                    message: str = getattr(result, "message", "")

                    # Get new state from the result
                    new_state: SessionState | SessionStateAdapter | None = getattr(
                        result, "new_state", None
                    )
                    # If the handler returned a new state and we were passed a
                    # SessionStateAdapter instance as the current_state, apply
                    # the new state to the adapter in-place so legacy tests that
                    # pass adapters observe mutated state.
                    try:
                        if new_state is not None and isinstance(
                            current_state, SessionStateAdapter
                        ):
                            if isinstance(new_state, SessionStateAdapter):
                                current_state._state = new_state._state
                            elif isinstance(new_state, SessionState):
                                current_state._state = new_state
                            else:
                                # If it's some other ISessionState, attempt to extract
                                # a concrete SessionState via to_dict/from_dict as a best-effort.
                                try:
                                    concrete = SessionState.from_dict(
                                        new_state.to_dict()
                                    )
                                    current_state._state = concrete  # type: ignore
                                except Exception:
                                    # Be defensive: if extraction fails, don't crash
                                    pass
                    except Exception:
                        # If import or manipulation fails, continue without applying
                        pass
                    logger.info(
                        f"Handler {self.name} result - success: {success}, has new_state: {new_state is not None}"
                    )
                    if new_state:
                        logger.info(f"New state from handler: {new_state}")
                    if success and new_state:
                        # Don't apply here - let the command service handle it
                        logger.info(
                            f"Got new state from {self.name} command, returning to command service"
                        )

                    return NewResult(
                        name=self.name,
                        success=success,
                        message=message,
                        data={},
                        new_state=new_state,  # Pass the new state through
                    )
                except Exception as e:
                    return NewResult(
                        name=self.name, success=False, message=str(e), data={}
                    )

        # Special case for help command - needs the registry
        help_ctor = self._handler_classes.get("help")
        if help_ctor:
            help_handler = _make(help_ctor)
            handlers.append(help_handler)
            self._handlers["help"] = help_handler

        # Create other handlers
        for name, ctor in self._handler_classes.items():
            if name == "help":
                continue
            handler = _make(ctor)
            # Wrap if no execute
            if not hasattr(handler, "execute") or not callable(handler.execute):
                handler = cast(ICommandHandler, _ExecuteAdapter(handler))
            handlers.append(handler)
            self._handlers[name] = handler

        # Update help handler with registry if it exists
        help_handler = self._handlers.get("help")
        if (
            help_handler is not None
            and hasattr(help_handler, "set_registry")
            and callable(help_handler.set_registry)
        ):
            help_handler.set_registry(self._handlers)

        return handlers

    def register_with_registry(self, registry: CommandRegistry) -> None:
        """Register all handlers with a command registry.

        Args:
            registry: The command registry to register with
        """
        # Create handlers if not already created
        if not self._handlers:
            self.create_handlers()

        # Adapter to bridge ICommandHandler to BaseCommand
        from src.core.domain.commands import BaseCommand

        class _BaseCommandAdapter(BaseCommand):
            def __init__(self, handler: ICommandHandler):
                self._handler: ICommandHandler = handler
                self._name: str = handler.name

            @property
            def name(self) -> str:
                return self._name

            @name.setter
            def name(self, value: str) -> None:
                self._name = value

            async def execute(self, *args: Any, **kwargs: Any) -> NewResult:
                # Expecting (args_dict, session, context)
                from typing import cast

                from src.core.domain.session import Session

                cmd_args: dict[str, Any] = args[0] if len(args) > 0 else {}
                session: Session | None = (
                    cast(Session, args[1]) if len(args) > 1 else None
                )
                context: dict[str, Any] | None = args[2] if len(args) > 2 else None
                result: NewResult = await self._handler.execute(cmd_args, session, context)  # type: ignore[arg-type]
                logger.info(
                    f"_BaseCommandAdapter for {self.name} - result has new_state: {hasattr(result, 'new_state') and result.new_state is not None}"
                )
                return result

        # Register each handler via adapter
        for _name, handler in self._handlers.items():
            registry.register(_BaseCommandAdapter(handler))

        logger.info(f"Registered {len(self._handlers)} command handlers with registry")


def register_command_handlers(registry: CommandRegistry) -> None:
    """Register all command handlers with a registry.

    Args:
        registry: The command registry to register with
    """
    factory = CommandHandlerFactory()
    factory.register_with_registry(registry)
