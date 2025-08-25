import logging
import re
from typing import Any, cast

from src.command_config import CommandProcessorConfig
from src.core.domain.chat import MessageContentPart, MessageContentPartText
from src.core.domain.command_results import CommandResult
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.session import SessionState  # Import SessionState
from src.core.interfaces.command_processor_interface import ICommandProcessor

logger = logging.getLogger(__name__)

# Regex matching comment lines that should be ignored when detecting
# command-only messages. This helps to strip agent-provided context such as
# "# foo" lines that might precede a user command.
COMMENT_LINE_PATTERN = re.compile(r"^\s*#[^\n]*\n?", re.MULTILINE)


def parse_arguments(args_str: str) -> dict[str, Any]:
    """Parse a comma separated key=value string into a dictionary."""
    logger.debug("Parsing arguments from string: '%s'", args_str)
    args: dict[str, Any] = {}
    if not args_str.strip():
        logger.debug("Argument string is empty, returning empty dict.")
        return args
    for part in args_str.split(","):
        if "=" in part:
            key, param_value = part.split("=", 1)
            param_value = param_value.strip()
            if (param_value.startswith('"') and param_value.endswith('"')) or (
                param_value.startswith("'") and param_value.endswith("'")
            ):
                param_value = param_value[1:-1]
            args[key.strip()] = param_value
        else:
            args[part.strip()] = True
    return args


def get_command_pattern(command_prefix: str) -> re.Pattern:
    prefix_escaped = re.escape(command_prefix)
    # Updated regex to correctly handle commands with and without arguments.
    # - (?P<cmd>[\w-]+) captures the command name.
    # - (?:\s*\((?P<args>[^)]*)\))? is an optional non-capturing group for arguments.
    pattern_string = rf"{prefix_escaped}(?P<cmd>[\w-]+)" r"(?:\s*\((?P<args>[^)]*)\))?"
    return re.compile(pattern_string, re.VERBOSE)


class CommandProcessor(ICommandProcessor):
    """Handles the parsing and execution of a single command."""

    def __init__(self, config: "CommandProcessorConfig") -> None:
        self.config = config

    async def process_messages(
        self, messages: list[Any], session_id: str, context: Any | None = None
    ) -> ProcessedResult:
        """Processes a list of messages, identifies and executes commands, and returns the modified messages."""
        if not messages:
            return ProcessedResult(
                modified_messages=[], command_executed=False, command_results=[]
            )

        # Create a mutable copy of the messages to avoid changing the original list
        # Ensure we are copying dictionaries if messages are dicts, or other objects if they are Pydantic models
        modified_messages = [
            msg.model_copy(deep=True) if hasattr(msg, "model_copy") else msg.copy()
            for msg in messages
        ]
        any_command_executed = False
        all_command_results: list[CommandResult] = []

        # Process the last message first
        last_message = modified_messages[-1]
        content = getattr(last_message, "content", None)

        if isinstance(content, str):
            (
                processed_content,
                command_found,
                content_modified,
            ) = await self.handle_string_content(content)
            if command_found:
                any_command_executed = True
                all_command_results.extend(self.config.command_results)
                self.config.command_results.clear()  # Clear after collecting

            if content_modified:
                if hasattr(last_message, "model_copy"):
                    modified_messages[-1] = last_message.model_copy(
                        update={"content": processed_content}
                    )
                else:
                    last_message["content"] = processed_content
        elif isinstance(content, list):
            (
                processed_list,
                command_found,
                content_modified,
            ) = await self.handle_list_content(content)
            if command_found:
                any_command_executed = True
                all_command_results.extend(self.config.command_results)
                self.config.command_results.clear()  # Clear after collecting

            if content_modified:
                if hasattr(last_message, "model_copy"):
                    modified_messages[-1] = last_message.model_copy(
                        update={"content": processed_list}
                    )
                else:
                    last_message["content"] = processed_list

        # If a command was executed in the last message, we are done.
        # Otherwise, check previous messages.
        if not any_command_executed:
            for i in range(len(modified_messages) - 2, -1, -1):
                message = modified_messages[i]
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    (
                        processed_content,
                        command_found,
                        content_modified,
                    ) = await self.handle_string_content(content)
                    if command_found:
                        any_command_executed = True
                        all_command_results.extend(self.config.command_results)
                        self.config.command_results.clear()  # Clear after collecting
                        if content_modified:
                            if hasattr(message, "model_copy"):
                                modified_messages[i] = message.model_copy(
                                    update={"content": processed_content}
                                )
                            else:
                                message["content"] = processed_content
                        # Stop after the first command from the end is found and processed.
                        break
                elif isinstance(content, list):
                    (
                        processed_list,
                        command_found,
                        content_modified,
                    ) = await self.handle_list_content(content)
                    if command_found:
                        any_command_executed = True
                        all_command_results.extend(self.config.command_results)
                        self.config.command_results.clear()
                        if content_modified:
                            if hasattr(message, "model_copy"):
                                modified_messages[i] = message.model_copy(
                                    update={"content": processed_list}
                                )
                            else:
                                message["content"] = processed_list
                        break

        return ProcessedResult(
            modified_messages=modified_messages,
            command_executed=any_command_executed,
            command_results=all_command_results,
        )

    async def process_text_and_execute_command(
        self, text_content: str, *, normalize_whitespace: bool = True
    ) -> tuple[str, bool]:
        """Processes text for a single command and executes it."""
        commands_found = False
        modified_text = text_content

        match = self.config.command_pattern.search(text_content)
        if match:
            commands_found = True
            executed_first = False
            # Work on a moving window to remove additional commands when asked
            while match is not None:
                command_full = match.group(0)
                command_name = match.group("cmd").lower()
                args_str = match.group("args") or ""
                logger.debug(
                    "Regex match: Full='%s', Command='%s', ArgsStr='%s'",
                    command_full,
                    command_name,
                    args_str,
                )
                args = parse_arguments(args_str)

                replacement = ""
                command_handler = self.config.handlers.get(command_name)
                if command_handler and not executed_first:
                    # Get the result from the command handler
                    # New BaseCommand classes have async execute methods
                    import asyncio

                    # Create a temporary session for the command execution
                    from src.core.domain.session import Session

                    # Always create a proper Session object
                    # Type ignore because we're ensuring temp_session is always a Session
                    if hasattr(self.config.proxy_state, "session_id"):
                        # It's already a proper session object
                        temp_session: Session = self.config.proxy_state  # type: ignore
                    else:
                        # It's a state object, wrap it in a session
                        temp_session = Session(
                            session_id="temp", state=self.config.proxy_state
                        )

                    # Handle both async and sync execute methods
                    execution_result: CommandResult | None = None
                    try:
                        # Provide context as a dict to support domain command expectations
                        context = {
                            "app": self.config.app,
                            "handlers": self.config.handlers,
                        }
                        coro_result = command_handler.execute(args, temp_session, context)  # type: ignore
                        if asyncio.iscoroutine(coro_result):
                            execution_result = await coro_result
                    except Exception:
                        # Fallback - try calling again with context dict but suppress errors
                        import contextlib

                        with contextlib.suppress(Exception):
                            execution_result = await command_handler.execute(
                                args, temp_session, {"app": self.config.app}
                            )  # type: ignore

                        # If we still don't have a result, we'll handle the error later
                        if execution_result is None:  # type: ignore[unreachable]
                            execution_result = await command_handler.execute(
                                args, temp_session, {"app": self.config.app}
                            )  # type: ignore

                    if execution_result:
                        self.config.command_results.append(execution_result)
                    new_state = getattr(execution_result, "new_state", None)
                    if new_state is not None:
                        logger.debug(
                            f"execution_result: success={getattr(execution_result, 'success', None)} message={getattr(execution_result, 'message', None)} new_state_type={type(new_state)}"
                        )
                        try:
                            self._apply_new_state(new_state)
                            logger.debug("_apply_new_state completed")
                        except Exception as e:
                            logger.debug(f"_apply_new_state failed: {e}")
                            logger.debug(
                                "Could not apply new_state to proxy_state: %s",
                                type(self.config.proxy_state),
                            )
                    # If this is a pure command (the entire text is just the command),
                    # return empty string to clear the content
                    if text_content.strip() == command_full.strip():
                        return "", True
                    executed_first = True
                else:
                    # Unknown command or subsequent commands when normalize_whitespace is False
                    if not command_handler:
                        logger.warning("Unknown command: %s.", command_name)
                        error_message = f"cmd not found: {command_name}"
                        unknown_cmd_result = CommandResult(
                            name=command_name, success=False, message=error_message
                        )
                        self.config.command_results.append(unknown_cmd_result)
                    # For CommandParser path (normalize_whitespace=False), always remove unknown and subsequent commands.
                    # For direct calls (normalize_whitespace=True), respect preserve_unknown on the first (and only) pass.
                    if (
                        normalize_whitespace
                        and self.config.preserve_unknown
                        and not executed_first
                        and not command_handler
                    ):
                        replacement = command_full
                    else:
                        replacement = ""

                # Remove the command text without altering surrounding whitespace.
                before_command = modified_text[: match.start()]
                after_command = modified_text[match.end() :]
                modified_text = before_command + replacement + after_command

                # Continue scanning only when preserving whitespace (CommandParser path)
                if normalize_whitespace:
                    break
                else:
                    match = self.config.command_pattern.search(modified_text)

        # Optionally normalize: collapse internal whitespace and trim ends
        if normalize_whitespace:
            final_text = re.sub(r"\s+", " ", modified_text).strip()
            logger.debug("Text after command processing (normalized): '%s'", final_text)
            return final_text, commands_found
        else:
            logger.debug(
                "Text after command processing (whitespace preserved): '%s'",
                modified_text,
            )
            return modified_text, commands_found

    def _apply_new_state(self, new_state: Any) -> None:
        """Normalize and apply a new_state returned by a command to the parser proxy_state.

        Handles the following proxy_state shapes:
        - `Session` instances exposing `update_state` or `state` setter
        - `SessionStateAdapter` instances with mutable `_state`
        - Raw dict-like or other objects (attempt to convert via to_dict/from_dict)
        """
        # If proxy_state is a Session with update_state
        proxy = self.config.proxy_state
        # Use print for test-time visibility (tests run with logging suppressed)
        logger.debug(
            f"_apply_new_state called: proxy_type={type(proxy)}, new_state_type={type(new_state)}"
        )

        # Handle interactive_just_enabled flag specially - this needs to be propagated
        # from the command result to the proxy state
        prop = getattr(type(proxy), "interactive_just_enabled", None)
        if (
            hasattr(new_state, "interactive_just_enabled")
            and hasattr(proxy, "interactive_just_enabled")
            and isinstance(prop, property)
            and getattr(prop, "fset", None) is not None
        ):
            try:
                # Use type ignore to bypass the read-only check for compatibility
                proxy.interactive_just_enabled = new_state.interactive_just_enabled  # type: ignore[misc]
                logger.debug(
                    f"Propagated interactive_just_enabled={new_state.interactive_just_enabled} to proxy state"
                )
            except Exception as e:
                logger.warning(f"Failed to propagate interactive_just_enabled: {e}")

        # If new_state is an adapter, unwrap repeatedly to get concrete SessionState
        concrete_state = new_state
        # Only unwrap if it's an adapter that actually *wraps* another state
        # Check if concrete_state has _state and that _state is not concrete_state itself to avoid infinite loop
        while (
            hasattr(concrete_state, "_state")
            and concrete_state._state is not concrete_state
        ):
            concrete_state = concrete_state._state

        # Case 1: Session-like with update_state
        from src.core.domain.session import SessionStateAdapter
        from src.core.interfaces.domain_entities_interface import ISessionState

        # Case 2: Adapter with internal _state (e.g., SessionStateAdapter)
        # Explicitly check if proxy is SessionStateAdapter to safely access _state
        if isinstance(proxy, SessionStateAdapter):
            try:
                # If concrete_state is adapter (already unwrapped, unlikely here)
                if hasattr(concrete_state, "_state"):
                    # concrete_state._state should be SessionState
                    # Cast the result of getattr to SessionState to satisfy type checker
                    inner_state = concrete_state._state
                    if isinstance(inner_state, SessionState):
                        proxy._state = inner_state
                    else:
                        # If it's not a SessionState, log a warning and don't assign
                        logger.warning(
                            f"Inner state is not a SessionState: {type(inner_state)}"
                        )
                else:
                    # concrete_state is the final state. It should be SessionState.
                    # Cast the concrete_state to SessionState to satisfy type checker
                    if isinstance(concrete_state, SessionState):
                        proxy._state = concrete_state
                    else:
                        # If it's not a SessionState, log a warning and don't assign
                        logger.warning(
                            f"Concrete state is not a SessionState: {type(concrete_state)}"
                        )
                logger.debug(
                    "Applied new_state to proxy._state; proxy._state type=%s",
                    type(proxy._state),
                )
                return
            except Exception as e:
                logger.warning(f"Failed to apply new_state to SessionStateAdapter: {e}")
        # If proxy is an ISessionState (but not SessionStateAdapter) and concrete_state is also ISessionState
        # We can't directly assign _state, but we can try to update fields if they exist and are mutable.
        # This is a more generic approach, though less reliable than the SessionStateAdapter path.
        # Note: This check is after the SessionStateAdapter check, so we're dealing with other ISessionState implementations
        elif isinstance(proxy, ISessionState) and isinstance(
            concrete_state, ISessionState
        ):
            # This is a fallback for other ISessionState implementations.
            # It's not as robust as the SessionStateAdapter path.
            # For now, we'll just log and return, as direct field assignment is complex and error-prone
            # without knowing the exact implementation details of the ISessionState.
            logger.debug(
                "Proxy and concrete_state are both ISessionState, but not SessionStateAdapter. Cannot directly assign _state."
            )
            return

        # Case 3: Fallback try dict conversion
        try:
            if (
                hasattr(proxy, "to_dict")
                and hasattr(concrete_state, "to_dict")
                and isinstance(concrete_state, dict)
            ):
                # SessionState.from_dict returns IValueObject, so we need to cast it.
                new_session_state_value = SessionState.from_dict(concrete_state)
                # Ensure the returned object is indeed a SessionState
                if not isinstance(new_session_state_value, SessionState):
                    logger.warning(
                        f"SessionState.from_dict did not return a SessionState: {type(new_session_state_value)}"
                    )
                    return
                # Cast to SessionState to satisfy type checker
                new_session_state = cast(SessionState, new_session_state_value)

                # If proxy is SessionStateAdapter, we can assign to _state
                if isinstance(proxy, SessionStateAdapter):
                    try:
                        proxy._state = new_session_state
                        logger.debug(
                            "Applied new_state to SessionStateAdapter._state via dict conversion."
                        )
                        return
                    except Exception as e:
                        logger.warning(
                            f"Failed to assign to SessionStateAdapter._state: {e}"
                        )

                # If proxy is not SessionStateAdapter, try to update the config.proxy_state
                # This is a last resort and might not always work as expected.
                else:
                    try:
                        from src.core.domain.session import SessionStateAdapter

                        self.config.proxy_state = SessionStateAdapter(new_session_state)
                        logger.debug(
                            "Replaced config.proxy_state with new SessionStateAdapter via dict conversion."
                        )
                        return
                    except Exception as e:
                        logger.warning(
                            f"Failed to replace config.proxy_state with new SessionStateAdapter: {e}"
                        )

            # If we can't do dict conversion, log and return
            logger.debug("Could not apply new_state via dict conversion.")
            return
        except Exception as e:
            logger.warning(f"Exception during dict conversion attempt: {e}")
            return

    def _clean_remaining_text(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = COMMENT_LINE_PATTERN.sub("", text)
        return text

    async def handle_string_content(self, msg_content: str) -> tuple[str, bool, bool]:
        original_content = msg_content
        processed_text, command_found = await self.process_text_and_execute_command(
            original_content, normalize_whitespace=False
        )
        content_modified = command_found or processed_text != original_content

        if command_found:
            original_content_stripped = original_content.strip()
            is_prefix_match = original_content_stripped.startswith(
                self.config.command_pattern.pattern.split("(")[0].replace(
                    "\\", ""
                )  # Extract prefix from pattern
            )
            command_pattern_match = None
            if is_prefix_match:
                command_pattern_match = self.config.command_pattern.match(
                    original_content_stripped
                )

            is_full_command_match_condition = False
            if command_pattern_match:
                is_full_command_match_condition = (
                    original_content_stripped == command_pattern_match.group(0)
                )

            if (
                is_prefix_match
                and command_pattern_match
                and is_full_command_match_condition
                and processed_text == ""
            ) or processed_text != original_content:
                content_modified = True

        return processed_text, command_found, content_modified

    async def process_single_part(
        self, part: MessageContentPart
    ) -> tuple[MessageContentPart | None, bool]:
        """Processes a single part of a message."""
        if not isinstance(part, MessageContentPartText):
            return part.model_copy(deep=True), False

        processed_text, found_in_part = await self.process_text_and_execute_command(
            part.text, normalize_whitespace=False
        )

        if found_in_part:
            if (
                not processed_text.strip()
            ):  # Command processed AND resulted in empty text
                return None, True  # Drop the part, but signal command was handled
            return MessageContentPartText(type="text", text=processed_text), True

        # No command found in this part
        if (
            processed_text.strip()
        ):  # If text remains (e.g. from cleaning non-command text)
            return (MessageContentPartText(type="text", text=processed_text), False)

        return None, False  # No command, and text is empty

    async def handle_list_content(
        self, msg_content_list: list[MessageContentPart]
    ) -> tuple[list[MessageContentPart], bool, bool]:
        new_parts: list[MessageContentPart] = []
        any_command_found_overall = (
            False  # Tracks if any command was found in any part of this list
        )
        list_actually_changed = False

        command_processed_within_this_list = (
            False  # Flag for this specific list processing pass
        )

        if not msg_content_list:
            return [], False, False

        original_parts_copy = [part.model_copy(deep=True) for part in msg_content_list]
        # new_parts is already initialized above

        for original_part in original_parts_copy:  # Iterate over copy
            processed_part_current_iteration: MessageContentPart | None = None
            command_found_in_this_specific_part = False

            if not command_processed_within_this_list:
                # If no command has been processed yet in this list, try to process this part
                (
                    processed_part_current_iteration,
                    command_found_in_this_specific_part,
                ) = await self.process_single_part(original_part)

                if command_found_in_this_specific_part:
                    any_command_found_overall = (
                        True  # Mark that a command was found somewhere in this list
                    )
                    command_processed_within_this_list = (
                        True  # Stop processing further parts for commands
                    )
            else:
                # A command was already found and processed in a previous part of this list.
                # Add this part as is (it's a copy from original_parts_copy).
                processed_part_current_iteration = original_part

            if processed_part_current_iteration is not None:
                new_parts.append(processed_part_current_iteration)

        # Determine if the list's content actually changed by comparing new_parts with original_parts_copy
        if len(new_parts) != len(original_parts_copy):
            list_actually_changed = True
        else:
            if new_parts != original_parts_copy:
                list_actually_changed = True

        # should_consider_modified is True if a command was found OR the list content changed.
        should_consider_modified = any_command_found_overall or list_actually_changed

        return new_parts, any_command_found_overall, should_consider_modified
