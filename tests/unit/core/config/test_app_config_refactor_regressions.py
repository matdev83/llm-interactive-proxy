from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig, load_config
from src.core.config.env.util import get_env_value
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.services.backend_config_provider import BackendConfigProvider


def test_from_env_discovers_numbered_backend_instances() -> None:
    env = {
        "LLM_BACKEND": "openai",
        "OPENAI_API_KEY_1": "val-one",
    }

    with (
        patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["openai"],
        ),
        patch(
            "src.core.config.models.backends.backend_registry.get_registered_backends",
            return_value=["openai"],
        ),
    ):
        cfg = AppConfig.from_env(environ=env)

    instance = cfg.backends.get("openai.1")
    assert instance is not None
    assert instance.api_key == "val-one"


def test_resolution_tracks_numbered_backend_instance_origin() -> None:
    env = {
        "LLM_BACKEND": "openai",
        "OPENAI_API_KEY_1": "val-one",
    }
    resolution = ParameterResolution()

    with (
        patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["openai"],
        ),
        patch(
            "src.core.config.models.backends.backend_registry.get_registered_backends",
            return_value=["openai"],
        ),
    ):
        cfg = load_config(None, environ=env, resolution=resolution)

    report = {entry.name: entry for entry in resolution.build_report(cfg)}
    entry = report['backends["openai.1"].api_key']
    assert entry.source is ParameterSource.ENVIRONMENT
    assert entry.origin == "OPENAI_API_KEY_1"


def test_from_env_discovers_numbered_opencode_go_backend_instances() -> None:
    env = {
        "LLM_BACKEND": "opencode-go",
        "OPENCODE_GO_API_KEY_1": "val-one",
    }

    with (
        patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["opencode-go"],
        ),
        patch(
            "src.core.config.models.backends.backend_registry.get_registered_backends",
            return_value=["opencode-go"],
        ),
    ):
        cfg = AppConfig.from_env(environ=env)

    instance = cfg.backends.get("opencode-go.1")
    assert instance is not None
    assert instance.api_key == "val-one"


def test_opencode_go_numbered_instances_take_precedence_over_base_env_key() -> None:
    env = {
        "LLM_BACKEND": "opencode-go",
        "OPENCODE_GO_API_KEY": "base-key",
        "OPENCODE_GO_API_KEY_1": "numbered-key",
    }

    with (
        patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["opencode-go"],
        ),
        patch(
            "src.core.config.models.backends.backend_registry.get_registered_backends",
            return_value=["opencode-go"],
        ),
    ):
        cfg = AppConfig.from_env(environ=env)

    base_cfg = cfg.backends.lookup("opencode-go")
    instance_cfg = cfg.backends.lookup("opencode-go.1")

    assert base_cfg is not None
    assert instance_cfg is not None
    assert base_cfg.api_key is None
    assert instance_cfg.api_key == "numbered-key"


def test_load_config_unsupported_suffix_raises_configuration_error(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    with (
        patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=[],
        ),
        patch(
            "src.core.config.models.backends.backend_registry.get_registered_backends",
            return_value=[],
        ),
        pytest.raises(ConfigurationError),
    ):
        load_config(config_path, environ={})


def test_get_env_value_transform_error_raises_configuration_error() -> None:
    env = {"JSON_REPAIR_SCHEMA": "not-json"}
    with pytest.raises(ConfigurationError) as excinfo:
        get_env_value(
            env,
            "JSON_REPAIR_SCHEMA",
            None,
            path="session.json_repair_schema",
            transform=json.loads,
        )
    assert excinfo.value.details["env"] == "JSON_REPAIR_SCHEMA"


def test_backend_config_provider_missing_backend_returns_default_without_mutation() -> (
    None
):
    with patch(
        "src.core.config.models.backends.backend_registry.get_registered_backends",
        return_value=[],
    ):
        cfg = AppConfig()

    provider = BackendConfigProvider(cfg)
    cfg_value = provider.get_backend_config("does-not-exist")
    assert cfg_value is not None
    assert cfg_value.api_key is None
    assert "does-not-exist" not in cfg.backends.__dict__
