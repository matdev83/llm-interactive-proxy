"""URI parameter applicator implementation.

Resolves and applies URI parameters with proper precedence.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from pydantic.types import JsonValue

from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)

if TYPE_CHECKING:
    from src.core.domain.chat import ChatRequest
    from src.core.interfaces.configuration_interface import IConfig
    from src.core.services.parameter_resolution_service import ResolvedParameters


logger = logging.getLogger(__name__)


class URIParameterApplicator(IURIParameterApplicator):
    """Service for applying URI parameters to requests."""

    def __init__(self, config: IConfig | None = None) -> None:
        """Initialize the URI parameter applicator.

        Args:
            config: Application configuration.
        """
        self._config = config

    def apply(
        self,
        request: ChatRequest,
        uri_params: dict[str, JsonValue],
        backend_type: str,
        session: Any | None = None,
    ) -> ChatRequest:
        """Apply URI parameters to request with precedence resolution.

        Sources and precedence (highest to lowest):
        1. Session overrides (from commands)
        2. URI parameters
        3. Request/extra_body fields (headers)
        4. Backend/app config

        Type coercion rules:
        - temperature, top_p -> float
        - top_k -> int (rejects non-integer floats)
        - reasoning_effort -> str

        Edit-precision mode promotes one-shot request fields into session-level
        precedence. Early-returns if uri_params is empty.
        """
        # Early return if no URI parameters to apply
        if not uri_params:
            return request

        try:
            return self._apply_uri_parameters(
                request, uri_params, backend_type, session
            )
        except Exception as outer_error:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Unexpected error applying URI parameters for {backend_type}: "
                    f"{outer_error}. Continuing with original request.",
                    exc_info=True,
                )
            return request

    def _apply_uri_parameters(
        self,
        request: ChatRequest,
        uri_params: dict[str, JsonValue],
        backend_type: str,
        session: Any | None,
    ) -> ChatRequest:
        """Internal method to apply URI parameters."""
        normalized_uri_params = self._validate_uri_params(uri_params, backend_type)
        if normalized_uri_params is None:
            return request

        config_params = self._extract_config_params(backend_type)
        header_params = self._extract_header_params(request, backend_type)
        session_params = self._extract_session_params(session, backend_type)
        self._apply_edit_precision_overrides(request, session_params)

        resolved = self._resolve_parameters(
            normalized_uri_params=normalized_uri_params,
            header_params=header_params,
            config_params=config_params,
            session_params=session_params,
            backend_type=backend_type,
        )
        if resolved is None:
            return request

        return self._apply_resolved_parameters(request, resolved, backend_type)

    @staticmethod
    def _coerce_parameter(name: str, value: Any) -> Any | None:
        if value is None:
            return None

        try:
            if name in {"temperature", "top_p"}:
                return float(value)
            if name == "top_k":
                if isinstance(value, float):
                    if not value.is_integer():
                        raise ValueError(f"{value!r} is not an integer value")
                    return int(value)
                if isinstance(value, int):
                    return value

                string_value = str(value).strip()
                float_value = float(string_value)
                if not float_value.is_integer():
                    raise ValueError(f"{value!r} is not an integer value")
                return int(float_value)
            if name == "reasoning_effort":
                return str(value)
        except (TypeError, ValueError) as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to coerce raw value %r to type for %s: %s",
                    value,
                    name,
                    exc,
                )
            return None

        return value

    @classmethod
    def _assign_param(cls, target: dict[str, Any], name: str, value: Any) -> None:
        coerced = cls._coerce_parameter(name, value)
        if coerced is not None:
            target[name] = coerced

    @classmethod
    def _assign_from_obj(cls, target: dict[str, Any], obj: Any, name: str) -> None:
        if obj is None:
            return
        value = getattr(obj, name, None)
        if value is not None:
            cls._assign_param(target, name, value)

    @staticmethod
    def _param_names() -> tuple[str, ...]:
        return ("temperature", "top_p", "top_k", "reasoning_effort")

    def _validate_uri_params(
        self, uri_params: dict[str, JsonValue], backend_type: str
    ) -> dict[str, Any] | None:
        from src.core.services.uri_parameter_validator import URIParameterValidator

        try:
            validator = URIParameterValidator()
            normalized_params, validation_errors = validator.validate_and_normalize(
                uri_params
            )
            if validation_errors and logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "URI parameter validation errors for %s: %s. Invalid parameters excluded.",
                    backend_type,
                    ", ".join(validation_errors),
                )
            return normalized_params
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to validate URI parameters for %s: %s. Continuing without URI parameters.",
                    backend_type,
                    exc,
                    exc_info=True,
                )
            return None

    def _extract_config_params(self, backend_type: str) -> dict[str, Any]:
        config_params: dict[str, Any] = {}
        try:
            if not self._config:
                return config_params

            from src.core.config.app_config import AppConfig

            app_config = cast(AppConfig, self._config)
            backend_config = app_config.backends.get(backend_type)
            if not backend_config:
                return config_params

            for param_name in self._param_names():
                self._assign_from_obj(config_params, backend_config, param_name)

            extra_cfg = getattr(backend_config, "extra", None)
            if isinstance(extra_cfg, dict):
                for param_name in self._param_names():
                    if param_name in extra_cfg:
                        self._assign_param(
                            config_params, param_name, extra_cfg[param_name]
                        )
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to extract config parameters for %s: %s",
                    backend_type,
                    exc,
                    exc_info=True,
                )

        return config_params

    def _extract_header_params(
        self, request: ChatRequest, backend_type: str
    ) -> dict[str, Any]:
        header_params: dict[str, Any] = {}
        try:
            if request.extra_body:
                for param_name in self._param_names():
                    if param_name in request.extra_body:
                        self._assign_param(
                            header_params, param_name, request.extra_body[param_name]
                        )

            for param_name in self._param_names():
                value = getattr(request, param_name, None)
                if value is not None:
                    self._assign_param(header_params, param_name, value)
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to extract header parameters for %s: %s",
                    backend_type,
                    exc,
                    exc_info=True,
                )

        return header_params

    def _extract_session_params(
        self, session: Any | None, backend_type: str
    ) -> dict[str, Any]:
        session_params: dict[str, Any] = {}
        if session is None:
            return session_params

        try:
            reasoning_config = getattr(session, "get_reasoning_mode", lambda: None)()
            if reasoning_config is not None:
                for param_name in self._param_names():
                    self._assign_from_obj(session_params, reasoning_config, param_name)
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to extract session parameters for %s: %s",
                    backend_type,
                    exc,
                    exc_info=True,
                )

        return session_params

    @staticmethod
    def _apply_edit_precision_overrides(
        request: ChatRequest, session_params: dict[str, Any]
    ) -> None:
        try:
            extra_body = getattr(request, "extra_body", None)
            if not (
                isinstance(extra_body, dict) and extra_body.get("_edit_precision_mode")
            ):
                return
            if getattr(request, "temperature", None) is not None:
                session_params["temperature"] = request.temperature
            if getattr(request, "top_p", None) is not None:
                session_params["top_p"] = request.top_p
            if getattr(request, "top_k", None) is not None:
                session_params["top_k"] = request.top_k
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to apply edit-precision overrides: %s",
                    exc,
                    exc_info=True,
                )

    def _resolve_parameters(
        self,
        *,
        normalized_uri_params: dict[str, Any],
        header_params: dict[str, Any],
        config_params: dict[str, Any],
        session_params: dict[str, Any],
        backend_type: str,
    ) -> ResolvedParameters | None:

        from src.core.services.parameter_resolution_service import (
            ParameterResolutionService,
        )

        try:
            resolution_service = ParameterResolutionService()
            return resolution_service.resolve_parameters(
                uri_params=normalized_uri_params,
                header_params=header_params,
                config_params=config_params,
                session_params=session_params,
                backend=backend_type,
            )
        except Exception as exc:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to resolve parameters for %s: %s. Continuing without URI parameters.",
                    backend_type,
                    exc,
                    exc_info=True,
                )
            return None

    @staticmethod
    def _apply_resolved_parameters(
        request: ChatRequest, resolved: ResolvedParameters, backend_type: str
    ) -> ChatRequest:

        try:
            resolved_params = resolved.to_dict()
            if not resolved_params:
                return request

            updates: dict[str, Any] = {}
            for param_name in ("temperature", "top_p", "top_k", "reasoning_effort"):
                if param_name in resolved_params:
                    updates[param_name] = resolved_params[param_name]

            extra_body_dict = dict(request.extra_body) if request.extra_body else {}
            extra_body_dict.update(resolved_params)
            updates["extra_body"] = extra_body_dict

            updated = request.model_copy(update=updates)
            debug_info = resolved.get_debug_info()
            if debug_info and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Applied URI parameters for %s: %s", backend_type, debug_info
                )
            return updated
        except Exception as exc:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to apply resolved parameters for %s: %s. Continuing with original request.",
                    backend_type,
                    exc,
                    exc_info=True,
                )
            return request
