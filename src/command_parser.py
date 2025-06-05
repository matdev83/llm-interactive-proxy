import logging
import re
from typing import Any, Dict, List, Tuple

import src.models as models
from .proxy_logic import ProxyState
from .constants import DEFAULT_COMMAND_PREFIX
from .commands import (
    BaseCommand,
    CommandResult,
    SetCommand,
    UnsetCommand,
    HelloCommand,
)

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
        rf"{prefix_escaped}(?: (?P<hello>hello)\b | (?P<cmd>\w+)\((?P<args>[^)]*)\) )",
        re.VERBOSE,
    )


class CommandParser:
    """Parse and apply proxy commands embedded in chat messages."""

    def __init__(
        self,
        proxy_state: ProxyState,
        command_prefix: str = DEFAULT_COMMAND_PREFIX,
        preserve_unknown: bool = True,
    ) -> None:
        self.proxy_state = proxy_state
        self.command_prefix = command_prefix
        self.preserve_unknown = preserve_unknown
        self.command_pattern = get_command_pattern(command_prefix)
        self.handlers: Dict[str, BaseCommand] = {}
        self.register_command(SetCommand())
        self.register_command(UnsetCommand())
        self.register_command(HelloCommand())
        self.results: List[CommandResult] = []

    def register_command(self, command: BaseCommand) -> None:
        self.handlers[command.name.lower()] = command

    # ------------------------------------------------------------------
    def process_text(self, text_content: str) -> Tuple[str, bool]:
        logger.debug(f"Processing text for commands: '{text_content}'")
        commands_found = False
        modified_text = text_content

        matches = list(self.command_pattern.finditer(text_content))
        for match in reversed(matches):
            commands_found = True
            command_full = match.group(0)
            if match.group("hello"):
                command_name = "hello"
                args_str = ""
            else:
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
            else:
                logger.warning(f"Unknown command: {command_name}.")
                self.results.append(
                    CommandResult(command_name, False, f"unknown command: {command_name}")
                )
                if self.preserve_unknown:
                    replacement = command_full

            modified_text = modified_text[: match.start()] + replacement + modified_text[match.end() :]

        final_text = re.sub(r"\s+", " ", modified_text).strip()
        logger.debug(f"Text after command processing and normalization: '{final_text}'")
        return final_text, commands_found

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
                processed_text, found = self.process_text(msg.content)
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
                break

        final_messages: List[models.ChatMessage] = []
        for msg in modified_messages:
            if isinstance(msg.content, list) and not msg.content:
                logger.info(
                    f"Removing message (role: {msg.role}) as its multimodal content became empty after command processing."
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
    text_content: str, current_proxy_state: ProxyState, command_pattern: re.Pattern
) -> Tuple[str, bool]:
    parser = CommandParser(current_proxy_state, command_prefix="")
    parser.command_pattern = command_pattern
    return parser.process_text(text_content)


def process_commands_in_messages(
    messages: List[models.ChatMessage],
    current_proxy_state: ProxyState,
    command_prefix: str = DEFAULT_COMMAND_PREFIX,
) -> Tuple[List[models.ChatMessage], bool]:
    parser = CommandParser(current_proxy_state, command_prefix=command_prefix)
    return parser.process_messages(messages)
