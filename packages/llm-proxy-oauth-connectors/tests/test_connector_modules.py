from __future__ import annotations

import sys
from importlib import import_module
from unittest.mock import patch

import pytest

_CONNECTOR_MODULE_CASES: list[tuple[str, str, str]] = [
    (
        "anthropic-oauth",
        "llm_proxy_oauth_connectors.anthropic_oauth",
        "AnthropicOAuthBackend",
    ),
    (
        "antigravity-oauth",
        "llm_proxy_oauth_connectors.antigravity_oauth",
        "AntigravityOAuthConnector",
    ),
    (
        "gemini-oauth-auto",
        "llm_proxy_oauth_connectors.gemini_oauth_auto.connector",
        "GeminiOAuthAutoConnector",
    ),
    (
        "gemini-oauth-free",
        "llm_proxy_oauth_connectors.gemini_oauth_free",
        "GeminiOAuthFreeConnector",
    ),
    (
        "gemini-oauth-plan",
        "llm_proxy_oauth_connectors.gemini_oauth_plan",
        "GeminiOAuthPlanConnector",
    ),
    (
        "qwen-oauth",
        "llm_proxy_oauth_connectors.qwen_oauth",
        "QwenOAuthConnector",
    ),
]


_CONNECTOR_MODULE_PATHS = [module_path for _, module_path, _ in _CONNECTOR_MODULE_CASES]


@pytest.mark.parametrize(
    ("expected_backend", "module_path", "class_name"),
    _CONNECTOR_MODULE_CASES,
)
def test_connector_module_exports_expected_backend_class(
    expected_backend: str, module_path: str, class_name: str
) -> None:
    module = import_module(module_path)
    connector_cls = getattr(module, class_name)
    assert connector_cls.backend_type == expected_backend


@pytest.mark.parametrize("module_path", _CONNECTOR_MODULE_PATHS)
def test_connector_import_has_no_registry_side_effects(module_path: str) -> None:
    """Connector imports must not self-register; entry points are canonical path."""
    from src.core.services.backend_registry import backend_registry

    with patch.object(backend_registry, "register_backend") as register_backend:
        sys.modules.pop(module_path, None)
        import_module(module_path)

    register_backend.assert_not_called()
