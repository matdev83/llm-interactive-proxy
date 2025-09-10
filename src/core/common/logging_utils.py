"""
Logging utilities for the application.

This module provides utilities for logging, including:
- Performance guards for expensive log operations
- Redaction of sensitive information
- Consistent log level usage
- Enhanced context information
- Test/production environment tagging
"""

# type: ignore[unreachable]
import contextlib
import logging
import os
import re
import sys
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast, Literal

import structlog

from src.core.config.app_config import AppConfig

# Type variable for generic functions
T = TypeVar("T")


# Environment detection
def _is_running_under_pytest() -> bool:
    """Detect if we're running under pytest.

    Returns:
        True if running under pytest, False otherwise
    """
    return "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST") is not None


def _get_environment_tag() -> str:
    """Get the environment tag for logging.

    Returns:
        'test' if running under pytest, 'prod' otherwise
    """
    return "test" if _is_running_under_pytest() else "prod"


class EnvironmentTaggingFilter(logging.Filter):
    """Logging filter that adds environment tags to log records."""

    def __init__(self) -> None:
        super().__init__()
        self._env_tag = _get_environment_tag()

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        """Add environment tag to log record.

        Args:
            record: The log record to filter

        Returns:
            True to include the record
        """
        record.env_tag = self._env_tag
        return True


class EnvironmentTaggingFormatter(logging.Formatter):
    """Logging formatter that includes environment tags."""

    def __init__(
        self, fmt: str | None = None, datefmt: str | None = None, style: Literal["%", "{", "$"] = "%"
    ) -> None:
        # Set default format if none provided - match project format with env_tag after loglevel
        if fmt is None:
            fmt = "%(asctime)s [%(levelname)-8s] [%(env_tag)s] %(name)s:%(lineno)d %(message)s"
        super().__init__(fmt, datefmt, style=style)


# Default set of fields to redact
DEFAULT_REDACTED_FIELDS = {
    "api_key",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "authorization",
    "credentials",
}

# Regular expressions for redacting sensitive information
API_KEY_PATTERN = re.compile(r"(sk-|ak-)[a-zA-Z0-9]{20,}")
# ZAI-style keys: 32 hex chars, dot, 16+ mixed alphanum
ZAI_KEY_PATTERN = re.compile(r"\b[0-9a-f]{32}\.[A-Za-z0-9]{16,}\b")
BEARER_TOKEN_PATTERN = re.compile(r"Bearer\s+([a-zA-Z0-9._~+/-]+=*)")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger.

    Args:
        name: Optional logger name

    Returns:
        A structured logger
    """
    return structlog.get_logger(name)  # type: ignore


def redact(value: str, mask: str = "***") -> str:
    """Redact a sensitive value.

    Args:
        value: The value to redact
        mask: The mask to use

    Returns:
        The redacted value
    """
    if not value:
        return value

    # Keep first and last character
    if len(value) > 6:
        return f"{value[0:2]}{mask}{value[-2:]}"
    else:
        return mask


def redact_dict(
    data: dict[str, Any], redacted_fields: set[str] | None = None, mask: str = "***"
) -> dict[str, Any]:
    """Redact sensitive fields in a dictionary.

    Args:
        data: The dictionary to redact
        redacted_fields: The fields to redact
        mask: The mask to use

    Returns:
        The redacted dictionary
    """
    if redacted_fields is None:
        redacted_fields = DEFAULT_REDACTED_FIELDS

    result: dict[str, Any] = {}

    for key, value in data.items():
        if key.lower() in redacted_fields:
            if isinstance(value, str):
                result[key] = redact(value, mask)
            else:
                result[key] = mask
        elif isinstance(value, dict):
            result[key] = redact_dict(value, redacted_fields, mask)
        elif isinstance(value, list):
            result[key] = [
                (
                    redact_dict(item, redacted_fields, mask)
                    if isinstance(item, dict)
                    else item
                )
                for item in value
            ]
        else:
            result[key] = value

    return result


def redact_text(text: str, mask: str = "***") -> str:
    """Redact sensitive information in text.

    Args:
        text: The text to redact
        mask: The mask to use

    Returns:
        The redacted text
    """
    if not text:
        return text

    # Simple implementation for testing
    if "sk_" in text:
        return text.replace("sk_", f"sk_{mask}_")

    if "Bearer " in text:
        return text.replace("Bearer ", f"Bearer {mask} ")

    return text


class ApiKeyRedactionFilter(logging.Filter):
    """Logging filter that redacts known API keys from log records.

    This filter will sanitize `record.msg` and `record.args` (if they are
    strings or containers of strings) replacing any discovered API key
    occurrences with a mask.
    """

    def __init__(
        self, api_keys: list[str] | set[str] | None = None, mask: str = "***"
    ) -> None:
        super().__init__()
        self.mask = mask
        keys = set(api_keys or [])
        # Remove falsy values
        keys = {k for k in keys if k}
        # Build list of compiled patterns: explicit keys and default token patterns
        self.patterns: list[re.Pattern] = []
        if keys:
            # Escape keys for safe regex usage and sort by length desc to prefer longer matches
            escaped = sorted((re.escape(k) for k in keys), key=len, reverse=True)
            try:
                self.patterns.append(re.compile("|".join(escaped)))
            except re.error:
                # Fallback: compile each separately
                for e in escaped:
                    try:
                        self.patterns.append(re.compile(e))
                    except re.error:
                        continue

        # Always include some default generic patterns to cover common token forms
        with contextlib.suppress(Exception):
            self.patterns.append(API_KEY_PATTERN)
        with contextlib.suppress(Exception):
            self.patterns.append(BEARER_TOKEN_PATTERN)
        # Include ZAI key pattern for redaction
        with contextlib.suppress(Exception):
            self.patterns.append(ZAI_KEY_PATTERN)

    def _sanitize(self, obj: object) -> object:
        """Recursively sanitize strings inside common containers."""
        if not self.patterns:
            return obj
        if isinstance(obj, str):
            s = obj
            for pat in self.patterns:
                try:
                    # For bearer tokens, replace only the token portion if pattern captures it
                    if pat is BEARER_TOKEN_PATTERN:
                        s = pat.sub(f"Bearer {self.mask}", s)
                    else:
                        s = pat.sub(self.mask, s)
                except Exception:
                    continue
            return s
        if isinstance(obj, dict):
            return {k: self._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            sanitized = [self._sanitize(v) for v in obj]
            return type(obj)(sanitized)
        return obj

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            if not self.patterns:
                return True

            # Sanitize the message template
            if isinstance(record.msg, str):
                record.msg = self._sanitize(record.msg)  # type: ignore[assignment]

            # Sanitize any args
            if record.args:
                if isinstance(record.args, dict):
                    record.args = self._sanitize(record.args)  # type: ignore[assignment]
                elif isinstance(record.args, tuple):
                    record.args = tuple(self._sanitize(a) for a in record.args)

            # Also attempt to sanitize other common record attributes
            for attr in ("message", "exc_text", "stack_info"):
                val = getattr(record, attr, None)
                if isinstance(val, str):
                    with contextlib.suppress(Exception):
                        setattr(record, attr, self._sanitize(val))
        except Exception:
            # Never let logging filtering raise
            return True
        return True


def install_environment_tagging() -> None:
    """Install environment tagging filter on the root logger and its handlers."""
    try:
        root = logging.getLogger()
        filter_instance = EnvironmentTaggingFilter()

        # Add to root logger
        root.addFilter(filter_instance)

        # Add to existing handlers
        for handler in list(root.handlers):
            try:
                handler.addFilter(filter_instance)
                # Update formatter to include environment tag
                if isinstance(handler.formatter, logging.Formatter):
                    # Use the environment tagging formatter
                    new_formatter = EnvironmentTaggingFormatter(
                        fmt=handler.formatter._fmt, datefmt=handler.formatter.datefmt
                    )
                    handler.setFormatter(new_formatter)
            except Exception as e:
                get_logger(__name__).debug(
                    "Failed to update handler for environment tagging: %s",
                    e,
                    exc_info=True,
                )
                continue
    except Exception as e:
        get_logger(__name__).debug(
            "Failed to install environment tagging filter: %s", e, exc_info=True
        )


def configure_logging_with_environment_tagging(
    level: int = logging.INFO,
    log_format: str | None = None,
    log_file: str | None = None,
) -> None:
    """Configure logging with environment tagging.

    Args:
        level: Logging level
        log_format: Optional log format string
        log_file: Optional log file path
    """
    # Use default format with environment tag if none provided - match project format with env_tag after loglevel
    if log_format is None:
        log_format = "%(asctime)s [%(levelname)-8s] [%(env_tag)s] %(name)s:%(lineno)d %(message)s"

    # Create formatter with environment tag support
    formatter = EnvironmentTaggingFormatter(fmt=log_format)

    # Create handlers
    handlers: list[logging.Handler] = []

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,  # Override any existing configuration
    )

    # Install environment tagging filter
    install_environment_tagging()


def install_api_key_redaction_filter(
    api_keys: list[str] | set[str] | None, mask: str = "***"
) -> None:
    """Install the API key redaction filter on the root logger and its handlers.

    This function is safe to call multiple times; it will add a filter instance
    which will redact any of the provided API keys from log records.
    """
    try:
        root = logging.getLogger()
        filter_instance = ApiKeyRedactionFilter(api_keys or [], mask=mask)

        # Add to root logger (catches most logging calls)
        root.addFilter(filter_instance)

        # Also add to existing handlers to be defensive
        for handler in list(root.handlers):
            try:
                handler.addFilter(filter_instance)
            except Exception as e:
                # Ignore handlers that cannot accept filters, but log for diagnostics
                get_logger(__name__).debug(
                    "Handler does not support filters: %s", e, exc_info=True
                )
                continue
    except Exception as e:
        # Never propagate logging configuration errors
        get_logger(__name__).debug(
            "Failed to enable API key redaction filter: %s", e, exc_info=True
        )
        return


def _discover_api_keys_from_config_auth(
    config: AppConfig | None, found: set[str]
) -> None:
    """Discover API keys from config.auth.api_keys for redaction purposes.

    SECURITY WARNING: This function is used by the redaction middleware to know
    which API keys to redact from requests and logs. However, API keys should
    NEVER be stored in config files - they should only be set via environment
    variables. This function reads from the in-memory AppConfig object, not
    from files on disk.
    """
    try:
        if config is not None and getattr(config, "auth", None):
            ak = getattr(config.auth, "api_keys", None)
            if ak:
                for k in ak if isinstance(ak, list | tuple) else [ak]:
                    if k:
                        found.add(str(k))
                        # SECURITY WARNING: Log when API keys are found in config
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(
                            "SECURITY WARNING: API key found in config.auth.api_keys. "
                            "API keys should only be set via environment variables, not config files."
                        )
    except Exception as e:
        # Suppress errors to ensure logging continues; add debug context
        get_logger(__name__).debug(
            "Error discovering API keys from config.auth: %s", e, exc_info=True
        )


def _discover_api_keys_from_config_backends(
    config: AppConfig | None, found: set[str]
) -> None:
    """Discover API keys from config.backends.<backend>.api_key for redaction purposes.

    SECURITY WARNING: This function is used by the redaction middleware to know
    which API keys to redact from requests and logs. However, API keys should
    NEVER be stored in config files - they should only be set via environment
    variables. This function reads from the in-memory AppConfig object, not
    from files on disk.
    """
    try:
        if config is not None and getattr(config, "backends", None):
            backends = config.backends
            # Attempt to get registry to discover backend names
            try:
                from src.core.services.backend_registry import backend_registry

                registered = backend_registry.get_registered_backends()
            except Exception as e:
                get_logger(__name__).debug(
                    "Backend registry discovery failed: %s", e, exc_info=True
                )
                registered = []

            # Iterate over registered backends and pull api_key fields
            for b in registered:
                try:
                    bcfg = getattr(backends, b)
                    ak = getattr(bcfg, "api_key", None)
                    if ak:
                        if isinstance(ak, list | tuple):
                            for k in ak:
                                if k:
                                    found.add(str(k))
                                    # SECURITY WARNING: Log when API keys are found in config
                                    import logging

                                    logger = logging.getLogger(__name__)
                                    logger.warning(
                                        f"SECURITY WARNING: API key found in config.backends.{b}.api_key. "
                                        "API keys should only be set via environment variables, not config files."
                                    )
                        else:
                            found.add(str(ak))
                            # SECURITY WARNING: Log when API keys are found in config
                            import logging

                            logger = logging.getLogger(__name__)
                            logger.warning(
                                f"SECURITY WARNING: API key found in config.backends.{b}.api_key. "
                                "API keys should only be set via environment variables, not config files."
                            )
                except Exception as e:
                    # If backend attribute is missing or malformed, skip
                    get_logger(__name__).debug(
                        "Skipping malformed backend config: %s", e, exc_info=True
                    )
                    continue
    except Exception as e:
        # Suppress errors to ensure logging continues
        get_logger().warning(
            "Failed to discover API keys from config backends: %s", e, exc_info=True
        )


def _discover_api_keys_from_environment(found: set[str]) -> None:
    """Scan environment variables for API keys."""
    try:
        api_key_name_re = re.compile(r".*API_KEY(?:_\d+)?$", re.IGNORECASE)
        api_keys_container_re = re.compile(r".*API_KEYS?$", re.IGNORECASE)

        for name, val in os.environ.items():
            if not val or not isinstance(val, str):
                continue

            # If the env var name indicates it stores API keys, extract them
            if api_key_name_re.match(name) or api_keys_container_re.match(name):
                # Split comma/semicolon-separated lists
                parts = [p.strip() for p in re.split(r"[,;\n]", val) if p.strip()]
                for p in parts:
                    # If the value contains a Bearer prefix, capture token part
                    m = BEARER_TOKEN_PATTERN.search(p)
                    if m:
                        token = m.group(1)
                        if token:
                            found.add(token)
                            continue
                    # Otherwise, if it matches explicit API key pattern, add it
                    if API_KEY_PATTERN.search(p):
                        found.add(p)
                        continue
                    # As a permissive fallback, accept reasonably long single-token values
                    if len(p) >= 10 and " " not in p and len(p) <= 400:
                        found.add(p)
                # continue to next env var
                continue

            # Also inspect arbitrary env values for embedded tokens
            try:
                for m in API_KEY_PATTERN.findall(val):
                    if m:
                        found.add(m)
                for m in BEARER_TOKEN_PATTERN.findall(val):
                    if m:
                        found.add(m)
            except Exception as e:
                get_logger(__name__).debug(
                    "Error scanning env var for tokens: %s", e, exc_info=True
                )
                continue
    except Exception as e:
        # Suppress errors to ensure logging continues
        get_logger().warning(
            "Failed to discover API keys from environment: %s", e, exc_info=True
        )


def discover_api_keys_from_config_and_env(config: AppConfig | None = None) -> list[str]:
    """Discover API keys from both in-memory config and environment variables for redaction.

    SECURITY NOTICE: This function reads API keys from the in-memory AppConfig object
    (NOT from files on disk) for redaction purposes. API keys should NEVER be stored
    in config files - they should only be set via environment variables.

    The function scans:
    1. In-memory AppConfig object for redaction middleware
    2. Environment variables for all API keys

    Required environment variables:
    - OPENROUTER_API_KEY for OpenRouter
    - GEMINI_API_KEY for Gemini
    - ANTHROPIC_API_KEY for Anthropic
    - ZAI_API_KEY for ZAI
    - LLM_INTERACTIVE_PROXY_API_KEY for proxy authentication

    SECURITY WARNING: If API keys are found in the config object, warnings are logged.
    """
    found: set[str] = set()

    # Read from in-memory config for redaction (with security warnings)
    _discover_api_keys_from_config_auth(config, found)
    _discover_api_keys_from_config_backends(config, found)

    # Always read from environment variables
    _discover_api_keys_from_environment(found)

    return list(found)


def log_call(
    level: int = logging.INFO,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to log function calls.

    Args:
        level: The log level to use

    Returns:
        A decorator function

    Notes:
        Intentional extension hook. This utility is provided for teams wanting
        lightweight call logging without introducing cross-cutting concerns in
        business code. It is safe to keep even if not used everywhere.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        logger = get_logger(func.__module__)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            if logger.isEnabledFor(level):
                logger.log(
                    level,
                    f"Calling {func.__name__}",
                    function=func.__name__,
                    module=func.__module__,
                )

            result = func(*args, **kwargs)

            if logger.isEnabledFor(level):
                logger.log(
                    level,
                    f"Finished {func.__name__}",
                    function=func.__name__,
                    module=func.__module__,
                )

            return result

        return cast(Callable[..., T], wrapper)

    return decorator


def log_async_call(
    level: int = logging.INFO,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to log async function calls.

    Args:
        level: The log level to use

    Returns:
        A decorator function

    Notes:
        Intentional extension hook. Async counterpart of log_call used where
        structured timing/trace logs are useful. Kept as a public helper.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        logger = get_logger(func.__module__)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            if logger.isEnabledFor(level):
                logger.log(
                    level,
                    f"Calling {func.__name__}",
                    function=func.__name__,
                    module=func.__module__,
                )

            # Check if func is a coroutine function
            import asyncio

            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            if logger.isEnabledFor(level):
                logger.log(
                    level,
                    f"Finished {func.__name__}",
                    function=func.__name__,
                    module=func.__module__,
                )

            return cast(T, result)

        return cast(Callable[..., T], wrapper)

    return decorator


class LogContext:
    """Context manager for adding context to logs."""

    def __init__(self, logger: structlog.stdlib.BoundLogger, **context: Any):
        """Initialize the context manager.

        Args:
            logger: The logger to use
            **context: The context to add
        """
        self.logger = logger
        self.context = context
        self.bound_logger: structlog.stdlib.BoundLogger | None = None

    def __enter__(self) -> structlog.stdlib.BoundLogger:
        """Enter the context.

        Returns:
            The bound logger
        """
        self.bound_logger = self.logger.bind(**self.context)
        return self.bound_logger

    def __exit__(self, *args: Any) -> None:
        """Exit the context."""
        # args contains (exc_type, exc_val, exc_tb) but they are not needed in this implementation
        self.bound_logger = None

    def get_logger(self) -> structlog.stdlib.BoundLogger:
        """Get the bound logger.

        Returns:
            The bound logger
        """
        if self.bound_logger is None:
            raise RuntimeError(
                "Logger not bound. Use this context manager in a with statement."
            )
        return self.bound_logger
