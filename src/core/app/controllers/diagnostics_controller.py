from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.core.app.controllers.models_controller import get_backend_service
from src.core.interfaces.backend_service import IBackendService

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
    except Exception:
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
    except Exception:
        return None


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
    is_rate_limited: bool
    retry_after_seconds: float | None = None
    is_functional: bool
    validation_errors: list[str]
    models: list[ModelInfo]
    activity: ActivityInfo | None = None


class GlobalActivityInfo(BaseModel):
    """Global activity summary across all backends."""

    enabled: bool = True
    total_active_connections: int
    total_bytes_rx: int
    total_bytes_tx: int


class DiagnosticResponse(BaseModel):
    """Response from the diagnostics endpoint."""

    timestamp: float
    instances: list[BackendInstanceInfo]
    global_activity: GlobalActivityInfo | None = None
    activity_tracking_enabled: bool = False


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
    instances = []

    # Check if activity tracking is enabled and get tracker
    activity_tracker = _get_activity_tracker_if_enabled()
    activity_tracking_enabled = activity_tracker is not None
    global_snapshot = None

    if activity_tracker is not None:
        try:
            global_snapshot = activity_tracker.get_global_snapshot()
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to get activity tracker snapshot", exc_info=True)

    for name, backend in active_backends.items():
        # Derive connector type from instance name (e.g., "openai.1" -> "openai")
        connector_type = name.split(".")[0] if "." in name else name

        # Get available models
        models = []
        try:
            available = backend.get_available_models()
            models = [ModelInfo(name=m) for m in available]
        except Exception:
            # If listing models fails, return empty list but still show backend status
            pass

        # Check functional status
        is_functional = True
        validation_errors = []
        if hasattr(backend, "is_backend_functional"):
            is_functional = backend.is_backend_functional()
        if hasattr(backend, "get_validation_errors"):
            validation_errors = backend.get_validation_errors()

        # Get activity info for this backend (only if tracking is enabled)
        activity_info = None
        if activity_tracker is not None:
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
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to get activity for backend %s", name, exc_info=True
                    )

        instances.append(
            BackendInstanceInfo(
                name=name,
                connector_type=connector_type,
                is_rate_limited=backend.is_rate_limited(),
                retry_after_seconds=backend.get_retry_after_remaining(),
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
        instances=instances,
        global_activity=global_activity,
        activity_tracking_enabled=activity_tracking_enabled,
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
    except Exception:
        logger.warning("Failed to get activity snapshot", exc_info=True)
        return GlobalActivityInfo(
            enabled=True,  # Tracking is enabled but errored
            total_active_connections=0,
            total_bytes_rx=0,
            total_bytes_tx=0,
        )
