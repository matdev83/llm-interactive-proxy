"""Backend initialization strategies package.

This package contains initialization strategies for backend connectors,
allowing backend-specific configuration augmentation without modifying
BackendFactory or BackendStage.
"""

# Import strategy modules to trigger auto-registration
from src.connectors.strategies import (  # noqa: F401  # pyright: ignore[reportUnusedImport]
    anthropic,  # pyright: ignore[reportUnusedImport]
    gemini,  # pyright: ignore[reportUnusedImport]
    openrouter,  # pyright: ignore[reportUnusedImport]
)
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
