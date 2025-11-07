"""Parameter utilities for the hybrid connector."""

from __future__ import annotations

import contextlib
from dataclasses import asdict, is_dataclass
from typing import Any, cast

from src.connectors.utils.model_capabilities import (
    get_execution_params,
    get_reasoning_params,
    supports_system_messages,
)
from src.core.config.app_config import AppConfig
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO

from .logging_utils import get_hybrid_logger


class HybridParameterMixin:
    """Shared helpers for applying hybrid parameter presets."""

    config: AppConfig

    def _apply_reasoning_params(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        backend_or_params: str | dict[str, Any],
        enable_reasoning: bool | None = None,
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply backend-specific reasoning parameters to the request."""

        if isinstance(backend_or_params, str):
            if enable_reasoning is None:
                raise TypeError(
                    "enable_reasoning flag is required when backend name is provided"
                )
            params = (
                get_reasoning_params(backend_or_params)
                if enable_reasoning
                else get_execution_params(backend_or_params)
            )
        elif isinstance(backend_or_params, dict):
            params = backend_or_params
        else:  # pragma: no cover - defensive guard
            raise TypeError(
                "backend_or_params must be a backend string or parameter dictionary"
            )

        return self._apply_parameter_overrides(request_data, params)

    def _apply_parameter_overrides(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        params: dict[str, Any],
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply a parameter dictionary to the request data."""

        if not params:
            return request_data

        logger = get_hybrid_logger()
        for key, value in params.items():
            logger.debug("Applying override %s=%s to request", key, value)

        if isinstance(request_data, DomainModel):
            current_extra_body = getattr(request_data, "extra_body", None)
            new_extra_body = dict(current_extra_body) if current_extra_body else {}
            new_extra_body.update(params)
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)
            return request_data.model_copy(
                update={
                    "extra_body": new_extra_body if new_extra_body else None,
                    **params,
                }
            )

        if isinstance(request_data, dict):
            request_copy = dict(request_data)
            current_extra_body = request_copy.get("extra_body")
            new_extra_body = (
                dict(current_extra_body) if isinstance(current_extra_body, dict) else {}
            )
            new_extra_body.update(params)
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)
            request_copy["extra_body"] = new_extra_body if new_extra_body else None
            request_copy.update(params)
            return request_copy

        if is_dataclass(request_data) and not isinstance(request_data, type):
            request_dict = asdict(request_data)
            current_extra_body = request_dict.get("extra_body")
            new_extra_body = (
                dict(current_extra_body) if isinstance(current_extra_body, dict) else {}
            )
            new_extra_body.update(params)
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)
            request_dict["extra_body"] = new_extra_body if new_extra_body else None
            request_dict.update(params)
            return request_dict

        logger = get_hybrid_logger()
        logger.warning(
            "Unsupported request_data type in _apply_reasoning_params: %s",
            type(request_data).__name__,
        )
        return request_data

    def _resolve_backend_identity(
        self,
        backend: str,
        request_identity: IAppIdentityConfig | None,
        backend_config: Any = None,
    ) -> IAppIdentityConfig | None:
        """Resolve identity configuration for backend calls."""

        if backend_config is not None and getattr(backend_config, "identity", None):
            return cast(IAppIdentityConfig, backend_config.identity)

        backend_identity = None
        if hasattr(self.config, "backends"):
            with contextlib.suppress(AttributeError):
                backend_settings = getattr(self.config.backends, backend)
                backend_identity = getattr(backend_settings, "identity", None)
        if backend_identity is not None:
            return cast(IAppIdentityConfig, backend_identity)

        if request_identity is not None:
            return request_identity

        return getattr(self.config, "identity", None)

    def get_reasoning_params(self, backend: str = "openai") -> dict[str, Any]:
        """Expose reasoning parameter presets for tests and diagnostics."""

        return get_reasoning_params(backend)

    def get_execution_params(self, backend: str = "openai") -> dict[str, Any]:
        """Expose execution parameter presets for tests and diagnostics."""

        return get_execution_params(backend)

    def _supports_system_messages(self, backend: str) -> bool:
        """Check if backend supports system messages."""

        return supports_system_messages(backend)
