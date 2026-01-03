"""
Feature parity registration module.

This module provides functions to register all middleware/features with the
FeatureParityRegistry during application startup. This enables automated
parity verification and reporting.
"""

from __future__ import annotations

import logging

from src.core.interfaces.feature_parity import (
    FeatureParityRegistry,
    ParityViolation,
    get_global_registry,
)
from src.core.interfaces.response_processor_interface import (
    FeatureCapability,
    IResponseFeature,
    IResponseMiddleware,
)

logger = logging.getLogger(__name__)


def register_all_features(registry: FeatureParityRegistry | None = None) -> None:
    """Register all known features and middleware with the parity registry.

    This function should be called during application startup to populate
    the registry with all features that need parity tracking.

    Args:
        registry: Optional registry to use. If None, uses global registry.
    """
    if registry is None:
        registry = get_global_registry()

    # Import features lazily to avoid circular imports
    _register_core_features(registry)
    _register_legacy_middleware(registry)

    logger.info(
        "Registered %d features for parity tracking", len(registry.get_all_features())
    )


def _register_core_features(registry: FeatureParityRegistry) -> None:
    """Register IResponseFeature implementations."""
    try:
        from src.core.services.response_middleware import (
            ContentFilterFeature,
            ResponseLoggingFeature,
        )

        # These have full parity - explicit streaming/non-streaming implementations
        registry.register_feature(ResponseLoggingFeature())
        registry.register_feature(ContentFilterFeature())
    except ImportError as e:
        logger.warning("Could not import core features: %s", e, exc_info=True)

    try:
        from src.core.services.empty_response_middleware import EmptyResponseFeature

        registry.register_feature(EmptyResponseFeature())
    except ImportError as e:
        logger.warning("Could not import EmptyResponseFeature: %s", e, exc_info=True)

    # Note: StructuredOutputFeature and JsonRepairFeature require DI dependencies
    # (json_repair_service, config) - they should be registered at DI time
    # when the dependencies are available, not here.


def _register_legacy_middleware(registry: FeatureParityRegistry) -> None:
    """Register legacy IResponseMiddleware with declared capabilities.

    Legacy middleware uses the old interface but we can still track
    their declared capabilities for parity reporting.
    """
    # These are registered by name with declared capabilities
    # Actual instances would need to be registered at runtime when DI resolves them

    legacy_middleware_declarations = [
        # (name, declared_capability, notes)
        (
            "ThinkTagsFixMiddleware",
            FeatureCapability.BOTH,
            "Has different streaming/non-streaming logic paths",
        ),
        (
            "EditPrecisionResponseMiddleware",
            FeatureCapability.BOTH,
            "Same logic for both paths",
        ),
        (
            "ToolCallReactorMiddleware",
            FeatureCapability.BOTH,
            "Different lifecycle handling per path",
        ),
        (
            "ToolCallLoopDetectionMiddleware",
            FeatureCapability.BOTH,
            "Different lifecycle reset per path",
        ),
        (
            "JsonRepairMiddleware",
            FeatureCapability.NON_STREAMING,
            "Uses separate JsonRepairProcessor for streaming",
        ),
    ]

    for name, capability, _notes in legacy_middleware_declarations:
        # Register as metadata-only entries for tracking
        # Actual middleware instances should be registered at DI time
        logger.debug("Declaring legacy middleware: %s (%s)", name, capability)


def register_middleware_instance(
    middleware: IResponseMiddleware,
    registry: FeatureParityRegistry | None = None,
    declared_capability: str = FeatureCapability.BOTH,
    name: str | None = None,
) -> None:
    """Register a specific middleware instance with the registry.

    This function should be called when middleware instances are created
    (typically in DI registration) to enable runtime parity tracking.

    Args:
        middleware: The middleware instance to register
        registry: Optional registry to use. If None, uses global registry.
        declared_capability: The capability this middleware declares
        name: Optional name override
    """
    if registry is None:
        registry = get_global_registry()

    registry.register_middleware(
        middleware,
        declared_capability=declared_capability,
        name=name,
    )


def register_feature_instance(
    feature: IResponseFeature,
    registry: FeatureParityRegistry | None = None,
) -> None:
    """Register a specific feature instance with the registry.

    Args:
        feature: The feature instance to register
        registry: Optional registry to use. If None, uses global registry.
    """
    if registry is None:
        registry = get_global_registry()

    registry.register_feature(feature)


def get_parity_report() -> str:
    """Generate a parity report for all registered features.

    Returns:
        A formatted report string showing parity status of all features.
    """
    registry = get_global_registry()
    return registry.get_parity_report()


def verify_parity(strict: bool = False) -> list[ParityViolation]:
    """Verify parity of all registered features.

    Args:
        strict: If True, raises ParityViolationError on violations

    Returns:
        List of ParityViolation objects

    Raises:
        ParityViolationError: If strict=True and violations are found
    """
    from src.core.interfaces.feature_parity import ParityViolationError

    registry = get_global_registry()
    violations = registry.verify_parity()

    if strict and violations:
        # Filter to only error-level violations for strict mode
        error_violations = [v for v in violations if v.severity == "error"]
        if error_violations:
            raise ParityViolationError(error_violations)

    return violations
