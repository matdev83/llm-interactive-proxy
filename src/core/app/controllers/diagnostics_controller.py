from __future__ import annotations

import logging
import os
import time
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.core.app.controllers.models_controller import get_backend_service
from src.core.common.exceptions import ServiceResolutionError
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.resilience_interface import IResilienceCoordinator

logger = logging.getLogger(__name__)

router = APIRouter()


def _is_activity_tracking_enabled() -> bool:
    """Check if activity tracking is enabled in the DI container."""
    try:
        from src.core.di.services import get_or_build_service_provider
        from src.core.services.connection_activity_tracker import (
            ConnectionActivityTracker,
        )

        provider = get_or_build_service_provider()
        tracker = provider.get_service(ConnectionActivityTracker)
        return tracker is not None
    except (ImportError, ModuleNotFoundError, ServiceResolutionError) as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Activity tracking not available: %s", e, exc_info=True)
        return False


def _get_activity_tracker_if_enabled():
    """Get the activity tracker if activity tracking is enabled.

    Returns:
        ConnectionActivityTracker instance or None if tracking is disabled.
    """
    try:
        from src.core.di.services import get_or_build_service_provider
        from src.core.services.connection_activity_tracker import (
            ConnectionActivityTracker,
        )

        provider = get_or_build_service_provider()
        return provider.get_service(ConnectionActivityTracker)
    except (ImportError, ModuleNotFoundError, ServiceResolutionError) as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Activity tracker not available: %s", e, exc_info=True)
        return None


def _get_backend_routing_service_if_available() -> Any | None:
    """Get backend routing service if available in DI."""
    try:
        from src.core.di.services import get_or_build_service_provider
        from src.core.services.backend_routing_service import BackendRoutingService

        provider = get_or_build_service_provider()
        return provider.get_service(BackendRoutingService)
    except (ImportError, ModuleNotFoundError, ServiceResolutionError):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Backend routing service not available", exc_info=True)
        return None


def _get_backend_lifecycle_manager_if_available() -> IBackendLifecycleManager | None:
    """Get backend lifecycle manager if available in DI."""
    try:
        from src.core.di.services import get_or_build_service_provider

        provider = get_or_build_service_provider()
        manager = provider.get_service(cast(type, IBackendLifecycleManager))
        if manager is None:
            return None
        return cast(IBackendLifecycleManager, manager)
    except (ImportError, ModuleNotFoundError, ServiceResolutionError):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Backend lifecycle manager not available", exc_info=True)
        return None


def _get_resilience_coordinator_if_available() -> IResilienceCoordinator | None:
    """Get resilience coordinator if available in DI."""
    try:
        from src.core.di.services import get_or_build_service_provider
        from src.core.services.resilience.coordinator import ResilienceCoordinator

        provider = get_or_build_service_provider()
        coordinator = provider.get_service(ResilienceCoordinator)
        if coordinator is None:
            return None
        return cast(IResilienceCoordinator, coordinator)
    except (ImportError, ModuleNotFoundError, ServiceResolutionError):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Resilience coordinator not available", exc_info=True)
        return None


def _get_backend_reactivation_control_if_available():
    """Get backend reactivation control service if available in DI."""
    try:
        from src.core.di.services import get_or_build_service_provider
        from src.core.services.backend_reactivation_control import (
            BackendReactivationControl,
        )

        provider = get_or_build_service_provider()
        return provider.get_service(BackendReactivationControl)
    except (ImportError, ModuleNotFoundError, ServiceResolutionError):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Backend reactivation control not available", exc_info=True)
        return None


def _get_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


class ModelInfo(BaseModel):
    """Information about a model available on a backend."""

    name: str


class ConnectionInfo(BaseModel):
    """Information about an active connection."""

    session_id: str
    connection_type: str
    started_at: float
    duration_seconds: float
    model: str | None = None
    bytes_rx: int
    bytes_tx: int


class ActivityInfo(BaseModel):
    """Activity information for a backend instance."""

    active_connections: int
    connections: list[ConnectionInfo]
    total_bytes_rx: int
    total_bytes_tx: int


class BackendInstanceInfo(BaseModel):
    """Diagnostic information about a backend instance."""

    name: str
    connector_type: str
    availability_status: str = "active"
    cooldown_remaining_seconds: float | None = None
    is_rate_limited: bool
    retry_after_seconds: float | None = None
    is_functional: bool
    validation_errors: list[str]
    models: list[ModelInfo]
    activity: ActivityInfo | None = None
    proxy_routing_scope: str = "proxy_instance_model_selection"
    connector_scheduling_scope: str = "connector_internal_and_opaque"


class GlobalActivityInfo(BaseModel):
    """Global activity summary across all backends."""

    enabled: bool = True
    total_active_connections: int
    total_bytes_rx: int
    total_bytes_tx: int


class RoutingEligibilityTruncationInfo(BaseModel):
    """Boundedness metadata for routing eligibility diagnostics."""

    model_limit: int
    instances_per_model_limit: int
    models_truncated: bool
    models_omitted: int


class ModelEligibilityInfo(BaseModel):
    """Model routing eligibility summary."""

    model: str
    eligible_instances: list[str]
    eligible_instance_count: int
    instances_truncated: bool
    instances_omitted: int
    applied_preference_policy: str
    equivalent_score_tie_sets: list[list[str]]


class RoutingEligibilityInfo(BaseModel):
    """Routing diagnostics metadata separated from connector internals."""

    default_preference_policy: str
    proxy_selection_scope: str
    connector_scheduling_scope: str
    truncation: RoutingEligibilityTruncationInfo
    model_eligibility: list[ModelEligibilityInfo]


class DiagnosticResponse(BaseModel):
    """Response from the diagnostics endpoint."""

    timestamp: float
    instances: list[BackendInstanceInfo]
    routing: RoutingEligibilityInfo | None = None
    global_activity: GlobalActivityInfo | None = None
    activity_tracking_enabled: bool = False


class ReactivationRequest(BaseModel):
    """Request payload for explicit backend reactivation."""

    clear_unsupported: bool = False


class ReactivationResponse(BaseModel):
    """Response payload for explicit backend reactivation."""

    backend_instance: str
    reactivated: bool
    lifecycle_reactivated: bool
    resilience_reactivated: bool
    unsupported_pairs_cleared: int


async def verify_local_access(request: Request) -> None:
    """Ensure the request originates from localhost."""
    client = request.client
    if not client or client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=403,
            detail="Diagnostic endpoint is restricted to local access only",
        )


@router.get(
    "/v1/diagnostics",
    response_model=DiagnosticResponse,
    dependencies=[Depends(verify_local_access)],
)
async def get_diagnostics(
    backend_service: IBackendService = Depends(get_backend_service),
) -> DiagnosticResponse:
    """Get diagnostic information about backend instances and their state.

    This endpoint provides real-time visibility into:
    - Backend instance status (functional, rate-limited, validation errors)
    - Available models per backend
    - Active connection activity with RX/TX byte counters per session
      (only when activity tracking is enabled via --enable-activity-tracking)
    """
    active_backends = backend_service.get_active_backends()
    instances: list[BackendInstanceInfo] = []

    # Check if activity tracking is enabled and get tracker
    activity_tracker = _get_activity_tracker_if_enabled()
    activity_tracking_enabled = activity_tracker is not None
    global_snapshot = None

    if activity_tracker is not None:
        try:
            global_snapshot = activity_tracker.get_global_snapshot()
        except (AttributeError, RuntimeError) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to get activity tracker snapshot: %s", e, exc_info=True
                )

    routing_service = _get_backend_routing_service_if_available()
    lifecycle_manager = _get_backend_lifecycle_manager_if_available()
    resilience = _get_resilience_coordinator_if_available()

    disabled_backends: dict[str, Any] = {}
    if lifecycle_manager is not None:
        try:
            disabled_backends = lifecycle_manager.get_disabled_backends()
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to load disabled backends", exc_info=True)

    instance_states: dict[str, dict[str, Any]] = {}
    if resilience is not None:
        state_manager = getattr(resilience, "state_manager", None)
        if state_manager is not None:
            try:
                raw_states = state_manager.get_all_instance_states()
                if isinstance(raw_states, dict):
                    instance_states = raw_states
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Failed to load resilience state", exc_info=True)

    routing: RoutingEligibilityInfo | None = None
    if routing_service is not None:
        builder = getattr(routing_service, "build_model_eligibility_diagnostics", None)
        if callable(builder):
            model_limit = _get_positive_int_env(
                "LLM_PROXY_DIAGNOSTICS_MODEL_LIMIT", 200
            )
            instances_limit = _get_positive_int_env(
                "LLM_PROXY_DIAGNOSTICS_INSTANCES_PER_MODEL_LIMIT", 20
            )
            try:
                routing_data = builder(
                    model_limit=model_limit,
                    instances_per_model_limit=instances_limit,
                )
                if isinstance(routing_data, dict):
                    routing = RoutingEligibilityInfo(**routing_data)
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to build model eligibility diagnostics", exc_info=True
                    )

    known_instance_names = sorted(
        set(active_backends.keys())
        | set(disabled_backends.keys())
        | set(instance_states.keys())
    )

    for name in known_instance_names:
        backend = active_backends.get(name)
        connector_type = name.split(".")[0] if "." in name else name

        # Get available models for active instances.
        models: list[ModelInfo] = []
        if backend is not None:
            try:
                available = backend.get_available_models()
                models = [ModelInfo(name=m) for m in available]
            except (AttributeError, NotImplementedError, RuntimeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to get models for backend %s: %s",
                        name,
                        e,
                        exc_info=True,
                    )

        # Resolve validation + functional status.
        is_functional = backend is not None
        validation_errors: list[str] = []
        if backend is not None and hasattr(backend, "is_backend_functional"):
            is_functional = backend.is_backend_functional()
        if backend is not None and hasattr(backend, "get_validation_errors"):
            validation_errors = list(backend.get_validation_errors())

        state = instance_states.get(name, {})
        availability_status = str(state.get("status", "active"))
        cooldown_remaining = state.get("cooldown_remaining")

        disabled_info = disabled_backends.get(name)
        if disabled_info is not None:
            availability_status = "disabled"
            is_functional = False
            reason = getattr(disabled_info, "reason", None)
            if isinstance(reason, str) and reason and reason not in validation_errors:
                validation_errors.append(reason)

        # Retain backward-compatible fields while reflecting resilience state.
        is_rate_limited = availability_status == "rate_limited"
        retry_after_seconds = (
            float(cooldown_remaining) if cooldown_remaining is not None else None
        )
        if backend is not None:
            try:
                backend_rate_limited = bool(backend.is_rate_limited())
                backend_retry_after = backend.get_retry_after_remaining()
                if backend_rate_limited:
                    is_rate_limited = True
                    availability_status = "rate_limited"
                if backend_retry_after is not None:
                    retry_after_seconds = backend_retry_after
            except (AttributeError, RuntimeError):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to read rate-limit status for backend %s",
                        name,
                        exc_info=True,
                    )

        if (
            cooldown_remaining is None
            and retry_after_seconds is not None
            and availability_status == "rate_limited"
        ):
            cooldown_remaining = retry_after_seconds

        # Get activity info for this backend (only if tracking is enabled)
        activity_info = None
        if activity_tracker is not None and backend is not None:
            try:
                backend_activity = activity_tracker.get_backend_snapshot(name)
                connections = [
                    ConnectionInfo(
                        session_id=conn.session_id,
                        connection_type=conn.connection_type.value,
                        started_at=conn.started_at,
                        duration_seconds=round(conn.duration_seconds, 3),
                        model=conn.model,
                        bytes_rx=conn.bytes_rx,
                        bytes_tx=conn.bytes_tx,
                    )
                    for conn in backend_activity.connections
                ]
                activity_info = ActivityInfo(
                    active_connections=backend_activity.active_connections,
                    connections=connections,
                    total_bytes_rx=backend_activity.total_bytes_rx,
                    total_bytes_tx=backend_activity.total_bytes_tx,
                )
            except (AttributeError, RuntimeError, KeyError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to get activity for backend %s: %s",
                        name,
                        e,
                        exc_info=True,
                    )

        instances.append(
            BackendInstanceInfo(
                name=name,
                connector_type=connector_type,
                availability_status=availability_status,
                cooldown_remaining_seconds=(
                    float(cooldown_remaining)
                    if cooldown_remaining is not None
                    else None
                ),
                is_rate_limited=is_rate_limited,
                retry_after_seconds=retry_after_seconds,
                is_functional=is_functional,
                validation_errors=validation_errors,
                models=models,
                activity=activity_info,
            )
        )

    # Build global activity info
    global_activity = None
    if global_snapshot is not None:
        global_activity = GlobalActivityInfo(
            enabled=True,
            total_active_connections=global_snapshot.total_active_connections,
            total_bytes_rx=global_snapshot.total_bytes_rx,
            total_bytes_tx=global_snapshot.total_bytes_tx,
        )

    return DiagnosticResponse(
        timestamp=time.time(),
        instances=sorted(instances, key=lambda item: item.name),
        routing=routing,
        global_activity=global_activity,
        activity_tracking_enabled=activity_tracking_enabled,
    )


@router.post(
    "/v1/diagnostics/backends/{backend_instance}/reactivate",
    response_model=ReactivationResponse,
    dependencies=[Depends(verify_local_access)],
)
async def reactivate_backend_instance(
    backend_instance: str,
    payload: ReactivationRequest | None = None,
) -> ReactivationResponse:
    """Explicitly reactivate a disabled backend instance."""
    control = _get_backend_reactivation_control_if_available()
    if control is None:
        raise HTTPException(status_code=503, detail="Reactivation service unavailable")

    clear_unsupported = bool(payload.clear_unsupported) if payload else False
    try:
        result = control.reactivate_backend_instance(
            backend_instance,
            clear_unsupported=clear_unsupported,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ReactivationResponse(
        backend_instance=result.backend_instance,
        reactivated=result.reactivated,
        lifecycle_reactivated=result.lifecycle_reactivated,
        resilience_reactivated=result.resilience_reactivated,
        unsupported_pairs_cleared=result.unsupported_pairs_cleared,
    )


@router.get(
    "/v1/diagnostics/activity",
    response_model=GlobalActivityInfo,
    dependencies=[Depends(verify_local_access)],
)
async def get_activity() -> GlobalActivityInfo:
    """Get current connection activity across all backends.

    This lightweight endpoint returns only the activity counters
    without backend status information.

    Note: Activity tracking must be enabled via --enable-activity-tracking
    for this endpoint to return meaningful data.
    """
    activity_tracker = _get_activity_tracker_if_enabled()

    if activity_tracker is None:
        # Activity tracking is disabled
        return GlobalActivityInfo(
            enabled=False,
            total_active_connections=0,
            total_bytes_rx=0,
            total_bytes_tx=0,
        )

    try:
        snapshot = activity_tracker.get_global_snapshot()
        return GlobalActivityInfo(
            enabled=True,
            total_active_connections=snapshot.total_active_connections,
            total_bytes_rx=snapshot.total_bytes_rx,
            total_bytes_tx=snapshot.total_bytes_tx,
        )
    except (AttributeError, RuntimeError) as e:
        logger.warning("Failed to get activity snapshot: %s", str(e), exc_info=True)
        return GlobalActivityInfo(
            enabled=True,  # Tracking is enabled but errored
            total_active_connections=0,
            total_bytes_rx=0,
            total_bytes_tx=0,
        )
    except Exception as e:
        logger.warning(
            "Failed to get activity snapshot unexpectedly: %s", str(e), exc_info=True
        )
        return GlobalActivityInfo(
            enabled=True,  # Tracking is enabled but errored
            total_active_connections=0,
            total_bytes_rx=0,
            total_bytes_tx=0,
        )
