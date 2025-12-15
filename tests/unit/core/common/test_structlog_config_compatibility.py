import logging

from src.core.common.structlog_config import get_logger


def test_get_logger_returns_compatible_logger() -> None:
    """Test that get_logger returns a logger with isEnabledFor method."""
    logger = get_logger("test_logger")

    # Check if isEnabledFor exists and is callable
    assert hasattr(logger, "isEnabledFor")
    assert callable(logger.isEnabledFor)

    # Check if it works as expected
    assert logger.isEnabledFor(logging.CRITICAL) is True

    # Check if it wraps a structlog logger (CompatibleBoundLogger should pass through attributes)
    # We can check for a structlog-specific method like 'bind'
    assert hasattr(logger, "bind")
    assert callable(logger.bind)
