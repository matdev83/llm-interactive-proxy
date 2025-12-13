"""Model alias resolver implementation.

Applies regex-based model name transformations.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, cast

from src.core.interfaces.model_alias_resolver_interface import IModelAliasResolver

if TYPE_CHECKING:
    from src.core.interfaces.configuration_interface import IConfig

logger = logging.getLogger(__name__)


class ModelAliasResolver(IModelAliasResolver):
    """Service for resolving model aliases using regex patterns."""

    def __init__(self, config: IConfig | None = None) -> None:
        """Initialize the model alias resolver.

        Args:
            config: Application configuration containing model aliases.
        """
        self._config = config

    def resolve(self, model: str) -> str:
        """Apply configured model aliases and return resolved model name.

        Matching uses `re.match` semantics (start-anchored unless explicitly anchored).
        First match wins. Replacements use `match.expand` to support capture groups.

        Invalid regex patterns are skipped with a WARNING log, never throwing.
        If no valid match exists, returns the original model name.
        """
        if not self._config:
            return model

        from src.core.config.app_config import AppConfig

        app_config = cast(AppConfig, self._config)

        # Handle case where config might be a Mock object (in tests)
        try:
            model_aliases = getattr(app_config, "model_aliases", [])
            if not model_aliases:
                return model

            # Check if model_aliases is iterable (not a Mock)
            iter(model_aliases)
        except (AttributeError, TypeError):
            # If model_aliases is not iterable (e.g., Mock object), return original
            return model

        for alias in model_aliases:
            try:
                # Handle case where alias might be a Mock object
                pattern = getattr(alias, "pattern", None)
                replacement = getattr(alias, "replacement", None)

                if not pattern or not replacement:
                    continue

                # Anchor patterns to the start of the string by default to
                # preserve the historical behaviour of ``re.match`` while
                # still honoring any explicit anchors provided in the
                # configuration.
                match = re.match(pattern, model)
                if match:
                    # Use match.expand to honor capture groups
                    new_model = match.expand(replacement)
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Applied model alias: '{model}' -> '{new_model}'")
                    return new_model
            except (re.error, AttributeError, TypeError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Invalid regex pattern in model alias or mock object: {e}"
                    )
                continue

        return model
