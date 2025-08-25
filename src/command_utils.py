import logging
import re
from typing import Any

from src.core.domain.chat import MessageContentPartText

logger = logging.getLogger(__name__)

# Regex matching comment lines that should be ignored when detecting
# command-only messages. This helps to strip agent-provided context such as
# "# foo" lines that might precede a user command.
COMMENT_LINE_PATTERN = re.compile(r"^\s*#[^\n]*\n?", re.MULTILINE)


def is_content_effectively_empty(content: Any) -> bool:
    """Checks if message content is effectively empty after processing."""
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        if not content:  # An empty list is definitely empty
            return True
        # If the list has any non-text part (e.g., image), it's not empty.
        # If all parts are text parts, then it's empty if all those text parts are empty.
        for part in content:
            if not isinstance(part, MessageContentPartText):
                return False  # Contains a non-text part (like an image), so not empty
            if part.text.strip():
                return False  # Contains a non-empty text part
        return True  # All parts are empty text parts, or list was empty initially
    return False  # Should not be reached if content is always str or list


def is_original_purely_command(
    original_content: Any, command_pattern: re.Pattern
) -> bool:
    """Checks if the original message content was purely a command.

    Rules:
    - For string content: consider the message purely a command only if the
      stripped text matches the command pattern exactly. Do NOT ignore
      comment lines (e.g., lines starting with '#'): their presence means the
      message is not purely a command.
    - For list content: consider it purely a command if there is exactly one
      text part and that text part's stripped text matches the command pattern
      exactly. Any additional parts (e.g., images) make it not purely a command.
    """
    # String content case
    if isinstance(original_content, str):
        text = original_content.strip()
        if not text:
            return False
        match = command_pattern.match(text)
        return bool(match and text == match.group(0))

    # List content case (multimodal)
    if isinstance(original_content, list):
        from src.core.domain.chat import MessageContentPartText

        text_parts = [
            p for p in original_content if isinstance(p, MessageContentPartText)
        ]
        # Exactly one part and it's a text part that is a pure command
        if len(text_parts) == 1 and len(original_content) == 1:
            text = text_parts[0].text.strip()
            if not text:
                return False
            match = command_pattern.match(text)
            return bool(match and text == match.group(0))
        return False

    return False


def is_tool_call_result(text: str) -> bool:
    """Check if the text appears to be a tool call result rather than direct user input."""
    # Tool call results typically start with patterns like:
    # "[tool_name for 'arg'] Result:"
    # "[attempt_completion] Result:"
    # "[read_file for 'filename'] Result:"
    tool_result_patterns = [
        r'^\s*\[[\w_]+(?:\s+for\s+[\'"][^\'"\]]+[\'"])?\]\s+Result:',
        r"^\s*\[[\w_]+\]\s+Result:",
    ]

    for pattern in tool_result_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            logger.debug("Detected tool call result pattern: %s", pattern)
            return True
    return False


def extract_feedback_from_tool_result(text: str) -> str:
    """Extract user feedback from tool call results that contain feedback sections."""
    # Look for feedback within tool call results, typically in format:
    # <feedback>
    # !/command or user input
    # </feedback>
    feedback_pattern = r"<feedback>\s*(.*?)\s*</feedback>"
    match = re.search(feedback_pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        feedback_content = match.group(1).strip()
        logger.debug("Extracted feedback from tool result: %r", feedback_content)
        return feedback_content
    return ""


def get_text_for_command_check(content: Any) -> str:
    """Extracts and prepares text from message content for command checking."""
    text_to_check = ""
    if isinstance(content, str):
        text_to_check = content
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, MessageContentPartText):
                text_to_check += part.text + " "  # Add space to simulate separate words

    # CRITICAL FIX: Handle tool call results with embedded feedback
    if is_tool_call_result(text_to_check):
        # Check if this tool call result contains user feedback with commands
        feedback_text = extract_feedback_from_tool_result(text_to_check)
        if not feedback_text:
            logger.debug("Skipping command detection in tool call result content")
            return ""
        logger.debug(
            "Found feedback in tool call result, checking for commands in feedback"
        )
        return COMMENT_LINE_PATTERN.sub("", feedback_text).strip()

    # Remove comments and strip whitespace for accurate command pattern matching
    return COMMENT_LINE_PATTERN.sub("", text_to_check).strip()
