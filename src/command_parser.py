import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import src.models as models

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


from .proxy_logic import ProxyState


def get_command_pattern(command_prefix: str) -> re.Pattern:
    prefix_escaped = re.escape(command_prefix)
    return re.compile(
        rf"{prefix_escaped}(?:(?P<bare>hello|help)(?!\()\b|(?P<cmd>[\w-]+)\((?P<args>[^)]*)\))",
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
        logger.debug(f"Found {len(matches)} command matches for text: '{text_content}'")
        for match in reversed(matches):
            commands_found = True
            command_full = match.group(0)
            # Check if the 'bare' group was matched (meaning it's a bare command)
            if "bare" in match.groupdict() and match.group("bare"):
                command_name = match.group("bare").lower()
                args_str = ""
            else:  # It's a function-like command
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
                    CommandResult(
                        command_name, False, f"unknown command: {command_name}"
                    )
                )
                if self.preserve_unknown:
                    replacement = command_full

            modified_text = (
                modified_text[: match.start()]
                + replacement
                + modified_text[match.end() :]
            )

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
                # Check if this is a command-only message
                if msg.content.strip().startswith(self.command_prefix):
                    command_match = self.command_pattern.match(msg.content.strip())
                    if command_match and msg.content.strip() == command_match.group(0):
                        # This is a command-only message, process it and return empty
                        processed_text, found = self.process_text(msg.content)
                        logger.debug(f"Command-only message processed. Found: {found}")
                        if found:
                            any_command_processed = True
                            msg.content = ""
                            content_modified = True
                            # Don't break here, continue processing other messages
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
                            new_parts.append(
                                models.MessageContentPartText(
                                    type="text", text=processed_text
                                )
                            )
                        elif not found:
                            new_parts.append(
                                models.MessageContentPartText(
                                    type="text", text=processed_text
                                )
                            )
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
                if isinstance(
                    original_msg.content, str
                ) and original_msg.content.strip().startswith(self.command_prefix):
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
    return parser.process_text(text_content)


def process_commands_in_messages(
    messages: List[models.ChatMessage],
    current_proxy_state: ProxyState,
    app: Optional[FastAPI] = None,
) -> Tuple[List[models.ChatMessage], bool]:
    """
    Process commands in messages and update proxy state.
    Returns processed messages and whether any commands were processed.
    """
    if not messages:
        return messages, False

    processed_messages = []
    commands_processed = False
    command_pattern = get_command_pattern("")

    # Process messages in reverse order to handle commands from last to first
    for i, message in enumerate(reversed(messages)):
        message_index = len(messages) - 1 - i
        logger.debug(
            f"Processing message index {message_index} (from end): {message.content}"
        )

        # Check for commands in the message
        command_matches = list(command_pattern.finditer(message.content))
        if command_matches:
            logger.debug(
                f"Found {len(command_matches)} command matches in message: {message.content}"
            )
            commands_processed = True

            # Process each command
            for match in command_matches:
                full_match = match.group(0)
                command = match.group(1)
                args_str = match.group(2) if match.group(2) else ""
                logger.debug(f"Processing command: {command} with args: {args_str}")

                # Parse and execute command
                args = parse_arguments(args_str)
                if command == "set":
                    if "backend" in args:
                        current_proxy_state.set_override_backend(args["backend"])
                    elif "model" in args:
                        current_proxy_state.set_override_model(args["model"])
                    elif "project" in args or "project-name" in args:
                        project = args.get("project") or args.get("project-name")
                        current_proxy_state.set_project(project)
                elif command == "unset":
                    if "backend" in args:
                        current_proxy_state.unset_override_backend()
                    elif "model" in args:
                        current_proxy_state.unset_override_model()
                    elif "project" in args or "project-name" in args:
                        current_proxy_state.unset_project()

            # Remove commands from message content
            new_content = command_pattern.sub("", message.content).strip()
            logger.debug(f"Message content after command removal: {new_content}")

            # If message is empty after command removal, skip it
            if not new_content:
                logger.debug(f"Skipping empty message at index {message_index}")
                continue

            # Create new message with processed content
            processed_message = models.ChatMessage(
                role=message.role, content=new_content
            )
            processed_messages.append(processed_message)
        else:
            # No commands in this message, keep it as is
            processed_messages.append(message)

    # Reverse back to original order
    processed_messages.reverse()
    logger.debug(f"Final processed messages: {processed_messages}")
    return processed_messages, commands_processed
