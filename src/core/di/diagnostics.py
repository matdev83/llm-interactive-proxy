"""
DI diagnostics module for resolution path tracking.

This module provides concurrency-safe resolution path tracking using Python's
contextvars to enable actionable error messages when DI_STRICT_DIAGNOSTICS is enabled.
"""

import os
from contextvars import ContextVar

from src.core.common.exceptions import ServiceResolutionError

# Context variable for tracking resolution stack per async task/thread
_resolution_stack: ContextVar[list[type]] = ContextVar(
    "di_resolution_stack", default=[]
)


def is_diagnostics_enabled() -> bool:
    """Check if DI diagnostics are enabled via environment variable.

    Returns:
        True if DI_STRICT_DIAGNOSTICS is set to a truthy value, False otherwise.
    """
    return os.getenv("DI_STRICT_DIAGNOSTICS", "false").lower() in (
        "true",
        "1",
        "yes",
    )


def push_resolution(service_type: type) -> None:
    """Push a service type onto the resolution stack.

    Args:
        service_type: The service type being resolved.
    """
    if not is_diagnostics_enabled():
        return

    stack = _resolution_stack.get([])
    new_stack = [*stack, service_type]
    _resolution_stack.set(new_stack)


def pop_resolution() -> None:
    """Pop a service type from the resolution stack."""
    if not is_diagnostics_enabled():
        return

    stack = _resolution_stack.get([])
    if stack:
        new_stack = stack[:-1]
        _resolution_stack.set(new_stack)


def get_resolution_path() -> list[str]:
    """Get the current resolution path as a list of type names.

    Returns:
        List of service type names in the resolution order (outermost first).
    """
    if not is_diagnostics_enabled():
        return []

    stack = _resolution_stack.get([])
    return [
        getattr(service_type, "__name__", str(service_type)) for service_type in stack
    ]


def enrich_missing_service_error(
    service_type: type, base_error: ServiceResolutionError
) -> ServiceResolutionError:
    """Enrich a missing-service error with resolution path details.

    Args:
        service_type: The service type that could not be resolved.
        base_error: The base ServiceResolutionError to enrich.

    Returns:
        A new ServiceResolutionError with resolution path details added.
    """
    if not is_diagnostics_enabled():
        return base_error

    type_name = getattr(service_type, "__name__", str(service_type))
    resolution_path = [*get_resolution_path(), type_name]

    details = base_error.details.copy() if base_error.details else {}
    details.update(
        {
            "missing_service": type_name,
            "resolution_path": resolution_path,
            "diagnostics_enabled": True,
        }
    )

    return ServiceResolutionError(
        base_error.args[0] if base_error.args else "Service resolution failed",
        details=details,
    )


def enrich_scoped_from_root_error(service_type: type) -> ServiceResolutionError:
    """Create a ServiceResolutionError for scoped-from-root misuse.

    Args:
        service_type: The scoped service type that was requested from root.

    Returns:
        A ServiceResolutionError with scoped-from-root details.
    """
    type_name = getattr(service_type, "__name__", str(service_type))
    resolution_path = [*get_resolution_path(), type_name]

    details = {
        "reason": "scoped_service_from_root",
        "missing_service": type_name,
        "resolution_path": resolution_path,
        "diagnostics_enabled": True,
    }

    return ServiceResolutionError(
        f"Cannot resolve scoped service {type_name} from root provider",
        details=details,
    )


def enrich_factory_error(
    service_type: type, original_exception: Exception
) -> ServiceResolutionError:
    """Wrap a factory/constructor failure with resolution path details.

    Args:
        service_type: The service type that failed to be created.
        original_exception: The original exception raised by the factory/constructor.

    Returns:
        A ServiceResolutionError wrapping the original exception with resolution path.
    """
    type_name = getattr(service_type, "__name__", str(service_type))
    resolution_path = [*get_resolution_path(), type_name]

    error_type = type(original_exception).__name__
    error_message = str(original_exception)

    # If the original exception is a ServiceResolutionError with diagnostics,
    # preserve its missing_service and merge resolution paths
    missing_service = type_name
    if (
        isinstance(original_exception, ServiceResolutionError)
        and original_exception.details
    ):
        original_details = original_exception.details
        if "missing_service" in original_details:
            # Preserve the original missing service (e.g., ServiceA when ServiceB's factory fails)
            missing_service = original_details["missing_service"]
        if "resolution_path" in original_details:
            # Merge resolution paths: current path + original path (avoiding duplicates)
            original_path = original_details["resolution_path"]
            # Combine paths, ensuring the missing service is at the end
            if original_path and original_path[-1] == missing_service:
                resolution_path = resolution_path[:-1] + original_path
            else:
                resolution_path = (
                    resolution_path + original_path[1:]
                    if len(original_path) > 1
                    else resolution_path
                )

    details = {
        "reason": "factory_exception",
        "error_type": error_type,
        "error_message": error_message,
        "missing_service": missing_service,
        "resolution_path": resolution_path,
        "diagnostics_enabled": True,
    }

    error = ServiceResolutionError(
        f"Failed to create instance of {type_name}: {error_message}",
        details=details,
    )
    error.__cause__ = original_exception
    return error
