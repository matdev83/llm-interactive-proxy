import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import src.models as models
from fastapi import FastAPI
from .proxy_logic import ProxyState

from .commands import BaseCommand, CommandResult, create_command_instances
from .constants import DEFAULT_COMMAND_PREFIX

logger = logging.getLogger(__name__)


def parse_arguments(args_str: str) -> Dict[str, Any]:
    """Parse a comma separated key=value string into a dictionary."""
    logger.debug(f"Parsing arguments from string: '{args_str}'")
    args: Dict[str, Any] = {}
    if not args_str.strip():
        logger.debug("Argument string is empty, returning empty dict.")
        return args
    for part in args_str.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            args[key.strip()] = value
        else:
            args[part.strip()] = True
    return args


def get_command_pattern(command_prefix: str) -> re.Pattern:
    prefix_escaped = re.escape(command_prefix)
    # E501: Split pattern string for readability
    pattern_string = (
        rf"{prefix_escaped}(?:(?P<bare>hello|help)(?!\()\b|"
        r"(?P<cmd>[\w-]+)\((?P<args>[^)]*)\))"
    )
    return re.compile(pattern_string, re.VERBOSE)


class CommandParser:
    """Parse and apply proxy commands embedded in chat messages."""

    def __init__(
        self,
        proxy_state: ProxyState,
        app: FastAPI,
        command_prefix: str = DEFAULT_COMMAND_PREFIX,
        preserve_unknown: bool = True,
        functional_backends: Set[str] | None = None, # Line length check (80)
    ) -> None:
        self.proxy_state = proxy_state
        self.app = app
        self.command_prefix = command_prefix
        self.preserve_unknown = preserve_unknown
        self.command_pattern = get_command_pattern(command_prefix)
        self.handlers: Dict[str, BaseCommand] = {}
        self.functional_backends = functional_backends or set()

        # E501: Wrapped create_command_instances arguments
        for cmd_instance in create_command_instances(
            self.app, self.functional_backends
        ):
            self.register_command(cmd_instance)
        self.results: List[CommandResult] = []

    def register_command(self, command: BaseCommand) -> None:
        self.handlers[command.name.lower()] = command

    # ------------------------------------------------------------------
    def process_text(self, text_content: str) -> Tuple[str, bool]:
        logger.debug(f"Processing text for commands: '{text_content}'")
        commands_found = False
        modified_text = text_content

        matches = list(self.command_pattern.finditer(text_content))
        logger.debug( # E501: Wrapped log message
            f"Found {len(matches)} command matches for text: '{text_content}'"
        )
        for match in reversed(matches):
            commands_found = True
            command_full = match.group(0)
            if "bare" in match.groupdict() and match.group("bare"):
                command_name = match.group("bare").lower()
                args_str = ""
            else:
                command_name = match.group("cmd").lower()
                args_str = match.group("args")
            logger.debug( # E501: Wrapped log message
                f"Regex match: Full='{command_full}', Command='{command_name}', "
                f"ArgsStr='{args_str}'"
            )
            args = parse_arguments(args_str)

            replacement = ""
            handler = self.handlers.get(command_name)
            if handler:
                result = handler.execute(args, self.proxy_state)
                self.results.append(result)
                if not result.success:
                    return result.message, True
                if text_content.strip() == command_full.strip():
                    return "", True
            else:
                logger.warning(f"Unknown command: {command_name}.")
                # E501: Wrapped CommandResult arguments
                unknown_cmd_result = CommandResult(
                    command_name,
                    False,
                    f"unknown command: {command_name}"
                )
                self.results.append(unknown_cmd_result)
                if self.preserve_unknown:
                    replacement = command_full

            modified_text = (
                modified_text[: match.start()]
                + replacement
                + modified_text[match.end() :]
            )

        final_text = re.sub(r"\s+", " ", modified_text).strip()
        final_text = self._strip_xml_tags(final_text)
        logger.debug( # E501: Wrapped log message
            f"Text after command processing and normalization: '{final_text}'"
        )
        return final_text, commands_found

    def _strip_xml_tags(self, text: str) -> str:
        """Removes XML-like tags from a string."""
        return re.sub(r"<[^>]+>", "", text)

    def process_messages(
        self, messages: List[models.ChatMessage]
    ) -> Tuple[List[models.ChatMessage], bool]:
        self.results.clear()
        if not messages:
            logger.debug("process_messages received empty messages list.")
            return messages, False

        modified_messages = [msg.model_copy(deep=True) for msg in messages]
        any_command_processed_overall = False
        # Tracks if a command was executed in the specific message at this index
        message_had_executed_command = [False] * len(messages)
        # Ensures commands are only processed from the last message block that contains them
        already_executed_commands_in_a_message_sequence = False

        for i in range(len(modified_messages) - 1, -1, -1):
            msg = modified_messages[i]
            content_modified_this_iteration = False # Tracks if current msg was changed

            if not already_executed_commands_in_a_message_sequence:
                command_found_in_current_message = False
                if isinstance(msg.content, str):
                    # Process text for string content
                    processed_text, found_command_in_str = self.process_text(msg.content)
                    if found_command_in_str:
                        command_found_in_current_message = True
                        msg.content = processed_text
                        content_modified_this_iteration = True
                elif isinstance(msg.content, list):
                    # Process text for list content (e.g., multimodal)
                    new_parts: List[models.MessageContentPart] = []
                    found_command_in_list_parts = False
                    for part_idx, part in enumerate(msg.content):
                        if isinstance(part, models.MessageContentPartText):
                            processed_text, found_in_part = self.process_text(part.text)
                            if found_in_part:
                                found_command_in_list_parts = True
                            # Add part if it's not empty OR if it was originally empty and no command was in it (to preserve original empty parts)
                            # If a command was found, processed_text might be empty, this is handled later by final_messages logic
                            new_parts.append(models.MessageContentPartText(type="text", text=processed_text))
                        else:
                            new_parts.append(part.model_copy(deep=True))

                    if found_command_in_list_parts:
                        command_found_in_current_message = True
                        msg.content = new_parts # Update message content with processed parts
                        content_modified_this_iteration = True

                if command_found_in_current_message:
                    any_command_processed_overall = True
                    message_had_executed_command[i] = True # Mark command execution for this message index
                    already_executed_commands_in_a_message_sequence = True # Stop processing earlier messages for commands
                    logger.debug(
                        f"Command processed in message index {i} (from end). Role: {msg.role}."
                    )

            if content_modified_this_iteration:
                logger.info(
                    f"Content modified for message index {i} (from end). Role: {msg.role}. New content: '{msg.content}'"
                )

        final_messages: List[models.ChatMessage] = []
        for idx, msg in enumerate(modified_messages):
            is_content_effectively_empty = False
            if isinstance(msg.content, str):
                is_content_effectively_empty = not msg.content.strip()
            elif isinstance(msg.content, list):
                if not msg.content:  # Empty list
                    is_content_effectively_empty = True
                else:
                    all_parts_are_empty_text = True
                    for part_item in msg.content:
                        if isinstance(part_item, models.MessageContentPartText):
                            if part_item.text.strip():
                                all_parts_are_empty_text = False
                                break
                        else: # Non-text part means content is not effectively empty
                            all_parts_are_empty_text = False
                            break
                    if all_parts_are_empty_text:
                        is_content_effectively_empty = True

            if is_content_effectively_empty:
                if message_had_executed_command[idx]:
                    logger.info(
                        f"Retaining message (index {idx}, role {msg.role}) as empty/whitespace "
                        "because an executed command was processed in it."
                    )
                    final_messages.append(msg)
                else:
                    logger.info(
                        f"Removing message (index {idx}, role {msg.role}) as its content is "
                        "empty/whitespace and no command was executed in it."
                    )
            else:
                final_messages.append(msg)

        if not final_messages and any_command_processed_overall and messages:
            logger.info(
                "All messages were removed after command processing, but commands were processed. "
                "This implies all original messages led to empty content post-command execution "
                "and none were marked for retention due to containing an executed command (which might be a bug if commands were expected to leave content)."
            )

        logger.debug(
            f"Finished processing messages. Final message count: {len(final_messages)}. "
            f"Commands processed overall: {any_command_processed_overall}"
        )
        return final_messages, any_command_processed_overall


def _process_text_for_commands(
    text_content: str,
    current_proxy_state: ProxyState,
    command_pattern: re.Pattern,
    app: FastAPI,
    functional_backends: Set[str] | None = None,
) -> Tuple[str, bool]:
    parser = CommandParser(
        current_proxy_state,
        app,
        command_prefix="",
        functional_backends=functional_backends,
    )
    parser.command_pattern = command_pattern
    return parser.process_text(text_content)


def process_commands_in_messages(
    messages: List[models.ChatMessage],
    current_proxy_state: ProxyState,
    app: Optional[FastAPI] = None,
    command_prefix: str = DEFAULT_COMMAND_PREFIX,
) -> Tuple[List[models.ChatMessage], bool]:
    if not messages:
        return messages, False

    functional_backends: Optional[Set[str]] = None
    if app and hasattr(app, "state") and hasattr(app.state, "functional_backends"):
        functional_backends = app.state.functional_backends
    else:
        logger.warning( # E501: Wrapped
            "FastAPI app instance or functional_backends not available in "
            "app.state. CommandParser will be initialized without specific "
            "functional_backends."
        )

    parser = CommandParser(
        proxy_state=current_proxy_state,
        app=app,  # type: ignore
        command_prefix=command_prefix,
        functional_backends=functional_backends,
    )

    return parser.process_messages(messages)
