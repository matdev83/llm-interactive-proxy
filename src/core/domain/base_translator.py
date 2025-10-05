from __future__ import annotations

from typing import Any


class BaseTranslator:
    """Base class for API translators with common functionality."""

    def _extract_text_content(self, content: Any) -> str:
        """Extract text content from various content formats."""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            return " ".join(text_parts)
        return str(content)

    def _validate_and_convert_messages(
        self, messages: list[Any]
    ) -> list[dict[str, Any]]:
        """Validate and convert messages to a standard format."""
        validated_messages = []
        for message in messages:
            if not hasattr(message, "role") or not message.role:
                continue

            validated_message = {
                "role": message.role,
                "content": self._extract_text_content(getattr(message, "content", "")),
            }

            # Add other fields if present
            for field in ["name", "tool_calls", "tool_call_id"]:
                if hasattr(message, field):
                    validated_message[field] = getattr(message, field)

            validated_messages.append(validated_message)

        return validated_messages
