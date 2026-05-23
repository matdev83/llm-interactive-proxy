from typing import Any

from src.core.services.backend_completion_flow.availability_checker import (
    BackendAvailabilityChecker,
)
from src.core.services.backend_completion_flow.backend_manager import BackendManager
from src.core.services.backend_completion_flow.backend_request_preparer import (
    BackendRequestPreparer,
)
from src.core.services.backend_completion_flow.completion_session_resolver import (
    CompletionSessionResolver,
)
from src.core.services.backend_completion_flow.failure_recovery_executor import (
    FailureRecoveryExecutor,
)
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.backend_completion_flow.usage_accounting_orchestrator import (
    UsageAccountingOrchestrator,
)
from src.core.services.backend_completion_flow.wire_capture_orchestrator import (
    WireCaptureOrchestrator,
)


def create_test_backend_completion_flow(deps: dict[str, Any]) -> BackendCompletionFlow:
    """Create BackendCompletionFlow with real collaborators using mocked dependencies."""

    # Collaborators
    availability_checker = BackendAvailabilityChecker(
        backend_lifecycle_manager=deps["backend_lifecycle_manager"],
        resilience_coordinator=deps.get("resilience_coordinator"),
        failover_routes=deps.get("failover_routes"),
    )

    request_preparer = BackendRequestPreparer(
        backend_model_resolver=deps["backend_model_resolver"],
        backend_config_service=deps["backend_config_service"],
        reasoning_config_applicator=deps["reasoning_config_applicator"],
        uri_parameter_applicator=deps["uri_parameter_applicator"],
        config=deps["config"],
    )

    session_resolver = CompletionSessionResolver(
        session_service=deps["session_service"],
    )

    backend_invoker = BackendManager(
        backend_lifecycle_manager=deps["backend_lifecycle_manager"],
        resilience_coordinator=deps.get("resilience_coordinator"),
        failover_routes=deps.get("failover_routes"),
    )

    failover_executor = FailureRecoveryExecutor(
        failover_planner=deps["failover_planner"],
        failure_handling_strategy=deps.get("failure_handling_strategy"),
        routing_service=deps.get("routing_service"),
        config=deps["config"],
        failover_routes=deps.get("failover_routes"),
    )

    wire_capture_orchestrator = WireCaptureOrchestrator(
        wire_capture=deps.get("wire_capture"),
        config=deps["config"],
        backend_config_service=deps["backend_config_service"],
    )

    usage_accounting = UsageAccountingOrchestrator(
        usage_tracking_service=deps.get("usage_tracking_service"),
        usage_tracking_wrapper=deps["usage_tracking_wrapper"],
        stream_session_id_resolver=deps["stream_session_id_resolver"],
        planning_phase_manager=deps["planning_phase_manager"],
        resilience_coordinator=deps.get("resilience_coordinator"),
        backend_factory=deps["backend_factory"],
        backend_lifecycle_manager=deps["backend_lifecycle_manager"],
    )

    from src.core.services.connector_invoker import ConnectorInvoker

    connector_invoker = ConnectorInvoker()

    return BackendCompletionFlow(
        availability_checker=availability_checker,
        request_preparer=request_preparer,
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting_orchestrator=usage_accounting,
        exception_normalizer=deps["exception_normalizer"],
        stream_formatting_service=deps["stream_formatting_service"],
        connector_invoker=connector_invoker,
        resilience_coordinator=deps.get("resilience_coordinator"),
    )
