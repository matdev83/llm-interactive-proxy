"""Backend request preparation collaborator."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, cast

from pydantic.types import JsonValue

from src.core.config.app_config import AppConfig
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatRequest
from src.core.domain.model_utils import has_explicit_backend_selector
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
from src.core.services.auxiliary_identity import (
    build_auxiliary_effective_session_id,
    derive_auxiliary_operation_key,
)

if TYPE_CHECKING:
    from src.core.services.auxiliary_request_router import AuxiliaryRequestRouter

logger = logging.getLogger(__name__)

_REQUIRES_NON_EMPTY_SESSION_ID_FAMILIES: frozenset[str] = frozenset(
    {
        "openai-codex",
    }
)
_SKIP_STATIC_ROUTE_CONTEXT_KEY = "skip_static_route"


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
        async def _resolve_target_with_optional_static_route_skip(
            request_to_resolve: CanonicalChatRequest,
            *,
            skip_static_route: bool,
        ) -> BackendTarget:
            had_previous_skip_static_route = False
            previous_skip_static_route: JsonValue | None = None
            if (
                skip_static_route
                and context is not None
                and isinstance(context.extensions, dict)
            ):
                had_previous_skip_static_route = (
                    _SKIP_STATIC_ROUTE_CONTEXT_KEY in context.extensions
                )
                if had_previous_skip_static_route:
                    previous_skip_static_route = cast(
                        JsonValue | None,
                        context.extensions.get(_SKIP_STATIC_ROUTE_CONTEXT_KEY),
                    )
                context.extensions[_SKIP_STATIC_ROUTE_CONTEXT_KEY] = True

            try:
                return await self._backend_model_resolver.resolve_target(
                    request_to_resolve, context
                )
            finally:
                if (
                    skip_static_route
                    and context is not None
                    and isinstance(context.extensions, dict)
                ):
                    if not had_previous_skip_static_route:
                        context.extensions.pop(_SKIP_STATIC_ROUTE_CONTEXT_KEY, None)
                    else:
                        context.extensions[_SKIP_STATIC_ROUTE_CONTEXT_KEY] = (
                            previous_skip_static_route
                        )

        should_route_auxiliary = (
            self._auxiliary_router is not None
            and self._auxiliary_router.enabled
            and self._auxiliary_router.should_route_to_auxiliary(request)
        )

        # First, resolve the default target. When we already know this is an
        # auxiliary request, skip static_route to avoid clobbering the auxiliary
        # backend before the reroute pass.
        target = await _resolve_target_with_optional_static_route_skip(
            request, skip_static_route=should_route_auxiliary
        )

        # Check if this is an auxiliary request that should be routed differently
        if should_route_auxiliary and self._auxiliary_router:
            auxiliary_backend = self._auxiliary_router.get_auxiliary_backend()
            auxiliary_model = self._auxiliary_router.get_auxiliary_model()
            original_backend = target.backend
            original_model = target.model
            auxiliary_selector: str
            if auxiliary_model and has_explicit_backend_selector(auxiliary_model):
                auxiliary_selector = auxiliary_model
            elif auxiliary_model:
                auxiliary_selector = f"{auxiliary_backend}:{auxiliary_model}"
            else:
                auxiliary_selector = f"{auxiliary_backend}:{target.model}"

            auxiliary_extra_body: dict[str, JsonValue] | None = None
            if isinstance(request.extra_body, dict):
                auxiliary_extra_body = dict(request.extra_body)
            if auxiliary_extra_body is None:
                auxiliary_extra_body = {}
            auxiliary_extra_body.pop("backend_type", None)
            auxiliary_request = request.model_copy(
                update={
                    "model": auxiliary_selector,
                    "extra_body": (
                        auxiliary_extra_body if auxiliary_extra_body else None
                    ),
                }
            )
            target = await _resolve_target_with_optional_static_route_skip(
                auxiliary_request,
                skip_static_route=True,
            )

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Routing auxiliary request via shared resolver using '%s' -> "
                    "'%s:%s' instead of '%s:%s'",
                    auxiliary_selector,
                    target.backend,
                    target.model,
                    original_backend,
                    original_model,
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
                    auxiliary_purpose = f"{target.backend}:{target.model}"
                    operation_key = derive_auxiliary_operation_key(
                        context=context,
                        request_data=request,
                        purpose=auxiliary_purpose,
                    )
                    auxiliary_attempt_ordinal = 1
                    context.extensions["auxiliary_effective_session_id"] = (
                        build_auxiliary_effective_session_id(
                            root_session_id=root_session_id,
                            purpose=auxiliary_purpose,
                            operation_key=operation_key,
                            attempt_ordinal=auxiliary_attempt_ordinal,
                        )
                    )
                    context.extensions["auxiliary_root_session_id"] = root_session_id
                    context.extensions["auxiliary_purpose"] = auxiliary_purpose
                    context.extensions["auxiliary_operation_key"] = operation_key
                    context.extensions["auxiliary_attempt_ordinal"] = (
                        auxiliary_attempt_ordinal
                    )
                context.extensions["auxiliary_request"] = True
                context.extensions["auxiliary_original_backend"] = cast(
                    JsonValue, original_backend
                )
                context.extensions["auxiliary_original_model"] = cast(
                    JsonValue, original_model
                )
                context.extensions["auxiliary_backend"] = cast(
                    JsonValue, target.backend
                )
                context.extensions["auxiliary_model"] = cast(JsonValue, target.model)

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

    @staticmethod
    def _normalize_backend_family(backend_type: str) -> str:
        normalized = backend_type.strip().lower().replace("_", "-")
        if "." in normalized:
            normalized = normalized.split(".", 1)[0]
        return normalized

    @classmethod
    def _requires_non_empty_session_id(cls, backend_type: str) -> bool:
        family = cls._normalize_backend_family(backend_type)
        return family in _REQUIRES_NON_EMPTY_SESSION_ID_FAMILIES

    @classmethod
    def _build_opaque_surrogate_session_id(
        cls,
        *,
        context: RequestContext | None,
        backend_type: str,
    ) -> str:
        normalized_backend = cls._normalize_backend_family(backend_type) or "backend"
        request_id = (
            str(getattr(context, "request_id", "")).strip()
            if context is not None
            else ""
        )
        extensions = (
            getattr(context, "extensions", None) if context is not None else None
        )

        retry_attempt = 0
        auxiliary_attempt_ordinal = 1
        if isinstance(extensions, dict):
            raw_retry_attempt = extensions.get("retry_attempt")
            if isinstance(raw_retry_attempt, int):
                retry_attempt = max(0, raw_retry_attempt)
            elif isinstance(raw_retry_attempt, str) and raw_retry_attempt.strip():
                try:
                    retry_attempt = max(0, int(raw_retry_attempt.strip()))
                except ValueError:
                    retry_attempt = 0

            raw_auxiliary_attempt_ordinal = extensions.get("auxiliary_attempt_ordinal")
            if isinstance(raw_auxiliary_attempt_ordinal, int):
                auxiliary_attempt_ordinal = max(1, raw_auxiliary_attempt_ordinal)
            elif (
                isinstance(raw_auxiliary_attempt_ordinal, str)
                and raw_auxiliary_attempt_ordinal.strip()
            ):
                try:
                    auxiliary_attempt_ordinal = max(
                        1, int(raw_auxiliary_attempt_ordinal.strip())
                    )
                except ValueError:
                    auxiliary_attempt_ordinal = max(1, retry_attempt + 1)
            else:
                auxiliary_attempt_ordinal = max(1, retry_attempt + 1)

        identity = (
            getattr(context, "b2bua_identity", None) if context is not None else None
        )
        a_session_id = (
            str(getattr(identity, "a_session_id", "")).strip()
            if isinstance(identity, B2buaIdentity)
            else ""
        )
        client_session_id = (
            str(getattr(identity, "client_session_id", "")).strip()
            if isinstance(identity, B2buaIdentity)
            else ""
        )
        auth_scope_id = (
            str(getattr(identity, "auth_scope_id", "")).strip()
            if isinstance(identity, B2buaIdentity)
            else ""
        )

        seed = "|".join(
            [
                normalized_backend,
                request_id,
                str(retry_attempt),
                str(auxiliary_attempt_ordinal),
                a_session_id,
                client_session_id,
                auth_scope_id,
            ]
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
        return f"sur-{normalized_backend}-{digest}"

    def prepare_backend_kwargs(
        self,
        session_id_for_backend: str | None,
        session: ISession | None,
        context: RequestContext | None,
        backend_type: str,
    ) -> dict[str, JsonValue]:
        """Prepare kwargs for backend call."""

        backend_call_kwargs: dict[str, JsonValue] = {}

        auxiliary_session_id: str | None = None
        extensions = getattr(context, "extensions", None) if context else None
        if isinstance(extensions, dict) and bool(extensions.get("auxiliary_request")):
            raw_auxiliary_session_id = extensions.get("auxiliary_effective_session_id")
            if isinstance(raw_auxiliary_session_id, str):
                normalized_auxiliary_session_id = raw_auxiliary_session_id.strip()
                if normalized_auxiliary_session_id:
                    auxiliary_session_id = normalized_auxiliary_session_id

        backend_session_id = session_id_for_backend
        identity = getattr(context, "b2bua_identity", None) if context else None
        if auxiliary_session_id is not None:
            backend_session_id = auxiliary_session_id
        elif isinstance(identity, B2buaIdentity):
            # In B2BUA mode connector/provider correlation must use B-leg identity.
            backend_session_id = identity.b_session_id
        if (
            backend_session_id is None
            and isinstance(identity, B2buaIdentity)
            and self._requires_non_empty_session_id(backend_type)
        ):
            backend_session_id = self._build_opaque_surrogate_session_id(
                context=context,
                backend_type=backend_type,
            )
        if backend_session_id:
            backend_call_kwargs["session_id"] = backend_session_id

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

        if context is not None:
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
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to extract headers from context: %s",
                        e,
                        exc_info=True,
                    )
            except Exception as e:
                logger.warning(
                    "Unexpected error extracting headers from context: %s",
                    e,
                    exc_info=True,
                )

        return backend_call_kwargs
