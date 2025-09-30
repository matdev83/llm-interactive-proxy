"""Module that imports all connector modules to ensure backend registration.

This module should be imported at application startup to ensure all backend
connectors register themselves with the backend registry.
"""

# Import the connectors package to trigger auto-discovery and registration
import src.connectors  # noqa: F401

__all__: list[str] = []
