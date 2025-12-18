"""Backend and model target resolution service.

This service isolates the logic for determining which backend and model to use
for a given request, including model alias resolution, backend prefix parsing,
URI parameter extraction, and static routing overrides.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from pydantic.types import JsonValue

from src.core.config.app_config import AppConfig
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatRequest
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_model_resolver_interface import (
    IBackendModelResolver,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.model_alias_resolver_interface import IModelAliasResolver
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_routing_service import BackendRoutingService

logger = logging.getLogger(__name__)


class BackendModelResolver(IBackendModelResolver):
    """Resolver for backend and model targets from requests.

    This implementation consolidates target resolution logic including:
    - Session-based backend configuration
    - Model alias resolution (applied before backend parsing)
    - Backend prefix parsing from model strings (e.g., "anthropic:claude-3-5-sonnet")
    - URI parameter extraction (e.g., "?temperature=0.5&max_tokens=100")
    - Static routing overrides from configuration
    - Backend discovery and routing via BackendRoutingService
    """

    def __init__(
        self,
        session_service: ISessionService,
        model_alias_resolver: IModelAliasResolver,
        planning_phase_manager: IPlanningPhaseManager,
        backend_lifecycle_manager: IBackendLifecycleManager,
        config: IConfig,
        routing_service: BackendRoutingService | None = None,
    ):
        """Initialize the backend model resolver.

        Args:
            session_service: Service for session lookups
            model_alias_resolver: Resolver for model aliases
            planning_phase_manager: Manager for planning phase application
            backend_lifecycle_manager: Manager for backend lifecycle
            config: Application configuration
            routing_service: Optional service for backend routing and discovery
        """
        self._session_service = session_service
        self._model_alias_resolver = model_alias_resolver
        self._planning_phase_manager = planning_phase_manager
        self._backend_lifecycle_manager = backend_lifecycle_manager
        self._config = config
        self._routing_service = routing_service

    async def resolve_target(
        self, request: ChatRequest, context: RequestContext | None = None
    ) -> BackendTarget:
        """Resolve backend, model, and URI parameters from request.

        Resolution order:
        1. Session backend configuration (if available)
        2. Request extra_body backend_type (if available)
        3. Model alias resolution (MUST happen before backend parsing)
        4. Backend prefix parsing from model string
        5. URI parameter extraction
        6. Backend discovery via routing service
        7. Static routing overrides

        Args:
            request: The chat completion request
            context: Optional request context (currently unused)

        Returns:
            ResolvedTarget with backend, model, and URI parameters
        """
        # Extract session ID and fetch session
        session_id = (
            request.extra_body.get("session_id") if request.extra_body else None
        )
        session = (
            await self._session_service.get_session(session_id) if session_id else None
        )

        # Get default backend from configuration
        app_config = cast(AppConfig, self._config)
        default_backend: str = (
            app_config.backends.default_backend
            if hasattr(app_config, "backends")
            else "openai"
        )

        # Apply planning phase if needed
        await self._planning_phase_manager.apply_if_needed(session, default_backend)

        # Get disabled backends for filtering
        excluded_backends = set(
            self._backend_lifecycle_manager.get_disabled_backends().keys()
        )

        # Priority 1: Session backend configuration
        backend_type: str | None = None
        if session and session.state and session.state.backend_config:
            backend_type = cast(
                BackendConfiguration, session.state.backend_config
            ).backend_type

        # Priority 2: Request extra_body backend_type
        if not backend_type:
            backend_type = (
                request.extra_body.get("backend_type") if request.extra_body else None
            )

        # Get the effective model from request
        effective_model: str = request.model

        # CRITICAL: Apply model aliases BEFORE parsing backend from model name
        # This ensures aliases that expand to "backend:model" format are handled correctly
        effective_model = self._model_alias_resolver.resolve(effective_model)

        # Parse model string with URI parameters
        uri_params: dict[str, JsonValue] = {}

        if not backend_type:
            # No backend type set yet - parse from model string
            from src.core.domain.model_utils import parse_model_with_params

            # Pass empty string as default to detect if backend was specified
            parsed_backend, parsed_model, uri_params = parse_model_with_params(
                effective_model, ""
            )

            # Try backend discovery if no backend was parsed
            if not parsed_backend and self._routing_service:
                discovered = self._routing_service.resolve_backend_instance(
                    None, parsed_model, excluded_backends
                )
                if discovered:
                    parsed_backend = discovered

            # Fallback to default backend if discovery failed or not used
            backend_type = parsed_backend or default_backend
            effective_model = parsed_model

            # Route the backend type (either parsed or default)
            if self._routing_service:
                resolved = self._routing_service.resolve_backend_instance(
                    backend_type, effective_model, excluded_backends
                )
                if resolved:
                    if logger.isEnabledFor(logging.DEBUG) and resolved != backend_type:
                        logger.debug(
                            f"RoutingService resolved '{backend_type}' -> '{resolved}'"
                        )
                    backend_type = resolved

        else:
            # Backend type already set (from session or extra_body)
            # Still need to parse URI parameters from the model string
            from src.core.domain.model_utils import parse_model_with_params

            # Parse with empty default backend since we already have backend_type
            _, parsed_model, uri_params = parse_model_with_params(effective_model, "")
            effective_model = parsed_model

            # Try to route the explicitly set backend
            if self._routing_service:
                resolved = self._routing_service.resolve_backend_instance(
                    backend_type, effective_model, excluded_backends
                )
                if resolved:
                    if logger.isEnabledFor(logging.DEBUG) and resolved != backend_type:
                        logger.debug(
                            f"RoutingService resolved '{backend_type}' -> '{resolved}'"
                        )
                    backend_type = resolved

        # Apply static_route override if configured
        if (
            hasattr(app_config, "backends")
            and hasattr(app_config.backends, "static_route")
            and app_config.backends.static_route
        ):
            static_route = app_config.backends.static_route
            # Parse backend:model format (check it's a string first)
            if isinstance(static_route, str) and ":" in static_route:
                forced_backend, forced_model = static_route.split(":", 1)
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Applying static_route override: {backend_type}:{effective_model} -> {forced_backend}:{forced_model}"
                    )
                backend_type = forced_backend
                effective_model = forced_model
            else:
                # If no colon, treat as model only
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Applying static_route model override: {effective_model} -> {static_route}"
                    )
                effective_model = static_route

        return BackendTarget(
            backend=backend_type,
            model=effective_model,
            uri_params=uri_params,
        )

    def synchronize_request_with_target(
        self, request: ChatRequest, resolved: BackendTarget
    ) -> ChatRequest:
        """Update request to match resolved backend and model.

        Ensures the request object and its extra_body reflect the resolved
        backend and model information, preserving the original format where
        appropriate.

        Args:
            request: Original chat request
            resolved: Resolved target information

        Returns:
            Updated request with synchronized backend/model
        """
        backend_type = resolved.backend
        effective_model = resolved.model

        updates: dict[str, Any] = {}

        # Preserve the original model format if it contains a backend prefix that matches
        # the resolved backend. This allows connectors to see the original client request.
        # However, if the backend was overridden (e.g., via static_route), update the model.
        should_update_model = False
        if request.model != effective_model:
            if ":" in request.model:
                # Model has backend prefix - check if it matches the resolved backend
                request_backend, _ = request.model.split(":", 1)
                if request_backend != backend_type:
                    # Backend was overridden, update the model
                    should_update_model = True
                # else: Backend matches, preserve original format
            else:
                # No backend prefix, update to effective model
                should_update_model = True

        if should_update_model:
            updates["model"] = effective_model

        extra_body = getattr(request, "extra_body", None)
        if isinstance(extra_body, dict):
            updated_extra_body = dict(extra_body)
            extra_changed = False

            if updated_extra_body.get("model") != effective_model:
                updated_extra_body["model"] = effective_model
                extra_changed = True

            if backend_type:
                if updated_extra_body.get("backend_type") != backend_type:
                    updated_extra_body["backend_type"] = backend_type
                    extra_changed = True
            elif "backend_type" in updated_extra_body:
                # Remove stale backend_type when backend resolution is empty
                updated_extra_body.pop("backend_type")
                extra_changed = True

            if extra_changed:
                updates["extra_body"] = updated_extra_body

        if not updates:
            return request

        return request.model_copy(update=updates)
