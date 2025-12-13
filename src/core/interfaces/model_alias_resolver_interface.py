"""Interface for model alias resolver.

Responsible for applying regex-based model name transformations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IModelAliasResolver(ABC):
    """Service interface for resolving model aliases."""

    @abstractmethod
    def resolve(self, model: str) -> str:
        """Apply configured model aliases and return resolved model name.

        Matching uses `re.match` semantics (start-anchored unless explicitly anchored).
        First match wins. Replacements use `match.expand` to support capture groups.

        Invalid regex patterns are skipped with a WARNING log, never throwing.
        If no valid match exists, returns the original model name.

        Args:
            model: The original model name.

        Returns:
            The rewritten model name, or the original if no rules match.
        """
