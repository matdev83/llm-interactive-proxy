"""Logging helpers for the hybrid connector."""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

_BASE_LOGGER = logging.getLogger("src.connectors.hybrid")


def get_hybrid_logger() -> logging.Logger:
    """Return the shared hybrid connector logger, honoring runtime patches."""

    package = sys.modules.get("src.connectors.hybrid")
    if package is not None:
        candidate: Any = getattr(package, "logger", None)
        if candidate is not None:
            return cast(logging.Logger, candidate)
    return _BASE_LOGGER
