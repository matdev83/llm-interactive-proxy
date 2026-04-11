"""Usage summary canonical contract.

This module defines the UsageSummary value object which represents
a canonical usage summary with token counts and provider-specific extensions.
"""

from __future__ import annotations

from typing import Any

from pydantic.types import JsonValue

from src.core.domain.base import ValueObject


class UsageSummary(ValueObject):
    """Canonical contract for usage summary.

    Represents standard usage fields (prompt_tokens, completion_tokens, total_tokens)
    with a single extension container for provider-specific usage details.
    This is the canonical contract used for cross-layer data exchange
    in usage recording and response metadata.

    Attributes:
        prompt_tokens: Number of prompt tokens (optional)
        completion_tokens: Number of completion tokens (optional)
        total_tokens: Total number of tokens (optional)
        extensions: Provider-specific usage details (JSON-serializable values)
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    extensions: dict[str, JsonValue] = {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageSummary:
        """Create UsageSummary from a dictionary (e.g., from API response).

        Handles common formats:
        - OpenAI format: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
        - OpenRouter format: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int, ...}
        - Generic format with extensions

        Args:
            data: Dictionary with usage data

        Returns:
            UsageSummary instance
        """
        prompt_tokens = data.get("prompt_tokens")
        if not isinstance(prompt_tokens, int):
            prompt_tokens = data.get("input_tokens")
        completion_tokens = data.get("completion_tokens")
        if not isinstance(completion_tokens, int):
            completion_tokens = data.get("output_tokens")
        total_tokens = data.get("total_tokens")
        if not isinstance(total_tokens, int):
            computed = (prompt_tokens or 0) + (completion_tokens or 0)
            total_tokens = computed if computed > 0 else None

        # Extract extensions
        # If "extensions" key exists, use it directly; otherwise extract all non-standard fields
        if "extensions" in data and isinstance(data["extensions"], dict):
            extensions = data["extensions"]
        else:
            # Extract extensions (all keys except standard fields)
            standard_fields = {"prompt_tokens", "completion_tokens", "total_tokens"}
            extensions = {k: v for k, v in data.items() if k not in standard_fields}

        return cls(
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            completion_tokens=(
                completion_tokens if isinstance(completion_tokens, int) else None
            ),
            total_tokens=total_tokens if isinstance(total_tokens, int) else None,
            extensions=extensions,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to a canonical dictionary form.

        This preserves the explicit `extensions` container for provider-specific
        usage fields.
        """
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "extensions": dict(self.extensions),
        }

    def to_legacy_dict(self) -> dict[str, Any]:
        """Convert to a legacy-compatible dictionary form.

        - Standard keys are emitted at top-level when present.
        - Provider-specific extensions are flattened into the same dict.
        - The `extensions` key itself is not emitted.
        """
        result: dict[str, Any] = {}
        if self.prompt_tokens is not None:
            result["prompt_tokens"] = self.prompt_tokens
        if self.completion_tokens is not None:
            result["completion_tokens"] = self.completion_tokens
        if self.total_tokens is not None:
            result["total_tokens"] = self.total_tokens
        if self.extensions:
            result.update(self.extensions)
        return result

    def merge(self, other: UsageSummary) -> UsageSummary:
        """Merge this UsageSummary with another, combining token counts and extensions.

        Token counts are added together (None values are treated as 0).
        Extensions are merged, with values from `other` taking precedence.

        Args:
            other: Another UsageSummary to merge with

        Returns:
            New UsageSummary with merged values
        """
        prompt_sum = (self.prompt_tokens or 0) + (other.prompt_tokens or 0)
        completion_sum = (self.completion_tokens or 0) + (other.completion_tokens or 0)
        total_sum = (self.total_tokens or 0) + (other.total_tokens or 0)

        # Merge extensions, with other taking precedence
        merged_extensions = dict(self.extensions)
        merged_extensions.update(other.extensions)

        # For numeric extension values, try to add them if both exist
        for key in set(self.extensions.keys()) & set(other.extensions.keys()):
            val1 = self.extensions[key]
            val2 = other.extensions[key]
            if isinstance(val1, int | float) and isinstance(val2, int | float):
                merged_extensions[key] = val1 + val2
            else:
                # Non-numeric or incompatible types: use other's value
                merged_extensions[key] = val2

        return UsageSummary(
            prompt_tokens=prompt_sum if prompt_sum > 0 else None,
            completion_tokens=completion_sum if completion_sum > 0 else None,
            total_tokens=total_sum if total_sum > 0 else None,
            extensions=merged_extensions,
        )

    def __getitem__(self, key: str) -> JsonValue:
        if key == "prompt_tokens":
            return self.prompt_tokens
        if key == "completion_tokens":
            return self.completion_tokens
        if key == "total_tokens":
            return self.total_tokens
        if key in self.extensions:
            return self.extensions[key]
        raise KeyError(key)

    def get(self, key: str, default: JsonValue | None = None) -> JsonValue | None:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key in {"prompt_tokens", "completion_tokens", "total_tokens"}:
            return True
        return key in self.extensions

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self.to_legacy_dict() == other
        return super().__eq__(other)
