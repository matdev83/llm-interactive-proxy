"""Tests for AccessMode enum and AccessModeConfig model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.interfaces.model_bases import DomainModel


class TestAccessModeEnum:
    """Tests for AccessMode enum values."""

    def test_single_user_value(self) -> None:
        """Test that SINGLE_USER has correct string value."""
        assert AccessMode.SINGLE_USER == "single_user"
        assert AccessMode.SINGLE_USER.value == "single_user"

    def test_multi_user_value(self) -> None:
        """Test that MULTI_USER has correct string value."""
        assert AccessMode.MULTI_USER == "multi_user"
        assert AccessMode.MULTI_USER.value == "multi_user"

    def test_enum_string_representation(self) -> None:
        """Test enum string representation."""
        assert AccessMode.SINGLE_USER.value == "single_user"
        assert AccessMode.MULTI_USER.value == "multi_user"


class TestAccessModeConfigDefaults:
    """Tests for AccessModeConfig default values."""

    def test_default_mode_is_single_user(self) -> None:
        """Test that default mode is SINGLE_USER."""
        config = AccessModeConfig()

        assert config.mode == AccessMode.SINGLE_USER

    def test_can_instantiate_without_arguments(self) -> None:
        """Test that config can be instantiated without arguments."""
        config = AccessModeConfig()

        assert config is not None
        assert config.mode == AccessMode.SINGLE_USER


class TestAccessModeConfigHelperMethods:
    """Tests for AccessModeConfig helper methods."""

    def test_is_single_user_returns_true_for_single_user_mode(self) -> None:
        """Test that is_single_user() returns True when mode is SINGLE_USER."""
        config = AccessModeConfig(mode=AccessMode.SINGLE_USER)

        assert config.is_single_user() is True

    def test_is_single_user_returns_false_for_multi_user_mode(self) -> None:
        """Test that is_single_user() returns False when mode is MULTI_USER."""
        config = AccessModeConfig(mode=AccessMode.MULTI_USER)

        assert config.is_single_user() is False

    def test_is_multi_user_returns_true_for_multi_user_mode(self) -> None:
        """Test that is_multi_user() returns True when mode is MULTI_USER."""
        config = AccessModeConfig(mode=AccessMode.MULTI_USER)

        assert config.is_multi_user() is True

    def test_is_multi_user_returns_false_for_single_user_mode(self) -> None:
        """Test that is_multi_user() returns False when mode is SINGLE_USER."""
        config = AccessModeConfig(mode=AccessMode.SINGLE_USER)

        assert config.is_multi_user() is False


class TestAccessModeConfigImmutability:
    """Tests for AccessModeConfig immutability."""

    def test_config_is_frozen(self) -> None:
        """Test that config is frozen (immutable)."""
        config = AccessModeConfig()

        # Pydantic frozen models raise ValidationError when trying to set attributes
        with pytest.raises(ValidationError):
            config.mode = AccessMode.MULTI_USER  # type: ignore[misc]


class TestAccessModeConfigCustomValues:
    """Tests for AccessModeConfig with custom values."""

    def test_can_create_with_explicit_single_user_mode(self) -> None:
        """Test that config can be created with explicit SINGLE_USER mode."""
        config = AccessModeConfig(mode=AccessMode.SINGLE_USER)

        assert config.mode == AccessMode.SINGLE_USER
        assert config.is_single_user() is True
        assert config.is_multi_user() is False

    def test_can_create_with_explicit_multi_user_mode(self) -> None:
        """Test that config can be created with explicit MULTI_USER mode."""
        config = AccessModeConfig(mode=AccessMode.MULTI_USER)

        assert config.mode == AccessMode.MULTI_USER
        assert config.is_single_user() is False
        assert config.is_multi_user() is True


class TestAccessModeConfigInheritance:
    """Tests for AccessModeConfig DomainModel inheritance."""

    def test_config_extends_domain_model(self) -> None:
        """Test that AccessModeConfig extends DomainModel."""
        config = AccessModeConfig()

        assert isinstance(config, DomainModel)
