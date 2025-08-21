"""
Architectural guards to prevent SOLID violations.

This module provides runtime and static analysis tools to enforce
proper architectural patterns and prevent direct state access violations.
"""

from __future__ import annotations

import functools
import inspect
import logging
import warnings
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class ArchitecturalViolationError(Exception):
    """Raised when architectural rules are violated."""


class DeprecatedStateAccessWarning(UserWarning):
    """Warning for deprecated direct state access patterns."""


def enforce_no_direct_state_access(func: F) -> F:
    """Decorator to prevent direct app.state access in domain/service methods.
    
    This decorator inspects the call stack to detect if code is trying to
    access app.state directly and raises an error if found.
    
    Args:
        func: The function to protect
        
    Returns:
        The wrapped function
        
    Raises:
        ArchitecturalViolationError: If direct state access is detected
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get the calling frame
        frame = inspect.currentframe()
        try:
            if frame and frame.f_back:
                caller_frame = frame.f_back
                caller_locals = caller_frame.f_locals
                caller_code = caller_frame.f_code
                
                # Check for suspicious variable names that might indicate direct state access
                suspicious_vars = [
                    name for name in caller_locals.keys() 
                    if 'app' in name.lower() and 'state' in str(caller_locals.get(name, ''))
                ]
                
                if suspicious_vars:
                    caller_file = caller_code.co_filename
                    caller_line = caller_frame.f_lineno
                    
                    # Only enforce in domain and service layers
                    if any(path in caller_file for path in ['/domain/', '/services/']):
                        logger.warning(
                            f"Potential direct state access detected in {caller_file}:{caller_line}. "
                            f"Suspicious variables: {suspicious_vars}. "
                            f"Use dependency injection instead."
                        )
                        
                        # In strict mode, raise an error
                        if getattr(func, '_strict_mode', False):
                            raise ArchitecturalViolationError(
                                f"Direct state access detected in {caller_file}:{caller_line}. "
                                f"Use IApplicationState service through DI instead."
                            )
        finally:
            del frame
            
        return func(*args, **kwargs)
    
    return wrapper  # type: ignore


def deprecated_state_access(message: str = "Direct state access is deprecated. Use DI services instead."):
    """Decorator to mark state access methods as deprecated.
    
    Args:
        message: Custom deprecation message
        
    Returns:
        Decorator function
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            warnings.warn(
                f"{func.__name__}: {message}",
                DeprecatedStateAccessWarning,
                stacklevel=2
            )
            return func(*args, **kwargs)
        return wrapper  # type: ignore
    return decorator


def require_di_service(service_type: type):
    """Decorator to ensure a method receives a DI service parameter.
    
    Args:
        service_type: The expected service type
        
    Returns:
        Decorator function
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Check if the service is provided as a parameter
            sig = inspect.signature(func)
            service_param = None
            
            for param_name, param in sig.parameters.items():
                if param.annotation == service_type:
                    service_param = param_name
                    break
            
            if service_param and service_param not in kwargs:
                # Try to get from args
                param_names = list(sig.parameters.keys())
                if service_param in param_names:
                    param_index = param_names.index(service_param)
                    if param_index >= len(args):
                        raise ArchitecturalViolationError(
                            f"Method {func.__name__} requires {service_type.__name__} "
                            f"to be injected as parameter '{service_param}'"
                        )
            
            return func(*args, **kwargs)
        return wrapper  # type: ignore
    return decorator


class StateAccessMonitor:
    """Monitor for detecting and logging state access patterns."""
    
    def __init__(self):
        self.violations: list[dict[str, Any]] = []
        self.enabled = True
    
    def log_violation(self, violation_type: str, location: str, details: str):
        """Log an architectural violation.
        
        Args:
            violation_type: Type of violation
            location: Where the violation occurred
            details: Additional details about the violation
        """
        if not self.enabled:
            return
            
        violation = {
            'type': violation_type,
            'location': location,
            'details': details,
            'timestamp': __import__('time').time()
        }
        
        self.violations.append(violation)
        logger.warning(f"Architectural violation: {violation}")
    
    def get_violations(self) -> list[dict[str, Any]]:
        """Get all recorded violations."""
        return self.violations.copy()
    
    def clear_violations(self):
        """Clear all recorded violations."""
        self.violations.clear()


# Global monitor instance
state_access_monitor = StateAccessMonitor()


def domain_layer_guard(cls):
    """Class decorator to protect domain layer classes from state access violations.
    
    Args:
        cls: The class to protect
        
    Returns:
        The protected class
    """
    # Wrap all methods with the guard
    for attr_name in dir(cls):
        attr = getattr(cls, attr_name)
        if callable(attr) and not attr_name.startswith('_'):
            setattr(cls, attr_name, enforce_no_direct_state_access(attr))
    
    return cls


def service_layer_guard(cls):
    """Class decorator to protect service layer classes from state access violations.
    
    Args:
        cls: The class to protect
        
    Returns:
        The protected class
    """
    # Similar to domain layer guard but with different rules
    for attr_name in dir(cls):
        attr = getattr(cls, attr_name)
        if callable(attr) and not attr_name.startswith('_'):
            # Add monitoring but don't enforce as strictly
            wrapped = enforce_no_direct_state_access(attr)
            wrapped._strict_mode = False  # type: ignore
            setattr(cls, attr_name, wrapped)
    
    return cls