import hashlib
import logging
import re
from collections import OrderedDict
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)


class APIKeyRedactor:
    """Redact known API keys from user provided prompts."""

    def __init__(self, api_keys: Iterable[str] | None = None) -> None:
        # Filter out falsy values and sort by length so longer keys are redacted first
        unique_keys = {k for k in (api_keys or []) if k}
        self.api_keys = sorted(unique_keys, key=len, reverse=True)
        # Pre-compile regex patterns for better performance
        self._key_patterns: dict[str, re.Pattern[str]] = {}
        for key in self.api_keys:
            # Escape special regex characters and compile pattern
            self._key_patterns[key] = re.compile(re.escape(key))

        # Initialize cache for frequently processed content
        self._redact_cache: OrderedDict[str, str] = OrderedDict()
        self._cache_max_size = 512

    def _redact_cached(self, text: str) -> str:
        """Cached version of redact for frequently processed content."""
        # Use hash of text instead of full text as key to reduce memory
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # Move to end if accessed (LRU behavior)
        if text_hash in self._redact_cache:
            self._redact_cache.move_to_end(text_hash)
            return self._redact_cache[text_hash]

        result = self._redact_internal(text)

        # Add new entry and enforce size limit
        self._redact_cache[text_hash] = result
        if len(self._redact_cache) > self._cache_max_size:
            # Remove oldest entry (LRU eviction)
            self._redact_cache.popitem(last=False)

        return result

    def redact(self, text: str) -> str:
        """Replace any occurrences of known API keys in *text*. """
        if not text:
            return text

        # For short texts, use cached version for better performance
        if len(text) < 1000:
            return self._redact_cached(text)
        else:
            return self._redact_internal(text)

    def _redact_internal(self, text: str) -> str:
        """Internal redact implementation."""
        redacted_text = text

        # Quick containment check before expensive regex operations
        for key in self.api_keys:
            if key and key in redacted_text:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "API key detected in prompt. Redacting before forwarding."
                    )
                # Use pre-compiled regex for replacement
                pattern = self._key_patterns[key]
                redacted_text = pattern.sub(
                    "(API_KEY_HAS_BEEN_REDACTED)", redacted_text
                )

        return redacted_text


class ProxyCommandFilter:
    """Emergency filter to detect and remove proxy commands from text being sent to remote LLMs."""

    def __init__(self, command_prefix: str = "!/") -> None:
        self.command_prefix = command_prefix
        self._update_pattern()
        # Initialize cache for frequently processed content
        self._filter_cache: OrderedDict[str, str] = OrderedDict()
        self._cache_max_size = 512

    def _update_pattern(self) -> None:
        """Update the regex pattern when command prefix changes."""
        prefix_escaped = re.escape(self.command_prefix)
        # Pattern to match any proxy command: prefix followed by command name and optional arguments
        self.command_pattern = re.compile(
            rf"{prefix_escaped}[A-Za-z0-9_-]+(?:\([^)]*\))?",
            re.IGNORECASE,
        )
        # Clear cache when pattern changes
        if hasattr(self, "_filter_cache"):
            self._filter_cache.clear()

    def set_command_prefix(self, new_prefix: str) -> None:
        """Update the command prefix and regenerate the pattern."""
        self.command_prefix = new_prefix
        self._update_pattern()

    def _filter_cached(self, text: str, filter_func: Callable[[str], str]) -> str:
        """Helper for caching filter results."""
        if not text:
            return text

        # Use hash of text + function name as key
        cache_key = hashlib.sha256(
            f"{text}:{filter_func.__name__}".encode("utf-8")
        ).hexdigest()

        if cache_key in self._filter_cache:
            self._filter_cache.move_to_end(cache_key)
            return self._filter_cache[cache_key]

        result = filter_func(text)

        self._filter_cache[cache_key] = result
        if len(self._filter_cache) > self._cache_max_size:
            self._filter_cache.popitem(last=False)

        return result

    def filter_commands(self, text: str) -> str:
        """
        Remove any proxy commands from text and issue warnings.
        This is an emergency filter to prevent command leaks to remote LLMs.
        """
        # For short texts, use cached version
        if text and len(text) < 1000:
            return self._filter_cached(text, self._filter_commands_internal)
        return self._filter_commands_internal(text)

    def _filter_commands_internal(self, text: str) -> str:
        if not text or not text.strip():
            return text

        # Get the last non-blank line
        lines = text.split("\n")
        last_line = ""
        for line in reversed(lines):
            if line.strip():  # Non-blank line
                last_line = line
                break

        if not last_line:
            return text

        # Find command matches only in the last line
        matches = list(self.command_pattern.finditer(last_line))

        if matches:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "EMERGENCY FILTER TRIGGERED: %d proxy command(s) detected on last non-blank line. "
                    "This indicates a potential command leak or mishandling. Commands will be removed.",
                    len(matches),
                )

                # Log each detected command for debugging
                for i, match in enumerate(matches, 1):
                    command_text = match.group(0)
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "  Command %d: '%s' at position %d-%d (line %d)",
                            i,
                            command_text,
                            match.start(),
                            match.end(),
                            len(lines) - lines.index(last_line),
                        )

            # Remove commands from the original text by finding and replacing them
            filtered_text = text
            # Process matches in reverse to avoid index shifting
            for match in reversed(matches):
                command_text = match.group(0)
                # Find the command in the original text (in the last line)
                start_pos = text.rfind(last_line) + match.start()
                end_pos = start_pos + len(command_text)
                before = filtered_text[:start_pos]
                after = filtered_text[end_pos:]
                filtered_text = before + after

            # If text became empty or whitespace-only after filtering, insert a benign placeholder
            if not filtered_text.strip():
                filtered_text = "(command_removed)"
            return filtered_text

        return text

    def filter_end_of_message_commands_only(self, text: str) -> str:
        """
        Remove proxy commands only if they appear at the end of the text (after trimming whitespace).
        This is used when processing user input where commands should only be executed if at the end.
        """
        # For short texts, use cached version
        if text and len(text) < 1000:
            return self._filter_cached(text, self._filter_end_of_message_commands_only_internal)
        return self._filter_end_of_message_commands_only_internal(text)

    def _filter_end_of_message_commands_only_internal(self, text: str) -> str:
        if not text or not text.strip():
            return text

        # Trim trailing whitespace for end-of-message detection
        trimmed_text = text.rstrip()

        # Find command matches
        matches = list(self.command_pattern.finditer(trimmed_text))

        # Only process if command is at the end of the trimmed text
        if matches and matches[-1].end() == len(trimmed_text):
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "END-OF-MESSAGE COMMAND FILTER TRIGGERED: %d proxy command(s) detected at end of message. "
                    "This indicates a potential command leak or mishandling. Commands will be removed.",
                    len(matches),
                )

                # Log each detected command for debugging
                for i, match in enumerate(matches, 1):
                    command_text = match.group(0)
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "  Command %d: '%s' at position %d-%d",
                            i,
                            command_text,
                            match.start(),
                            match.end(),
                        )

            # Remove the end-of-message command
            match = matches[-1]
            start, end = match.span()
            before = text[:start]
            after = text[end:]  # Keep the original trailing whitespace

            filtered_text = before + after

            # If text became empty or whitespace-only after filtering, insert a benign placeholder
            if not filtered_text.strip():
                filtered_text = "(command_removed)"
            return filtered_text

        return text

    def filter_commands_with_strict_mode(self, text: str) -> str:
        """
        Remove proxy commands only if they appear on the last non-blank line.
        This is used when strict command detection is enabled.
        """
        # For short texts, use cached version
        if text and len(text) < 1000:
            return self._filter_cached(text, self._filter_commands_with_strict_mode_internal)
        return self._filter_commands_with_strict_mode_internal(text)

    def _filter_commands_with_strict_mode_internal(self, text: str) -> str:
        if not text or not text.strip():
            return text

        # Get the last non-blank line
        lines = text.split("\n")
        last_line = ""
        for line in reversed(lines):
            if line.strip():  # Non-blank line
                last_line = line
                break

        if not last_line:
            return text

        # Find command matches only in the last line
        matches = list(self.command_pattern.finditer(last_line))

        if matches:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "STRICT COMMAND FILTER TRIGGERED: %d proxy command(s) detected on last non-blank line. "
                    "This indicates a potential command leak or mishandling. Commands will be removed.",
                    len(matches),
                )

                # Log each detected command for debugging
                for i, match in enumerate(matches, 1):
                    command_text = match.group(0)
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "  Command %d: '%s' at position %d-%d (line %d)",
                            i,
                            command_text,
                            match.start(),
                            match.end(),
                            len(lines) - lines.index(last_line),
                        )

            # Remove commands from the original text by finding and replacing them
            filtered_text = text
            # Process matches in reverse to avoid index shifting
            for match in reversed(matches):
                command_text = match.group(0)
                # Find the command in the original text (in the last line)
                start_pos = text.rfind(last_line) + match.start()
                end_pos = start_pos + len(command_text)
                before = filtered_text[:start_pos]
                after = filtered_text[end_pos:]
                filtered_text = before + after

            # If text became empty or whitespace-only after filtering, insert a benign placeholder
            if not filtered_text.strip():
                filtered_text = "(command_removed)"
            return filtered_text

        return text