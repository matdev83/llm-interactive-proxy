"""
Unit tests for feature parity enforcement infrastructure.

This module tests:
1. IResponseFeature interface and template method pattern
2. FeatureParityRegistry for tracking feature support
3. Adapters for bridging middleware/feature interfaces
4. Parity verification and violation detection

Scope note: :meth:`FeatureParityRegistry.verify_parity` is declaration-focused for
``IResponseFeature`` (capability vs. ``process_chunk`` presence) and emits
informational notices for legacy ``IResponseMiddleware``. It does **not** prove
streaming vs. non-streaming semantic equivalence for legacy middleware; that
requires runtime checks (see ``TestParityVerification`` and adapter tests below).
"""

from __future__ import annotations

from typing import Any

import pytest
from src.core.interfaces.feature_parity import (
    FeatureParityRegistry,
    FeatureToMiddlewareAdapter,
    MiddlewareToFeatureAdapter,
    ParityViolation,
    ParityViolationError,
    get_global_registry,
    reset_global_registry,
)
from src.core.interfaces.response_processor_interface import (
    FeatureCapability,
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)

# ============================================================================
# Test Fixtures: Concrete Implementations for Testing
# ============================================================================


class ConcreteFeatureWithParity(IResponseFeature):
    """A feature that properly implements both paths with equivalent behavior."""

    def __init__(self, transform_fn=None, priority: int = 0) -> None:
        super().__init__(priority)
        self._transform_fn = transform_fn or (lambda x: x)
        self._streaming_calls: list[Any] = []
        self._non_streaming_calls: list[Any] = []

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        if is_streaming:
            self._streaming_calls.append(payload)
        else:
            self._non_streaming_calls.append(payload)
        if isinstance(payload, ProcessedResponse):
            return ProcessedResponse(
                content=self._transform_fn(payload.content),
                usage=payload.usage,
                metadata=payload.metadata,
            )
        return self._transform_fn(payload)


class StreamingOnlyFeature(IResponseFeature):
    """A feature that only provides meaningful streaming implementation."""

    @property
    def capability(self) -> str:
        return FeatureCapability.STREAMING

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        if not is_streaming:
            return payload
        if isinstance(payload, ProcessedResponse):
            return ProcessedResponse(
                content=f"[STREAM] {payload.content}",
                usage=payload.usage,
                metadata=payload.metadata,
            )
        return f"[STREAM] {payload}"


class NonStreamingOnlyFeature(IResponseFeature):
    """A feature that only provides meaningful non-streaming implementation."""

    @property
    def capability(self) -> str:
        return FeatureCapability.NON_STREAMING

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        if is_streaming:
            return payload
        if isinstance(payload, ProcessedResponse):
            return ProcessedResponse(
                content=f"[COMPLETE] {payload.content}",
                usage=payload.usage,
                metadata=payload.metadata,
            )
        return f"[COMPLETE] {payload}"


class LegacyMiddleware(IResponseMiddleware):
    """A legacy middleware using the old interface."""

    def __init__(self, priority: int = 0) -> None:
        super().__init__(priority)
        self._calls: list[tuple[Any, bool]] = []

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Legacy process method that handles both paths."""
        self._calls.append((response, is_streaming))
        if isinstance(response, ProcessedResponse):
            return ProcessedResponse(
                content=f"[LEGACY:{is_streaming}] {response.content}",
                usage=response.usage,
                metadata=response.metadata,
            )
        return f"[LEGACY:{is_streaming}] {response}"


class DivergentLegacyMiddleware(IResponseMiddleware):
    """A legacy middleware with different behavior for streaming vs non-streaming."""

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process with divergent behavior."""
        if is_streaming:
            # Different behavior for streaming
            return response  # Pass-through for streaming
        else:
            # Actual processing for non-streaming
            if isinstance(response, ProcessedResponse):
                return ProcessedResponse(
                    content=f"[PROCESSED] {response.content}",
                    usage=response.usage,
                    metadata=response.metadata,
                )
            return f"[PROCESSED] {response}"


# ============================================================================
# Test: IResponseFeature Interface
# ============================================================================


class TestIResponseFeature:
    """Tests for IResponseFeature interface and template method pattern."""

    @pytest.mark.asyncio
    async def test_template_method_delegates_to_streaming(self):
        """Test that process() hits process_chunk with is_streaming=True."""
        feature = ConcreteFeatureWithParity(lambda x: f"TRANSFORMED:{x}")
        response = ProcessedResponse(content="test")

        result = await feature.process(response, "session1", {}, is_streaming=True)

        assert len(feature._streaming_calls) == 1
        assert len(feature._non_streaming_calls) == 0
        assert result.content == "TRANSFORMED:test"

    @pytest.mark.asyncio
    async def test_template_method_delegates_to_non_streaming(self):
        """Test that process() hits process_chunk with is_streaming=False."""
        feature = ConcreteFeatureWithParity(lambda x: f"TRANSFORMED:{x}")
        response = ProcessedResponse(content="test")

        result = await feature.process(response, "session1", {}, is_streaming=False)

        assert len(feature._streaming_calls) == 0
        assert len(feature._non_streaming_calls) == 1
        assert result.content == "TRANSFORMED:test"

    @pytest.mark.asyncio
    async def test_default_capability_is_both(self):
        """Test that default capability is BOTH."""
        feature = ConcreteFeatureWithParity()
        assert feature.capability == FeatureCapability.BOTH

    @pytest.mark.asyncio
    async def test_custom_capability(self):
        """Test that capability can be overridden."""
        feature = StreamingOnlyFeature()
        assert feature.capability == FeatureCapability.STREAMING

        feature = NonStreamingOnlyFeature()
        assert feature.capability == FeatureCapability.NON_STREAMING

    @pytest.mark.asyncio
    async def test_feature_name_defaults_to_class_name(self):
        """Test that feature_name defaults to class name."""
        feature = ConcreteFeatureWithParity()
        assert feature.feature_name == "ConcreteFeatureWithParity"

    @pytest.mark.asyncio
    async def test_priority_is_settable(self):
        """Test that priority can be set in constructor."""
        feature = ConcreteFeatureWithParity(priority=100)
        assert feature.priority == 100


# ============================================================================
# Test: FeatureParityRegistry
# ============================================================================


class TestFeatureParityRegistry:
    """Tests for FeatureParityRegistry functionality."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry for each test."""
        return FeatureParityRegistry()

    def test_register_feature_success(self, registry):
        """Test successful feature registration."""
        feature = ConcreteFeatureWithParity()
        registry.register_feature(feature)

        all_features = registry.get_all_features()
        assert "ConcreteFeatureWithParity" in all_features

        reg = all_features["ConcreteFeatureWithParity"]
        assert reg.capability == FeatureCapability.BOTH
        assert reg.has_streaming_impl is True
        assert reg.has_non_streaming_impl is True

    def test_register_feature_type_error(self, registry):
        """Test that non-IResponseFeature raises TypeError."""
        with pytest.raises(TypeError, match="Expected IResponseFeature"):
            registry.register_feature("not a feature")  # type: ignore

    def test_register_middleware_success(self, registry):
        """Test successful middleware registration."""
        middleware = LegacyMiddleware()
        registry.register_middleware(middleware, declared_capability="both")

        all_features = registry.get_all_features()
        assert "LegacyMiddleware" in all_features

        reg = all_features["LegacyMiddleware"]
        assert reg.capability == "both"
        assert reg.metadata.get("legacy") is True

    def test_register_middleware_with_custom_name(self, registry):
        """Test middleware registration with custom name."""
        middleware = LegacyMiddleware()
        registry.register_middleware(middleware, name="CustomName")

        all_features = registry.get_all_features()
        assert "CustomName" in all_features

    def test_get_features_by_capability_streaming(self, registry):
        """Test filtering features by streaming capability."""
        registry.register_feature(ConcreteFeatureWithParity())
        registry.register_feature(StreamingOnlyFeature())
        registry.register_feature(NonStreamingOnlyFeature())
        registry.register_middleware(
            LegacyMiddleware(),
            declared_capability="non_streaming",
            name="MwDeclaredNonStreamingOnly",
        )

        streaming = registry.get_features_by_capability("streaming")
        names = [f.name for f in streaming]

        assert "ConcreteFeatureWithParity" in names
        assert "StreamingOnlyFeature" in names
        assert "NonStreamingOnlyFeature" in names
        assert "MwDeclaredNonStreamingOnly" not in names

    def test_get_features_by_capability_both(self, registry):
        """Test filtering features with both capabilities."""
        registry.register_feature(ConcreteFeatureWithParity())
        registry.register_feature(StreamingOnlyFeature())
        registry.register_middleware(
            LegacyMiddleware(),
            declared_capability="streaming",
            name="MwDeclaredStreamingOnly",
        )
        registry.register_middleware(
            LegacyMiddleware(),
            declared_capability="non_streaming",
            name="MwDeclaredNonStreamingOnly2",
        )

        both = registry.get_features_by_capability("both")
        names = [f.name for f in both]

        assert "ConcreteFeatureWithParity" in names
        assert "StreamingOnlyFeature" in names
        assert "MwDeclaredStreamingOnly" not in names
        assert "MwDeclaredNonStreamingOnly2" not in names

    def test_get_features_by_capability_non_streaming(self, registry):
        """Legacy middleware declared streaming-only is excluded from non-streaming filter."""
        registry.register_feature(ConcreteFeatureWithParity())
        registry.register_feature(StreamingOnlyFeature())
        registry.register_middleware(
            LegacyMiddleware(),
            declared_capability="streaming",
            name="MwDeclaredStreamingOnlyForNonStreamTest",
        )

        non_streaming = registry.get_features_by_capability("non_streaming")
        names = [f.name for f in non_streaming]

        assert "ConcreteFeatureWithParity" in names
        assert "StreamingOnlyFeature" in names
        assert "MwDeclaredStreamingOnlyForNonStreamTest" not in names

    def test_verify_parity_no_violations(self, registry):
        """Test that properly implemented features have no violations."""
        registry.register_feature(ConcreteFeatureWithParity())

        violations = registry.verify_parity()
        # Filter out info-level violations (like legacy warnings)
        errors = [v for v in violations if v.severity in ("error", "warning")]
        assert len(errors) == 0

    def test_verify_parity_legacy_middleware_info(self, registry):
        """Test that legacy middleware generates info violation."""
        registry.register_middleware(LegacyMiddleware(), declared_capability="both")

        violations = registry.verify_parity()
        info_violations = [v for v in violations if v.severity == "info"]

        assert len(info_violations) == 1
        assert "legacy IResponseMiddleware" in info_violations[0].description

    def test_verify_parity_divergent_legacy_middleware_stays_declaration_only(
        self, registry
    ):
        """Divergent legacy middleware still only triggers registry declaration checks."""
        registry.register_middleware(
            DivergentLegacyMiddleware(),
            declared_capability="both",
            name="DivergentLegacyForRegistry",
        )

        violations = registry.verify_parity()
        assert len(violations) == 1
        assert violations[0].severity == "info"
        assert "legacy" in violations[0].description.lower()
        assert not any(v.severity in ("error", "warning") for v in violations)

    def test_parity_report_generation(self, registry):
        """Test that parity report is generated correctly."""
        registry.register_feature(ConcreteFeatureWithParity())
        registry.register_middleware(LegacyMiddleware(), declared_capability="both")

        report = registry.get_parity_report()

        assert "Feature Parity Report" in report
        assert "Total features: 2" in report
        assert "Legacy middleware: 1" in report

    def test_clear_removes_all_registrations(self, registry):
        """Test that clear() removes all registrations."""
        registry.register_feature(ConcreteFeatureWithParity())
        registry.register_middleware(LegacyMiddleware())

        assert len(registry.get_all_features()) == 2

        registry.clear()

        assert len(registry.get_all_features()) == 0


# ============================================================================
# Test: Global Registry
# ============================================================================


class TestGlobalRegistry:
    """Tests for global registry singleton."""

    def setup_method(self):
        """Reset global registry before each test."""
        reset_global_registry()

    def teardown_method(self):
        """Reset global registry after each test."""
        reset_global_registry()

    def test_get_global_registry_returns_singleton(self):
        """Test that get_global_registry returns same instance."""
        reg1 = get_global_registry()
        reg2 = get_global_registry()
        assert reg1 is reg2

    def test_reset_global_registry(self):
        """Test that reset creates new instance."""
        reg1 = get_global_registry()
        reg1.register_feature(ConcreteFeatureWithParity())

        reset_global_registry()

        reg2 = get_global_registry()
        assert reg1 is not reg2
        assert len(reg2.get_all_features()) == 0


# ============================================================================
# Test: Adapters
# ============================================================================


class TestMiddlewareToFeatureAdapter:
    """Tests for MiddlewareToFeatureAdapter."""

    @pytest.mark.asyncio
    async def test_adapter_delegates_streaming(self):
        """Test that adapter delegates streaming calls correctly."""
        middleware = LegacyMiddleware()
        adapter = MiddlewareToFeatureAdapter(middleware)

        result = await adapter.process_chunk(
            ProcessedResponse(content="test"), "session1", {}, is_streaming=True
        )

        assert len(middleware._calls) == 1
        assert middleware._calls[0][1] is True  # is_streaming=True
        assert "[LEGACY:True]" in result.content

    @pytest.mark.asyncio
    async def test_adapter_delegates_non_streaming(self):
        """Test that adapter delegates non-streaming calls correctly."""
        middleware = LegacyMiddleware()
        adapter = MiddlewareToFeatureAdapter(middleware)

        result = await adapter.process_chunk(
            ProcessedResponse(content="test"), "session1", {}, is_streaming=False
        )

        assert len(middleware._calls) == 1
        assert middleware._calls[0][1] is False  # is_streaming=False
        assert "[LEGACY:False]" in result.content

    @pytest.mark.asyncio
    async def test_adapter_process_method(self):
        """Test that adapter process() method works like IResponseFeature."""
        middleware = LegacyMiddleware()
        adapter = MiddlewareToFeatureAdapter(middleware)

        result = await adapter.process(
            ProcessedResponse(content="test"), "session1", {}, is_streaming=True
        )

        assert "[LEGACY:True]" in result.content

    def test_adapter_type_error_for_non_middleware(self):
        """Test that adapter rejects non-middleware."""
        with pytest.raises(TypeError, match="Expected IResponseMiddleware"):
            MiddlewareToFeatureAdapter("not middleware")  # type: ignore

    def test_adapter_priority_passthrough(self):
        """Test that adapter preserves middleware priority."""
        middleware = LegacyMiddleware(priority=50)
        adapter = MiddlewareToFeatureAdapter(middleware)
        assert adapter.priority == 50

    def test_adapter_feature_name(self):
        """Test that adapter feature_name defaults to middleware class name."""
        middleware = LegacyMiddleware()
        adapter = MiddlewareToFeatureAdapter(middleware)
        assert adapter.feature_name == "LegacyMiddleware"

        adapter_named = MiddlewareToFeatureAdapter(
            middleware, feature_name="CustomName"
        )
        assert adapter_named.feature_name == "CustomName"


class TestFeatureToMiddlewareAdapter:
    """Tests for FeatureToMiddlewareAdapter."""

    @pytest.mark.asyncio
    async def test_adapter_delegates_to_feature(self):
        """Test that adapter delegates to feature correctly."""
        feature = ConcreteFeatureWithParity(lambda x: f"PROCESSED:{x}")
        adapter = FeatureToMiddlewareAdapter(feature)

        result = await adapter.process(
            ProcessedResponse(content="test"),
            "session1",
            {},
            is_streaming=True,
        )

        assert len(feature._streaming_calls) == 1
        assert result.content == "PROCESSED:test"

    @pytest.mark.asyncio
    async def test_adapter_non_streaming(self):
        """Test adapter with non-streaming."""
        feature = ConcreteFeatureWithParity(lambda x: f"PROCESSED:{x}")
        adapter = FeatureToMiddlewareAdapter(feature)

        result = await adapter.process(
            ProcessedResponse(content="test"),
            "session1",
            {},
            is_streaming=False,
        )

        assert len(feature._non_streaming_calls) == 1
        assert result.content == "PROCESSED:test"

    def test_adapter_type_error_for_non_feature(self):
        """Test that adapter rejects non-feature."""
        with pytest.raises(TypeError, match="Expected IResponseFeature"):
            FeatureToMiddlewareAdapter("not feature")  # type: ignore

    def test_adapter_priority_passthrough(self):
        """Test that adapter preserves feature priority."""
        feature = ConcreteFeatureWithParity(priority=75)
        adapter = FeatureToMiddlewareAdapter(feature)
        assert adapter.priority == 75


# ============================================================================
# Test: ParityViolationError
# ============================================================================


class TestParityViolationError:
    """Tests for ParityViolationError exception."""

    def test_error_message_includes_violations(self):
        """Test that error message includes all violations."""
        violations = [
            ParityViolation(
                feature_name="Feature1",
                violation_type="missing_streaming",
                description="Missing streaming implementation",
            ),
            ParityViolation(
                feature_name="Feature2",
                violation_type="missing_non_streaming",
                description="Missing non-streaming implementation",
            ),
        ]

        error = ParityViolationError(violations)

        assert "Feature1" in str(error)
        assert "Feature2" in str(error)
        assert "Missing streaming" in str(error)
        assert "Missing non-streaming" in str(error)

    def test_error_stores_violations(self):
        """Test that error stores violation list."""
        violations = [
            ParityViolation(
                feature_name="Test",
                violation_type="test",
                description="Test violation",
            )
        ]

        error = ParityViolationError(violations)
        assert error.violations == violations


# ============================================================================
# Test: Parity Verification (Runtime Behavior Testing)
# ============================================================================


class TestParityVerification:
    """Tests for runtime parity verification.

    These tests verify that features behave equivalently for streaming
    and non-streaming inputs when they claim to support both.
    """

    @pytest.mark.asyncio
    async def test_feature_with_parity_produces_equivalent_results(self):
        """Test that a feature with parity produces equivalent results."""
        feature = ConcreteFeatureWithParity(lambda x: f"[PROCESSED]{x}")

        # Same input
        input_content = "test content"

        streaming_result = await feature.process_chunk(
            ProcessedResponse(content=input_content),
            "session",
            {},
            is_streaming=True,
        )
        non_streaming_result = await feature.process_chunk(
            ProcessedResponse(content=input_content),
            "session",
            {},
            is_streaming=False,
        )

        # Results should be equivalent
        assert streaming_result.content == non_streaming_result.content
        assert streaming_result.content == f"[PROCESSED]{input_content}"

    @pytest.mark.asyncio
    async def test_divergent_middleware_shows_different_results(self):
        """Test that divergent middleware produces different results."""
        middleware = DivergentLegacyMiddleware()
        adapter = MiddlewareToFeatureAdapter(middleware)

        input_content = "test content"

        streaming_result = await adapter.process_chunk(
            ProcessedResponse(content=input_content),
            "session",
            {},
            is_streaming=True,
        )
        non_streaming_result = await adapter.process_chunk(
            ProcessedResponse(content=input_content),
            "session",
            {},
            is_streaming=False,
        )

        # Results should be DIFFERENT (divergent behavior)
        assert streaming_result.content != non_streaming_result.content
        # Streaming passes through
        assert streaming_result.content == input_content
        # Non-streaming processes
        assert "[PROCESSED]" in non_streaming_result.content


# ============================================================================
# Test: Integration with Real Middleware Pattern
# ============================================================================


class TestIntegrationWithMiddlewarePipeline:
    """Integration tests showing how features work with middleware pipeline."""

    @pytest.mark.asyncio
    async def test_feature_can_be_used_in_middleware_list(self):
        """Test that IResponseFeature can be used alongside IResponseMiddleware."""
        # Create a mix of features and middleware
        feature = ConcreteFeatureWithParity(lambda x: f"[FEATURE]{x}")
        legacy = LegacyMiddleware()

        # Both should be callable with process()
        input_data = ProcessedResponse(content="test")
        context: dict[str, Any] = {}

        feature_result = await feature.process(
            input_data, "session", context, is_streaming=True
        )
        legacy_result = await legacy.process(
            input_data, "session", context, is_streaming=True
        )

        assert "[FEATURE]" in feature_result.content
        assert "[LEGACY:True]" in legacy_result.content

    @pytest.mark.asyncio
    async def test_adapted_middleware_works_in_feature_context(self):
        """Test that adapted middleware works in feature-based pipeline."""
        legacy = LegacyMiddleware()
        adapted = MiddlewareToFeatureAdapter(legacy)

        result = await adapted.process_chunk(
            ProcessedResponse(content="test"), "session", {}, is_streaming=True
        )

        assert "[LEGACY:True]" in result.content

    @pytest.mark.asyncio
    async def test_adapted_feature_works_in_middleware_context(self):
        """Test that adapted feature works in middleware-based pipeline."""
        feature = ConcreteFeatureWithParity(lambda x: f"[NEW]{x}")
        adapted = FeatureToMiddlewareAdapter(feature)

        # Now we can call the middleware-style method
        result = await adapted.process(
            ProcessedResponse(content="test"),
            "session",
            {},
            is_streaming=True,
        )

        assert "[NEW]" in result.content
