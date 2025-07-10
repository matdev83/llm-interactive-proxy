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
                # Always return empty string for command-only messages, regardless of success/failure
                # The error will be handled through the command_results and XML wrapping in main.py
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
            if not processed_text.strip(): # Command processed AND resulted in empty text
                return None, True  # Drop the part, but signal command was handled
            return models.MessageContentPartText(type="text", text=processed_text), True

        # No command found in this part
        if processed_text.strip(): # If text remains (e.g. from cleaning non-command text)
            return models.MessageContentPartText(type="text", text=processed_text), False

        return None, False # No command, and text is empty

    def _handle_list_content(
        self,
        msg_content_list: List[models.MessageContentPart],
    ) -> Tuple[List[models.MessageContentPart], bool, bool]:
        new_parts: List[models.MessageContentPart] = []
        any_command_found_overall = False # Tracks if any command was found in any part of this list
        list_actually_changed = False

        command_processed_within_this_list = False # Flag for this specific list processing pass

        if not msg_content_list:
            return [], False, False

        new_parts: List[models.MessageContentPart] = [] # Initialize new_parts here
        original_parts_copy = [part.model_copy(deep=True) for part in msg_content_list]


        for original_part in original_parts_copy: # Iterate over copy
            processed_part_current_iteration: Optional[models.MessageContentPart] = None
            command_found_in_this_specific_part = False

            if not command_processed_within_this_list:
                # If no command has been processed yet in this list, try to process this part
                processed_part_current_iteration, command_found_in_this_specific_part = \
                    self._process_single_part(original_part)

                if command_found_in_this_specific_part:
                    any_command_found_overall = True # Mark that a command was found somewhere in this list
                    command_processed_within_this_list = True # Stop processing further parts for commands
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
            for i in range(len(new_parts)):
                if new_parts[i] != original_parts_copy[i]: # Assumes MessageContentPart has __eq__
                    list_actually_changed = True
                    break

        # should_consider_modified is True if a command was found OR the list content changed.
        should_consider_modified = any_command_found_overall or list_actually_changed

        return new_parts, any_command_found_overall, should_consider_modified

    def _is_content_effectively_empty(self, content: Any) -> bool:
        """Checks if message content is effectively empty after processing."""
        if isinstance(content, str):
            return not content.strip()
        if isinstance(content, list):
            if not content:  # An empty list is definitely empty
                return True
            # If the list has any non-text part (e.g., image), it's not empty.
            # If all parts are text parts, then it's empty if all those text parts are empty.
            for part in content:
                if not isinstance(part, models.MessageContentPartText):
                    return False  # Contains a non-text part (like an image), so not empty
                if part.text.strip():
                    return False  # Contains a non-empty text part
            return True  # All parts are empty text parts, or list was empty initially
        return False # Should not be reached if content is always str or list

    def _is_original_purely_command(self, original_content: Any) -> bool:
        """Checks if the original message content was purely a command, ignoring comments."""
        if not isinstance(original_content, str):
            # Assuming commands can only be in string content for "purely command" messages
            return False

        # Remove comment lines first
        content_without_comments = COMMENT_LINE_PATTERN.sub("", original_content).strip()

        if not content_without_comments: # If only comments or empty after stripping comments
            return False

        match = self.command_pattern.match(content_without_comments)
        # Check if the entire content (after comment removal and stripping) is the command
        return bool(match and content_without_comments == match.group(0))

    def _get_text_for_command_check(self, content: Any) -> str:
        """Extracts and prepares text from message content for command checking."""
        text_to_check = ""
        if isinstance(content, str):
            text_to_check = content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, models.MessageContentPartText):
                    text_to_check += part.text + " " # Add space to simulate separate words

        # Remove comments and strip whitespace for accurate command pattern matching
        return COMMENT_LINE_PATTERN.sub("", text_to_check).strip()

    def _execute_commands_in_target_message(
            self,
            target_idx: int,
            modified_messages: List[models.ChatMessage]
        ) -> bool:
        """Processes commands in the specified message and updates it.
        Returns True if a command was found and an attempt to execute it was made.
        """
        msg_to_process = modified_messages[target_idx]
        processed_content = None
        command_found_in_target_msg = False
        content_modified_by_cmd = False # Tracks if the content was actually changed by the command

        original_content_for_comparison = msg_to_process.content # Hold for comparison if not str/list

        if isinstance(msg_to_process.content, str):
            processed_content, command_found_in_target_msg, content_modified_by_cmd = \
                self._handle_string_content(msg_to_process.content)
        elif isinstance(msg_to_process.content, list):
            processed_content, command_found_in_target_msg, content_modified_by_cmd = \
                self._handle_list_content(msg_to_process.content)

        if command_found_in_target_msg:
            # Update content only if it was actually modified by the command processing
            # and processed_content is not None (it could be None if list content became empty)
            if content_modified_by_cmd and processed_content is not None:
                msg_to_process.content = processed_content
                logger.info(
                    "Content modified by command in message index %s. Role: %s.",
                    target_idx,
                    msg_to_process.role,
                )
            elif content_modified_by_cmd and processed_content is None and isinstance(original_content_for_comparison, list):
                # This case handles when a list content is entirely consumed by a command, resulting in None (empty list)
                msg_to_process.content = [] # Ensure it's an empty list
                logger.info(
                    "List content removed by command in message index %s. Role: %s.",
                    target_idx,
                    msg_to_process.role,
                )

            return True # A command was found and an attempt to execute it was made.
        return False

    def _filter_empty_messages(
            self,
            processed_messages: List[models.ChatMessage],
            original_messages: List[models.ChatMessage]
        ) -> List[models.ChatMessage]:
        """Filters out messages that became empty, unless they were purely commands."""
        final_messages: List[models.ChatMessage] = []
        for original_msg_idx, current_msg_state in enumerate(processed_messages):
            is_empty = self._is_content_effectively_empty(current_msg_state.content)

            if is_empty:
                original_content = original_messages[original_msg_idx].content
                if not self._is_original_purely_command(original_content):
                    logger.info(
                        "Removing message (role: %s, index: %s) as its content "
                        "became effectively empty after command processing and was not a pure command.",
                        current_msg_state.role,
                        original_msg_idx
                    )
                    continue
                else:
                    # Pure command became empty. Retain it, ensuring content is canonical empty.
                    current_msg_state.content = [] if isinstance(original_content, list) else ""
                    logger.info(
                        "Retaining message (role: %s, index: %s) as transformed empty content "
                        "because it was originally a pure command.",
                        current_msg_state.role,
                        original_msg_idx
                    )
            final_messages.append(current_msg_state)
        return final_messages

    def process_messages(
        self, messages: List[models.ChatMessage]
    ) -> Tuple[List[models.ChatMessage], bool]:
        self.command_results.clear()
        if not messages:
            logger.debug("process_messages received empty messages list.")
            return messages, False

        modified_messages = [msg.model_copy(deep=True) for msg in messages]
        overall_commands_processed = False

        # Stage 1: Find the last message that potentially contains a command
        target_message_idx_for_command_processing = -1
        for i in range(len(modified_messages) - 1, -1, -1):
            text_for_check = self._get_text_for_command_check(modified_messages[i].content)
            if self.command_pattern.search(text_for_check):
                target_message_idx_for_command_processing = i
                break

        if target_message_idx_for_command_processing != -1:
            overall_commands_processed = self._execute_commands_in_target_message(
                target_message_idx_for_command_processing, modified_messages
            )

        final_messages = self._filter_empty_messages(modified_messages, messages)

        if not final_messages and overall_commands_processed and messages: # `messages` here refers to original non-empty input
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

    final_messages, commands_processed = parser.process_messages(messages)

    # If a one-off command was just used, clear it after processing the request.
    # Clear oneoff route after any message processing where oneoff is set,
    # except when it's a pure command-only message (single message with empty content after command processing)
    if current_proxy_state.oneoff_backend or current_proxy_state.oneoff_model:
        # Check if this is a pure command-only message: single message with empty content and commands were processed
        is_pure_command_only = (
            len(final_messages) == 1 and
            commands_processed and
            final_messages[0].content.strip() == ""
        )

        if not is_pure_command_only:
            # This is either a command+prompt message or a follow-up prompt after command-only
            current_proxy_state.clear_oneoff_route()

    return final_messages, commands_processed
