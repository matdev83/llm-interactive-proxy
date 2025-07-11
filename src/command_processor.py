import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from src.command_config import CommandProcessorConfig

from fastapi import FastAPI

from src import models
from src.commands import BaseCommand, CommandResult
from src.proxy_logic import ProxyState

logger = logging.getLogger(__name__)

# Regex matching comment lines that should be ignored when detecting
# command-only messages. This helps to strip agent-provided context such as
# "# foo" lines that might precede a user command.
COMMENT_LINE_PATTERN = re.compile(r"^\s*#[^\n]*\n?", re.MULTILINE)


def parse_arguments(args_str: str) -> Dict[str, Any]:
    """Parse a comma separated key=value string into a dictionary."""
    logger.debug("Parsing arguments from string: '%s'", args_str)
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
    # Updated regex to correctly handle commands with and without arguments.
    # - (?P<cmd>[\w-]+) captures the command name.
    # - (?:\s*\((?P<args>[^)]*)\))? is an optional non-capturing group for arguments.
    pattern_string = (
        rf"{prefix_escaped}(?P<cmd>[\w-]+)" r"(?:\s*\((?P<args>[^)]*)\))?"
    )
    return re.compile(pattern_string, re.VERBOSE)


class CommandProcessor:
    """Handles the parsing and execution of a single command."""

    def __init__(
        self,
        config: "CommandProcessorConfig",
    ) -> None:
        self.config = config

    def process_text_and_execute_command(self, text_content: str) -> Tuple[str, bool]:
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
                execution_result = command_handler.execute(args, self.config.proxy_state)
                self.config.command_results.append(execution_result)
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
                modified_text[:match.start()] + replacement + modified_text[match.end():]
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

    def handle_string_content(
        self,
        msg_content: str,
    ) -> Tuple[str, bool, bool]:
        original_content = msg_content
        processed_text, command_found = self.process_text_and_execute_command(original_content)

        content_modified = False
        if command_found:
            original_content_stripped = original_content.strip()
            is_prefix_match = original_content_stripped.startswith(
                self.config.command_pattern.pattern.split('(')[0].replace('\\', '') # Extract prefix from pattern
            )
            command_pattern_match = None
            if is_prefix_match:
                command_pattern_match = self.config.command_pattern.match(
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

    def process_single_part(
        self,
        part: models.MessageContentPart,
    ) -> Tuple[Optional[models.MessageContentPart], bool]:
        """Processes a single part of a message."""
        if not isinstance(part, models.MessageContentPartText):
            return part.model_copy(deep=True), False

        processed_text, found_in_part = self.process_text_and_execute_command(part.text)

        if found_in_part:
            if not processed_text.strip(): # Command processed AND resulted in empty text
                return None, True  # Drop the part, but signal command was handled
            return models.MessageContentPartText(type="text", text=processed_text), True

        # No command found in this part
        if processed_text.strip(): # If text remains (e.g. from cleaning non-command text)
            return models.MessageContentPartText(type="text", text=processed_text), False

        return None, False # No command, and text is empty

    def handle_list_content(
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
                    self.process_single_part(original_part)

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
            if new_parts != original_parts_copy:
                list_actually_changed = True

        # should_consider_modified is True if a command was found OR the list content changed.
        should_consider_modified = any_command_found_overall or list_actually_changed

        return new_parts, any_command_found_overall, should_consider_modified