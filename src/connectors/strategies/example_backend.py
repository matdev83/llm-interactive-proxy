"""Example backend initialization strategy.

This module demonstrates how to add a backend-specific initialization strategy
without modifying BackendFactory or BackendStage, proving OCP-compliant extension.

To add a new backend initialization strategy:
1. Create a new strategy class implementing IBackendInitializationStrategy
2. Register it with initialization_strategy_registry at module import time
3. No changes to BackendFactory or BackendStage are required
"""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.registry import initialization_strategy_registry


class ExampleBackendInitializationStrategy:
    """Example initialization strategy for demonstration purposes.

    This strategy demonstrates how backend-specific initialization configuration
    augmentation can be added without modifying existing code (OCP compliance).

    The strategy sets `key_name` to "example_backend" and adds an example
    configuration field to demonstrate augmentation behavior.
    """

    def augment_init_config(self, init_config: dict[str, Any]) -> dict[str, Any]:
        """Augment initialization configuration for example backend.

        Sets `key_name = "example_backend"` and adds an example configuration
        field, preserving all other existing configuration values.

        Args:
            init_config: The base initialization configuration dictionary.

        Returns:
            A new dictionary with `key_name` set to "example_backend", an
            example field added, and all other values preserved.
        """
        augmented = dict(init_config)
        augmented["key_name"] = "example_backend"
        # Add an example configuration field to demonstrate augmentation
        augmented["example_config"] = "example_value"
        return augmented


# Register the strategy at module import time
# This demonstrates OCP: new strategies can be added without modifying
# BackendFactory or BackendStage - they are automatically discovered via
# the registry pattern.
_example_strategy = ExampleBackendInitializationStrategy()
initialization_strategy_registry.register_strategy("example_backend", _example_strategy)
