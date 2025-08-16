# DEPRECATED: Legacy Adapters Package
#
# This package is deprecated and will be removed in a future version.
# The new architecture now uses direct service implementations rather than adapters.

import warnings

# Show deprecation warning when this package is imported
warnings.warn(
    "The legacy adapters are deprecated and will be removed in a future version. "
    "Please use the new SOLID architecture services directly.",
    DeprecationWarning,
    stacklevel=2
)

from src.core.adapters.legacy_backend_adapter import (
    LegacyBackendAdapter,
    create_legacy_backend_adapter,
)
from src.core.adapters.legacy_command_adapter import (
    LegacyCommandAdapter,
    create_legacy_command_adapter,
)
from src.core.adapters.legacy_config_adapter import (
    LegacyConfigAdapter,
    create_legacy_config_adapter,
)
from src.core.adapters.legacy_session_adapter import (
    LegacySessionAdapter,
    create_legacy_session_adapter,
)

__all__ = [
    "LegacyBackendAdapter",
    "LegacyCommandAdapter",
    "LegacyConfigAdapter",
    "LegacySessionAdapter",
    "create_legacy_backend_adapter",
    "create_legacy_command_adapter",
    "create_legacy_config_adapter",
    "create_legacy_session_adapter",
]
