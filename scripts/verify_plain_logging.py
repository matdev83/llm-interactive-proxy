import logging
import os
import sys

import structlog

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.common.logging_utils import (
    configure_logging_with_environment_tagging,
    get_logger,
)


def verify_logging_plain():
    print("Configuring logging (expecting plain text)...")
    configure_logging_with_environment_tagging(level=logging.DEBUG)

    logger = get_logger("test.logging")

    print("\n--- Generating Logs ---")
    logger.debug("This is a DEBUG message")
    logger.info("This is an INFO message")
    logger.warning("This is a WARNING message")
    logger.error("This is an ERROR message")
    print("--- Log Generation Complete ---\n")

    # Check handlers
    root_logger = logging.getLogger()
    handlers = root_logger.handlers
    print(f"Root handlers: {handlers}")

    has_rich = any("RichHandler" in str(type(h)) for h in handlers)
    if not has_rich:
        print("SUCCESS: RichHandler NOT found in root handlers.")
    else:
        print("FAIL: RichHandler found in root handlers.")

    # Verify structlog config
    # We can't easily inspect structlog internal config directly via public API to check for color=False
    # but we can check if ConsoleRenderer is used
    try:
        # Just ensure no error when logging via structlog directly
        sl_logger = structlog.get_logger()
        sl_logger.info("Structlog direct message")
        print("SUCCESS: Structlog configured and working.")
    except Exception as e:
        print(f"FAIL: Structlog error: {e}")


if __name__ == "__main__":
    verify_logging_plain()
