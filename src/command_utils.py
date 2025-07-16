import logging
import re
from typing import Any

from src import models

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
            if not isinstance(part, models.MessageContentPartText):
                return False  # Contains a non-text part (like an image), so not empty
            if part.text.strip():
                return False  # Contains a non-empty text part
        return True  # All parts are empty text parts, or list was empty initially
    return False # Should not be reached if content is always str or list


def is_original_purely_command(original_content: Any, command_pattern: re.Pattern) -> bool:
    """Checks if the original message content was purely a command, ignoring comments."""
    if not isinstance(original_content, str):
        # Assuming commands can only be in string content for "purely command" messages
        return False

    # Remove comment lines first
    content_without_comments = COMMENT_LINE_PATTERN.sub("", original_content).strip()

    if not content_without_comments: # If only comments or empty after stripping comments
        return False

    match = command_pattern.match(content_without_comments)
    # Check if the entire content (after comment removal and stripping) is the command
    return bool(match and content_without_comments == match.group(0))


def is_tool_call_result(text: str) -> bool:
    """Check if the text appears to be a tool call result rather than direct user input."""
    # Tool call results typically start with patterns like:
    # "[tool_name for 'arg'] Result:"
    # "[attempt_completion] Result:"
    # "[read_file for 'filename'] Result:"
    tool_result_patterns = [
        r'^\s*\[[\w_]+(?:\s+for\s+[\'"][^\'"\]]+[\'"])?\]\s+Result:',
        r'^\s*\[[\w_]+\]\s+Result:',
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
    feedback_pattern = r'<feedback>\s*(.*?)\s*</feedback>'
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
            if isinstance(part, models.MessageContentPartText):
                text_to_check += part.text + " " # Add space to simulate separate words

    # CRITICAL FIX: Handle tool call results with embedded feedback
    if is_tool_call_result(text_to_check):
        # Check if this tool call result contains user feedback with commands
        feedback_text = extract_feedback_from_tool_result(text_to_check)
        if not feedback_text:
            logger.debug("Skipping command detection in tool call result content")
            return ""
        logger.debug("Found feedback in tool call result, checking for commands in feedback")
        return COMMENT_LINE_PATTERN.sub("", feedback_text).strip()

    # Remove comments and strip whitespace for accurate command pattern matching
    return COMMENT_LINE_PATTERN.sub("", text_to_check).strip()