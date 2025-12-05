from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.core.app.controllers.models_controller import get_backend_service
from src.core.interfaces.backend_service import IBackendService

router = APIRouter()


class ModelInfo(BaseModel):
    name: str


class BackendInstanceInfo(BaseModel):
    name: str
    connector_type: str
    is_rate_limited: bool
    retry_after_seconds: float | None = None
    is_functional: bool
    validation_errors: list[str]
    models: list[ModelInfo]


class DiagnosticResponse(BaseModel):
    timestamp: float
    instances: list[BackendInstanceInfo]


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
    """Get diagnostic information about backend instances and their state."""
    active_backends = backend_service.get_active_backends()
    instances = []

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

        instances.append(
            BackendInstanceInfo(
                name=name,
                connector_type=connector_type,
                is_rate_limited=backend.is_rate_limited(),
                retry_after_seconds=backend.get_retry_after_remaining(),
                is_functional=is_functional,
                validation_errors=validation_errors,
                models=models,
            )
        )

    return DiagnosticResponse(timestamp=time.time(), instances=instances)
