"""Tests for AuxiliaryRoutingApplicator."""

import argparse
import os
from unittest.mock import patch

import pytest
from src.core.cli_support.applicators.auxiliary_routing_applicator import (
    AuxiliaryRoutingApplicator,
    _has_openrouter_api_key,
)
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.models.access_mode import AccessMode
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestAuxiliaryRoutingApplicator:
    """Tests for AuxiliaryRoutingApplicator."""

    @pytest.fixture
    def applicator(self):
        """Create an AuxiliaryRoutingApplicator instance."""
        return AuxiliaryRoutingApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            auxiliary_routing_enabled=None,
            auxiliary_routing_backend=None,
            auxiliary_routing_model=None,
            auxiliary_routing_max_messages=None,
            disable_default_openrouter_auxiliary_routing=None,
            disable_auxiliary_routing=None,
            auxiliary_routing_disabled_from_base_config=False,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_applies_enabled_flag(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --enable-auxiliary-routing is applied."""
        empty_args.auxiliary_routing_enabled = True
        with patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        assert resolution.is_set("auxiliary_routing.enabled")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.enabled" in cli_params

    def test_applies_backend(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --auxiliary-routing-backend is applied."""
        empty_args.auxiliary_routing_backend = "openrouter"
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["backend"] == "openrouter"
        assert resolution.is_set("auxiliary_routing.backend")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.backend" in cli_params

    def test_applies_model(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --auxiliary-routing-model is applied."""
        empty_args.auxiliary_routing_model = "google/gemini-flash-1.5"
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["model"] == "google/gemini-flash-1.5"
        assert resolution.is_set("auxiliary_routing.model")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.model" in cli_params

    def test_applies_max_messages(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --auxiliary-routing-max-messages is applied."""
        empty_args.auxiliary_routing_max_messages = 5
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["max_message_count"] == 5
        assert resolution.is_set("auxiliary_routing.max_message_count")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.max_message_count" in cli_params

    def test_applies_all_arguments(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that all arguments are applied together."""
        empty_args.auxiliary_routing_enabled = True
        empty_args.auxiliary_routing_backend = "openrouter"
        empty_args.auxiliary_routing_model = "google/gemini-flash-1.5"
        empty_args.auxiliary_routing_max_messages = 5

        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        assert overrides["auxiliary_routing"]["backend"] == "openrouter"
        assert overrides["auxiliary_routing"]["model"] == "google/gemini-flash-1.5"
        assert overrides["auxiliary_routing"]["max_message_count"] == 5

    def test_model_only_selector_with_colon_suffix_is_not_split(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Model-only selectors like vendor/model:free remain model-only."""
        empty_args.auxiliary_routing_model = "openrouter/anthropic/claude-3-haiku:free"
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert "backend" not in overrides["auxiliary_routing"]
        assert (
            overrides["auxiliary_routing"]["model"]
            == "openrouter/anthropic/claude-3-haiku:free"
        )

    def test_no_overrides_when_no_args(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no CLI-originated overrides are created when no arguments are provided."""

        with patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

        assert len(resolution.latest_by_source(ParameterSource.CLI)) == 0

    def test_applies_disable_default_openrouter_flag(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --disable-default-open-router-auxiliary-routing is applied."""
        empty_args.disable_default_openrouter_auxiliary_routing = True
        applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["disable_default_openrouter"] is True
        assert resolution.is_set("auxiliary_routing.disable_default_openrouter")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "auxiliary_routing.disable_default_openrouter" in cli_params


class TestOpenRouterAutoDetection:
    """Tests for OpenRouter API key auto-detection."""

    @pytest.fixture
    def applicator(self):
        """Create an AuxiliaryRoutingApplicator instance."""
        return AuxiliaryRoutingApplicator()

    @pytest.fixture
    def enabled_args(self) -> CliArgs:
        """Create CLI arguments with auxiliary routing enabled."""
        return argparse.Namespace(
            auxiliary_routing_enabled=True,
            auxiliary_routing_backend=None,
            auxiliary_routing_model=None,
            auxiliary_routing_max_messages=None,
            disable_default_openrouter_auxiliary_routing=None,
            disable_auxiliary_routing=None,
            auxiliary_routing_disabled_from_base_config=False,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_has_openrouter_api_key_with_base_key(self):
        """Test _has_openrouter_api_key returns True when OPENROUTER_API_KEY is set."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            assert _has_openrouter_api_key() is True

    def test_has_openrouter_api_key_with_numbered_key(self):
        """Test _has_openrouter_api_key returns True for OPENROUTER_API_KEY_1."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY_1": "test-key"}):
            assert _has_openrouter_api_key() is True

    def test_has_openrouter_api_key_with_multiple_numbered_keys(self):
        """Test _has_openrouter_api_key returns True for any numbered variant."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY_5": "test-key"}):
            assert _has_openrouter_api_key() is True

    def test_has_openrouter_api_key_returns_false_when_not_set(self):
        """Test _has_openrouter_api_key returns False when no key is set."""
        with patch.dict(os.environ, {}, clear=True):
            assert _has_openrouter_api_key() is False

    def test_has_openrouter_api_key_ignores_invalid_patterns(self):
        """Test _has_openrouter_api_key ignores similar but invalid env var names."""
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY_EXTRA": "test-key",
                "MY_OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_API_KEY": "",
            },
        ):
            assert _has_openrouter_api_key() is False

    def test_auto_applies_default_openrouter_model_when_key_present(
        self,
        applicator,
        enabled_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that default OpenRouter model is applied when API key is present."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(enabled_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["backend"] == "openrouter"
        assert overrides["auxiliary_routing"]["model"] == "openrouter/free"
        assert resolution.is_set("auxiliary_routing.backend")
        assert resolution.is_set("auxiliary_routing.model")

    def test_auto_applies_default_openrouter_model_with_numbered_key(
        self,
        applicator,
        enabled_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that default OpenRouter model is applied when numbered key is present."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY_1": "test-key"}):
            applicator.apply(enabled_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["backend"] == "openrouter"
        assert overrides["auxiliary_routing"]["model"] == "openrouter/free"

    def test_no_auto_apply_when_openrouter_key_missing(
        self,
        applicator,
        enabled_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that default model is NOT applied when no OpenRouter key is present."""
        with patch.dict(os.environ, {}, clear=True):
            applicator.apply(enabled_args, overrides, resolution)

        # Should only have enabled flag, not backend/model
        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        assert "backend" not in overrides["auxiliary_routing"]
        assert "model" not in overrides["auxiliary_routing"]

    def test_no_auto_apply_when_disable_flag_set(
        self,
        applicator,
        enabled_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that default model is NOT applied when disable flag is set."""
        enabled_args.disable_default_openrouter_auxiliary_routing = True

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(enabled_args, overrides, resolution)

        # Should have enabled and disable flag, but not backend/model
        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        assert overrides["auxiliary_routing"]["disable_default_openrouter"] is True
        assert "backend" not in overrides["auxiliary_routing"]
        assert "model" not in overrides["auxiliary_routing"]

    def test_no_auto_apply_when_model_explicitly_set(
        self,
        applicator,
        enabled_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that default model is NOT applied when model is explicitly configured."""
        enabled_args.auxiliary_routing_model = "gemini-flash"

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(enabled_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["model"] == "gemini-flash"
        # Backend should not be auto-set since model was explicitly provided
        assert "backend" not in overrides["auxiliary_routing"]

    def test_no_auto_apply_when_backend_explicitly_set(
        self,
        applicator,
        enabled_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that default model is NOT applied when backend is explicitly configured."""
        enabled_args.auxiliary_routing_backend = "gemini-oauth"

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(enabled_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["backend"] == "gemini-oauth"
        assert "model" not in overrides["auxiliary_routing"]

    def test_no_auto_apply_when_routing_not_enabled(
        self,
        applicator,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no explicit enable fires when routing args are all None (auto-enable may still fire)."""
        disabled_args = argparse.Namespace(
            auxiliary_routing_enabled=None,
            auxiliary_routing_backend=None,
            auxiliary_routing_model=None,
            auxiliary_routing_max_messages=None,
            disable_default_openrouter_auxiliary_routing=None,
            disable_auxiliary_routing=None,
            auxiliary_routing_disabled_from_base_config=False,
        )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(disabled_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        aux = overrides["auxiliary_routing"]
        assert aux["enabled"] is True
        assert aux["backend"] == "openrouter"
        assert aux["model"] == "openrouter/free"

    @staticmethod
    def _make_disabled_args() -> argparse.Namespace:
        """Helper to create a namespace with all disable flags set."""
        return argparse.Namespace(
            auxiliary_routing_enabled=None,
            auxiliary_routing_backend=None,
            auxiliary_routing_model=None,
            auxiliary_routing_max_messages=None,
            disable_default_openrouter_auxiliary_routing=None,
            disable_auxiliary_routing=True,
            auxiliary_routing_disabled_from_base_config=False,
        )

    def test_no_overrides_when_all_disabled(
        self,
        applicator,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        disabled_args = self._make_disabled_args()
        applicator.apply(disabled_args, overrides, resolution)
        assert "auxiliary_routing" not in overrides


class TestAuxiliaryRoutingAutoEnable:
    """Tests for auto-enable of auxiliary routing in single user mode."""

    @pytest.fixture
    def applicator(self):
        """Create an AuxiliaryRoutingApplicator instance."""
        return AuxiliaryRoutingApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            auxiliary_routing_enabled=None,
            auxiliary_routing_backend=None,
            auxiliary_routing_model=None,
            auxiliary_routing_max_messages=None,
            disable_default_openrouter_auxiliary_routing=None,
            disable_auxiliary_routing=None,
            auxiliary_routing_disabled_from_base_config=False,
        )

    @pytest.fixture
    def enabled_args(self) -> CliArgs:
        """Create CLI arguments with auxiliary routing enabled."""
        return argparse.Namespace(
            auxiliary_routing_enabled=True,
            auxiliary_routing_backend=None,
            auxiliary_routing_model=None,
            auxiliary_routing_max_messages=None,
            disable_default_openrouter_auxiliary_routing=None,
            disable_auxiliary_routing=None,
            auxiliary_routing_disabled_from_base_config=False,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_auto_enables_when_openrouter_key_set_and_single_user_mode(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Auto-enable auxiliary routing when OPENROUTER_API_KEY is set and single user mode."""
        overrides["access_mode"] = {"mode": AccessMode.SINGLE_USER}

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        assert overrides["auxiliary_routing"]["backend"] == "openrouter"
        assert overrides["auxiliary_routing"]["model"] == "openrouter/free"

    def test_auto_enable_not_triggered_when_disable_flag_set(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Auto-enable is skipped when disable_auxiliary_routing flag is set."""
        empty_args.disable_auxiliary_routing = True
        overrides["access_mode"] = {"mode": AccessMode.SINGLE_USER}

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(empty_args, overrides, resolution)

        assert len(overrides) == 1
        assert "access_mode" in overrides
        assert "auxiliary_routing" not in overrides

    def test_auto_enable_not_triggered_when_disabled_in_base_config(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Auto-enable is skipped when auxiliary routing is disabled in base config."""
        empty_args.auxiliary_routing_disabled_from_base_config = True
        overrides["access_mode"] = {"mode": AccessMode.SINGLE_USER}

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(empty_args, overrides, resolution)

        assert len(overrides) == 1
        assert "access_mode" in overrides
        assert "auxiliary_routing" not in overrides

    def test_auto_enable_not_triggered_when_multi_user_mode(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Auto-enable is skipped when access mode is multi user."""
        overrides["access_mode"] = {"mode": AccessMode.MULTI_USER}

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(empty_args, overrides, resolution)

        assert len(overrides) == 1
        assert "access_mode" in overrides
        assert "auxiliary_routing" not in overrides

    def test_auto_enable_not_triggered_when_explicit_enable_already_set(
        self,
        applicator,
        enabled_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Auto-enable respects already enabled auxiliary routing without double-setting."""
        overrides["access_mode"] = {"mode": AccessMode.SINGLE_USER}

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(enabled_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        assert overrides["auxiliary_routing"]["backend"] == "openrouter"
        assert overrides["auxiliary_routing"]["model"] == "openrouter/free"

    def test_auto_enable_not_triggered_when_openrouter_key_missing(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Auto-enable is skipped when OPENROUTER_API_KEY is not set."""
        overrides["access_mode"] = {"mode": AccessMode.SINGLE_USER}

        with patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

        assert len(overrides) == 1
        assert "access_mode" in overrides
        assert "auxiliary_routing" not in overrides

    def test_auto_enable_respects_explicit_model_when_also_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Auto-enable sets enabled=True but respects explicitly provided model."""
        empty_args.auxiliary_routing_model = "gemini:gemini-1.5-flash"
        overrides["access_mode"] = {"mode": AccessMode.SINGLE_USER}

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            applicator.apply(empty_args, overrides, resolution)

        assert "auxiliary_routing" in overrides
        assert overrides["auxiliary_routing"]["enabled"] is True
        # Model is parsed by has_explicit_backend_selector: "gemini:gemini-1.5-flash"
        # becomes backend="gemini", model="gemini-1.5-flash"
        assert overrides["auxiliary_routing"]["backend"] == "gemini"
        assert overrides["auxiliary_routing"]["model"] == "gemini-1.5-flash"
