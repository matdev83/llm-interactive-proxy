import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import src.models as models
from fastapi import FastAPI
from .proxy_logic import ProxyState

from .commands import BaseCommand, CommandResult, create_command_instances
from .constants import DEFAULT_COMMAND_PREFIX

logger = logging.getLogger(__name__)

# Regex matching comment lines that should be ignored when detecting
# command-only messages. This helps to strip agent-provided context such as
# "# foo" lines that might precede a user command.
COMMENT_LINE_PATTERN = re.compile(r"^\s*#[^\n]*\n?", re.MULTILINE)


def parse_arguments(args_str: str) -> Dict[str, Any]:
    """Parse a comma separated key=value string into a dictionary."""
    logger.debug(f"Parsing arguments from string: '{args_str}'")
    args: Dict[str, Any] = {}
    if not args_str.strip():
        logger.debug("Argument string is empty, returning empty dict.")
        return args
    for part in args_str.split(","):
        if "=" in part:
            key, param_value = part.split("=", 1)
            param_value = param_value.strip()
            if (param_value.startswith('"') and param_value.endswith('"')) or \
               (param_value.startswith("'") and param_value.endswith("'")):
                param_value = param_value[1:-1]
            args[key.strip()] = param_value
        else:
            args[part.strip()] = True
    return args


def get_command_pattern(command_prefix: str) -> re.Pattern:
    prefix_escaped = re.escape(command_prefix)
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
        functional_backends: Set[str] | None = None,
    ) -> None:
        self.proxy_state = proxy_state
        self.app = app
        self.command_prefix = command_prefix
        self.preserve_unknown = preserve_unknown
        self.command_pattern = get_command_pattern(command_prefix)
        self.handlers: Dict[str, BaseCommand] = {}
        self.functional_backends = functional_backends or set()

        for cmd_instance in create_command_instances(
            self.app, self.functional_backends
        ):
            self.register_command(cmd_instance)
        self.command_results: List[CommandResult] = []

    def register_command(self, command: BaseCommand) -> None:
        self.handlers[command.name.lower()] = command

    def process_text(self, text_content: str) -> Tuple[str, bool]:
        logger.debug(f"Processing text for commands: '{text_content}'")
        commands_found = False
        modified_text = text_content

        matches = list(self.command_pattern.finditer(text_content))
        logger.debug(
            "Found %s command matches for text: '%s'",
            len(matches),
            text_content,
        )
        if matches:
            match = matches[0]
            commands_found = True
            command_full = match.group(0)
            if "bare" in match.groupdict() and match.group("bare"):
                command_name = match.group("bare").lower()
                args_str = ""
            else:
                command_name = match.group("cmd").lower()
                args_str = match.group("args")
            logger.debug(
                "Regex match: Full='%s', Command='%s', ArgsStr='%s'",
                command_full,
                command_name,
                args_str,
            )
            args = parse_arguments(args_str)

            replacement = ""
            command_handler = self.handlers.get(command_name)
            if command_handler:
                execution_result = command_handler.execute(
                    args, self.proxy_state
                )
                self.command_results.append(execution_result)
                if not execution_result.success:
                    return execution_result.message, True
                if text_content.strip() == command_full.strip():
                    return "", True  # Command-only message, content becomes empty
            else:
                logger.warning(f"Unknown command: {command_name}.")
                error_message = f"cmd not found: {command_name}"
                unknown_cmd_result = CommandResult(
                    name=command_name,  # Changed from command_name
                    success=False,
                    message=error_message,
                )
                self.command_results.append(unknown_cmd_result)
                if self.preserve_unknown:
                    replacement = command_full

            # Only replace the first command occurrence
            modified_text = (
                modified_text[:match.start()] +
                replacement +
                modified_text[match.end():]
            )

        final_text = re.sub(r"\s+", " ", modified_text).strip()
        final_text = self._clean_remaining_text(final_text)
        logger.debug(
            "Text after command processing and normalization: '%s'", final_text
        )
        return final_text, commands_found

    def _clean_remaining_text(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = COMMENT_LINE_PATTERN.sub("", text)
        return text

    def _handle_string_content(
        self,
        msg_content: str,
    ) -> Tuple[str, bool, bool]:
        original_content = msg_content
        processed_text, command_found = self.process_text(original_content)

        content_modified = False
        if command_found:
            original_content_stripped = original_content.strip()
            is_prefix_match = original_content_stripped.startswith(
                self.command_prefix)
            command_pattern_match = None
            if is_prefix_match:
                command_pattern_match = self.command_pattern.match(
                    original_content_stripped)

            is_full_command_match_condition = False
            if command_pattern_match:
                is_full_command_match_condition = (
                    original_content_stripped == command_pattern_match.group(0)
                )

            if is_prefix_match and command_pattern_match and \
               is_full_command_match_condition and processed_text == "":
                content_modified = True
            elif processed_text != original_content:
                content_modified = True

        return processed_text, command_found, content_modified

    def _process_single_part(
        self,
        part: models.MessageContentPart,
    ) -> Tuple[Optional[models.MessageContentPart], bool]:
        """Processes a single part of a message."""
        if not isinstance(part, models.MessageContentPartText):
            return part.model_copy(deep=True), False

        processed_text, found_in_part = self.process_text(part.text)

        if found_in_part:
            return models.MessageContentPartText(
                type="text", text=processed_text
            ), True

        if processed_text.strip():
            return models.MessageContentPartText(
                type="text", text=processed_text
            ), False

        return None, False

    def _handle_list_content(
        self,
        msg_content_list: List[models.MessageContentPart],
    ) -> Tuple[List[models.MessageContentPart], bool, bool]:
        new_parts: List[models.MessageContentPart] = []
        any_command_found_in_list = False
        list_was_modified = False

        if not msg_content_list:
            return [], False, False

        for original_part in msg_content_list:
            processed_part, command_found = self._process_single_part(original_part)

            if command_found:
                any_command_found_in_list = True

            if processed_part is not None:
                new_parts.append(processed_part)

            if command_found or \
               (processed_part is None and original_part is not None) or \
               (processed_part is not None and original_part != processed_part):
                list_was_modified = True

        if not new_parts and any_command_found_in_list:
            return [], True, True

        if len(new_parts) != len(msg_content_list) and not any_command_found_in_list:
            list_was_modified = True

        return new_parts, any_command_found_in_list, list_was_modified

    def process_messages(
        self, messages: List[models.ChatMessage]
    ) -> Tuple[List[models.ChatMessage], bool]:
        self.command_results.clear()
        if not messages:
            logger.debug("process_messages received empty messages list.")
            return messages, False

        modified_messages = [msg.model_copy(deep=True) for msg in messages]
        overall_commands_processed = False
        last_message_had_command_processed = False

        for message_idx in range(len(modified_messages) - 1, -1, -1):
            msg = modified_messages[message_idx]
            current_msg_content_modified = False
            current_msg_command_found = False

            if last_message_had_command_processed:
                continue

            if isinstance(msg.content, str):
                str_content, str_found, str_modified = self._handle_string_content(
                    msg.content,
                )
                msg.content = str_content
                current_msg_content_modified = str_modified
                current_msg_command_found = str_found
            elif isinstance(msg.content, list):
                list_content, list_found, list_modified = self._handle_list_content(
                    msg.content,
                )
                msg.content = list_content
                current_msg_content_modified = list_modified
                current_msg_command_found = list_found

            if current_msg_command_found:
                overall_commands_processed = True
                last_message_had_command_processed = True

            if current_msg_content_modified:
                logger.info(
                    "Content modified in message index %s (from end). Role: %s.",
                    message_idx,
                    msg.role,
                )

        final_messages: List[models.ChatMessage] = []
        for original_msg_idx, msg in enumerate(modified_messages):
            is_empty_list_content = isinstance(msg.content, list) and not any(
                (isinstance(
                    part, models.MessageContentPartText) and part.text.strip()) or
                not isinstance(part, models.MessageContentPartText)
                for part in msg.content
            )
            is_empty_str_content = isinstance(
                msg.content, str) and not msg.content.strip()

            if is_empty_list_content:
                logger.info(
                    "Removing message (role: %s) as its list content "
                    "became effectively empty after command processing.",
                    msg.role,
                )
                continue

            if is_empty_str_content:
                original_msg = messages[original_msg_idx]
                is_original_purely_command = False
                if isinstance(original_msg.content, str):
                    command_match = self.command_pattern.match(
                        original_msg.content.strip())
                    if command_match and \
                       original_msg.content.strip() == command_match.group(0):
                        is_original_purely_command = True

                if not is_original_purely_command:
                    logger.info(
                        "Removing message (role: %s) as its string content "
                        "became empty and was not a pure command.",
                        msg.role,
                    )
                    continue

            final_messages.append(msg)

        if not final_messages and overall_commands_processed and messages:
            logger.info(
                "All messages were removed after command processing. "
                "This might indicate a command-only request."
            )

        logger.debug(
            "Finished processing messages. Final message count: %s. "
            "Commands processed overall: %s",
            len(final_messages),
            overall_commands_processed,
        )
        return final_messages, overall_commands_processed


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
    if app and hasattr(
            app,
            "state") and hasattr(
            app.state,
            "functional_backends"):
        functional_backends = app.state.functional_backends
    else:
        logger.warning(
            "FastAPI app instance or functional_backends not available in "
            "app.state. CommandParser will be initialized without specific "
            "functional_backends.",
        )

    parser = CommandParser(
        proxy_state=current_proxy_state,
        app=app,  # type: ignore
        command_prefix=command_prefix,
        functional_backends=functional_backends,
    )

    return parser.process_messages(messages)
