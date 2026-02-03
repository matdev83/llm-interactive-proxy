"""Backend request preparation collaborator."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from pydantic.types import JsonValue

from src.core.config.app_config import AppConfig
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_completion_collaborators import (
    IBackendRequestPreparer,
)
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_model_resolver_interface import IBackendModelResolver
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.domain_entities_interface import ISession
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)

if TYPE_CHECKING:
    from src.core.services.auxiliary_request_router import AuxiliaryRequestRouter

logger = logging.getLogger(__name__)


class BackendRequestPreparer(IBackendRequestPreparer):
    """Handles request preparation, config application, and parameter resolution."""

    def __init__(
        self,
        backend_model_resolver: IBackendModelResolver,
        backend_config_service: IBackendConfigProvider,
        reasoning_config_applicator: IReasoningConfigApplicator,
        uri_parameter_applicator: IURIParameterApplicator,
        config: IConfig,
        auxiliary_router: AuxiliaryRequestRouter | None = None,
    ):
        """Initialize the request preparer."""
        self._backend_model_resolver = backend_model_resolver
        self._backend_config_service = backend_config_service
        self._reasoning_config_applicator = reasoning_config_applicator
        self._uri_parameter_applicator = uri_parameter_applicator
        self._config = config
        self._auxiliary_router = auxiliary_router

    async def prepare_request(
        self, request: CanonicalChatRequest, context: RequestContext | None
    ) -> BackendTarget:
        """Resolve backend type, effective model, and URI parameters.

        If auxiliary request routing is enabled and this request is detected
        as an auxiliary request (title/summary generation), the target will
        be overridden to use the configured auxiliary backend.
        """
        # First, resolve the default target
        target = await self._backend_model_resolver.resolve_target(request, context)

        # Check if this is an auxiliary request that should be routed differently
        if (
            self._auxiliary_router
            and self._auxiliary_router.enabled
            and self._auxiliary_router.should_route_to_auxiliary(request)
        ):
            auxiliary_backend = self._auxiliary_router.get_auxiliary_backend()
            auxiliary_model = self._auxiliary_router.get_auxiliary_model()

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Routing auxiliary request to backend '%s' (model: %s) "
                    "instead of '%s' (model: %s)",
                    auxiliary_backend,
                    auxiliary_model or "default",
                    target.backend,
                    target.model,
                )

            if context is not None:
                # IMPORTANT: Auxiliary requests (title/summary generation) must not
                # interfere with the primary conversation session lifecycle (EoS
                # detection, dedup status, fingerprinting).
                #
                # We keep the client-visible session_id unchanged, but run the
                # backend call under a derived internal session id.
                root_session_id = getattr(context, "session_id", None)
                if isinstance(root_session_id, str) and root_session_id:
                    context.extensions["auxiliary_effective_session_id"] = (
                        f"aux::{root_session_id}"
                    )
                context.extensions["auxiliary_request"] = True
                context.extensions["auxiliary_original_backend"] = cast(
                    JsonValue, target.backend
                )
                context.extensions["auxiliary_original_model"] = cast(
                    JsonValue, target.model
                )
                context.extensions["auxiliary_backend"] = cast(
                    JsonValue, auxiliary_backend
                )
                context.extensions["auxiliary_model"] = cast(
                    JsonValue, auxiliary_model or target.model
                )

            # Create a new target with the auxiliary backend/model
            target = BackendTarget(
                backend=auxiliary_backend,
                model=auxiliary_model or target.model,
                uri_params=target.uri_params,
            )

        return target

    def synchronize_request_with_target(
        self, request: CanonicalChatRequest, target: BackendTarget
    ) -> CanonicalChatRequest:
        """Ensure the request payload reflects the resolved backend and model."""
        result = self._backend_model_resolver.synchronize_request_with_target(
            request, target
        )
        return cast(CanonicalChatRequest, result)

    async def prepare_backend_request(
        self,
        request: CanonicalChatRequest,
        backend_type: str,
        session: ISession | None,
        uri_params: dict[str, JsonValue],
    ) -> CanonicalChatRequest:
        """Apply reasoning config, backend config, and URI parameters to the request."""
        domain_request: ChatRequest = request

        # Apply session reasoning configuration if available
        # Note: ReasoningConfigApplicator.apply handles exceptions internally
        if session is not None:
            domain_request = self._reasoning_config_applicator.apply(
                domain_request, session
            )

        # Apply backend configuration
        if self._backend_config_service:
            domain_request = self._backend_config_service.apply_backend_config(
                domain_request, backend_type, cast(AppConfig, self._config)
            )

        # Apply URI parameters with precedence resolution
        # Note: URIParameterApplicator.apply handles exceptions internally
        if uri_params:
            domain_request = self._uri_parameter_applicator.apply(
                domain_request, uri_params, backend_type, session
            )

        return cast(CanonicalChatRequest, domain_request)

    def prepare_backend_kwargs(
        self,
        session_id_for_backend: str | None,
        session: ISession | None,
        context: RequestContext | None,
        backend_type: str,
    ) -> dict[str, JsonValue]:
        """Prepare kwargs for backend call."""

        backend_call_kwargs: dict[str, JsonValue] = {}

        if session_id_for_backend:
            backend_call_kwargs["session_id"] = session_id_for_backend

        if session is not None and hasattr(session, "state"):
            try:
                project_value = getattr(session.state, "project", None)
                if isinstance(project_value, str) and project_value:
                    backend_call_kwargs["project"] = project_value
            except (AttributeError, TypeError) as e:
                # Expected exceptions from attribute access or type checking
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to extract project value from session state: %s",
                        e,
                        exc_info=True,
                    )
            except Exception as e:
                # Unexpected exceptions should be logged at WARNING level for visibility
                logger.warning(
                    "Unexpected error extracting project value from session state: %s",
                    e,
                    exc_info=True,
                )
            try:
                project_dir_value = getattr(session.state, "project_dir", None)
                if isinstance(project_dir_value, str) and project_dir_value:
                    backend_call_kwargs["project_dir"] = project_dir_value
            except (AttributeError, TypeError) as e:
                # Expected exceptions from attribute access or type checking
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to extract project_dir value from session state: %s",
                        e,
                        exc_info=True,
                    )
            except Exception as e:
                # Unexpected exceptions should be logged at WARNING level for visibility
                logger.warning(
                    "Unexpected error extracting project_dir value from session state: %s",
                    e,
                    exc_info=True,
                )

        # Special handling for cline backend
        if context is not None and backend_type == "cline":
            try:
                incoming_headers = getattr(context, "headers", None)
                headers_dict: dict[str, JsonValue] | None = None

                to_dict = getattr(incoming_headers, "to_dict", None)
                if callable(to_dict):
                    headers_dict = cast(dict[str, JsonValue], to_dict())
                elif incoming_headers:
                    headers_dict = dict(incoming_headers)  # type: ignore[assignment]

                if headers_dict is not None:
                    backend_call_kwargs["incoming_headers"] = headers_dict
            except (AttributeError, TypeError, ValueError) as e:
                # Expected exceptions from attribute access, type checking, or dict conversion
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to extract headers from context for cline backend: %s",
                        e,
                        exc_info=True,
                    )
            except Exception as e:
                # Unexpected exceptions should be logged at WARNING level for visibility
                logger.warning(
                    "Unexpected error extracting headers from context for cline backend: %s",
                    e,
                    exc_info=True,
                )

        return backend_call_kwargs
