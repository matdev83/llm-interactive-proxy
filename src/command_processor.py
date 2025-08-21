import logging
import re
from typing import Any, cast

from src.command_config import CommandProcessorConfig
from src.core.domain.chat import MessageContentPart, MessageContentPartText
from src.core.domain.command_results import CommandResult

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


class CommandProcessor:
    """Handles the parsing and execution of a single command."""

    def __init__(
        self,
        config: "CommandProcessorConfig",
    ) -> None:
        self.config = config

    async def process_text_and_execute_command(
        self, text_content: str
    ) -> tuple[str, bool]:
        """Processes text for a single command and executes it."""
        commands_found = False
        modified_text = text_content

        match = self.config.command_pattern.search(text_content)
        if match:
            commands_found = True
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
            if command_handler:
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
                execution_result: CommandResult
                try:
                    # Provide context as a dict to support domain command expectations
                    context = {"app": self.config.app, "handlers": self.config.handlers}
                    coro_result = command_handler.execute(
                        args, temp_session, context
                    )  # type: ignore
                    if asyncio.iscoroutine(coro_result):
                        execution_result = await coro_result
                    else:
                        execution_result = coro_result
                except Exception:
                    # Fallback - try calling again with context dict but suppress errors
                    import contextlib

                    with contextlib.suppress(Exception):
                        execution_result = await command_handler.execute(
                            args, temp_session, {"app": self.config.app}
                        )  # type: ignore
                    if "execution_result" not in locals():
                        # Re-raise original exception to surface the error
                        raise

                # No need to convert legacy CommandResult anymore since we removed the imports
                self.config.command_results.append(execution_result)
                # If the command returned a new_state, apply it to the original proxy_state
                new_state = getattr(execution_result, "new_state", None)
                if new_state is not None:
                    # Debug
                    logger.debug(
                        f"execution_result: success={getattr(execution_result,'success',None)} message={getattr(execution_result,'message',None)} new_state_type={type(new_state)}"
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
                if text_content.strip() == command_full.strip():
                    return "", True
            else:
                logger.warning("Unknown command: %s.", command_name)
                error_message = f"cmd not found: {command_name}"
                unknown_cmd_result = CommandResult(
                    name=command_name,
                    success=False,
                    message=error_message,
                )
                self.config.command_results.append(unknown_cmd_result)
                if self.config.preserve_unknown:
                    replacement = command_full

            modified_text = (
                modified_text[: match.start()]
                + replacement
                + modified_text[match.end() :]
            )

        final_text = re.sub(r"\s+", " ", modified_text).strip()
        final_text = self._clean_remaining_text(final_text)
        logger.debug(
            "Text after command processing and normalization: '%s'", final_text
        )
        return final_text, commands_found

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
        try:
            while hasattr(concrete_state, "_state"):
                concrete_state = concrete_state._state
        except Exception:
            # If unwrapping fails, keep original
            concrete_state = new_state

        # Case 1: Session-like with update_state
        # Use isinstance check to appease static typing when possible
        from src.core.domain.session import Session as _Session

        if (
            isinstance(proxy, _Session)
            and hasattr(proxy, "update_state")
            and callable(proxy.update_state)
        ):
            logger.debug("Applying new_state via proxy.update_state")
            logger.debug(
                f"before update_state: proxy._state id={(getattr(proxy,'_state',None) and id(proxy._state))}"
            )
            # mypy: proxy may be an ISessionState adapter or concrete Session with update_state
            proxy.update_state(concrete_state)  # type: ignore[arg-type]
            logger.debug(
                f"after update_state: proxy._state id={(getattr(proxy,'_state',None) and id(proxy._state))}"
            )
            return

        # Case 2: Adapter with internal _state
        if hasattr(proxy, "_state"):
            try:
                logger.debug(
                    f"before set proxy._state id={(getattr(proxy,'_state',None) and id(proxy._state))}"
                )
                # If concrete_state is adapter (already unwrapped, unlikely here)
                if hasattr(concrete_state, "_state"):
                    # concrete_state._state should be SessionState
                    try:
                        logger.debug(
                            "concrete_state._state.backend_config.model=",
                            concrete_state._state.backend_config.model,
                        )
                    except Exception:
                        logger.debug(
                            "concrete_state._state.backend_config.model=<unavailable>"
                        )
                    proxy._state = concrete_state._state
                else:
                    try:
                        logger.debug(
                            "concrete_state.backend_config.model=",
                            concrete_state.backend_config.model,
                        )
                    except Exception:
                        logger.debug(
                            "concrete_state.backend_config.model=<unavailable>"
                        )
                    proxy._state = concrete_state
                logger.debug(
                    f"after set proxy._state id={(getattr(proxy,'_state',None) and id(proxy._state))}"
                )
                try:
                    logger.debug(
                        "proxy._state.backend_config.model(after)=",
                        proxy._state.backend_config.model,
                    )
                except Exception:
                    logger.debug(
                        "proxy._state.backend_config.model(after)=<unavailable>"
                    )
                logger.debug(
                    "Applied new_state to proxy._state; proxy._state type=%s",
                    type(proxy._state),
                )
                return
            except Exception:
                pass

        # Case 3: Fallback try dict conversion
        try:
            if hasattr(proxy, "to_dict") and hasattr(concrete_state, "to_dict"):
                # attempt to set via from_dict -> adapter
                from src.core.domain.session import SessionState

                if isinstance(concrete_state, dict):
                    new_session_state = SessionState.from_dict(concrete_state)
                    if hasattr(proxy, "_state"):
                        # proxy._state may be an IValueObject adapter; assign carefully
                        import contextlib

                        with contextlib.suppress(Exception):
                            proxy._state = new_session_state  # type: ignore[attr-defined]
                    else:
                        # last resort
                        from src.core.domain.session import SessionStateAdapter

                        # Prefer replacing the configured proxy_state with a new adapter
                        try:
                            # cast new_session_state to concrete SessionState for adapter ctor
                            from src.core.domain.session import SessionState

                            self.config.proxy_state = SessionStateAdapter(cast(SessionState, new_session_state))  # type: ignore[attr-defined]
                        except Exception:
                            import contextlib

                            with contextlib.suppress(Exception):
                                # assign via dynamic attribute to avoid mypy attribute errors
                                cast(Any, proxy).state = new_session_state
            return
        except Exception:
            return

    def _clean_remaining_text(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = COMMENT_LINE_PATTERN.sub("", text)
        return text

    async def handle_string_content(
        self,
        msg_content: str,
    ) -> tuple[str, bool, bool]:
        original_content = msg_content
        processed_text, command_found = await self.process_text_and_execute_command(
            original_content
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
        self,
        part: MessageContentPart,
    ) -> tuple[MessageContentPart | None, bool]:
        """Processes a single part of a message."""
        if not isinstance(part, MessageContentPartText):
            return part.model_copy(deep=True), False

        processed_text, found_in_part = await self.process_text_and_execute_command(
            part.text
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
            return (
                MessageContentPartText(type="text", text=processed_text),
                False,
            )

        return None, False  # No command, and text is empty

    async def handle_list_content(
        self,
        msg_content_list: list[MessageContentPart],
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
