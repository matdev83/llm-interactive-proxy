"""Tests for ``CodexModelCatalogStage`` — startup discovery + DI registration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from src.connectors.openai_codex.catalog.config import (
    DEFAULT_CODEX_MODEL_CATALOG_CONFIG,
    CodexModelCatalogConfig,
)
from src.connectors.openai_codex.catalog.interfaces import ICodexModelCatalog
from src.core.app.stages.codex_model_catalog import (
    CodexModelCatalogStage,
    resolve_codex_model_catalog_config,
)
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.di.container import ServiceCollection

_MIN_RAW_CATALOG = {
    "models": [
        {
            "slug": "gpt-5.6-sol",
            "default_reasoning_level": "low",
            "supported_reasoning_levels": [
                {"effort": "low", "description": "d"},
                {"effort": "medium", "description": "d"},
                {"effort": "high", "description": "d"},
                {"effort": "xhigh", "description": "d"},
                {"effort": "max", "description": "d"},
                {"effort": "ultra", "description": "d"},
            ],
            "visibility": "list",
            "supported_in_api": True,
        },
        {
            "slug": "gpt-5.5",
            "default_reasoning_level": "medium",
            "supported_reasoning_levels": [
                {"effort": "low", "description": "d"},
                {"effort": "medium", "description": "d"},
                {"effort": "high", "description": "d"},
                {"effort": "xhigh", "description": "d"},
            ],
            "visibility": "list",
            "supported_in_api": True,
        },
    ]
}


def _write_catalog(path: Path) -> Path:
    path.write_text(json.dumps(_MIN_RAW_CATALOG), encoding="utf-8")
    return path


def _config_with_model_catalog(model_catalog: dict) -> AppConfig:
    backend = BackendConfig(extra={"codex": {"model_catalog": model_catalog}})
    base = AppConfig()
    return base.model_copy(
        update={
            "backends": base.backends.model_copy(
                update={"openai_codex": backend}
            )
        }
    )


class TestStageMetadata:
    def test_name(self) -> None:
        assert CodexModelCatalogStage().name == "codex_model_catalog"

    def test_dependencies(self) -> None:
        assert CodexModelCatalogStage().get_dependencies() == ["core_services"]


class TestResolveModelCatalogConfig:
    def test_defaults_when_no_model_catalog_section(self) -> None:
        config = AppConfig()
        cfg = resolve_codex_model_catalog_config(config)
        assert cfg == DEFAULT_CODEX_MODEL_CATALOG_CONFIG

    def test_reads_from_openai_codex_backend(self) -> None:
        config = _config_with_model_catalog(
            {
                "discovery_enabled": False,
                "fallback_path": "/x/catalog.json",
                "discovery_timeout_seconds": 7.0,
            }
        )
        cfg = resolve_codex_model_catalog_config(config)
        assert cfg == CodexModelCatalogConfig(
            discovery_enabled=False,
            fallback_path="/x/catalog.json",
            discovery_timeout_seconds=7.0,
        )

    def test_reads_from_v2_when_v1_absent(self) -> None:
        base = AppConfig()
        v2_backend = BackendConfig(
            extra={"codex": {"model_catalog": {"discovery_enabled": False}}}
        )
        config = base.model_copy(
            update={
                "backends": base.backends.model_copy(
                    update={
                        "openai_codex": None,
                        "openai_codex_v2": v2_backend,
                    }
                )
            }
        )
        cfg = resolve_codex_model_catalog_config(config)
        assert cfg.discovery_enabled is False


class TestStageExecute:
    @pytest.mark.asyncio
    async def test_registers_catalog_from_fallback_file(self, tmp_path: Path) -> None:
        catalog_file = _write_catalog(tmp_path / "catalog.json")
        config = _config_with_model_catalog(
            {
                "discovery_enabled": False,
                "fallback_path": str(catalog_file),
            }
        )

        services = ServiceCollection()
        stage = CodexModelCatalogStage()
        await stage.execute(services, config)

        provider = services.build_service_provider()
        catalog = provider.get_required_service(cast(type, ICodexModelCatalog))
        assert catalog.routable_slugs() == ("gpt-5.6-sol", "gpt-5.5")
        assert catalog.is_supported("gpt-5.6-sol") is True

    @pytest.mark.asyncio
    async def test_registers_catalog_even_when_no_model_catalog_section(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """With defaults (discovery enabled) but no codex binary present and a
        fallback override, the stage still registers a catalog."""
        catalog_file = _write_catalog(tmp_path / "catalog.json")
        # Force discovery to find no binary so it falls back to the override path.
        import src.connectors.openai_codex.catalog.discovery_service as ds_mod

        monkeypatch.setattr(ds_mod, "candidate_codex_executables", lambda configured: [])
        config = _config_with_model_catalog(
            {"discovery_enabled": True, "fallback_path": str(catalog_file)}
        )

        services = ServiceCollection()
        stage = CodexModelCatalogStage()
        await stage.execute(services, config)

        provider = services.build_service_provider()
        catalog = provider.get_required_service(cast(type, ICodexModelCatalog))
        assert catalog.routable_slugs() == ("gpt-5.6-sol", "gpt-5.5")
