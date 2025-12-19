"""Unit tests for IdentityResolver service.

Tests cover identity resolution preference order and None handling.

Requirements satisfied:
- Req 9: Phase Executor Extraction (IdentityResolver is part of infrastructure)
- Req 11: Test-preserving migration
"""

from unittest.mock import MagicMock

import pytest
from src.core.domain.configuration.app_identity_config import AppIdentityConfig


class TestIdentityResolver:
    """Test IdentityResolver service implementation."""

    @pytest.fixture
    def config(self):
        """Create a mock AppConfig for testing."""
        config = MagicMock()
        config.backends = MagicMock()
        config.identity = None
        return config

    @pytest.fixture
    def resolver(self, config):
        """Create an IdentityResolver instance for testing."""
        from src.connectors.hybrid_backend.infrastructure.identity_resolver import (
            IdentityResolver,
        )

        return IdentityResolver(config=config)

    @pytest.fixture
    def identity1(self):
        """Create a test identity."""
        return AppIdentityConfig(project="project1")

    @pytest.fixture
    def identity2(self):
        """Create another test identity."""
        return AppIdentityConfig(project="project2")

    @pytest.fixture
    def identity3(self):
        """Create a third test identity."""
        return AppIdentityConfig(project="project3")

    def test_backend_config_identity_takes_precedence(
        self, resolver, config, identity1, identity2
    ):
        """Test that backend_config.identity takes highest precedence."""
        backend_config = MagicMock()
        backend_config.identity = identity1
        config.backends.openai = MagicMock()
        config.backends.openai.identity = identity2
        request_identity = identity2
        config.identity = identity2

        result = resolver.resolve(
            backend="openai",
            request_identity=request_identity,
            backend_config=backend_config,
        )

        assert result == identity1

    def test_backend_settings_identity_second_precedence(
        self, resolver, config, identity1, identity2
    ):
        """Test that backend settings identity is second preference."""
        backend_settings = MagicMock()
        backend_settings.identity = identity1
        config.backends.openai = backend_settings
        request_identity = identity2
        config.identity = identity2

        result = resolver.resolve(
            backend="openai",
            request_identity=request_identity,
            backend_config=None,
        )

        assert result == identity1

    def test_request_identity_third_precedence(self, resolver, config, identity1):
        """Test that request identity is third preference."""
        config.backends.openai = MagicMock()
        config.backends.openai.identity = None
        request_identity = identity1
        config.identity = None

        result = resolver.resolve(
            backend="openai",
            request_identity=request_identity,
            backend_config=None,
        )

        assert result == identity1

    def test_global_identity_fallback(self, resolver, config, identity1):
        """Test that global config.identity is final fallback."""
        config.backends.openai = MagicMock()
        config.backends.openai.identity = None
        request_identity = None
        config.identity = identity1

        result = resolver.resolve(
            backend="openai",
            request_identity=request_identity,
            backend_config=None,
        )

        assert result == identity1

    def test_none_when_all_none(self, resolver, config):
        """Test that None is returned when all sources are None."""
        config.backends.openai = MagicMock()
        config.backends.openai.identity = None
        request_identity = None
        config.identity = None

        result = resolver.resolve(
            backend="openai",
            request_identity=request_identity,
            backend_config=None,
        )

        assert result is None

    def test_backend_config_without_identity(self, resolver, config, identity1):
        """Test that backend_config without identity falls through."""
        backend_config = MagicMock()
        backend_config.identity = None
        config.backends.openai = MagicMock()
        config.backends.openai.identity = identity1

        result = resolver.resolve(
            backend="openai",
            request_identity=None,
            backend_config=backend_config,
        )

        assert result == identity1

    def test_backend_not_in_settings(self, resolver, config, identity1):
        """Test handling when backend is not in config.backends."""
        # Simulate backend not existing
        config.backends = MagicMock()
        # Accessing non-existent attribute raises AttributeError
        type(config.backends).openai = property(
            lambda self: self._openai if hasattr(self, "_openai") else None
        )
        config.backends._openai = None
        request_identity = identity1
        config.identity = None

        result = resolver.resolve(
            backend="openai",
            request_identity=request_identity,
            backend_config=None,
        )

        assert result == identity1

    def test_backend_settings_without_identity_attribute(
        self, resolver, config, identity1
    ):
        """Test handling when backend settings exist but have no identity attribute."""
        backend_settings = MagicMock(spec=[])  # No identity attribute
        del backend_settings.identity  # Ensure it doesn't exist
        config.backends.openai = backend_settings
        request_identity = identity1
        config.identity = None

        result = resolver.resolve(
            backend="openai",
            request_identity=request_identity,
            backend_config=None,
        )

        assert result == identity1

    def test_preference_order_complete(
        self, resolver, config, identity1, identity2, identity3
    ):
        """Test complete preference order with all sources present."""
        backend_config = MagicMock()
        backend_config.identity = identity1
        backend_settings = MagicMock()
        backend_settings.identity = identity2
        config.backends.openai = backend_settings
        request_identity = identity3
        config.identity = None

        result = resolver.resolve(
            backend="openai",
            request_identity=request_identity,
            backend_config=backend_config,
        )

        # Should return backend_config identity (highest precedence)
        assert result == identity1
