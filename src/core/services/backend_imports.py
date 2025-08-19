"""Module that imports all connector modules to ensure backend registration.

This module should be imported at application startup to ensure all backend
connectors register themselves with the backend registry.
"""

# Import all connector modules to trigger backend registration

__all__: list[str] = []