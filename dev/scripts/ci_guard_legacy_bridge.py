#!/usr/bin/env python3
"""
CI guard: fail if new references to banned terms appear in code/tests.

This is a lightweight check intended for CI. It scans the repository for
occurrences of the words "legacy" or "bridge" in Python files under `src/`
and `tests/`, excluding this guard itself and documentation.

Usage:
  python scripts/ci_guard_legacy_bridge.py

Exit codes:
  0 - OK
  1 - Violations found
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_DIRS = [REPO_ROOT / "src", REPO_ROOT / "tests"]
ALLOWLIST = {
    # Allow known compatibility shims and explicit deprecation docstrings
    str(REPO_ROOT / "src/core/app/application_factory.py"),
    str(REPO_ROOT / "src/core/interfaces/backend_service_interface.py"),
}


def is_code_file(path: Path) -> bool:
    if not path.is_file():
        return False
    return path.suffix in {".py"}


def scan_file(path: Path) -> list[str]:
    if str(path) in ALLOWLIST:
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    findings: list[str] = []
    # Match whole word legacy or bridge in lowercase (case-insensitive)
    for lineno, line in enumerate(content.splitlines(), start=1):
        if re.search(r"\b(legacy|bridge)\b", line, flags=re.IGNORECASE):
            findings.append(f"{path}:{lineno}: {line.strip()}")
    return findings


def main() -> int:
    findings: list[str] = []
    for base in TARGET_DIRS:
        for path in base.rglob("*.py"):
            # Skip virtual envs or generated caches
            if any(part in {"__pycache__", "venv", ".venv"} for part in path.parts):
                continue
            findings.extend(scan_file(path))

    if findings:
        print("[CI GUARD] Found references to banned terms (legacy/bridge):")
        for f in findings:
            print(f"  {f}")
        print(
            "\nIf these are intentional (e.g., compatibility shims), add their file path to ALLOWLIST."
        )
        return 1
    print("[CI GUARD] OK: no banned term references found in code/tests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
