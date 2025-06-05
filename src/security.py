import logging
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
                logger.warning("API key detected in prompt. Redacting before forwarding.")
                redacted_text = redacted_text.replace(key, "(API_KEY_HAS_BEEN_REDACTED)")
        return redacted_text
