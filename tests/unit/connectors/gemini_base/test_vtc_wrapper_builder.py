"""
Unit tests for GeminiVtcWrapperBuilder.

Tests verify VTC wrapper building behavior including service resolution,
fallback handling, and wrapper construction.
"""

from collections.abc import AsyncIterator
from unittest.mock import Mock, patch

import pytest
from src.connectors.gemini_base.vtc_wrapper_builder import GeminiVtcWrapperBuilder
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def vtc_wrapper_builder():
    """Create a GeminiVtcWrapperBuilder instance."""
    return GeminiVtcWrapperBuilder(backend_type="test-backend")


@pytest.fixture
def mock_request_data():
    """Create a mock request data object."""
    request = Mock()
    request.vtc_enabled = False
    request.session_id = "test-session"
    request.agent = "test-agent"
    request.client_os = "test-os"
    return request


@pytest.fixture
def mock_request_data_with_vtc():
    """Create a mock request data object with VTC enabled."""
    request = Mock()
    request.vtc_enabled = True
    request.session_id = "test-session"
    request.agent = "test-agent"
    request.client_os = "test-os"
    return request


class TestBuild:
    """Test build method."""

    def test_returns_none_when_vtc_disabled(
        self, vtc_wrapper_builder, mock_request_data
    ):
        """Verify None is returned when VTC is disabled."""
        result = vtc_wrapper_builder.build(
            request_data=mock_request_data,
            effective_model="test-model",
        )
        assert result is None

    def test_returns_wrapper_when_vtc_enabled_but_no_services(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify wrapper is still returned when VTC enabled but services unavailable."""
        with patch("src.core.di.services.get_service_provider") as mock_get_provider:
            mock_get_provider.side_effect = Exception("Service unavailable")

            result = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            # Wrapper is still created, but with None services (fail-open pattern)
            assert result is not None
            assert callable(result)

    def test_returns_wrapper_when_vtc_enabled_and_services_available(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify wrapper is returned when VTC enabled and services available."""
        mock_reactor = Mock()
        mock_parser = Mock()
        mock_fixup = Mock()

        mock_provider = Mock()
        mock_provider.get_service = Mock(
            side_effect=lambda service_type: {
                "ToolCallReactorService": mock_reactor,
                "IToolArgumentsParser": mock_parser,
                "IToolArgumentsFixupPipeline": mock_fixup,
            }.get(
                service_type.__name__
                if hasattr(service_type, "__name__")
                else str(service_type)
            )
        )

        with patch(
            "src.core.di.services.get_service_provider",
            return_value=mock_provider,
        ):
            result = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            assert result is not None
            assert callable(result)

    def test_wrapper_function_signature(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify wrapper function has correct signature."""
        mock_provider = Mock()
        mock_provider.get_service = Mock(return_value=None)

        with patch(
            "src.core.di.services.get_service_provider",
            return_value=mock_provider,
        ):
            wrapper = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            if wrapper is not None:
                # Verify wrapper accepts AsyncIterator[ProcessedResponse]
                async def mock_generator() -> AsyncIterator[ProcessedResponse]:
                    yield ProcessedResponse(content={})

                # Should not raise when called with correct type
                wrapped = wrapper(mock_generator())
                assert wrapped is not None

    def test_handles_missing_vtc_enabled_attribute(self, vtc_wrapper_builder):
        """Verify handles missing vtc_enabled attribute gracefully."""
        request = Mock()
        del request.vtc_enabled  # Remove attribute

        result = vtc_wrapper_builder.build(
            request_data=request,
            effective_model="test-model",
        )

        assert result is None

    def test_handles_false_vtc_enabled(self, vtc_wrapper_builder):
        """Verify handles False vtc_enabled value."""
        request = Mock()
        request.vtc_enabled = False

        result = vtc_wrapper_builder.build(
            request_data=request,
            effective_model="test-model",
        )

        assert result is None

    def test_handles_none_vtc_enabled(self, vtc_wrapper_builder):
        """Verify handles None vtc_enabled value."""
        request = Mock()
        request.vtc_enabled = None

        result = vtc_wrapper_builder.build(
            request_data=request,
            effective_model="test-model",
        )

        assert result is None

    def test_backend_type_in_reactor_context(self, mock_request_data_with_vtc):
        """Verify backend_type is used when building wrapper."""
        builder = GeminiVtcWrapperBuilder(backend_type="custom-backend")
        mock_provider = Mock()
        mock_provider.get_service = Mock(return_value=None)

        with (
            patch(
                "src.core.di.services.get_service_provider",
                return_value=mock_provider,
            ),
            patch(
                "src.core.services.streaming.vtc_response_wrapper.wrap_processed_response_stream_with_vtc",
                return_value=Mock(__aiter__=lambda: iter([])),
            ),
        ):
            wrapper = builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            # Verify wrapper was created
            assert wrapper is not None

            # The wrapper function captures backend_type, model_name, etc. in its closure
            # We verify the builder uses the correct backend_type by checking it's set
            assert builder._backend_type == "custom-backend"

    def test_handles_partial_di_service_failure(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify handles partial DI service resolution failure gracefully.

        Requirement: 4.1 (unit testability), edge case coverage.
        """
        mock_provider = Mock()
        # First service resolves, second fails
        call_count = 0

        def get_service_side_effect(service_type):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Mock()  # First service succeeds
            elif call_count == 2:
                raise Exception("Service resolution failed")  # Second service fails
            return None

        mock_provider.get_service = Mock(side_effect=get_service_side_effect)

        with patch(
            "src.core.di.services.get_service_provider",
            return_value=mock_provider,
        ):
            # Should not raise, should handle partial failure gracefully
            result = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            # Wrapper should still be created (fail-open pattern)
            assert result is not None
            assert callable(result)

    def test_handles_get_service_provider_returning_none(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify handles get_service_provider returning None gracefully.

        Requirement: 4.1 (unit testability), edge case coverage.
        """
        with patch(
            "src.core.di.services.get_service_provider",
            return_value=None,
        ):
            # Should not raise when provider is None
            result = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            # Wrapper should still be created (fail-open pattern)
            assert result is not None
            assert callable(result)

    def test_handles_missing_tool_call_reactor_service(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify handles missing ToolCallReactorService gracefully.

        Requirement: 3.2 (DI wiring), design.md service resolution.
        """
        mock_provider = Mock()
        mock_provider.get_service = Mock(
            side_effect=lambda service_type: {
                "ToolCallReactorService": None,  # Missing
                "IToolArgumentsParser": Mock(),
                "IToolArgumentsFixupPipeline": Mock(),
            }.get(
                service_type.__name__
                if hasattr(service_type, "__name__")
                else str(service_type)
            )
        )

        with patch(
            "src.core.di.services.get_service_provider",
            return_value=mock_provider,
        ):
            result = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            # Wrapper should still be created (fail-open pattern)
            assert result is not None
            assert callable(result)

    def test_handles_missing_tool_arguments_parser(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify handles missing IToolArgumentsParser gracefully.

        Requirement: 3.2 (DI wiring), design.md service resolution.
        """
        mock_provider = Mock()
        mock_provider.get_service = Mock(
            side_effect=lambda service_type: {
                "ToolCallReactorService": Mock(),
                "IToolArgumentsParser": None,  # Missing
                "IToolArgumentsFixupPipeline": Mock(),
            }.get(
                service_type.__name__
                if hasattr(service_type, "__name__")
                else str(service_type)
            )
        )

        with patch(
            "src.core.di.services.get_service_provider",
            return_value=mock_provider,
        ):
            result = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            # Wrapper should still be created (fail-open pattern)
            assert result is not None
            assert callable(result)

    def test_handles_missing_tool_arguments_fixup_pipeline(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify handles missing IToolArgumentsFixupPipeline gracefully.

        Requirement: 3.2 (DI wiring), design.md service resolution.
        """
        mock_provider = Mock()
        mock_provider.get_service = Mock(
            side_effect=lambda service_type: {
                "ToolCallReactorService": Mock(),
                "IToolArgumentsParser": Mock(),
                "IToolArgumentsFixupPipeline": None,  # Missing
            }.get(
                service_type.__name__
                if hasattr(service_type, "__name__")
                else str(service_type)
            )
        )

        with patch(
            "src.core.di.services.get_service_provider",
            return_value=mock_provider,
        ):
            result = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            # Wrapper should still be created (fail-open pattern)
            assert result is not None
            assert callable(result)

    def test_handles_all_services_missing(
        self, vtc_wrapper_builder, mock_request_data_with_vtc
    ):
        """Verify handles all services missing gracefully.

        Requirement: 3.2 (DI wiring), design.md fail-open pattern.
        """
        mock_provider = Mock()
        mock_provider.get_service = Mock(return_value=None)  # All services return None

        with patch(
            "src.core.di.services.get_service_provider",
            return_value=mock_provider,
        ):
            result = vtc_wrapper_builder.build(
                request_data=mock_request_data_with_vtc,
                effective_model="test-model",
            )

            # Wrapper should still be created (fail-open pattern)
            assert result is not None
            assert callable(result)
