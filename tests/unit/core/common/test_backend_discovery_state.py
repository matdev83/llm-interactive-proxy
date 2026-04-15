"""Tests for backend discovery shared state helpers."""

from importlib import metadata
from typing import Any, cast

import pytest
from src.core.common.backend_discovery_state import (
    clear_plugin_post_build_hooks,
    filter_oauth_style_backend_names,
    get_extracted_backend_names,
    get_extracted_connector_module_names,
    get_oauth_install_command,
    get_plugin_post_build_hooks,
    is_extracted_backend_name,
    normalize_backend_name,
    register_plugin_post_build_hook,
)


def test_is_extracted_backend_name_handles_instances_and_underscore_aliases() -> None:
    assert is_extracted_backend_name("gemini-oauth-plan")
    assert is_extracted_backend_name("gemini_oauth_plan")
    assert is_extracted_backend_name("gemini-oauth-plan.primary")
    assert not is_extracted_backend_name("openai")


def test_get_extracted_connector_module_names_are_underscore_form() -> None:
    module_names = get_extracted_connector_module_names()
    assert module_names == sorted(module_names)
    assert all("-" not in name for name in module_names)


def test_filter_oauth_style_backend_names_uses_pattern_only_no_hardcoding() -> None:
    """OAuth list derived from input; any *-oauth or *-oauth-* name included."""
    result = filter_oauth_style_backend_names(
        ["openai", "qwen-oauth", "custom_oauth_bar", "gemini-oauth-auto", "x"]
    )
    assert result == ["custom_oauth_bar", "gemini-oauth-auto", "qwen-oauth"]


def test_normalize_backend_name_normalizes_instance_and_case() -> None:
    assert normalize_backend_name("Gemini_OAuth_Plan.PRIMARY") == "gemini-oauth-plan"


def test_normalize_backend_name_strips_model_suffix_after_colon() -> None:
    assert normalize_backend_name("zai-coding-plan:glm-5.1") == "zai-coding-plan"


def test_oauth_install_command_is_stable() -> None:
    assert get_oauth_install_command() == "pip install llm-interactive-proxy[oauth]"


def test_extracted_backend_catalog_matches_plugin_entry_points() -> None:
    """Catalog in core should stay aligned with optional plugin entry points."""
    try:
        entry_points = metadata.entry_points(group="llm_proxy_backends")
    except TypeError:
        discovered = metadata.entry_points()
        if hasattr(discovered, "select"):
            entry_points = discovered.select(group="llm_proxy_backends")
        else:
            legacy_discovered = cast(dict[str, Any], discovered)
            entry_points = legacy_discovered.get("llm_proxy_backends", ())

    discovered_entry_points = {
        ep.name
        for ep in entry_points
        if getattr(getattr(ep, "dist", None), "name", None)
        == "llm-interactive-proxy-oauth-connectors"
    }
    if not discovered_entry_points:
        pytest.skip("OAuth plugin package entry points not installed")

    assert discovered_entry_points == set(get_extracted_backend_names())


def test_plugin_post_build_hooks_are_sorted_and_resettable() -> None:
    clear_plugin_post_build_hooks()

    def hook_a(_provider: object) -> None:
        return None

    def hook_z(_provider: object) -> None:
        return None

    register_plugin_post_build_hook("z-backend", hook_z)
    register_plugin_post_build_hook("a-backend", hook_a)

    hooks = get_plugin_post_build_hooks()
    assert [name for name, _ in hooks] == ["a-backend", "z-backend"]

    clear_plugin_post_build_hooks()
    assert get_plugin_post_build_hooks() == []
