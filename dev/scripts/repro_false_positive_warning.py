"""Repro script for false-positive security warning bug.

The bug: _discover_api_keys_from_config_backends() in logging_utils.py
compares the config api_key against os.getenv(env_var), which only reads
the process environment. On Windows, the key can come from the persistent
registry via get_env_value_with_windows_persistent_fallback() in
from_env_part3.py. When the process env is stale/missing but the registry
has the value, the comparison fails and a false SECURITY WARNING is emitted.

BEFORE FIX: The check used os.getenv() which misses Windows persistent env.
AFTER FIX:  The check uses get_env_value_with_windows_persistent_fallback()
            which is consistent with how config loading works.

This repro simulates the Windows persistent-fallback scenario.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.core.common.logging_utils import (
    _discover_api_keys_from_config_backends,
    _logged_security_warnings,
)

API_KEY_VALUE = "fake-zai-coding-plan-key-12345"


def _make_config(backend_name: str, api_key: str) -> MagicMock:
    mock_backend = MagicMock()
    mock_backend.api_key = api_key
    mock_backends = MagicMock()
    setattr(mock_backends, backend_name, mock_backend)
    mock_config = MagicMock()
    mock_config.backends = mock_backends
    return mock_config


def main() -> None:
    print("=" * 70)
    print("Repro: False-positive SECURITY WARNING for backend API keys")
    print("=" * 70)

    original = os.environ.pop("ZAI_CODING_PLAN_API_KEY", None)
    print(f"\n[setup] ZAI_CODING_PLAN_API_KEY in process env: {os.getenv('ZAI_CODING_PLAN_API_KEY')}")

    mock_config = _make_config("zai-coding-plan", API_KEY_VALUE)
    _logged_security_warnings.clear()

    found: set[str] = set()
    warning_emitted = False

    with (
        patch(
            "src.core.services.backend_registry.backend_registry"
        ) as mock_registry,
        patch("src.core.common.logging_utils.get_logger") as mock_get_logger,
        patch(
            "src.core.common.env_utils.get_env_value_with_windows_persistent_fallback",
            return_value=(API_KEY_VALUE, "windows-user"),
        ),
    ):
        mock_registry.get_registered_backends.return_value = ["zai-coding-plan"]
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        _discover_api_keys_from_config_backends(mock_config, found)

        warning_calls = [
            call.args[0] for call in mock_logger.warning.call_args_list
        ]
        warning_emitted = any("SECURITY WARNING" in w for w in warning_calls)

    if original is not None:
        os.environ["ZAI_CODING_PLAN_API_KEY"] = original

    print(f"[result] api_key found set: {found}")
    print(f"[result] SECURITY WARNING emitted: {warning_emitted}")
    print()

    if warning_emitted:
        print("BUG STILL PRESENT: SECURITY WARNING emitted even though the key")
        print("was loaded from the Windows persistent environment.")
        sys.exit(1)
    else:
        print("FIX VERIFIED: No false-positive warning emitted.")
        print("The check correctly uses get_env_value_with_windows_persistent_fallback()")
        print("to match the same source used during config loading.")
        sys.exit(0)


if __name__ == "__main__":
    main()
