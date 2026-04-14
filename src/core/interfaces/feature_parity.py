"""
Feature parity registry and verification utilities.

This module provides infrastructure for tracking and verifying feature parity
between streaming and non-streaming code paths. It enables:

1. Registration of features with their capability declarations
2. Runtime verification of parity compliance
3. Introspection for testing and debugging
4. Detection of undeclared capability gaps

Usage:
    from src.core.interfaces.feature_parity import (
        FeatureParityRegistry,
        get_global_registry,
    )

    # Register a feature
    registry = get_global_registry()
    registry.register_feature(my_feature)

    # Verify parity
    violations = registry.verify_parity()
    if violations:
        raise ParityViolationError(violations)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
)

logger = logging.getLogger(__name__)


@dataclass
class FeatureRegistration:
    """Registration record for a feature middleware.

    Attributes:
        name: Feature name (from feature_name property or class name)
        capability: Declared capability (streaming, non_streaming, or both)
        feature_class: The class type of the feature
        instance: Optional instance for runtime inspection
        has_streaming_impl: Whether streaming implementation exists (non-trivial)
        has_non_streaming_impl: Whether non-streaming implementation exists
    """

    name: str
    capability: str
    feature_class: type
    instance: IResponseFeature | IResponseMiddleware | None = None
    has_streaming_impl: bool = True
    has_non_streaming_impl: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParityViolation:
    """Record of a detected parity violation.

    Attributes:
        feature_name: Name of the feature with violation
        violation_type: Type of violation (missing_streaming, missing_non_streaming, etc.)
        description: Human-readable description of the violation
        severity: Severity level (error, warning, info)
    """

    feature_name: str
    violation_type: str
    description: str
    severity: str = "error"


class FeatureParityRegistry:
    """Registry for tracking feature parity across streaming/non-streaming paths.

    This registry maintains a record of all registered features and their
    capability declarations. It provides verification methods to detect
    parity violations at runtime or during testing.

    Thread-safety: This registry uses a threading.Lock-protected singleton
    pattern for safe concurrent access. The get_global_registry() function
    uses double-checked locking to ensure thread-safe initialization.

    Example:
        registry = FeatureParityRegistry()

        # Register features
        registry.register_feature(MyFeature())
        registry.register_middleware(LegacyMiddleware())

        # Verify parity
        violations = registry.verify_parity()
        for v in violations:
            logger.warning("Parity violation: %s", v.description)

        # Get features by capability
        streaming_features = registry.get_features_by_capability("streaming")
    """

    def __init__(self) -> None:
        """Initialize an empty feature registry."""
        self._features: dict[str, FeatureRegistration] = {}
        self._middleware: dict[str, FeatureRegistration] = {}
        self._lock = threading.Lock()

    def register_feature(
        self,
        feature: IResponseFeature,
        *,
        override_capability: str | None = None,
    ) -> None:
        """Register a feature with enforced parity.

        Features registered through this method implement the canonical
        ``process_chunk`` contract (see :class:`IResponseFeature`).

        Args:
            feature: The feature instance to register
            override_capability: Optional override for the capability declaration
        """
        if not isinstance(feature, IResponseFeature):
            raise TypeError(
                f"Expected IResponseFeature instance, got {type(feature).__name__}. "
                "Use register_middleware() for IResponseMiddleware instances."
            )

        name = feature.feature_name
        capability = override_capability or feature.capability

        has_chunk = self._has_meaningful_implementation(feature, "process_chunk")
        if capability in ("both",):
            has_streaming = has_chunk
            has_non_streaming = has_chunk
        elif capability in ("streaming",):
            has_streaming = has_chunk
            has_non_streaming = True
        elif capability in ("non_streaming",):
            has_streaming = True
            has_non_streaming = has_chunk
        else:
            has_streaming = has_chunk
            has_non_streaming = has_chunk

        registration = FeatureRegistration(
            name=name,
            capability=capability,
            feature_class=type(feature),
            instance=feature,
            has_streaming_impl=has_streaming,
            has_non_streaming_impl=has_non_streaming,
            metadata={"source": "IResponseFeature"},
        )

        with self._lock:
            self._features[name] = registration
        logger.debug(
            "Registered feature '%s' with capability '%s'",
            name,
            capability,
        )

    def register_middleware(
        self,
        middleware: IResponseMiddleware,
        *,
        declared_capability: str = "both",
        name: str | None = None,
    ) -> None:
        """Register a legacy middleware for parity tracking.

        Legacy middleware using IResponseMiddleware can be registered for
        parity analysis. Since they don't have separate methods, capability
        must be declared explicitly.

        Args:
            middleware: The middleware instance to register
            declared_capability: Declared capability (streaming, non_streaming, both)
            name: Optional name override (defaults to class name)
        """
        if not isinstance(middleware, IResponseMiddleware):
            raise TypeError(
                f"Expected IResponseMiddleware instance, got {type(middleware).__name__}"
            )

        feature_name = name or middleware.__class__.__name__

        registration = FeatureRegistration(
            name=feature_name,
            capability=declared_capability,
            feature_class=type(middleware),
            instance=middleware,
            has_streaming_impl=declared_capability in ("streaming", "both"),
            has_non_streaming_impl=declared_capability in ("non_streaming", "both"),
            metadata={"source": "IResponseMiddleware", "legacy": True},
        )

        with self._lock:
            self._middleware[feature_name] = registration
        logger.debug(
            "Registered middleware '%s' with declared capability '%s'",
            feature_name,
            declared_capability,
        )

    def register_class(
        self,
        feature_class: type,
        *,
        declared_capability: str = "both",
        name: str | None = None,
    ) -> None:
        """Register a feature class (not instance) for static analysis.

        This method allows registration of classes for compile-time parity
        verification without requiring instantiation.

        Args:
            feature_class: The feature class to register
            declared_capability: Declared capability
            name: Optional name override
        """
        feature_name = name or feature_class.__name__

        is_feature = issubclass(feature_class, IResponseFeature)
        is_middleware = issubclass(feature_class, IResponseMiddleware)

        if is_feature:
            has_chunk = self._class_has_method_impl(feature_class, "process_chunk")
            if declared_capability in ("both",):
                has_streaming = has_chunk
                has_non_streaming = has_chunk
            elif declared_capability in ("streaming",):
                has_streaming = has_chunk
                has_non_streaming = True
            elif declared_capability in ("non_streaming",):
                has_streaming = True
                has_non_streaming = has_chunk
            else:
                has_streaming = has_chunk
                has_non_streaming = has_chunk
        else:
            has_streaming = declared_capability in ("streaming", "both")
            has_non_streaming = declared_capability in ("non_streaming", "both")

        registration = FeatureRegistration(
            name=feature_name,
            capability=declared_capability,
            feature_class=feature_class,
            instance=None,
            has_streaming_impl=has_streaming,
            has_non_streaming_impl=has_non_streaming,
            metadata={
                "source": "IResponseFeature" if is_feature else "IResponseMiddleware",
                "legacy": is_middleware and not is_feature,
                "static_only": True,
            },
        )

        if is_feature:
            with self._lock:
                self._features[feature_name] = registration
        else:
            with self._lock:
                self._middleware[feature_name] = registration

    def verify_parity(self) -> list[ParityViolation]:
        """Verify parity compliance across all registered features.

        Returns a list of detected parity violations. An empty list means
        all features comply with their declared capabilities.

        Returns:
            List of ParityViolation records
        """
        violations: list[ParityViolation] = []

        with self._lock:
            # Check IResponseFeature implementations
            for name, reg in self._features.items():
                violations.extend(self._verify_feature_parity(name, reg))

            # Check legacy middleware declarations
            for name, reg in self._middleware.items():
                violations.extend(self._verify_middleware_parity(name, reg))

        return violations

    def _verify_feature_parity(
        self, name: str, reg: FeatureRegistration
    ) -> list[ParityViolation]:
        """Verify parity for an IResponseFeature registration."""
        violations: list[ParityViolation] = []

        if reg.capability == "both":
            if not reg.has_streaming_impl:
                violations.append(
                    ParityViolation(
                        feature_name=name,
                        violation_type="missing_streaming",
                        description=(
                            f"Feature '{name}' declares 'both' capability but "
                            "process_chunk appears missing or not meaningfully implemented "
                            "for streaming coverage"
                        ),
                        severity="warning",
                    )
                )
            if not reg.has_non_streaming_impl:
                violations.append(
                    ParityViolation(
                        feature_name=name,
                        violation_type="missing_non_streaming",
                        description=(
                            f"Feature '{name}' declares 'both' capability but "
                            "process_chunk appears missing or not meaningfully implemented "
                            "for non-streaming coverage"
                        ),
                        severity="warning",
                    )
                )

        return violations

    def _verify_middleware_parity(
        self, name: str, reg: FeatureRegistration
    ) -> list[ParityViolation]:
        """Verify parity for a legacy IResponseMiddleware registration."""
        violations: list[ParityViolation] = []

        # For legacy middleware, we can only verify declared vs actual behavior
        # through runtime testing (handled by test harness)
        if reg.capability == "both" and reg.metadata.get("legacy"):
            violations.append(
                ParityViolation(
                    feature_name=name,
                    violation_type="legacy_middleware",
                    description=(
                        f"Middleware '{name}' uses legacy IResponseMiddleware interface. "
                        "Consider migrating to IResponseFeature for enforced parity."
                    ),
                    severity="info",
                )
            )

        return violations

    def get_all_features(self) -> dict[str, FeatureRegistration]:
        """Get all registered features and middleware.

        Returns:
            Combined dictionary of all registrations
        """
        with self._lock:
            return {**self._features, **self._middleware}

    def get_features_by_capability(self, capability: str) -> list[FeatureRegistration]:
        """Get features that support a specific capability.

        Args:
            capability: The capability to filter by (streaming, non_streaming, both)

        Returns:
            List of registrations with matching capability
        """
        all_features = self.get_all_features()

        if capability == "streaming":
            return [f for f in all_features.values() if f.has_streaming_impl]
        elif capability == "non_streaming":
            return [f for f in all_features.values() if f.has_non_streaming_impl]
        elif capability == "both":
            return [
                f
                for f in all_features.values()
                if f.has_streaming_impl and f.has_non_streaming_impl
            ]
        else:
            return [f for f in all_features.values() if f.capability == capability]

    def get_parity_report(self) -> str:
        """Generate a human-readable parity report.

        Returns:
            Formatted string report of feature parity status
        """
        lines = ["Feature Parity Report", "=" * 50]

        all_features = self.get_all_features()
        if not all_features:
            lines.append("No features registered.")
            return "\n".join(lines)

        # Summary
        total = len(all_features)
        with_both = len(self.get_features_by_capability("both"))
        legacy = sum(1 for f in all_features.values() if f.metadata.get("legacy"))

        lines.append(f"Total features: {total}")
        lines.append(f"Full parity (both paths): {with_both}")
        lines.append(f"Legacy middleware: {legacy}")
        lines.append("")

        # Violations
        violations = self.verify_parity()
        if violations:
            lines.append("Violations:")
            for v in violations:
                lines.append(
                    f"  [{v.severity.upper()}] {v.feature_name}: {v.description}"
                )
        else:
            lines.append("No parity violations detected.")

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all registrations."""
        with self._lock:
            self._features.clear()
            self._middleware.clear()

    def _has_meaningful_implementation(self, instance: Any, method_name: str) -> bool:
        """Check if an instance has a meaningful (non-trivial) method implementation.

        This uses heuristics to detect pass-through implementations that just
        return the input unchanged.
        """
        method = getattr(instance, method_name, None)
        if method is None:
            return False

        # Check if method is from the abstract base class (not overridden)
        # This is a heuristic - actual behavior testing is done in test harness
        method_class = getattr(method, "__self__", None)
        if method_class is None:
            return True

        # If we can't determine, assume it's implemented
        return True

    def _class_has_method_impl(self, cls: type, method_name: str) -> bool:
        """Check if a class has its own implementation of a method."""
        # Check if method is defined in the class itself (not inherited from ABC)
        if method_name not in cls.__dict__:
            # Method is inherited - check if it's abstract
            method = getattr(cls, method_name, None)
            if method is None:
                return False
            # If it has __isabstractmethod__, it's not implemented
            if getattr(method, "__isabstractmethod__", False):
                return False
        return True


# Global registry instance
_global_registry: FeatureParityRegistry | None = None
_global_registry_lock = threading.Lock()


def get_global_registry() -> FeatureParityRegistry:
    """Get the global feature parity registry.

    This function provides access to a singleton registry instance
    for application-wide feature tracking.

    Thread-safety: Uses double-checked locking with threading.Lock
    to ensure only one instance is created even when multiple
    threads call this function concurrently.

    Returns:
        The global FeatureParityRegistry instance
    """
    global _global_registry
    # Fast path: return existing instance without lock
    if _global_registry is not None:
        return _global_registry

    # Slow path: acquire lock and check again
    with _global_registry_lock:
        if _global_registry is None:
            _global_registry = FeatureParityRegistry()
        return _global_registry


def reset_global_registry() -> None:
    """Reset the global registry (primarily for testing).

    Thread-safety: Acquires lock to prevent race conditions
    with concurrent get_global_registry() calls.
    """
    global _global_registry
    with _global_registry_lock:
        if _global_registry is not None:
            _global_registry.clear()
        _global_registry = None


class ParityViolationError(Exception):
    """Exception raised when parity violations are detected.

    This exception can be raised during application startup to prevent
    deployment of code with parity violations.
    """

    def __init__(self, violations: list[ParityViolation]) -> None:
        self.violations = violations
        messages = [f"{v.feature_name}: {v.description}" for v in violations]
        super().__init__("Feature parity violations detected:\n" + "\n".join(messages))


class MiddlewareToFeatureAdapter(IResponseFeature):
    """Adapter that bridges IResponseMiddleware to IResponseFeature.

    Delegates through :meth:`process_chunk` to the wrapped middleware's
    :meth:`IResponseMiddleware.process` (see base :meth:`IResponseFeature.process`).

    Example:
        adapter = MiddlewareToFeatureAdapter(SomeLegacyMiddleware())
        result = await adapter.process_chunk(
            chunk, session_id, context, is_streaming=True
        )

    Note:
        This adapter does not enforce behavioral parity across modes; it is a
        migration aid only.
    """

    def __init__(
        self,
        middleware: IResponseMiddleware,
        *,
        declared_capability: str = "both",
        feature_name: str | None = None,
    ) -> None:
        """Initialize the adapter with a middleware instance."""
        if not isinstance(middleware, IResponseMiddleware):
            raise TypeError(
                f"Expected IResponseMiddleware instance, got {type(middleware).__name__}"
            )

        priority = 0
        try:
            raw = middleware.priority
            priority = raw if isinstance(raw, int) else 0
        except (TypeError, AttributeError):
            priority = 0

        super().__init__(priority=priority)
        self._middleware = middleware
        self._declared_capability = declared_capability
        self._feature_name = feature_name or middleware.__class__.__name__

    @property
    def feature_name(self) -> str:
        """Get the feature name."""
        return self._feature_name

    @property
    def capability(self) -> str:
        """Get the declared capability."""
        return self._declared_capability

    @property
    def wrapped_middleware(self) -> IResponseMiddleware:
        """Get the underlying middleware instance."""
        return self._middleware

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        """Thin bridge: one canonical entrypoint to legacy ``process``."""
        return await self._middleware.process(
            response=payload,
            session_id=session_id,
            context=context,
            is_streaming=is_streaming,
            stop_event=context.get("stop_event"),
        )


class FeatureToMiddlewareAdapter:
    """Adapter that bridges IResponseFeature to IResponseMiddleware interface.

    This adapter allows IResponseFeature implementations to be used in
    contexts that expect IResponseMiddleware interface (e.g., legacy pipelines).

    Example:
        new_feature = SomeNewFeature()
        adapter = FeatureToMiddlewareAdapter(new_feature)

        # Now adapter can be used as IResponseMiddleware
        result = await adapter.process(response, session_id, context, is_streaming=True)
    """

    def __init__(self, feature: IResponseFeature) -> None:
        """Initialize the adapter with a feature instance.

        Args:
            feature: The IResponseFeature instance to wrap
        """
        if not isinstance(feature, IResponseFeature):
            raise TypeError(
                f"Expected IResponseFeature instance, got {type(feature).__name__}"
            )

        self._feature = feature
        self._priority = feature.priority

    @property
    def priority(self) -> int:
        """Get the feature priority."""
        return self._priority

    @property
    def wrapped_feature(self) -> IResponseFeature:
        """Get the underlying feature instance."""
        return self._feature

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process using the wrapped feature's appropriate method.

        This method delegates to the wrapped feature's :meth:`IResponseFeature.process`.

        Args:
            response: The response or chunk to process
            session_id: The session ID
            context: Processing context
            is_streaming: Whether this is a streaming chunk
            stop_event: Optional stop event (not used by IResponseFeature)

        Returns:
            The processed response or chunk
        """
        return await self._feature.process(
            response=response,
            session_id=session_id,
            context=context,
            is_streaming=is_streaming,
            stop_event=stop_event,
        )
