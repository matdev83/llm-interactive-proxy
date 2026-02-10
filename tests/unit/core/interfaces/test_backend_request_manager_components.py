"""Tests for backend request manager component interfaces."""

from __future__ import annotations

import pytest
from src.core.interfaces.backend_request_manager_components import (
    IBackendRequestPreparation,
    ILoopDetectorFactory,
    INonStreamingBackendResponseHandler,
    IQualityVerifierStreamVerifier,
    IStreamingBackendResponseHandler,
    IStructuredOutputEnforcer,
    IToolCallRetryCoordinator,
)


class TestIBackendRequestPreparation:
    """Tests for IBackendRequestPreparation interface contract."""

    def test_interface_is_abstract(self) -> None:
        """Test that IBackendRequestPreparation cannot be instantiated."""
        with pytest.raises(TypeError):
            IBackendRequestPreparation()  # type: ignore[abstract]

    def test_interface_has_prepare_method(self) -> None:
        """Test that IBackendRequestPreparation defines prepare method."""
        assert hasattr(IBackendRequestPreparation, "prepare")
        assert callable(IBackendRequestPreparation.prepare)


class TestINonStreamingBackendResponseHandler:
    """Tests for INonStreamingBackendResponseHandler interface contract."""

    def test_interface_is_abstract(self) -> None:
        """Test that INonStreamingBackendResponseHandler cannot be instantiated."""
        with pytest.raises(TypeError):
            INonStreamingBackendResponseHandler()  # type: ignore[abstract]

    def test_interface_has_handle_method(self) -> None:
        """Test that INonStreamingBackendResponseHandler defines handle method."""
        assert hasattr(INonStreamingBackendResponseHandler, "handle")
        assert callable(INonStreamingBackendResponseHandler.handle)


class TestIStreamingBackendResponseHandler:
    """Tests for IStreamingBackendResponseHandler interface contract."""

    def test_interface_is_abstract(self) -> None:
        """Test that IStreamingBackendResponseHandler cannot be instantiated."""
        with pytest.raises(TypeError):
            IStreamingBackendResponseHandler()  # type: ignore[abstract]

    def test_interface_has_handle_method(self) -> None:
        """Test that IStreamingBackendResponseHandler defines handle method."""
        assert hasattr(IStreamingBackendResponseHandler, "handle")
        assert callable(IStreamingBackendResponseHandler.handle)


class TestIToolCallRetryCoordinator:
    """Tests for IToolCallRetryCoordinator interface contract."""

    def test_interface_is_abstract(self) -> None:
        """Test that IToolCallRetryCoordinator cannot be instantiated."""
        with pytest.raises(TypeError):
            IToolCallRetryCoordinator()  # type: ignore[abstract]

    def test_interface_has_handle_non_streaming_method(self) -> None:
        """Test that IToolCallRetryCoordinator defines handle_non_streaming method."""
        assert hasattr(IToolCallRetryCoordinator, "handle_non_streaming")
        assert callable(IToolCallRetryCoordinator.handle_non_streaming)

    def test_interface_has_handle_streaming_method(self) -> None:
        """Test that IToolCallRetryCoordinator defines handle_streaming method."""
        assert hasattr(IToolCallRetryCoordinator, "handle_streaming")
        assert callable(IToolCallRetryCoordinator.handle_streaming)


class TestIStructuredOutputEnforcer:
    """Tests for IStructuredOutputEnforcer interface contract."""

    def test_interface_is_abstract(self) -> None:
        """Test that IStructuredOutputEnforcer cannot be instantiated."""
        with pytest.raises(TypeError):
            IStructuredOutputEnforcer()  # type: ignore[abstract]

    def test_interface_has_enforce_method(self) -> None:
        """Test that IStructuredOutputEnforcer defines enforce method."""
        assert hasattr(IStructuredOutputEnforcer, "enforce")
        assert callable(IStructuredOutputEnforcer.enforce)


class TestILoopDetectorFactory:
    """Tests for ILoopDetectorFactory interface contract."""

    def test_interface_is_abstract(self) -> None:
        """Test that ILoopDetectorFactory cannot be instantiated."""
        with pytest.raises(TypeError):
            ILoopDetectorFactory()  # type: ignore[abstract]

    def test_interface_has_create_method(self) -> None:
        """Test that ILoopDetectorFactory defines create method."""
        assert hasattr(ILoopDetectorFactory, "create")
        assert callable(ILoopDetectorFactory.create)


class TestIQualityVerifierStreamVerifier:
    """Tests for IQualityVerifierStreamVerifier interface contract."""

    def test_interface_is_abstract(self) -> None:
        """Test that IQualityVerifierStreamVerifier cannot be instantiated."""
        with pytest.raises(TypeError):
            IQualityVerifierStreamVerifier()  # type: ignore[abstract]

    def test_interface_has_verify_or_passthrough_method(self) -> None:
        """Test that IQualityVerifierStreamVerifier defines verify_or_passthrough method."""
        assert hasattr(IQualityVerifierStreamVerifier, "verify_or_passthrough")
        assert callable(IQualityVerifierStreamVerifier.verify_or_passthrough)
