"""
Credential providers for Gemini OAuth connectors.

This package contains different credential loading implementations:
- FileCredentialProvider: Loads from JSON file (oauth_creds.json)
- AntigravitySQLiteCredentialProvider: Loads from SQLite database (state.vscdb)
"""

from src.connectors.gemini_base.credential_providers.file_provider import (
    FileCredentialProvider,
)
from src.connectors.gemini_base.credential_providers.sqlite_provider import (
    AntigravitySQLiteCredentialProvider,
)

__all__ = [
    "AntigravitySQLiteCredentialProvider",
    "FileCredentialProvider",
]
