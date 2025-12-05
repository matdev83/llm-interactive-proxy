import argparse
import hashlib
import os
import subprocess
import sys

import pytest

# Files that define CLI arguments.
# Adjust this list if flags are defined in other files.
CLI_SOURCE_FILES = ["src/core/cli.py", "src/core/config/cli_args.py"]


def calculate_sources_hash():
    """Calculates MD5 hash of the CLI source files to detect changes."""
    hasher = hashlib.md5()
    for rel_path in CLI_SOURCE_FILES:
        abs_path = os.path.abspath(rel_path)
        if os.path.exists(abs_path):
            with open(abs_path, "rb") as f:
                hasher.update(f.read())
    return hasher.hexdigest()


def get_cli_flags():
    """Extracts all CLI flags from the application's argument parser."""
    # Defer import to avoid overhead when using cached results
    from src.core.cli import build_cli_parser

    # Ensure we can import the module even if not installed as package in current env
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    parser = build_cli_parser()
    flags = []
    for action in parser._actions:
        # Skip help arguments
        if "help" in action.option_strings:
            continue

        # Skip suppressed arguments (internal/hidden)
        if action.help == argparse.SUPPRESS:
            continue

        for option in action.option_strings:
            flags.append(option)
    return flags


def test_cli_flags_documented(request):
    """
    Ensures that all public CLI flags are mentioned in the documentation.

    Optimization:
    Uses pytest cache to store the hash of CLI source files.
    If the source code hasn't changed since the last *successful* run,
    the test passes immediately to save time (skipping imports and scanning).
    """
    current_hash = calculate_sources_hash()

    # Cache keys
    hash_key = "cli_flags_docs_source_hash"
    result_key = "cli_flags_docs_last_result"

    cached_hash = request.config.cache.get(hash_key, None)
    last_result = request.config.cache.get(result_key, None)

    # If hash matches and last run passed, return immediately (Pass)
    if cached_hash == current_hash and last_result == "PASS":
        # We treat this as a pass without execution
        return

    # Otherwise, perform the check
    flags = get_cli_flags()
    missing_flags = []

    for flag in flags:
        # Run rg -F (fixed string) -q (quiet) -e <flag> ./docs/
        # We use literal matching.
        # Use -e to handle flags starting with dashes
        cmd = ["rg", "-F", "-q", "-e", flag, "./docs/"]

        # Run the command
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            missing_flags.append(flag)

    if missing_flags:
        # Record failure (or clear cache)
        request.config.cache.set(result_key, "FAIL")
        request.config.cache.set(
            hash_key, current_hash
        )  # Still update hash to know which version failed

        pytest.fail(
            "The following CLI flags are missing from documentation in ./docs/:\n"
            + "\n".join(f"- {flag}" for flag in missing_flags)
        )

    # If we get here, test passed
    request.config.cache.set(hash_key, current_hash)
    request.config.cache.set(result_key, "PASS")


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
