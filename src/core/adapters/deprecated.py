"""
DEPRECATED: Legacy Adapters Module

This module marks all legacy adapters as deprecated. They will be removed in a future version.
The new architecture now uses direct service implementations rather than adapters.
"""

import warnings

# Show deprecation warning when this module is imported
warnings.warn(
    "The legacy adapters are deprecated and will be removed in a future version. "
    "Please use the new SOLID architecture services directly.",
    DeprecationWarning,
    stacklevel=2
)
