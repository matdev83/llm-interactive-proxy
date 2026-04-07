#!/usr/bin/env python3
# ruff: noqa: N999
"""
Validate pre-commit hook configuration integrity.

Ensures that every script referenced by:
  1. .pre-commit-config.yaml (entry fields)
  2. dev/scripts/pre-commit-hook.py (hardcoded script paths)
actually exists on disk.

Exits with code 1 and a clear error message if any reference is broken.
Designed to run as a CI gate so broken hooks never go undetected.
"""

import re
import sys
from pathlib import Path


def _repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists() or (root / ".gitmodules").exists():
        return root
    print(f"Unable to determine repo root from {Path(__file__).resolve()}")
    sys.exit(2)


def _validate_pre_commit_config_yaml(root: Path) -> list[str]:
    errors: list[str] = []
    config_path = root / ".pre-commit-config.yaml"
    if not config_path.exists():
        errors.append(".pre-commit-config.yaml not found at repo root")
        return errors

    text = config_path.read_text(encoding="utf-8")
    for m in re.finditer(r"^\s+entry:\s+(.+)$", text, re.MULTILINE):
        entry = m.group(1).strip()
        parts = entry.split()
        script_part = None
        for i, p in enumerate(parts):
            if p == "python" or p == "python3":
                if i + 1 < len(parts):
                    script_part = parts[i + 1]
                break
            if "/" in p or p.endswith(".py"):
                script_part = p
                break
        if script_part is None:
            continue

        resolved = root / script_part
        if not resolved.exists():
            errors.append(
                f".pre-commit-config.yaml entry '{entry}' references "
                f"'{script_part}' which does not exist "
                f"(checked {resolved})"
            )
    return errors


def _validate_mandatory_hook_scripts(root: Path) -> list[str]:
    errors: list[str] = []
    hook_path = root / "dev" / "scripts" / "pre-commit-hook.py"
    if not hook_path.exists():
        errors.append("Mandatory hook script not found: dev/scripts/pre-commit-hook.py")
        return errors

    text = hook_path.read_text(encoding="utf-8")
    path_pattern = re.compile(r'["\']' r"((?:dev/|scripts/|src/)[\w\-/]+\.py)" r'["\']')
    for m in path_pattern.finditer(text):
        ref = m.group(1)
        resolved = root / ref
        if not resolved.exists():
            errors.append(
                f"dev/scripts/pre-commit-hook.py references '{ref}' "
                f"which does not exist (checked {resolved})"
            )
    return errors


def main() -> int:
    root = _repo_root()
    all_errors: list[str] = []

    all_errors.extend(_validate_pre_commit_config_yaml(root))
    all_errors.extend(_validate_mandatory_hook_scripts(root))

    if all_errors:
        print("ERROR: Pre-commit hook integrity check failed!\n", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        print(
            "\nOne or more scripts referenced by pre-commit hooks do not exist. "
            "This means hooks are silently broken and NOT protecting the repository.",
            file=sys.stderr,
        )
        return 1

    print("Pre-commit hook integrity check passed. All referenced scripts exist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
