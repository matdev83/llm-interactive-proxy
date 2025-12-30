import hashlib
import logging
import re
from collections import OrderedDict
from collections.abc import Iterable

logger = logging.getLogger(__name__)


class APIKeyRedactor:
    """Redact known API keys from user provided prompts."""

    def __init__(
        self,
        api_keys: Iterable[str] | None = None,
        logger_instance: logging.Logger | None = None,
    ) -> None:
        # Filter out falsy values and sort by length so longer keys are redacted first
        unique_keys = {k for k in (api_keys or []) if k}
        self.api_keys = sorted(unique_keys, key=len, reverse=True)
        self.logger = logger_instance or logger

        # Compile a single regex pattern for all keys
        if self.api_keys:
            # Create a single pattern with alternatives.
            # Since self.api_keys is sorted by length (descending), the regex engine
            # will prioritize longer matches when using '|'.
            pattern_str = "|".join(re.escape(key) for key in self.api_keys)
            self._combined_pattern: re.Pattern[str] | None = re.compile(pattern_str)
        else:
            self._combined_pattern = None

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
        """Replace any occurrences of known API keys in *text*."""
        if not text:
            return text

        # For short texts, use cached version for better performance
        if len(text) < 1000:
            return self._redact_cached(text)
        else:
            return self._redact_internal(text)

    def _redact_internal(self, text: str) -> str:
        """Internal redact implementation."""
        if not self._combined_pattern:
            return text

        found_keys: set[str] = set()

        def replacement(match: re.Match[str]) -> str:
            found_keys.add(match.group(0))
            return "(API_KEY_HAS_BEEN_REDACTED)"

        redacted_text = self._combined_pattern.sub(replacement, text)

        # Log warning for each unique key detected to preserve behavior
        if found_keys and self.logger.isEnabledFor(logging.WARNING):
            for _ in found_keys:
                self.logger.warning(
                    "API key detected in prompt. Redacting before forwarding."
                )

        return redacted_text
