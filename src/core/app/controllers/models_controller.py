"""
Models Controller

Handles model-related endpoints for the application.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Response

# Import HTTP status constants
from src.core.common.exceptions import (
    ServiceResolutionError,
)
from src.core.constants import HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
from src.core.domain.model_capabilities import ModelCapability
from src.core.domain.models_listing import ModelInfo, ModelsListingResponse
from src.core.interfaces.backend_service_interface import IBackendService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


class ModelsController:
    """Controller for model-related endpoints."""

    def __init__(
        self,
        backend_service: IBackendService,
        routing_service: Any | None = None,
    ) -> None:
        """Initialize the models controller.

        Args:
            backend_service: The backend service to use
            routing_service: Optional backend routing service provided via DI
        """
        self.backend_service = backend_service
        self._routing_service = routing_service

    async def list_models(
        self,
        response: Response | None = None,
    ) -> ModelsListingResponse:
        """List all available models using shared discovery logic."""
        routing_service = self._routing_service or get_backend_routing_service()

        result, headers = await _list_models_impl(
            backend_service=self.backend_service,
            routing_service=routing_service,
        )
        if response is not None:
            for k, v in headers.items():
                response.headers[k] = v
        return result


async def get_backend_service() -> IBackendService:
    """Get the backend service from the DI container.

    Returns:
        The backend service

    Raises:
        HTTPException: If the service provider is not available
    """
    try:
        from src.core.di.services import get_service_provider

        service_provider = get_service_provider()
        service = service_provider.get_required_service(IBackendService)  # type: ignore[type-abstract]
        return service  # type: ignore[no-any-return]
    except (KeyError, ServiceResolutionError, ImportError) as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Global service provider unavailable: %s; trying request context",
                e,
                exc_info=True,
            )
        # Try to get from current request context (for FastAPI dependency injection)
        try:
            from starlette.context import _request_context  # type: ignore[import]

            if _request_context.exists():
                connection = _request_context.get()
                if hasattr(connection, "app") and hasattr(
                    connection.app.state, "service_provider"
                ):
                    service = connection.app.state.service_provider.get_required_service(IBackendService)  # type: ignore[type-abstract]
                    return service  # type: ignore[no-any-return]
        except Exception as ctx_err:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Request-context provider lookup failed: %s", ctx_err, exc_info=True
                )

        raise HTTPException(
            status_code=503, detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
        )


def get_backend_routing_service() -> Any:
    """Get required backend routing service from the DI container."""
    try:
        from src.core.di.services import get_service_provider
        from src.core.services.backend_routing_service import BackendRoutingService

        service_provider = get_service_provider()
        routing_service = service_provider.get_service(BackendRoutingService)
        if routing_service is None:
            raise ServiceResolutionError("BackendRoutingService not registered")
        return routing_service
    except (KeyError, ServiceResolutionError, ImportError):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "BackendRoutingService not available from service provider",
                exc_info=True,
            )
        raise HTTPException(
            status_code=503,
            detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
        ) from None


def _infer_modalities_from_capabilities(
    capabilities: Any | None,
) -> tuple[list[str], list[str]]:
    """Infer input/output modalities for /models payload.

    This is a best-effort hint for clients. It does not enforce validation.
    """

    output_modalities = ["text"]
    if capabilities is None:
        return ["text"], output_modalities

    caps_list = getattr(capabilities, "capabilities", None)
    if isinstance(caps_list, list) and ModelCapability.VISION in caps_list:
        return ["text", "image"], output_modalities

    return ["text"], output_modalities


def _resolve_model_capabilities(model_id: str) -> Any | None:
    from src.core.domain.model_capabilities import KNOWN_MODEL_CAPABILITIES

    candidates = [model_id]
    if ":" in model_id:
        candidates.append(model_id.split(":", 1)[-1])
    if "/" in model_id:
        _, tail = model_id.split("/", 1)
        if tail:
            candidates.append(tail)
    for prefix in ("google/", "openai/", "anthropic/", "kimi/"):
        candidates.append(f"{prefix}{model_id}")

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        capabilities = KNOWN_MODEL_CAPABILITIES.get(candidate)
        if capabilities is not None:
            return capabilities
    return None


def _build_model_info(
    *,
    model_id: str,
    owned_by: str | None = None,
    canonical_id: str | None = None,
) -> ModelInfo:
    capabilities = _resolve_model_capabilities(model_id)
    context_window = None
    if capabilities and capabilities.limits:
        context_window = capabilities.limits.context_window

    input_modalities, output_modalities = _infer_modalities_from_capabilities(
        capabilities
    )
    extra_fields: dict[str, Any] = {
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
    }
    if capabilities is not None and getattr(capabilities, "capabilities", None):
        extra_fields["capabilities"] = [cap.value for cap in capabilities.capabilities]
    if canonical_id is not None:
        extra_fields["canonical_id"] = canonical_id

    resolved_owner = owned_by
    if resolved_owner is None:
        if "/" in model_id:
            resolved_owner = model_id.split("/", 1)[0]
        elif capabilities is not None:
            resolved_owner = getattr(capabilities, "backend_type", "unknown")
        else:
            resolved_owner = "unknown"

    return ModelInfo(
        id=model_id,
        object="model",
        owned_by=str(resolved_owner).lower() if resolved_owner else None,
        context_window=context_window,
        **extra_fields,
    )


def _canonicalize_model_id(
    canonical_model: str, snapshot: Mapping[str, tuple[str, ...]]
) -> str:
    if "/" in canonical_model:
        return canonical_model
    instances = snapshot.get(canonical_model, ())
    families = sorted({instance.split(".", 1)[0] for instance in instances if instance})
    if len(families) == 1:
        return f"{families[0]}/{canonical_model}"
    return canonical_model


def _build_models_from_capability_snapshot(
    *,
    snapshot: Any,
) -> list[ModelInfo]:
    canonical_values = sorted(set(snapshot.alias_to_canonical.values()))
    models: list[ModelInfo] = []
    seen: set[str] = set()

    for canonical_model in canonical_values:
        canonical_display = _canonicalize_model_id(
            canonical_model, snapshot.model_to_instances
        )
        instances = snapshot.model_to_instances.get(canonical_model, ())
        cursor_instances = [
            instance
            for instance in instances
            if instance.split(".", 1)[0] == "cursor-cli-acp"
        ]
        if cursor_instances:
            for instance_name in cursor_instances:
                exact_route = f"{instance_name}:{canonical_display}"
                if exact_route not in seen:
                    seen.add(exact_route)
                    models.append(
                        _build_model_info(
                            model_id=exact_route,
                            owned_by=instance_name,
                            canonical_id=canonical_display,
                        )
                    )
            non_cursor_instances = [
                instance for instance in instances if instance not in cursor_instances
            ]
            if not non_cursor_instances:
                continue
        if canonical_display not in seen:
            seen.add(canonical_display)
            models.append(_build_model_info(model_id=canonical_display))

    models.sort(key=lambda item: item.id)
    return models


def _collect_quota_headers_from_active_backends(
    backend_service: IBackendService,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    try:
        active_backends = backend_service.get_active_backends()
    except Exception:
        return headers

    for backend in active_backends.values():
        backend_headers = getattr(backend, "last_quota_headers", None)
        if isinstance(backend_headers, dict):
            headers.update(
                {str(k): str(v) for k, v in backend_headers.items() if v is not None}
            )
    return headers


async def _build_models_from_active_cursor_backends(
    backend_service: IBackendService,
    *,
    active_backends: Mapping[str, Any] | None = None,
) -> list[ModelInfo]:
    """Refresh exact Cursor routes from the connector's live ACP capability path."""
    if active_backends is None:
        try:
            active_backends = backend_service.get_active_backends()
        except Exception:
            return []

    models: list[ModelInfo] = []
    seen: set[str] = set()
    for instance_name, backend in active_backends.items():
        if instance_name.split(".", 1)[0] != "cursor-cli-acp":
            continue
        discover = getattr(backend, "get_available_models_async", None)
        if not callable(discover):
            continue
        try:
            discover_async = cast(Callable[[], Awaitable[object]], discover)
            available_models = await discover_async()
        except Exception:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Cursor ACP model discovery failed for %s",
                    instance_name,
                    exc_info=True,
                )
            continue
        if not isinstance(available_models, list):
            continue
        for model_id in available_models:
            if not isinstance(model_id, str) or not model_id.startswith("cursor/"):
                continue
            exact_route = f"{instance_name}:{model_id}"
            if exact_route in seen:
                continue
            seen.add(exact_route)
            models.append(
                _build_model_info(
                    model_id=exact_route,
                    owned_by=instance_name,
                    canonical_id=model_id,
                )
            )

    models.sort(key=lambda item: item.id)
    return models


def _cursor_snapshot_route_ids_for_active_instances(
    *, snapshot: Any, active_backends: Mapping[str, Any]
) -> set[str]:
    """Return snapshot Cursor routes owned by currently active instances.

    Live ACP discovery is authoritative for an active Cursor connector.  The
    capability snapshot can lag behind a failed or changed discovery refresh,
    so those routes must be removed before live routes are merged back in.
    """
    active_cursor_instances = {
        instance_name
        for instance_name in active_backends
        if instance_name.split(".", 1)[0] == "cursor-cli-acp"
    }
    if not active_cursor_instances:
        return set()

    route_ids: set[str] = set()
    for canonical_model, instances in snapshot.model_to_instances.items():
        if not any(instance in active_cursor_instances for instance in instances):
            continue
        canonical_display = _canonicalize_model_id(
            canonical_model, snapshot.model_to_instances
        )
        for instance_name in instances:
            if instance_name in active_cursor_instances:
                route_ids.add(f"{instance_name}:{canonical_display}")
    return route_ids


def _merge_global_quota_headers(current_headers: dict[str, str]) -> dict[str, str]:
    from src.core.services.quota_status_service import get_quota_status_service

    service = get_quota_status_service()
    final_headers = service.get_quota_headers()
    final_headers.update(current_headers)
    return final_headers


async def _list_models_impl(
    *,
    backend_service: IBackendService,
    routing_service: Any,
) -> tuple[ModelsListingResponse, dict[str, str]]:
    """Shared implementation for canonical capability-index model listing."""

    try:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Listing available models")

        get_snapshot = getattr(routing_service, "get_model_capability_snapshot", None)
        if not callable(get_snapshot):
            raise ServiceResolutionError(
                "BackendRoutingService missing get_model_capability_snapshot"
            )

        snapshot = get_snapshot()
        if snapshot is None:
            all_models: list[ModelInfo] = []
        else:
            all_models = _build_models_from_capability_snapshot(snapshot=snapshot)

        try:
            active_backends = backend_service.get_active_backends()
        except Exception:
            active_backends = {}

        if snapshot is not None:
            stale_cursor_route_ids = _cursor_snapshot_route_ids_for_active_instances(
                snapshot=snapshot,
                active_backends=active_backends,
            )
            if stale_cursor_route_ids:
                all_models = [
                    model
                    for model in all_models
                    if model.id not in stale_cursor_route_ids
                ]

        live_cursor_models = await _build_models_from_active_cursor_backends(
            backend_service,
            active_backends=active_backends,
        )
        models_by_id = {model.id: model for model in all_models}
        models_by_id.update({model.id: model for model in live_cursor_models})
        all_models = sorted(models_by_id.values(), key=lambda item: item.id)

        all_quota_headers = _collect_quota_headers_from_active_backends(backend_service)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Returning %d canonical models from capability index", len(all_models)
            )
        return ModelsListingResponse(
            object="list", data=all_models
        ), _merge_global_quota_headers(all_quota_headers)

    except ServiceResolutionError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Model listing unavailable: %s", e, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
        ) from e
    except Exception as e:  # type: ignore[misc]
        if logger.isEnabledFor(logging.ERROR):
            logger.error("Error listing models: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/models")
async def list_models(
    response: Response,
    backend_service: IBackendService = Depends(get_backend_service),
    routing_service: Any = Depends(get_backend_routing_service),
) -> ModelsListingResponse:
    """List available models from all configured backends."""

    result, headers = await _list_models_impl(
        backend_service=backend_service,
        routing_service=routing_service,
    )
    for k, v in headers.items():
        response.headers[k] = v
    return result
