"""Unit tests for fail-open plugin backend discovery."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from src.connectors.base import LLMBackend
from src.core.common.backend_discovery_state import (
    get_plugin_metadata,
    get_plugin_post_build_hooks,
)
from src.core.plugin_api import BackendPluginDefinition, PluginCompatibility
from src.core.services.backend_plugin_discovery import discover_plugin_backends


def _entry_point(
    *,
    name: str,
    provider: Any | None = None,
    load_error: Exception | None = None,
) -> Any:
    """Create lightweight entry-point test double."""

    def _load() -> Any:
        if load_error is not None:
            raise load_error
        return provider

    return SimpleNamespace(
        name=name,
        load=_load,
        module="llm_proxy_oauth_connectors.providers",
        attr=name,
        dist=SimpleNamespace(name="llm-interactive-proxy-oauth-connectors"),
    )


def _unused_factory(*args: Any, **kwargs: Any) -> LLMBackend:
    """Factory used only for discovery metadata tests."""
    raise RuntimeError("Factory should not be called in discovery tests.")


class TestBackendPluginDiscovery:
    """Tests for plugin discovery behavior and compatibility gating."""

    def test_no_entry_points_is_valid_optional_absence(self) -> None:
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[],
            ),
        ):
            discovered = discover_plugin_backends()

        assert discovered == []

    def test_retired_entry_point_is_silently_skipped(self, caplog: Any) -> None:
        """Stale setuptools metadata must not trigger load or WARNING."""
        retired = _entry_point(
            name="anthropic-oauth",
            load_error=RuntimeError("load must not be called for retired entry points"),
        )
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[retired],
            ),
            caplog.at_level("WARNING"),
        ):
            discovered = discover_plugin_backends()

        assert discovered == []
        assert "Failed to load backend plugin entry point" not in caplog.text

    def test_entry_point_load_failure_is_fail_open(self, caplog: Any) -> None:
        broken = _entry_point(
            name="broken-oauth", load_error=ImportError("Cannot import plugin module")
        )
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[broken],
            ),
            caplog.at_level("WARNING"),
        ):
            discovered = discover_plugin_backends()

        assert discovered == []
        assert "Failed to load backend plugin entry point 'broken-oauth'" in caplog.text

    def test_identical_entry_point_load_errors_warn_once(self, caplog: Any) -> None:
        """Repeated ModuleNotFoundError for the same message should not spam WARNING."""
        err = ModuleNotFoundError("No module named 'llm_proxy_oauth_connectors'")
        ep_a = _entry_point(name="oauth-a", load_error=err)
        ep_b = _entry_point(name="oauth-b", load_error=err)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[ep_a, ep_b],
            ),
            caplog.at_level("WARNING"),
        ):
            discover_plugin_backends()

        load_warnings = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "Failed to load backend plugin entry point" in r.getMessage()
        ]
        assert len(load_warnings) == 1
        assert "oauth-a" in load_warnings[0]
        assert "oauth-b" not in load_warnings[0]

    def test_strict_metadata_contract_skips_invalid_provider_result(
        self, caplog: Any
    ) -> None:
        invalid = _entry_point(name="invalid-oauth", provider=lambda: {"bad": "shape"})
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[invalid],
            ),
            caplog.at_level("WARNING"),
        ):
            discovered = discover_plugin_backends()

        assert discovered == []
        assert "strict metadata contract" in caplog.text

    def test_incompatible_plugin_is_skipped_with_warning(self, caplog: Any) -> None:
        provider = lambda: BackendPluginDefinition(
            backend_name="future-oauth",
            factory=_unused_factory,
            plugin_name="oauth-plugin",
            compatibility=PluginCompatibility(core_min_version="9.9.9"),
        )
        incompatible = _entry_point(name="future-oauth", provider=provider)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[incompatible],
            ),
            caplog.at_level("WARNING"),
        ):
            discovered = discover_plugin_backends()

        assert discovered == []
        assert "requires core>=9.9.9" in caplog.text

    def test_successful_plugin_registration_uses_deterministic_name_and_metadata(
        self,
    ) -> None:
        provider = lambda: BackendPluginDefinition(
            backend_name="non-deterministic-alias",
            factory=_unused_factory,
            plugin_name="oauth-plugin",
            compatibility=PluginCompatibility(core_min_version="0.1.0"),
        )
        entry_point = _entry_point(name="deterministic-oauth", provider=provider)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[entry_point],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.backend_registry.register_backend"
            ) as register_backend,
        ):
            discovered = discover_plugin_backends()

        assert discovered == ["deterministic-oauth"]
        register_backend.assert_called_once()
        call_args = register_backend.call_args
        assert call_args is not None
        assert call_args.args[0] == "deterministic-oauth"
        assert callable(call_args.args[1])

        metadata = get_plugin_metadata("deterministic-oauth")
        assert metadata is not None
        assert metadata.plugin_name == "oauth-plugin"
        assert metadata.core_min_version == "0.1.0"

    def test_successful_plugin_registration_records_post_build_hook(self) -> None:
        hook_calls: list[str] = []

        def plugin_hook(_provider: Any) -> None:
            hook_calls.append("called")

        provider = lambda: BackendPluginDefinition(
            backend_name="hooked-oauth",
            factory=_unused_factory,
            plugin_name="oauth-plugin",
            compatibility=PluginCompatibility(core_min_version="0.1.0"),
            post_build_hook=plugin_hook,
        )
        entry_point = _entry_point(name="hooked-oauth", provider=provider)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[entry_point],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.backend_registry.register_backend"
            ),
        ):
            discovered = discover_plugin_backends()

        assert discovered == ["hooked-oauth"]
        hooks = get_plugin_post_build_hooks()
        assert len(hooks) == 1
        assert hooks[0][0] == "hooked-oauth"
        hooks[0][1](object())
        assert hook_calls == ["called"]

    def test_incompatible_plugin_does_not_register_post_build_hook(self) -> None:
        provider = lambda: BackendPluginDefinition(
            backend_name="future-oauth",
            factory=_unused_factory,
            plugin_name="oauth-plugin",
            compatibility=PluginCompatibility(core_min_version="9.9.9"),
            post_build_hook=lambda _provider: None,
        )
        incompatible = _entry_point(name="future-oauth", provider=provider)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[incompatible],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.backend_registry.register_backend"
            ),
        ):
            discovered = discover_plugin_backends()

        assert discovered == []
        assert get_plugin_post_build_hooks() == []

    def test_non_callable_post_build_hook_is_rejected(self, caplog: Any) -> None:
        provider = lambda: BackendPluginDefinition(
            backend_name="bad-hook-oauth",
            factory=_unused_factory,
            plugin_name="oauth-plugin",
            compatibility=PluginCompatibility(core_min_version="0.1.0"),
            post_build_hook=cast(Any, "not-callable"),
        )
        entry_point = _entry_point(name="bad-hook-oauth", provider=provider)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[entry_point],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.backend_registry.register_backend"
            ),
            caplog.at_level("WARNING"),
        ):
            discovered = discover_plugin_backends()

        assert discovered == []
        assert "post_build_hook must be callable" in caplog.text

    def test_broken_plugin_does_not_block_valid_plugin_registration(
        self, caplog: Any
    ) -> None:
        broken = _entry_point(
            name="broken-oauth", load_error=ImportError("Cannot import plugin module")
        )
        hook_calls: list[str] = []

        def plugin_hook(_provider: Any) -> None:
            hook_calls.append("called")

        provider = lambda: BackendPluginDefinition(
            backend_name="healthy-oauth",
            factory=_unused_factory,
            plugin_name="oauth-plugin",
            compatibility=PluginCompatibility(core_min_version="0.1.0"),
            post_build_hook=plugin_hook,
        )
        healthy = _entry_point(name="healthy-oauth", provider=provider)

        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[broken, healthy],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.backend_registry.register_backend"
            ) as register_backend,
            caplog.at_level("WARNING"),
        ):
            discovered = discover_plugin_backends()

        assert discovered == ["healthy-oauth"]
        assert "Failed to load backend plugin entry point 'broken-oauth'" in caplog.text
        register_backend.assert_called_once()
        call_args = register_backend.call_args
        assert call_args is not None
        assert call_args.args[0] == "healthy-oauth"

        metadata = get_plugin_metadata("healthy-oauth")
        assert metadata is not None
        assert metadata.plugin_name == "oauth-plugin"

        hooks = get_plugin_post_build_hooks()
        assert len(hooks) == 1
        assert hooks[0][0] == "healthy-oauth"
        hooks[0][1](object())
        assert hook_calls == ["called"]

    def test_multi_user_mode_skips_extracted_plugin_and_merges_skip_diagnostics(
        self, caplog: Any
    ) -> None:
        provider = lambda: BackendPluginDefinition(
            backend_name="gemini-oauth-plan",
            factory=_unused_factory,
            plugin_name="oauth-plugin",
            compatibility=PluginCompatibility(core_min_version="0.1.0"),
        )
        entry_point = _entry_point(name="gemini-oauth-plan", provider=provider)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[entry_point],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.is_running_in_multi_user_mode",
                return_value=True,
            ),
            patch(
                "src.core.services.backend_plugin_discovery.get_skipped_oauth_connectors",
                return_value=["openai_codex"],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.replace_skipped_oauth_connectors"
            ) as replace_skipped_connectors,
            patch(
                "src.core.services.backend_plugin_discovery.backend_registry.register_backend"
            ) as register_backend,
            caplog.at_level("WARNING"),
        ):
            discovered = discover_plugin_backends()

        assert discovered == []
        register_backend.assert_not_called()
        replace_skipped_connectors.assert_called_once()
        call_args = replace_skipped_connectors.call_args
        assert call_args is not None
        assert call_args.args[0] == ["gemini-oauth-plan", "openai_codex"]
        assert "Skipping plugin backend 'gemini-oauth-plan'" in caplog.text

    def test_multi_user_mode_keeps_non_extracted_plugins_available(self) -> None:
        provider = lambda: BackendPluginDefinition(
            backend_name="safe-backend",
            factory=_unused_factory,
            plugin_name="safe-plugin",
            compatibility=PluginCompatibility(core_min_version="0.1.0"),
        )
        entry_point = _entry_point(name="safe-backend", provider=provider)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[entry_point],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.is_running_in_multi_user_mode",
                return_value=True,
            ),
            patch(
                "src.core.services.backend_plugin_discovery.is_extracted_backend_name",
                return_value=False,
            ),
            patch(
                "src.core.services.backend_plugin_discovery.replace_skipped_oauth_connectors"
            ) as replace_skipped_connectors,
            patch(
                "src.core.services.backend_plugin_discovery.backend_registry.register_backend"
            ) as register_backend,
        ):
            discovered = discover_plugin_backends()

        assert discovered == ["safe-backend"]
        register_backend.assert_called_once()
        replace_skipped_connectors.assert_not_called()

    def test_duplicate_entry_points_for_same_backend_register_once(self) -> None:
        """Overlapping entry point declarations must not double-register or duplicate metadata."""
        provider = lambda: BackendPluginDefinition(
            backend_name="dup-oauth",
            factory=_unused_factory,
            plugin_name="oauth-plugin",
            compatibility=PluginCompatibility(core_min_version="0.1.0"),
        )
        ep_a = _entry_point(name="dup-oauth", provider=provider)
        ep_b = _entry_point(name="dup-oauth", provider=provider)
        with (
            patch(
                "src.core.services.backend_plugin_discovery._resolve_core_version",
                return_value="0.1.0",
            ),
            patch(
                "src.core.services.backend_plugin_discovery._load_entry_points",
                return_value=[ep_a, ep_b],
            ),
            patch(
                "src.core.services.backend_plugin_discovery.backend_registry.register_backend",
                return_value=True,
            ) as register_backend,
        ):
            discovered = discover_plugin_backends()

        assert discovered == ["dup-oauth"]
        register_backend.assert_called_once()
