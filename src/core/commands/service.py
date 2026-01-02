import inspect
import logging
from typing import TYPE_CHECKING, Any

from src.core.commands.handler import ICommandHandler
from src.core.commands.handlers.failover_command_handler import FailoverCommandHandler
from src.core.commands.models import Command, CommandResultWrapper
from src.core.commands.parser import CommandParser
from src.core.commands.pipeline import CommandMatchFilter, CommandTailExtractor
from src.core.commands.registry import get_all_commands, get_command_handler
from src.core.common.env_utils import get_env_flag
from src.core.common.exceptions import (
    NonForwardableEnforcementError,
    NonForwardableTagLimitExceededError,
)
from src.core.config.app_config import AppConfig
from src.core.domain import chat as models
from src.core.domain.chat import ChatMessage
from src.core.domain.non_forwardable import NonForwardableTagScope
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.command_policy_service_interface import ICommandPolicyService
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.command_state_service_interface import ICommandStateService
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageIdentityService,
    INonForwardableMessageRegistry,
)
from src.core.interfaces.session_service_interface import ISessionService

if TYPE_CHECKING:
    from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class NewCommandService(ICommandService):
    """
    A service for processing and executing commands using the new architecture.
    """

    def __init__(
        self,
        session_service: ISessionService,
        command_parser: CommandParser,
        strict_command_detection: bool = False,
        app_state: IApplicationState | None = None,
        tail_extractor: CommandTailExtractor | None = None,
        match_filter: CommandMatchFilter | None = None,
        command_state_service: ICommandStateService | None = None,
        command_policy_service: ICommandPolicyService | None = None,
        config: AppConfig | None = None,
        non_forwardable_registry: INonForwardableMessageRegistry | None = None,
        non_forwardable_identity_service: (
            INonForwardableMessageIdentityService | None
        ) = None,
    ):
        """
        Initializes the command service.

        Args:
            session_service: The session service.
            command_parser: The command parser.
            strict_command_detection: Backward-compatibility flag (deprecated).
            non_forwardable_registry: Optional registry for tagging non-forwardable messages.
            non_forwardable_identity_service: Optional service for computing message identities.
        """
        self.session_service = session_service
        self.command_parser = command_parser
        if not strict_command_detection:
            strict_command_detection = get_env_flag("STRICT_COMMAND_DETECTION", False)
        self.strict_command_detection = strict_command_detection
        self._app_state = app_state
        if command_state_service is None:
            raise ValueError("command_state_service must be provided")
        if command_policy_service is None:
            raise ValueError("command_policy_service must be provided")

        self._tail_extractor = tail_extractor or CommandTailExtractor()
        self._match_filter = match_filter or CommandMatchFilter()
        self._state_service = command_state_service
        self._policy_service = command_policy_service
        self._non_forwardable_registry = non_forwardable_registry
        self._non_forwardable_identity_service = non_forwardable_identity_service

        # Initialize command parser with app state command prefix if available
        try:
            resolved_prefix = self._policy_service.resolve_command_prefix(
                session=None,
                fallback_prefix=self.command_parser.command_prefix,
            )
            if resolved_prefix:
                self.command_parser.command_prefix = resolved_prefix
        except (
            AttributeError,
            ValueError,
            TypeError,
            RuntimeError,
        ) as exc:  # pragma: no cover - defensive
            # Expected exceptions from command policy service during prefix resolution
            # Use default prefix if resolution fails (backward compatible)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to resolve initial command prefix, using default: %s",
                    exc,
                    exc_info=True,
                )

    def _determine_command_prefix(self, session: "Session | None") -> str:
        """Resolve the effective command prefix for the provided session."""

        return self._policy_service.resolve_command_prefix(
            session, self.command_parser.command_prefix
        )

    async def process_commands(
        self, messages: list[ChatMessage], session_id: str
    ) -> ProcessedResult:
        """
        Processes a list of messages to identify and execute commands.

        Args:
            messages: The list of messages to process.
            session_id: The ID of the session.

        Returns:
            A ProcessedResult object.
        """
        if not messages:
            return ProcessedResult(
                modified_messages=[], command_executed=False, command_results=[]
            )

        session = await self._state_service.get_session(session_id)
        if not session:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Session '{session_id}' not found.")
            return ProcessedResult(
                modified_messages=messages, command_executed=False, command_results=[]
            )

        if self._policy_service.are_interactive_commands_disabled(session):
            return ProcessedResult(
                modified_messages=messages,
                command_executed=False,
                command_results=[],
            )

        prefix_for_session = self._determine_command_prefix(session)

        modified_messages = messages.copy()
        command_results: list[Any] = []
        command_executed = False

        tail_segment = self._tail_extractor.extract_tail_segment(modified_messages)
        if tail_segment.message_index is None or not tail_segment.content:
            return ProcessedResult(
                modified_messages=modified_messages,
                command_executed=False,
                command_results=[],
            )

        parsed_commands = self.command_parser.parse(
            tail_segment.content, command_prefix=prefix_for_session
        )

        filtered_commands = self._match_filter.filter_tail_commands(
            parsed_commands,
            tail_segment.content,
            tail_segment.message_index,
        )

        if not filtered_commands:
            return ProcessedResult(
                modified_messages=modified_messages,
                command_executed=False,
                command_results=[],
            )

        parsed_command = filtered_commands[-1].command
        command = parsed_command.command
        matched_text = parsed_command.matched_text

        # Create a copy of the message to avoid in-place modification of the original request
        orig_message = modified_messages[tail_segment.message_index]

        # Tag the original command message as non-forwardable before modification
        # This ensures the identity matches what clients might resubmit in history
        if (
            self._non_forwardable_registry is not None
            and self._non_forwardable_identity_service is not None
        ):
            try:
                identity = self._non_forwardable_identity_service.compute_identity(
                    orig_message
                )
                await self._non_forwardable_registry.tag_identities(
                    session_id=session_id,
                    identities=[identity],
                    scope=NonForwardableTagScope.NEVER_FORWARD,
                    reason="slash_command",
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Tagged command message as never-forward for session {session_id}, "
                        f"command={command.name}, identity={identity[:16]}..."
                    )
            except NonForwardableTagLimitExceededError:
                # Fail closed - capacity exceeded (Req 14.3, 10.1)
                raise
            except Exception as e:
                # Fail closed on any tagging failure to prevent leakage (Req 10.1)
                raise NonForwardableEnforcementError(
                    f"Failed to tag command message as non-forwardable: {e}",
                    details={"session_id": session_id},
                ) from e

        message = orig_message.model_copy()
        modified_messages[tail_segment.message_index] = message

        handler_class = get_command_handler(command.name)
        if not handler_class:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Command '{command.name}' not found.")
            # Tag invalid/unsupported commands too (requirement 2.4)
            if (
                self._non_forwardable_registry is not None
                and self._non_forwardable_identity_service is not None
            ):
                try:
                    identity = self._non_forwardable_identity_service.compute_identity(
                        orig_message
                    )
                    await self._non_forwardable_registry.tag_identities(
                        session_id=session_id,
                        identities=[identity],
                        scope=NonForwardableTagScope.NEVER_FORWARD,
                        reason="slash_command",
                    )
                except NonForwardableTagLimitExceededError:
                    # Fail closed - capacity exceeded (Req 14.3, 10.1)
                    raise
                except Exception as e:
                    # Fail closed on any tagging failure to prevent leakage (Req 10.1)
                    raise NonForwardableEnforcementError(
                        f"Failed to tag invalid command message as non-forwardable: {e}",
                        details={"session_id": session_id},
                    ) from e
            return ProcessedResult(
                modified_messages=modified_messages,
                command_executed=False,
                command_results=[],
            )

        if isinstance(message.content, str):
            original_content = message.content
            idx = original_content.rfind(matched_text)
            if idx != -1:
                before = original_content[:idx]
                after = original_content[idx + len(matched_text) :]
                message.content = (before + after).rstrip()
        elif isinstance(message.content, list):
            part_index = tail_segment.part_index
            if part_index is not None and 0 <= part_index < len(message.content):
                part = message.content[part_index]
                if isinstance(part, models.MessageContentPartText):
                    part_text = part.text
                    idx = part_text.rfind(matched_text)
                    if idx != -1:
                        before = part_text[:idx]
                        after = part_text[idx + len(matched_text) :]
                        new_text = (before + after).rstrip()
                        if not new_text:
                            message.content.pop(part_index)
                        else:
                            part.text = new_text

        handler = self._create_handler(handler_class, session)

        result = await handler.handle(command, session)

        # Wrap the result with command name for proper response formatting
        executed_command_name = command.name
        wrapped_result = CommandResultWrapper(executed_command_name, result)
        command_executed = True
        command_results.append(wrapped_result)

        # If, after command execution, there is no meaningful user content left,
        # return a command-only result to avoid unnecessary backend calls.
        def _has_meaningful_user_content(msgs: list[ChatMessage]) -> bool:
            for m in msgs:
                if m.role != "user":
                    continue
                if isinstance(m.content, str) and m.content.strip():
                    return True
                if isinstance(m.content, list) and len(m.content) > 0:
                    return True
            return False

        # Only treat as command-only for specific commands (e.g., failover commands)
        command_only_names = {
            "create-failover-route",
            "delete-failover-route",
            "list-failover-routes",
            "route-append",
            "route-clear",
            "route-list",
            "route-prepend",
        }
        should_command_only = (
            executed_command_name in command_only_names
            if executed_command_name is not None
            else False
        )

        if should_command_only and not _has_meaningful_user_content(modified_messages):
            final_modified = []
        else:
            final_modified = modified_messages

        return ProcessedResult(
            modified_messages=final_modified,
            command_executed=command_executed,
            command_results=command_results,
        )

    async def execute_command(
        self, command: Command, session_id: str
    ) -> CommandResultWrapper:
        """Executes a single command and returns the result."""
        session = await self._state_service.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found.")

        handler_class = get_command_handler(command.name)
        if not handler_class:
            raise ValueError(f"Command '{command.name}' not found.")

        handler = self._create_handler(handler_class, session)
        result = await handler.handle(command, session)
        return CommandResultWrapper(command.name, result)

    def _create_handler(
        self,
        handler_class: type[ICommandHandler],
        session: "Session | None",
    ) -> ICommandHandler:
        """Instantiate a handler with the dependencies it declares."""
        if handler_class is FailoverCommandHandler and session is not None:
            adapter = self._state_service.build_session_adapter(session)
            return handler_class(
                self,
                secure_state_access=adapter,
                secure_state_modification=adapter,
            )

        init_params = inspect.signature(handler_class.__init__).parameters
        if "policy_service" in init_params:
            return handler_class(self, policy_service=self._policy_service)

        return handler_class(self)

    async def get_command_handler(
        self, name: str
    ) -> (
        type[ICommandHandler] | None
    ):  # pragma: no cover - exercised via integration tests
        """Return the registered handler class for the provided command name."""
        return get_command_handler(name)

    async def get_all_commands(
        self,
    ) -> dict[
        str, ICommandHandler
    ]:  # pragma: no cover - exercised via integration tests
        """Return instantiated handlers for all registered commands."""
        handlers: dict[str, ICommandHandler] = {}
        for name, handler_class in sorted(get_all_commands().items()):
            handlers[name] = self._create_handler(handler_class, session=None)
        return handlers
