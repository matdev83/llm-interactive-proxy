import logging
import re
from typing import Any, Dict, List, Tuple, Set, Optional

import src.models as models
from fastapi import FastAPI

from .constants import DEFAULT_COMMAND_PREFIX
from .commands import BaseCommand, CommandResult, create_command_instances
from .proxy_logic import ProxyState

logger = logging.getLogger(__name__)


def parse_arguments(args_str: str) -> Dict[str, Any]:
    """Parse a comma separated key=value string into a dictionary."""
    logger.debug(f"Parsing arguments from string: '{args_str}'")
    args: Dict[str, Any] = {}
    if not args_str.strip():
        logger.debug("Argument string is empty, returning empty dict.")
        return args
    for part in args_str.split(','):
        if '=' in part:
            key, value = part.split('=', 1)
            value = value.strip()
            if (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            args[key.strip()] = value
        else:
            args[part.strip()] = True
    return args

def get_command_pattern(command_prefix: str) -> re.Pattern:
    prefix_escaped = re.escape(command_prefix)
    return re.compile(
        rf"{prefix_escaped}(?:(?P<bare>hello|help)(?!\()\b|(?P<cmd>[\w-]+)\((?P<args>[^)]*)\))",
        re.VERBOSE,
    )


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

        for cmd in create_command_instances(self.app, self.functional_backends):
            self.register_command(cmd)
        self.results: List[CommandResult] = []

    def register_command(self, command: BaseCommand) -> None:
        self.handlers[command.name.lower()] = command

    # ------------------------------------------------------------------
    def process_text(self, text_content: str) -> Tuple[str, bool]:
        logger.debug(f"Processing text for commands: '{text_content}'")
        commands_found = False
        modified_text = text_content

        matches = list(self.command_pattern.finditer(text_content))
        logger.debug(f"Found {len(matches)} command matches for text: '{text_content}'")
        for match in reversed(matches):
            commands_found = True
            command_full = match.group(0)
            # Check if the 'bare' group was matched (meaning it's a bare command)
            if "bare" in match.groupdict() and match.group("bare"):
                command_name = match.group("bare").lower()
                args_str = ""
            else: # It's a function-like command
                command_name = match.group("cmd").lower()
                args_str = match.group("args")
            logger.debug(
                f"Regex match: Full='{command_full}', Command='{command_name}', ArgsStr='{args_str}'"
            )
            args = parse_arguments(args_str)

            replacement = ""
            handler = self.handlers.get(command_name)
            if handler:
                result = handler.execute(args, self.proxy_state)
                self.results.append(result)
                if not result.success:
                    # If command failed, return the error message
                    return result.message, True
                # If this is the only content in the message, return empty string
                if text_content.strip() == command_full.strip():
                    return "", True
            else:
                logger.warning(f"Unknown command: {command_name}.")
                self.results.append(
                    CommandResult(command_name, False, f"unknown command: {command_name}")
                )
                if self.preserve_unknown:
                    replacement = command_full

            modified_text = modified_text[: match.start()] + replacement + modified_text[match.end() :]

        final_text = re.sub(r"\s+", " ", modified_text).strip()
        final_text = self._strip_xml_tags(final_text)
        logger.debug(f"Text after command processing and normalization: '{final_text}'")
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
        any_command_processed = False

        for i in range(len(modified_messages) - 1, -1, -1):
            msg = modified_messages[i]
            content_modified = False

            if isinstance(msg.content, str):
                if msg.content.strip().startswith(self.command_prefix):
                    command_match = self.command_pattern.match(msg.content.strip())
                    if command_match and msg.content.strip() == command_match.group(0):
                        processed_text, found = self.process_text(msg.content)
                        logger.debug(f"Command-only message processed. Found: {found}")
                        if found:
                            any_command_processed = True
                            msg.content = ""
                            content_modified = True
                    else:
                        processed_text, found = self.process_text(msg.content)
                        logger.debug(f"Message with prefix processed. Found: {found}")
                        if found:
                            msg.content = processed_text
                            any_command_processed = True
                            content_modified = True
                else:
                    processed_text, found = self.process_text(msg.content)
                    logger.debug(f"Non-command-only message processed. Found: {found}")
                    if found:
                        msg.content = processed_text
                        any_command_processed = True
                        content_modified = True
            elif isinstance(msg.content, list):
                new_parts: List[models.MessageContentPart] = []
                part_level_found = False
                for part in msg.content:
                    if isinstance(part, models.MessageContentPartText):
                        processed_text, found = self.process_text(part.text)
                        if found:
                            part_level_found = True
                            any_command_processed = True
                        if processed_text.strip():
                            new_parts.append(models.MessageContentPartText(type="text", text=processed_text))
                        elif not found:
                            new_parts.append(models.MessageContentPartText(type="text", text=processed_text))
                    else:
                        new_parts.append(part.model_copy(deep=True))
                if part_level_found:
                    msg.content = new_parts
                    content_modified = True

            if content_modified:
                logger.info(
                    f"Commands processed in message index {i} (from end). Role: {msg.role}. New content: '{msg.content}'"
                )

        final_messages: List[models.ChatMessage] = []
        for msg in modified_messages:
            if isinstance(msg.content, list) and not msg.content:
                logger.info(
                    f"Removing message (role: {msg.role}) as its multimodal content became empty after command processing."
                )
                continue
            if isinstance(msg.content, str) and not msg.content.strip():
                # Check if this was a command-only message
                original_msg = messages[len(final_messages)]
                if isinstance(original_msg.content, str) and original_msg.content.strip().startswith(self.command_prefix):
                    # For command-only messages, we want to keep them in the list
                    # but with empty content to indicate they were processed
                    final_messages.append(msg)
                    continue
                logger.info(
                    f"Removing message (role: {msg.role}) as its content became empty after command processing."
                )
                continue
            final_messages.append(msg)

        if not final_messages and any_command_processed and messages:
            logger.info(
                "All messages were removed after command processing. This might indicate a command-only request."
            )

        logger.debug(
            f"Finished processing messages. Final message count: {len(final_messages)}. Commands processed overall: {any_command_processed}"
        )
        return final_messages, any_command_processed


# Convenience wrappers ----------------------------------------------

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
    processed_text, found = parser.process_text(text_content)
    if parser.results and any(not r.success for r in parser.results):
        if parser.results[0].message.startswith("unknown command"):
            processed_text = text_content
        else:
            processed_text = ""
    return processed_text, found


def process_commands_in_messages(
    messages: List[models.ChatMessage],
    current_proxy_state: ProxyState,
    app: Optional[FastAPI] = None,
    *,
    command_prefix: str = DEFAULT_COMMAND_PREFIX,
    functional_backends: Set[str] | None = None,
) -> Tuple[List[models.ChatMessage], bool]:
    """Legacy helper used by older unit tests."""

    if not messages:
        return messages, False

    last_with_cmd: int | None = None
    for idx, msg in enumerate(messages):
        if isinstance(msg.content, str) and command_prefix in msg.content:
            last_with_cmd = idx
        elif isinstance(msg.content, list):
            if any(
                isinstance(p, models.MessageContentPartText)
                and command_prefix in p.text
                for p in msg.content
            ):
                last_with_cmd = idx

    if last_with_cmd is None:
        return messages, False

    parser = CommandParser(
        current_proxy_state,
        app,
        command_prefix=command_prefix,
        functional_backends=functional_backends,
    )

    processed, processed_flag = parser.process_messages([messages[last_with_cmd]])
    result_messages = [m.model_copy(deep=True) for m in messages]
    if processed:
        result_messages[last_with_cmd] = processed[0]
    else:
        del result_messages[last_with_cmd]

    return result_messages, processed_flag
