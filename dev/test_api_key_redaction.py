#!/usr/bin/env python
"""
Test script to verify API key redaction in logs.

This script:
1. Sets up environment variables with various API key formats
2. Configures logging with the API key redaction filter
3. Logs messages containing API keys in different formats
4. Verifies the keys are properly redacted in the logs
"""

import logging
import os
import re
import sys


# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.common.logging_utils import (
    discover_api_keys_from_config_and_env,
    install_api_key_redaction_filter,
)


def setup_test_env() -> dict[str, str]:
    """Set up test environment variables with API keys."""
    test_keys = {
        # Standard API key format
        "OPENAI_API_KEY": "sk-1234567890abcdefghijklmn",
        # Numbered API key
        "GEMINI_API_KEY_1": "AIzaSyD-abcdefghijklmnopqrstuvwxyz12345",
        "GEMINI_API_KEY_14": "AIzaSyD-numbered14keyabcdefghijklmn",
        # Comma-separated API keys
        "ANTHROPIC_API_KEY": "sk-ant-api03-abcdefghijklmnopqrstuvwxyz,sk-ant-api03-secondkeyabcdefghijklmnopq",
        # Bearer token format
        "AUTH_TOKEN": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ",
        # Non-key values that shouldn't be redacted
        "NORMAL_ENV_VAR": "this is a normal value",
        "PORT": "8000",
    }

    # Set environment variables
    for name, value in test_keys.items():
        os.environ[name] = value

    return test_keys


class TestLogHandler(logging.Handler):
    """Custom log handler that captures log records for testing."""
    # Prevent pytest from collecting this as a test class
    __test__ = False

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def get_messages(self) -> list[str]:
        """Get formatted log messages."""
        return [self.format(r) for r in self.records]

    def clear(self) -> None:
        """Clear captured records."""
        self.records.clear()


def test_key_discovery() -> None:
    """Test API key discovery from environment variables."""
    # Set up test environment
    test_keys = setup_test_env()

    # Discover API keys
    discovered_keys = discover_api_keys_from_config_and_env()

    # Expected keys to find (extract actual key values, not env var names)
    expected_keys = set()
    for val in test_keys.values():
        # Handle comma-separated keys
        for part in val.split(","):
            # Extract Bearer token if present
            bearer_match = re.search(r"Bearer\s+([a-zA-Z0-9._~+/-]+=*)", part)
            if bearer_match:
                expected_keys.add(bearer_match.group(1))
            # Otherwise add the whole key if it looks like an API key
            elif re.search(r"(sk-|ak-|AIza)[a-zA-Z0-9]{10,}", part):
                expected_keys.add(part.strip())

    # Check if all expected keys were discovered
    found_count = 0
    missing_keys = set()

    for expected_key in expected_keys:
        if expected_key in discovered_keys:
            found_count += 1
        else:
            missing_keys.add(expected_key)

    print("API Key Discovery Test:")
    print(f"- Expected to find {len(expected_keys)} keys")
    print(f"- Actually discovered {len(discovered_keys)} keys")
    print(f"- Found {found_count} of the expected keys")

    if missing_keys:
        print(f"- Missing keys: {missing_keys}")
    else:
        print("- All expected keys were found!")

    # Check for unexpected keys
    unexpected = set(discovered_keys) - expected_keys
    if unexpected:
        print(f"- Found {len(unexpected)} unexpected keys")

    print()


def test_log_redaction() -> None:
    """Test API key redaction in log messages."""
    # Set up test environment
    test_keys = setup_test_env()

    # Configure logging with redaction
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Add a test handler to capture logs
    test_handler = TestLogHandler()
    test_handler.setLevel(logging.DEBUG)
    test_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(test_handler)

    # Install redaction filter
    discovered_keys = discover_api_keys_from_config_and_env()
    install_api_key_redaction_filter(discovered_keys)

    # Log messages containing API keys
    logger = logging.getLogger("test_redaction")

    print("Log Redaction Test:")

    # Test case 1: Direct API key in message
    logger.info(f"API Key: {test_keys['OPENAI_API_KEY']}")

    # Test case 2: API key in JSON-like structure
    logger.info(
        f"Config: {{ 'api_key': '{test_keys['GEMINI_API_KEY_1']}', 'model': 'gemini-pro' }}"
    )

    # Test case 3: API key in URL
    logger.info(
        f"URL: https://api.example.com/v1/chat?key={test_keys['GEMINI_API_KEY_14']}"
    )

    # Test case 4: Bearer token in Authorization header
    logger.info(f"Headers: {{ 'Authorization': '{test_keys['AUTH_TOKEN']}' }}")

    # Test case 5: Multiple API keys in one message
    logger.info(f"Keys: {test_keys['OPENAI_API_KEY']}, {test_keys['GEMINI_API_KEY_1']}")

    # Test case 6: Normal message (should not be affected)
    logger.info("Normal message without API keys")

    # Get logged messages
    messages = test_handler.get_messages()

    # Check if API keys were redacted
    all_passed = True
    for i, msg in enumerate(messages):
        # Skip the last message which doesn't contain keys
        if i == len(messages) - 1:
            continue

        # Check if any of the actual API key values appear in the log
        contains_key = False
        for key_name, key_value in test_keys.items():
            if key_name == "NORMAL_ENV_VAR" or key_name == "PORT":
                continue

            # For each key value, check if it appears in the log
            for key_part in key_value.split(","):
                # Extract actual key from Bearer token
                if key_part.startswith("Bearer "):
                    key_part = key_part.split(" ", 1)[1]

                # Skip short parts
                if len(key_part) < 10:
                    continue

                if key_part.strip() in msg:
                    contains_key = True
                    all_passed = False
                    print(f"- FAIL: Found unredacted API key in log message {i+1}")
                    break

            if contains_key:
                break

        if not contains_key:
            print(f"- PASS: Log message {i+1} properly redacted")

    if all_passed:
        print("- All API keys were properly redacted!")

    # Print the actual redacted messages for inspection
    print("\nRedacted log messages:")
    for i, msg in enumerate(messages):
        print(f"{i+1}. {msg}")


def main() -> None:
    """Run the tests."""
    print("=== API Key Redaction Tests ===\n")

    # Test API key discovery
    test_key_discovery()

    # Test log redaction
    test_log_redaction()

    print("\nTests completed!")


if __name__ == "__main__":
    main()
