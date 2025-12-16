"""Request preparation logic for backend completion flow."""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_model_resolver_interface import IBackendModelResolver
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)

logger = logging.getLogger(__name__)


class RequestPreparer:
    """Handles request preparation, session resolution, and parameter application."""

    def __init__(
        self,
        backend_model_resolver: IBackendModelResolver,
        session_service: ISessionService,
        backend_config_service: IBackendConfigProvider,
        reasoning_config_applicator: IReasoningConfigApplicator,
        uri_parameter_applicator: IURIParameterApplicator,
        config: IConfig,
    ):
        """Initialize the request preparer."""
        self._backend_model_resolver = backend_model_resolver
        self._session_service = session_service
        self._backend_config_service = backend_config_service
        self._reasoning_config_applicator = reasoning_config_applicator
        self._uri_parameter_applicator = uri_parameter_applicator
        self._config = config

    async def prepare_request(
        self, request: ChatRequest, context: RequestContext | None
    ) -> tuple[str, str, dict[str, Any]]:
        """Resolve backend type, effective model, and URI parameters.

        Args:
            request: The chat completion request
            context: Optional request context

        Returns:
            Tuple of (backend_type, effective_model, uri_params)
        """
        resolved = await self._backend_model_resolver.resolve_target(request, context)
        return resolved.backend, resolved.model, resolved.uri_params

    def synchronize_request_with_target(
        self, request: ChatRequest, backend_type: str, effective_model: str
    ) -> ChatRequest:
        """Ensure the request payload reflects the resolved backend and model.

        Args:
            request: Original chat request
            backend_type: Resolved backend name
            effective_model: Resolved model name

        Returns:
            Request object updated with resolved backend/model information
        """
        from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget

        resolved = ResolvedTarget(
            backend=backend_type,
            model=effective_model,
            uri_params={},  # URI params not needed for synchronization
        )
        return self._backend_model_resolver.synchronize_request_with_target(
            request, resolved
        )

    async def resolve_session(
        self, context: RequestContext | None, request: ChatRequest
    ) -> tuple[Any | None, str | None]:
        """Resolve session from context or request.

        Args:
            context: Optional request context
            request: The chat completion request

        Returns:
            Tuple of (session, session_id_for_backend)
        """
        session: Any | None = None
        session_id_for_backend: str | None = None

        # Resolve session from context when available
        if context and context.session_id:
            session_id_for_backend = context.session_id
            try:
                session = await self._session_service.get_session(context.session_id)
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to load session '%s' for backend call",
                        context.session_id,
                        exc_info=True,
                    )
                session = None

        # Try to get session from request extra_body if not found in context
        request_session_id = (
            request.extra_body.get("session_id") if request.extra_body else None
        )
        if (
            session is None
            and isinstance(request_session_id, str)
            and request_session_id
        ):
            if session_id_for_backend is None:
                session_id_for_backend = request_session_id
            try:
                session = await self._session_service.get_session(request_session_id)
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Could not load session {request_session_id} for backend from backend-only service"
                    )
                session = None

        return session, session_id_for_backend

    async def prepare_backend_request(
        self,
        request: ChatRequest,
        backend_type: str,
        session: Any | None,
        uri_params: dict[str, Any],
    ) -> ChatRequest:
        """Apply reasoning config, backend config, and URI parameters to the request.

        Args:
            request: The original request
            backend_type: The backend name
            session: Optional session object
            uri_params: URI parameters to apply

        Returns:
            Transformed request ready for backend invocation
        """
        domain_request: ChatRequest = request

        # Apply session reasoning configuration if available
        if session is not None:
            try:
                domain_request = self._reasoning_config_applicator.apply(
                    domain_request, session
                )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to apply reasoning config from session",
                        exc_info=True,
                    )

        # Apply backend configuration
        if self._backend_config_service:
            domain_request = self._backend_config_service.apply_backend_config(
                domain_request, backend_type, cast(AppConfig, self._config)
            )

        # Apply URI parameters with precedence resolution
        if uri_params:
            try:
                domain_request = self._uri_parameter_applicator.apply(
                    domain_request, uri_params, backend_type, session
                )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to apply URI parameters",
                        exc_info=True,
                    )

        return domain_request

    def prepare_backend_kwargs(
        self,
        session_id_for_backend: str | None,
        session: Any | None,
        context: RequestContext | None,
        backend_type: str,
    ) -> dict[str, Any]:
        """Prepare kwargs for backend call.

        Args:
            session_id_for_backend: Optional session ID
            session: Optional session object
            context: Optional request context
            backend_type: The backend name

        Returns:
            Dictionary of kwargs for backend.chat_completions()
        """
        backend_call_kwargs: dict[str, Any] = {}

        if session_id_for_backend:
            backend_call_kwargs["session_id"] = session_id_for_backend

        if session is not None and hasattr(session, "state"):
            try:
                project_value = getattr(session.state, "project", None)
                if isinstance(project_value, str) and project_value:
                    backend_call_kwargs["project"] = project_value
            except Exception:
                pass
            try:
                project_dir_value = getattr(session.state, "project_dir", None)
                if isinstance(project_dir_value, str) and project_dir_value:
                    backend_call_kwargs["project_dir"] = project_dir_value
            except Exception:
                pass

        # Special handling for cline backend
        if context is not None and backend_type == "cline":
            try:
                incoming_headers = getattr(context, "headers", None)
                headers_dict: dict[str, Any] | None = None

                to_dict = getattr(incoming_headers, "to_dict", None)
                if callable(to_dict):
                    headers_dict = cast(dict[str, Any], to_dict())
                elif incoming_headers:
                    headers_dict = dict(incoming_headers)

                if headers_dict is not None:
                    backend_call_kwargs["incoming_headers"] = headers_dict
            except Exception:
                pass

        return backend_call_kwargs
