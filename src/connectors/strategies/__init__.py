"""Backend initialization strategies package.

This package contains initialization strategies for backend connectors,
allowing backend-specific configuration augmentation without modifying
BackendFactory or BackendStage.

Strategies are auto-discovered lazily when first accessed via the registry.
"""

from src.connectors.strategies.registry import (
    DefaultInitializationStrategy,
    InitializationStrategyRegistry,
    initialization_strategy_registry,
)

__all__ = [
    "DefaultInitializationStrategy",
    "InitializationStrategyRegistry",
    "initialization_strategy_registry",
]
