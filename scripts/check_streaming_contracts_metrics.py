#!/usr/bin/env python3
"""
Check streaming contracts refactor scope against size and complexity thresholds.

This script validates that all files in the streaming-contracts refactor scope
meet the following thresholds:
- LOC per file: < 600 (Requirements 1.1, 1.2)
- Max function CC: < 50 (Requirement 1.3)
- Total module CC: < 200 (Requirement 1.5)

Scope definition per design.md:
- src/core/ports/streaming_contracts.py
- src/core/ports/streaming/*.py (single level)
- src/core/domain/streaming/*.py (single level)
- src/core/domain/streaming/parsing/*.py (single level)
- src/core/transport/streaming/*.py (single level)
- src/core/services/streaming/error_mapping.py

Exit codes:
- 0: All files meet thresholds
- 1: One or more files violate thresholds
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import validation functions from analyze_complexity.py
from analyze_complexity import (
    get_streaming_contracts_scope_files,
    validate_streaming_contracts_files,
)


def main() -> int:
    """
    Validate streaming contracts refactor scope against thresholds.

    Returns:
        0 if all thresholds pass, 1 if any violations found
    """
    base_path = Path(".")
    scope_files = get_streaming_contracts_scope_files(base_path)

    if not scope_files:
        print("Warning: No files found in refactor scope", file=sys.stderr)
        return 1

    violations, passed_count = validate_streaming_contracts_files(
        scope_files, base_path
    )

    if violations:
        print("=" * 100, file=sys.stderr)
        print(
            f"VALIDATION FAILED: {len(violations)} file(s) with violations",
            file=sys.stderr,
        )
        print("=" * 100, file=sys.stderr)
        print(file=sys.stderr)

        for violation in violations:
            print(f"[FAIL] {violation['file']}", file=sys.stderr)
            if "error" in violation:
                print(f"   Error: {violation['error']}", file=sys.stderr)
            else:
                if "metrics" in violation:
                    metrics = violation["metrics"]
                    print(
                        f"   Metrics: {metrics['lines']} lines, "
                        f"max CC: {metrics['max_complexity']}, "
                        f"total CC: {metrics['total_complexity']}",
                        file=sys.stderr,
                    )
                print("   Violations:", file=sys.stderr)
                for v in violation["violations"]:
                    print(f"     - {v}", file=sys.stderr)
            print(file=sys.stderr)

        print(
            f"[PASS] Passed: {passed_count}/{len(scope_files)} files", file=sys.stderr
        )
        return 1
    else:
        print("=" * 100)
        print(f"[PASS] VALIDATION PASSED: All {len(scope_files)} files meet thresholds")
        print("=" * 100)
        return 0


if __name__ == "__main__":
    sys.exit(main())
