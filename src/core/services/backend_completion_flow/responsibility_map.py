"""Responsibility map for backend completion flow orchestration subsystem.

This module provides a machine-verifiable mapping of responsibilities to collaborators
to reduce future refactor churn and enforce architectural boundaries.

The responsibility map defines:
- What each collaborator owns (its responsibilities)
- What each collaborator depends on (its dependencies)
- What behaviors belong to which collaborator (to prevent drift)

This map is used by tests to validate that responsibilities remain stable and
that new code is added to the correct collaborator rather than leaking into others.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Responsibility categories for classification
RESPONSIBILITY_CATEGORIES = {
    "availability": "Backend/model availability checks and gating",
    "session": "Session resolution and per-session backend selection",
    "request_prep": "Request preparation, config application, and synchronization",
    "backend_invocation": "Backend instance acquisition and lifecycle",
    "wire_capture": "Wire capture orchestration (outbound/inbound/errors)",
    "usage_accounting": "Usage tracking, response wrapping, and accounting",
    "failure_recovery": "Failure handling, retry, and failover execution",
    "orchestration": "Flow coordination and ordering",
}


@dataclass(frozen=True)
class CollaboratorResponsibility:
    """Defines a single responsibility owned by a collaborator."""

    collaborator_name: str
    responsibility: str
    category: str
    description: str
    interface_methods: list[str]
    dependencies: list[str]


# Machine-verifiable responsibility map
RESPONSIBILITY_MAP: dict[str, CollaboratorResponsibility] = {
    # Availability gating
    "availability_check": CollaboratorResponsibility(
        collaborator_name="BackendAvailabilityChecker",
        responsibility="Check backend/model availability",
        category="availability",
        description=(
            "Applies disabled-backend checks and resilience availability gates. "
            "Raises domain errors when backend/model is unavailable."
        ),
        interface_methods=["check_backend_availability"],
        dependencies=["IBackendLifecycleManager", "IResilienceCoordinator"],
    ),
    # Session resolution
    "session_resolution": CollaboratorResponsibility(
        collaborator_name="CompletionSessionResolver",
        responsibility="Resolve session and session ID",
        category="session",
        description=(
            "Resolves session from context or request. Returns session object "
            "and session_id_for_backend for backend calls."
        ),
        interface_methods=["resolve_session"],
        dependencies=["ISessionService"],
    ),
    # Request preparation
    "target_resolution": CollaboratorResponsibility(
        collaborator_name="BackendRequestPreparer",
        responsibility="Resolve target backend/model",
        category="request_prep",
        description=(
            "Resolves target backend and model using BackendModelResolver. "
            "Returns backend_type, effective_model, and URI parameters."
        ),
        interface_methods=["prepare_request"],
        dependencies=["IBackendModelResolver"],
    ),
    "request_synchronization": CollaboratorResponsibility(
        collaborator_name="BackendRequestPreparer",
        responsibility="Synchronize request with target",
        category="request_prep",
        description=(
            "Synchronizes ChatRequest with resolved target (backend/model). "
            "Updates request model and extra_body as needed."
        ),
        interface_methods=["synchronize_request_with_target"],
        dependencies=["IBackendModelResolver"],
    ),
    "backend_request_prep": CollaboratorResponsibility(
        collaborator_name="BackendRequestPreparer",
        responsibility="Prepare backend request",
        category="request_prep",
        description=(
            "Applies config, reasoning config, and URI parameters to prepare "
            "the domain request for backend invocation."
        ),
        interface_methods=["prepare_backend_request"],
        dependencies=[
            "IBackendConfigProvider",
            "IReasoningConfigApplicator",
            "IURIParameterApplicator",
        ],
    ),
    "backend_kwargs_prep": CollaboratorResponsibility(
        collaborator_name="BackendRequestPreparer",
        responsibility="Prepare backend call kwargs",
        category="request_prep",
        description=(
            "Builds keyword arguments for backend.chat_completions() call "
            "including session_id, project, project_dir from session."
        ),
        interface_methods=["prepare_backend_kwargs"],
        dependencies=[],
    ),
    # Backend invocation
    "backend_acquisition": CollaboratorResponsibility(
        collaborator_name="BackendManager",
        responsibility="Acquire backend instance",
        category="backend_invocation",
        description=(
            "Acquires backend instance from lifecycle manager. Handles "
            "backend creation, initialization, and lifecycle management."
        ),
        interface_methods=["acquire_backend"],
        dependencies=["IBackendLifecycleManager"],
    ),
    # Wire capture
    "wire_capture_context": CollaboratorResponsibility(
        collaborator_name="WireCaptureOrchestrator",
        responsibility="Prepare wire capture context",
        category="wire_capture",
        description=(
            "Prepares identity and backend config for wire capture. "
            "Returns identity object for backend calls."
        ),
        interface_methods=["prepare_wire_capture_context"],
        dependencies=["IWireCapture", "IBackendConfigProvider"],
    ),
    "wire_capture_outbound": CollaboratorResponsibility(
        collaborator_name="WireCaptureOrchestrator",
        responsibility="Capture outbound request",
        category="wire_capture",
        description=(
            "Captures outbound request payload before backend call. "
            "Best-effort behavior, errors are suppressed."
        ),
        interface_methods=["capture_wire_outbound"],
        dependencies=["IWireCapture"],
    ),
    "wire_capture_inbound": CollaboratorResponsibility(
        collaborator_name="WireCaptureOrchestrator",
        responsibility="Capture inbound response",
        category="wire_capture",
        description=(
            "Captures inbound response or error payload after backend call. "
            "Best-effort behavior, errors are suppressed."
        ),
        interface_methods=["capture_inbound_response"],
        dependencies=["IWireCapture"],
    ),
    "wire_capture_stream": CollaboratorResponsibility(
        collaborator_name="WireCaptureOrchestrator",
        responsibility="Wrap inbound stream for capture",
        category="wire_capture",
        description=(
            "Wraps streaming response for wire capture. Adapts domain stream "
            "to bytes and injects capture logic."
        ),
        interface_methods=["wrap_inbound_stream", "detect_key_name"],
        dependencies=["IWireCapture"],
    ),
    # Usage accounting
    "usage_calculation": CollaboratorResponsibility(
        collaborator_name="UsageAccountingOrchestrator",
        responsibility="Calculate and record usage",
        category="usage_accounting",
        description=(
            "Calculates outbound tokens and records usage before backend call. "
            "Returns outbound_tokens and record IDs for tracking."
        ),
        interface_methods=["calculate_and_record_usage"],
        dependencies=["IUsageTrackingService", "IUsageTrackingWrapper"],
    ),
    "usage_response_wrapping": CollaboratorResponsibility(
        collaborator_name="UsageAccountingOrchestrator",
        responsibility="Wrap response for usage tracking",
        category="usage_accounting",
        description=(
            "Wraps response envelope with usage tracking wrapper. "
            "Prepares response for usage accounting."
        ),
        interface_methods=["wrap_response_for_usage"],
        dependencies=["IUsageTrackingWrapper"],
    ),
    "usage_streaming_handling": CollaboratorResponsibility(
        collaborator_name="UsageAccountingOrchestrator",
        responsibility="Handle streaming response usage",
        category="usage_accounting",
        description=(
            "Handles usage tracking for streaming responses. Manages "
            "stream session ID resolution and usage recording."
        ),
        interface_methods=["handle_streaming_response"],
        dependencies=[
            "IUsageTrackingWrapper",
            "IStreamSessionIdResolver",
            "IPlanningPhaseManager",
        ],
    ),
    "usage_non_streaming_handling": CollaboratorResponsibility(
        collaborator_name="UsageAccountingOrchestrator",
        responsibility="Handle non-streaming response usage",
        category="usage_accounting",
        description=(
            "Handles usage tracking for non-streaming responses. Records "
            "final usage values and updates tracking."
        ),
        interface_methods=["handle_non_streaming_response"],
        dependencies=["IUsageTrackingWrapper"],
    ),
    "usage_auth_failure": CollaboratorResponsibility(
        collaborator_name="UsageAccountingOrchestrator",
        responsibility="Handle authentication failure",
        category="usage_accounting",
        description=(
            "Handles authentication failures with backend lifecycle side effects. "
            "Invalidates backend instance on auth failure."
        ),
        interface_methods=["handle_auth_failure"],
        dependencies=["IBackendLifecycleManager"],
    ),
    "usage_backend_error": CollaboratorResponsibility(
        collaborator_name="UsageAccountingOrchestrator",
        responsibility="Handle backend error",
        category="usage_accounting",
        description=(
            "Handles backend errors with resilience and usage updates. "
            "Records failures and updates resilience coordinator."
        ),
        interface_methods=["handle_backend_error"],
        dependencies=["IResilienceCoordinator"],
    ),
    # Failure recovery
    "complex_failover_check": CollaboratorResponsibility(
        collaborator_name="FailureRecoveryExecutor",
        responsibility="Check complex failover applicability",
        category="failure_recovery",
        description=(
            "Checks if complex model-specific failover applies. Returns True "
            "if complex failover routes are configured for the model."
        ),
        interface_methods=["check_complex_failover"],
        dependencies=["IFailoverPlanner"],
    ),
    "complex_failover_execution": CollaboratorResponsibility(
        collaborator_name="FailureRecoveryExecutor",
        responsibility="Execute complex failover",
        category="failure_recovery",
        description=(
            "Executes complex model-specific failover. Recursively calls "
            "completion flow with failover attempts."
        ),
        interface_methods=["execute_complex_failover"],
        dependencies=["IFailoverPlanner"],
    ),
    "failure_recovery": CollaboratorResponsibility(
        collaborator_name="FailureRecoveryExecutor",
        responsibility="Apply failure recovery",
        category="failure_recovery",
        description=(
            "Applies failure recovery (retry/failover) using injected strategy. "
            "Preserves streaming 'content started' safety and recursion prevention."
        ),
        interface_methods=["apply_failure_recovery"],
        dependencies=["IFailureHandlingStrategy", "IFailoverPlanner"],
    ),
    # Orchestration
    "flow_coordination": CollaboratorResponsibility(
        collaborator_name="BackendCompletionFlow",
        responsibility="Coordinate completion flow",
        category="orchestration",
        description=(
            "Coordinates the overall completion flow. Owns ordering and shared "
            "context. Delegates substantial logic to collaborators."
        ),
        interface_methods=["call_completion"],
        dependencies=[
            "IBackendAvailabilityChecker",
            "ICompletionSessionResolver",
            "IBackendRequestPreparer",
            "IBackendInvoker",
            "IWireCaptureOrchestrator",
            "IUsageAccountingOrchestrator",
            "IFailureRecoveryExecutor",
        ],
    ),
}


def get_responsibilities_by_collaborator(
    collaborator_name: str,
) -> list[CollaboratorResponsibility]:
    """Get all responsibilities for a specific collaborator."""
    return [
        resp
        for resp in RESPONSIBILITY_MAP.values()
        if resp.collaborator_name == collaborator_name
    ]


def get_responsibilities_by_category(
    category: str,
) -> list[CollaboratorResponsibility]:
    """Get all responsibilities for a specific category."""
    return [
        resp
        for resp in RESPONSIBILITY_MAP.values()
        if resp.category == category
    ]


def get_collaborator_for_responsibility(
    responsibility_key: str,
) -> str | None:
    """Get the collaborator name responsible for a given responsibility key."""
    resp = RESPONSIBILITY_MAP.get(responsibility_key)
    return resp.collaborator_name if resp else None


def validate_responsibility_boundaries() -> dict[str, Any]:
    """Validate that responsibility boundaries are stable.

    Returns a dict with validation results:
    - 'valid': bool - Whether all boundaries are valid
    - 'violations': list - Any boundary violations found
    - 'coverage': dict - Coverage statistics
    """
    violations: list[str] = []
    coverage: dict[str, int] = {}

    # Check that all collaborators have at least one responsibility
    collaborator_names = {
        resp.collaborator_name for resp in RESPONSIBILITY_MAP.values()
    }
    for name in collaborator_names:
        responsibilities = get_responsibilities_by_collaborator(name)
        coverage[name] = len(responsibilities)
        if len(responsibilities) == 0:
            violations.append(f"Collaborator {name} has no responsibilities")

    # Check that all categories are valid
    for resp in RESPONSIBILITY_MAP.values():
        if resp.category not in RESPONSIBILITY_CATEGORIES:
            violations.append(
                f"Invalid category '{resp.category}' for responsibility "
                f"'{resp.responsibility}'"
            )

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "coverage": coverage,
        "total_responsibilities": len(RESPONSIBILITY_MAP),
        "total_collaborators": len(collaborator_names),
    }

