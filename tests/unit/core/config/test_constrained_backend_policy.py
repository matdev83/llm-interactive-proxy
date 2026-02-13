"""Tests for constrained connector-family policy reuse."""

from __future__ import annotations

import pytest
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig, BackendSettings
from src.core.config.constrained_backend_policy import (
    group_constrained_backend_instances,
    is_constrained_connector_family,
    match_constrained_connector_family,
)
from src.core.config.semantic_validation import (
    validate_config_semantics,
    validate_constrained_backend_instances,
)


def test_policy_matches_explicit_and_wildcard_families() -> None:
    assert match_constrained_connector_family("qwen-oauth.1") == "qwen-oauth"
    assert (
        match_constrained_connector_family("gemini_oauth_plan.primary")
        == "gemini-oauth-plan"
    )
    assert (
        match_constrained_connector_family("antigravity-oauth.account-a")
        == "antigravity-oauth"
    )
    assert match_constrained_connector_family("openai.1") is None


def test_is_constrained_connector_family_uses_same_matcher() -> None:
    assert is_constrained_connector_family("qwen_oauth")
    assert is_constrained_connector_family("gemini-oauth-free")
    assert is_constrained_connector_family("antigravity-oauth")
    assert not is_constrained_connector_family("openai")


def test_grouping_uses_concrete_backend_family_keys() -> None:
    grouped = group_constrained_backend_instances(
        [
            "gemini-oauth-plan.primary",
            "gemini-oauth-free.secondary",
            "antigravity-oauth.alpha",
        ]
    )

    assert grouped["gemini-oauth-plan"] == ["gemini-oauth-plan.primary"]
    assert grouped["gemini-oauth-free"] == ["gemini-oauth-free.secondary"]
    assert grouped["antigravity-oauth"] == ["antigravity-oauth.alpha"]


def test_semantic_validation_rejects_multiple_constrained_instances(
    tmp_path,
) -> None:
    config_data = {
        "backends": {
            "default_backend": "openai",
            "qwen-oauth.1": {"connector": "qwen-oauth"},
            "qwen-oauth.2": {"connector": "qwen-oauth"},
        }
    }

    with pytest.raises(ConfigurationError) as exc_info:
        validate_config_semantics(config_data, tmp_path / "config.yaml")

    details = exc_info.value.details
    assert isinstance(details, dict)
    assert any(
        "qwen-oauth" in error and "single-instance" in error
        for error in details.get("errors", [])
    )


def test_semantic_validation_allows_cross_connector_wildcard_variants(
    tmp_path,
) -> None:
    config_data = {
        "backends": {
            "default_backend": "openai",
            "gemini-oauth-plan.primary": {"connector": "gemini-oauth-plan"},
            "gemini-oauth-free.secondary": {"connector": "gemini-oauth-free"},
        }
    }

    validate_config_semantics(config_data, tmp_path / "config.yaml")


def test_semantic_validation_rejects_family_key_plus_instance(
    tmp_path,
) -> None:
    """When both family key (no dot) and instance (with dot) exist, reject."""
    config_data = {
        "backends": {
            "default_backend": "openai",
            "qwen-oauth": {"connector": "qwen-oauth"},
            "qwen-oauth.1": {"connector": "qwen-oauth"},
        }
    }

    with pytest.raises(ConfigurationError) as exc_info:
        validate_config_semantics(config_data, tmp_path / "config.yaml")

    details = exc_info.value.details
    assert isinstance(details, dict)
    assert any(
        "qwen-oauth" in error and "single-instance" in error
        for error in details.get("errors", [])
    )


def test_runtime_validation_rejects_multiple_constrained_instances() -> None:
    backends = BackendSettings(
        default_backend="openai",
        **{
            "qwen-oauth.1": {"connector": "qwen-oauth"},
            "qwen-oauth.2": {"connector": "qwen-oauth"},
        },
    )
    config = AppConfig(backends=backends)

    with pytest.raises(ConfigurationError) as exc_info:
        validate_constrained_backend_instances(config)

    details = exc_info.value.details
    assert isinstance(details, dict)
    assert details.get("error_code") == "constrained_family_single_instance_violation"
    assert "migration_guidance" in details
    assert "qwen-oauth.1" in str(details)
    assert "qwen-oauth.2" in str(details)


def test_runtime_validation_allows_cross_connector_wildcard_variants() -> None:
    backends = BackendSettings(
        default_backend="openai",
        **{
            "gemini-oauth-plan.primary": {"connector": "gemini-oauth-plan"},
            "gemini-oauth-free.secondary": {"connector": "gemini-oauth-free"},
        },
    )
    config = AppConfig(backends=backends)

    validate_constrained_backend_instances(config)
