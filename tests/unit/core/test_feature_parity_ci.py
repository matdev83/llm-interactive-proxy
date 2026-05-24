"""
CI test for feature parity enforcement.

This test verifies that all middleware/features in the codebase have
declared their streaming/non-streaming capabilities, enabling automated
detection of feature parity gaps.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
)


def _find_middleware_classes() -> list[tuple[str, type]]:
    """Find all IResponseMiddleware and IResponseFeature classes in src."""
    middleware_classes: list[tuple[str, type]] = []

    # Walk through src directory to find all Python modules
    src_path = Path(__file__).parent.parent.parent.parent / "src"

    for module_info in pkgutil.walk_packages(
        [str(src_path)], prefix="src.", onerror=lambda _: None
    ):
        try:
            module = importlib.import_module(module_info.name)

            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Skip imported classes (only check classes defined in this module)
                if obj.__module__ != module_info.name:
                    continue

                # Check if it's a middleware or feature
                if issubclass(obj, IResponseMiddleware | IResponseFeature):
                    # Skip the base interfaces themselves
                    if obj in (IResponseMiddleware, IResponseFeature):
                        continue
                    # Skip test fixtures
                    if "test" in module_info.name.lower():
                        continue
                    middleware_classes.append((f"{module_info.name}.{name}", obj))

        except Exception:
            # Skip modules that fail to import
            continue

    return middleware_classes


@pytest.fixture(scope="session")
def middleware_classes_cache() -> list[tuple[str, type]]:
    """Session-scoped cache for discovered middleware classes."""
    return _find_middleware_classes()


class TestFeatureParityCI:
    """CI tests for feature parity enforcement."""

    @pytest.mark.quality
    def test_all_middleware_are_discoverable(self, middleware_classes_cache):
        """Test that we can discover middleware classes in codebase."""
        classes = middleware_classes_cache

        # We should find at least some middleware
        assert len(classes) > 0, "Should discover at least one middleware class"

        # Log discovered classes for debugging
        class_names = [name for name, _ in classes]
        assert (
            len(class_names) > 5
        ), f"Expected to find multiple middleware, found: {class_names}"

    @pytest.mark.quality
    def test_known_middleware_have_feature_versions(self, middleware_classes_cache):
        """Test that key middleware have IResponseFeature versions.

        This test verifies that middleware with known parity gaps have been
        updated to include IResponseFeature versions with explicit
        streaming/non-streaming support.
        """
        # These are middleware that previously had parity gaps
        # and should now have Feature versions
        # Note: JsonRepairFeature is in src.core.app.middleware which may not be
        # discovered by pkgutil in all scenarios, so we check it separately
        expected_features = {
            "EmptyResponseFeature",
            "StructuredOutputFeature",
            "ResponseLoggingFeature",
            "ContentFilterFeature",
        }

        # Verify JsonRepairFeature can be imported directly
        from src.core.app.middleware.json_repair_middleware import JsonRepairFeature

        assert issubclass(JsonRepairFeature, IResponseFeature)

        classes = middleware_classes_cache
        found_features = {
            name.split(".")[-1]
            for name, cls in classes
            if issubclass(cls, IResponseFeature) and cls is not IResponseFeature
        }

        missing = expected_features - found_features
        assert not missing, (
            f"Missing IResponseFeature versions for: {missing}\n"
            f"Found features: {found_features}"
        )

    @pytest.mark.quality
    def test_features_have_required_methods(self, middleware_classes_cache):
        """Test that all IResponseFeature classes implement required methods."""
        classes = middleware_classes_cache

        for full_name, cls in classes:
            if not issubclass(cls, IResponseFeature) or cls is IResponseFeature:
                continue

            assert hasattr(cls, "process_chunk"), (
                f"{full_name} missing process_chunk method "
                "(canonical IResponseFeature path)"
            )

            if inspect.isabstract(cls):
                continue

            assert callable(
                cls.process_chunk
            ), f"{full_name}.process_chunk should be callable"

    @pytest.mark.quality
    def test_middleware_have_capability_attribute(self, middleware_classes_cache):
        """Test that IResponseFeature classes declare their capability."""
        classes = middleware_classes_cache

        for full_name, cls in classes:
            if not issubclass(cls, IResponseFeature) or cls is IResponseFeature:
                continue

            if inspect.isabstract(cls):
                continue

            # Check for capability property
            assert hasattr(
                cls, "capability"
            ), f"{full_name} should have 'capability' property"

    @pytest.mark.quality
    def test_typed_feature_lifecycle_context_carries_stream_metadata(self) -> None:
        """Canonical feature path relies on typed lifecycle context (not startup registry)."""
        from src.core.domain.feature_lifecycle_context import FeatureLifecycleContext

        ctx = FeatureLifecycleContext(
            is_streaming=True,
            is_terminal_chunk=True,
            finish_reason="stop",
            session_id="sess-1",
            stream_id="str-9",
            request_id="req-2",
            backend_name="openai",
            model_name="gpt-test",
            non_streaming_single_chunk=False,
        )
        assert ctx.is_streaming is True
        assert ctx.is_terminal_chunk is True
        assert ctx.finish_reason == "stop"
        assert ctx.session_id == "sess-1"
        assert ctx.stream_id == "str-9"
        assert ctx.request_id == "req-2"
        assert ctx.backend_name == "openai"
        assert ctx.model_name == "gpt-test"
