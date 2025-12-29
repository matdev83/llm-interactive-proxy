"""OpenAI Codex connector module.

This module contains the refactored OpenAI Codex connector with separated
responsibilities and clear interfaces.
"""

from src.connectors._openai_codex_connector import (
    OPENAI_VENDOR_PREFIX,
    OpenAICodexConnector,
)

__all__ = ["OpenAICodexConnector", "OPENAI_VENDOR_PREFIX"]

# Also export OpenAICredentialsFileHandler from credentials module
try:
    from .credentials import (
        OpenAICredentialsFileHandler as OpenAICredentialsFileHandler,
    )

    __all__.append("OpenAICredentialsFileHandler")
except ImportError:
    pass
