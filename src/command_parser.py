import logging
import re
from typing import Any, Dict, List, Tuple, Set, Union # Added Union
from fastapi import FastAPI # Moved up

import src.models as models
from .constants import DEFAULT_COMMAND_PREFIX
from .commands import BaseCommand, CommandResult, create_command_instances
from .proxy_logic import ProxyState # Moved up

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

from .proxy_logic import ProxyState


def get_command_pattern(command_prefix: str) -> re.Pattern:
    prefix_escaped = re.escape(command_prefix)
    return re.compile(
        rf"{prefix_escaped}(?: (?P<bare>hello|help)(?!\()\b | (?P<cmd>[\w-]+)\((?P<args>[^)]*)\) )",
        re.VERBOSE,
    )


from fastapi import FastAPI

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
        for match in reversed(matches):
            commands_found = True
            command_full = match.group(0)
            if match.group("bare"):
                command_name = match.group("bare").lower()
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
        final_text = self._strip_xml_tags(final_text) # Add this line
        logger.debug(f"Text after command processing and normalization: '{final_text}'")
        return final_text, commands_found

    def _strip_xml_tags(self, text: str) -> str:
        """Removes XML-like tags from a string."""
        return re.sub(r"<[^>]+>", "", text)

    def _process_single_message_content(
        self, content: Union[str, List[models.MessageContentPart]]
    ) -> Tuple[Union[str, List[models.MessageContentPart]], bool, bool]:
        """
        Processes a single message's content (str or list of parts) for commands.
        Returns: (processed_content, command_found_in_this_content, content_became_empty)
        """
        if isinstance(content, str):
            processed_text, found = self.process_text(content)
            content_became_empty = not processed_text.strip() and found # Empty only if a command made it empty
            return processed_text, found, content_became_empty

        if isinstance(content, list):
            new_parts: List[models.MessageContentPart] = []
            part_level_found_command = False
            for part in content:
                if isinstance(part, models.MessageContentPartText):
                    processed_text, found_in_part = self.process_text(part.text)
                    if found_in_part:
                        part_level_found_command = True
                    # Add text part back if it's not empty OR if no command was found in it (preserve original empty text)
                    if processed_text.strip() or not found_in_part:
                         new_parts.append(models.MessageContentPartText(type="text", text=processed_text))
                else: # Non-text parts are preserved
                    new_parts.append(part.model_copy(deep=True))

            content_became_empty = not new_parts and part_level_found_command # Empty only if commands made all parts go away
            return new_parts, part_level_found_command, content_became_empty

        return content, False, False # Should not happen with current models.ChatMessage types

    def process_messages(
        self, messages: List[models.ChatMessage]
    ) -> Tuple[List[models.ChatMessage], bool]:
        self.results.clear()
        if not messages:
            logger.debug("process_messages received empty messages list.")
            return [], False

        modified_messages = [msg.model_copy(deep=True) for msg in messages]
        any_command_processed_overall = False
        processed_message_idx = -1
        processed_message_became_empty = False

        # Iterate from the last message to the first to find and process commands
        for i in range(len(modified_messages) - 1, -1, -1):
            msg_being_processed = modified_messages[i]

            processed_content, command_found, became_empty = \
                self._process_single_message_content(msg_being_processed.content)

            if command_found:
                modified_messages[i].content = processed_content  # Update the copy
                any_command_processed_overall = True
                processed_message_idx = i
                processed_message_became_empty = became_empty

                logger.info(
                    f"Commands processed in message index {i} (0-indexed, from start of original list). "
                    f"Role: {modified_messages[i].role}. Content became empty: {became_empty}. "
                    f"New content: '{modified_messages[i].content}'"
                )
                # Once a command is processed in a message, stop further processing in earlier messages
                break

        final_messages: List[models.ChatMessage] = []
        if not any_command_processed_overall:
            # No commands found anywhere, return all (copied) messages
            final_messages = modified_messages
        else:
            # A command was processed. Filter out the processed message if it became empty.
            for i in range(len(modified_messages)):
                if i == processed_message_idx and processed_message_became_empty:
                    logger.info(
                        f"Removing message (role: {modified_messages[i].role}, index: {i}) "
                        "as its content became empty after command processing."
                    )
                    continue
                final_messages.append(modified_messages[i])

        if not final_messages and any_command_processed_overall and messages: # Original messages list was not empty
            logger.info(
                "All messages were removed after command processing. This might indicate a command-only request."
            )

        logger.debug(
            f"Finished processing messages. Final message count: {len(final_messages)}. Commands processed overall: {any_command_processed_overall}"
        )
        return final_messages, any_command_processed_overall


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
    return parser.process_text(text_content)


def process_commands_in_messages(
    messages: List[models.ChatMessage],
    current_proxy_state: ProxyState,
    app: FastAPI,
    command_prefix: str = DEFAULT_COMMAND_PREFIX,
    functional_backends: Set[str] | None = None,
) -> Tuple[List[models.ChatMessage], bool]:
    parser = CommandParser(
        current_proxy_state,
        app,
        command_prefix=command_prefix,
        functional_backends=functional_backends,
    )
    return parser.process_messages(messages)
