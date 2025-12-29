"""OpenAI Codex connector module.

This module contains the refactored OpenAI Codex connector with separated
responsibilities and clear interfaces.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

__all__: list[str] = []

# Import the connector class from the file module
try:
    # Import the file as a module
    import importlib.util

    _connector_file = Path(__file__).parent.parent / "openai_codex.py"
    if _connector_file.exists():
        _spec = importlib.util.spec_from_file_location(
            "openai_codex_file", _connector_file
        )
        if _spec and _spec.loader:
            _openai_codex_file = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_openai_codex_file)
            OpenAICodexConnector = _openai_codex_file.OpenAICodexConnector
            OPENAI_VENDOR_PREFIX = _openai_codex_file.OPENAI_VENDOR_PREFIX
            __all__ = ["OpenAICodexConnector", "OPENAI_VENDOR_PREFIX"]
except (ImportError, AttributeError, OSError) as err:
    # Fallback: try direct import if file import fails
    logger.debug(
        "Failed to load OpenAI Codex connector via file import: %s",
        err,
        exc_info=True,
    )
    try:
        from ..openai_codex import (  # type: ignore[attr-defined]
            OPENAI_VENDOR_PREFIX,
            OpenAICodexConnector,
        )

        __all__ = ["OpenAICodexConnector", "OPENAI_VENDOR_PREFIX"]
    except (ImportError, AttributeError) as err2:
        logger.warning(
            "Failed to import OpenAI Codex connector: %s",
            err2,
            exc_info=True,
        )
        __all__ = []

# Also export OpenAICredentialsFileHandler from credentials module
try:
    from .credentials import (
        OpenAICredentialsFileHandler as OpenAICredentialsFileHandler,
    )

    __all__.append("OpenAICredentialsFileHandler")
except ImportError:
    pass
