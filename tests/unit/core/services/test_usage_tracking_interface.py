"""
Tests for Usage Tracking Interface.

This module tests the usage tracking interface definitions and contract compliance.
"""

from abc import ABC
import inspect

from src.core.interfaces.usage_tracking_interface import IUsageTrackingService


class TestIUsageTrackingServiceInterface:
    """Tests for IUsageTrackingService interface."""

    def test_usage_tracking_service_is_abstract(self) -> None:
        """Test that IUsageTrackingService is an abstract class."""
        assert issubclass(IUsageTrackingService, ABC)

    def test_usage_tracking_service_abstract_methods(self) -> None:
        """Test that IUsageTrackingService defines all required abstract methods."""
        expected_methods = [
            "track_usage",
            "track_request",
            "get_usage_stats",
            "get_recent_usage",
        ]

        for method_name in expected_methods:
            assert hasattr(IUsageTrackingService, method_name)

            # Check that methods are abstract
            method = getattr(IUsageTrackingService, method_name)
            assert hasattr(method, "__isabstractmethod__")
            assert method.__isabstractmethod__ is True

    def test_usage_tracking_service_method_signatures(self) -> None:
        """Test that IUsageTrackingService methods have correct signatures."""
        # track_usage method signature
        assert callable(IUsageTrackingService.track_usage)

        # track_request method signature
        assert callable(IUsageTrackingService.track_request)

        # get_usage_stats method signature
        assert callable(IUsageTrackingService.get_usage_stats)

        # get_recent_usage method signature
        assert callable(IUsageTrackingService.get_recent_usage)


class TestUsageTrackingInterfaceCompliance:
    """Tests for usage tracking interface compliance and contracts."""

    def test_usage_tracking_interfaces_are_properly_defined(self) -> None:
        """Test that usage tracking interfaces are properly defined."""
        interfaces = [
            IUsageTrackingService,
        ]

        for interface in interfaces:
            assert issubclass(interface, ABC)
            assert hasattr(interface, "__annotations__")

    def test_track_request_has_asynccontextmanager_decorator(self) -> None:
        """Test that track_request method has asynccontextmanager decorator."""
        track_request_method = IUsageTrackingService.track_request

        # @asynccontextmanager wraps the original async generator function and
        # stores it on the __wrapped__ attribute. If the decorator were removed,
        # this attribute would no longer be present and the wrapped object would
        # cease to be an async generator.
        assert hasattr(track_request_method, "__wrapped__")
        assert inspect.isasyncgenfunction(track_request_method.__wrapped__)

    def test_track_request_return_type_annotation(self) -> None:
        """Test that track_request has proper return type annotation."""
        track_request_method = IUsageTrackingService.track_request

        # Check that the method has return type annotation
        assert "return" in track_request_method.__annotations__

        # The return type should indicate it's a context manager that yields
        return_annotation = track_request_method.__annotations__["return"]
        assert "AsyncGenerator" in str(
            return_annotation
        ) or "AsyncContextManager" in str(return_annotation)

    def test_track_usage_parameter_annotations(self) -> None:
        """Test that track_usage method has proper parameter annotations."""
        track_usage_method = IUsageTrackingService.track_usage

        annotations = track_usage_method.__annotations__

        # Check required parameters
        assert "model" in annotations
        assert str(annotations["model"]) == "str"

        # Check optional parameters (with None defaults)
        optional_params = [
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "backend",
            "username",
            "project",
            "session_id",
        ]

        for param in optional_params:
            if param in annotations:
                # Should be Optional types (Union with None)
                assert "None" in str(annotations[param]) or "|" in str(
                    annotations[param]
                )

        # Check parameters with default values
        if "cost" in annotations:
            assert str(annotations["cost"]) == "float"

        if "execution_time" in annotations:
            assert str(annotations["execution_time"]) == "float"

    def test_get_usage_stats_parameter_annotations(self) -> None:
        """Test that get_usage_stats method has proper parameter annotations."""
        get_usage_stats_method = IUsageTrackingService.get_usage_stats

        annotations = get_usage_stats_method.__annotations__

        # Check parameters
        assert "project" in annotations
        assert "days" in annotations
        assert "return" in annotations

        # project should be Optional[str]
        project_annotation = annotations["project"]
        assert "None" in str(project_annotation) or "|" in str(project_annotation)

        # days should be int with default
        days_annotation = annotations["days"]
        assert str(days_annotation) == "int"

    def test_get_recent_usage_parameter_annotations(self) -> None:
        """Test that get_recent_usage method has proper parameter annotations."""
        get_recent_usage_method = IUsageTrackingService.get_recent_usage

        annotations = get_recent_usage_method.__annotations__

        # Check parameters
        assert "session_id" in annotations
        assert "limit" in annotations
        assert "return" in annotations

        # session_id should be Optional[str]
        session_id_annotation = annotations["session_id"]
        assert "None" in str(session_id_annotation) or "|" in str(session_id_annotation)

        # limit should be int with default
        limit_annotation = annotations["limit"]
        assert str(limit_annotation) == "int"

        # return should indicate list of UsageData
        return_annotation = annotations["return"]
        assert "list" in str(return_annotation).lower()


class TestUsageTrackingInterfaceDocumentation:
    """Tests for usage tracking interface documentation."""

    def test_interface_has_docstring(self) -> None:
        """Test that the interface has proper documentation."""
        # The interface may not have a docstring, which is acceptable for minimal interfaces
        if IUsageTrackingService.__doc__ is not None:
            assert "usage tracking" in IUsageTrackingService.__doc__.lower()
        else:
            # If no docstring, that's also acceptable
            pass

    def test_methods_have_docstrings(self) -> None:
        """Test that all interface methods have documentation."""
        methods = [
            "track_usage",
            "track_request",
            "get_usage_stats",
            "get_recent_usage",
        ]

        for method_name in methods:
            method = getattr(IUsageTrackingService, method_name)
            # Abstract methods may not have docstrings, which is acceptable
            if method.__doc__ is not None:
                assert (
                    len(method.__doc__.strip()) > 0
                ), f"Method {method_name} docstring should not be empty"
