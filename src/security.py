import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)


class APIKeyRedactor:
    """Redact known API keys from user provided prompts."""

    def __init__(self, api_keys: Iterable[str] | None = None) -> None:
        # filter out falsy values
        self.api_keys = [k for k in (api_keys or []) if k]

    def redact(self, text: str) -> str:
        """Replace any occurrences of known API keys in *text*."""
        redacted_text = text
        for key in self.api_keys:
            if key and key in redacted_text:
                logger.warning(
                    "API key detected in prompt. Redacting before forwarding."
                )
                redacted_text = redacted_text.replace(
                    key, "(API_KEY_HAS_BEEN_REDACTED)"
                )
        return redacted_text


class ProxyCommandFilter:
    """Emergency filter to detect and remove proxy commands from text being sent to remote LLMs."""

    def __init__(self, command_prefix: str = "!/") -> None:
        self.command_prefix = command_prefix
        self._update_pattern()

    def _update_pattern(self) -> None:
        """Update the regex pattern when command prefix changes."""
        prefix_escaped = re.escape(self.command_prefix)
        # Pattern to match any proxy command: prefix followed by command name and optional arguments
        self.command_pattern = re.compile(
            rf"{prefix_escaped}(?:(?:hello|help)(?!\()\b|[\w-]+(?:\([^)]*\))?)",
            re.IGNORECASE
        )

    def set_command_prefix(self, new_prefix: str) -> None:
        """Update the command prefix and regenerate the pattern."""
        self.command_prefix = new_prefix
        self._update_pattern()

    def filter_commands(self, text: str) -> str:
        """
        Remove any proxy commands from text and issue warnings.
        This is an emergency filter to prevent command leaks to remote LLMs.
        """
        if not text or not text.strip():
            return text

        # Find all command matches
        matches = list(self.command_pattern.finditer(text))

        if matches:
            logger.warning(
                "EMERGENCY FILTER TRIGGERED: %d proxy command(s) detected in text being sent to remote LLM. "
                "This indicates a potential command leak or mishandling. Commands will be removed.",
                len(matches)
            )

            # Log each detected command for debugging
            for i, match in enumerate(matches, 1):
                command_text = match.group(0)
                logger.warning("  Command %d: '%s' at position %d-%d", i, command_text, match.start(), match.end())

            # Remove all commands from the text
            filtered_text = self.command_pattern.sub("", text)

            # Clean up extra whitespace that might be left behind
            filtered_text = re.sub(r'\s+', ' ', filtered_text).strip()

            logger.info("Emergency filter removed %d command(s). Original length: %d, filtered length: %d", 
                        len(matches), len(text), len(filtered_text))

            return filtered_text

        return text
