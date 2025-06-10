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
        # Process only the first match
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
        final_text = self._clean_remaining_text(final_text)
        logger.debug( # E501: Wrapped log message
            f"Text after command processing and normalization: '{final_text}'"
        )
        return final_text, commands_found

    def _clean_remaining_text(self, text: str) -> str:
        """Remove XML-like tags and comment lines from text."""
        text = re.sub(r"<[^>]+>", "", text)
        text = COMMENT_LINE_PATTERN.sub("", text)
        return text

    def process_messages(
        self, messages: List[models.ChatMessage]
    ) -> Tuple[List[models.ChatMessage], bool]:
        self.results.clear()
        if not messages:
            logger.debug("process_messages received empty messages list.")
            return messages, False

        modified_messages = [msg.model_copy(deep=True) for msg in messages]
        any_command_processed = False
        already_processed_commands_in_a_message = False

        for i in range(len(modified_messages) - 1, -1, -1):
            msg = modified_messages[i]
            content_modified = False

            if not already_processed_commands_in_a_message:
                if isinstance(msg.content, str):
                    if msg.content.strip().startswith(self.command_prefix):
                        command_match = self.command_pattern.match(msg.content.strip())
                        if command_match and msg.content.strip() == command_match.group(0):
                            processed_text, found = self.process_text(msg.content)
                            logger.debug(
                                f"Command-only message processed. Found: {found}"
                            )
                            if found:
                                any_command_processed = True
                                msg.content = ""
                                content_modified = True
                                already_processed_commands_in_a_message = True
                        else:
                            processed_text, found = self.process_text(msg.content)
                            logger.debug(
                                f"Non-command-only message processed. Found: {found}"
                            )
                            if found:
                                msg.content = processed_text
                                any_command_processed = True
                                content_modified = True
                                already_processed_commands_in_a_message = True
                    else:
                        processed_text, found = self.process_text(msg.content)
                        logger.debug(
                            "Non-command-only message (not starting with prefix) "
                            f"processed. Found: {found}"
                        )
                        if found:
                            msg.content = processed_text
                            any_command_processed = True
                            content_modified = True
                            already_processed_commands_in_a_message = True
                elif isinstance(msg.content, list):
                    new_parts: List[models.MessageContentPart] = []
                    part_level_found_in_current_message = False
                    for part_idx, part in enumerate(msg.content):
                        if isinstance(part, models.MessageContentPartText):
                            if not already_processed_commands_in_a_message:
                                processed_text, found_in_part = self.process_text(
                                    part.text
                                )
                                if found_in_part:
                                    part_level_found_in_current_message = True
                                    any_command_processed = True
                                if processed_text.strip():
                                    new_parts.append(
                                        models.MessageContentPartText(
                                            type="text", text=processed_text
                                        )
                                    )
                                elif not found_in_part:
                                    new_parts.append(
                                        models.MessageContentPartText(
                                            type="text", text=processed_text
                                        )
                                    )
                            else:
                                new_parts.append(part.model_copy(deep=True))
                        else:
                            new_parts.append(part.model_copy(deep=True))

                    if part_level_found_in_current_message:
                        msg.content = new_parts
                        content_modified = True
                        already_processed_commands_in_a_message = True

            if content_modified:
                logger.info( # E501: Wrapped
                    f"Commands processed in message index {i} (from end). "
                    f"Role: {msg.role}. New content: '{msg.content}'"
                )

        final_messages: List[models.ChatMessage] = []
        for msg in modified_messages:
            if isinstance(msg.content, list) and not msg.content:
                logger.info(
                    f"Removing message (role: {msg.role}) as its multimodal "
                    "content became empty after command processing."
                )
                continue
            if isinstance(msg.content, str) and not msg.content.strip():
                original_msg = messages[len(final_messages)]
                if isinstance(
                    original_msg.content, str
                ) and original_msg.content.strip().startswith(self.command_prefix):
                    final_messages.append(msg)
                    continue
                logger.info(
                    f"Removing message (role: {msg.role}) as its content "
                    "became empty after command processing."
                )
                continue
            final_messages.append(msg)

        if not final_messages and any_command_processed and messages:
            logger.info(
                "All messages were removed after command processing. "
                "This might indicate a command-only request."
            )

        logger.debug( # E501: Wrapped
            f"Finished processing messages. Final message count: "
            f"{len(final_messages)}. Commands processed overall: {any_command_processed}"
        )
        return final_messages, any_command_processed


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
