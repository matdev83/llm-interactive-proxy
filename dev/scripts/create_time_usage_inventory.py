"""Create baseline inventory of time usage violations.

This script runs the time usage linter and creates a classified inventory
of all violations for Phase 4 remediation.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from tests.unit.test_time_usage_linter import (
    LintFinding,
    _scan_repo_for_time_usage,
)
from tests.utils.time_policy import load_allowlist


def classify_violation(finding: LintFinding, file_content: str) -> str:
    """Classify a violation as safe-to-replace, legitimate-exception, or needs-investigation.

    Args:
        finding: The lint finding to classify
        file_content: Content of the file containing the violation

    Returns:
        Classification: "safe-to-replace", "legitimate-exception", or "needs-investigation"
    """
    lines = file_content.splitlines()
    if finding.line > len(lines):
        return "needs-investigation"

    # Get context around the violation
    context_start = max(0, finding.line - 5)
    context_end = min(len(lines), finding.line + 5)
    context = "\n".join(lines[context_start:context_end])

    # Check for performance/benchmark indicators
    if any(
        keyword in context.lower()
        for keyword in [
            "benchmark",
            "performance",
            "latency",
            "timing",
            "elapsed",
            "duration",
            "measure",
            "speed",
        ]
    ):
        return "legitimate-exception"

    # Check for network/external API tests
    if any(
        keyword in context.lower()
        for keyword in [
            "network",
            "external",
            "api",
            "http",
            "request",
            "response",
            "timeout",
        ]
    ):
        # May be legitimate if measuring real response times
        return "needs-investigation"

    # Check if it's in a test that's clearly deterministic
    if any(
        keyword in context.lower()
        for keyword in [
            "assert",
            "expect",
            "should",
            "verify",
            "check",
        ]
    ):
        return "safe-to-replace"

    # Default: safe to replace unless proven otherwise
    return "safe-to-replace"


def create_inventory(repo_root: Path, output_path: Path) -> None:
    """Create classified inventory of time usage violations.

    Args:
        repo_root: Root directory of the repository
        output_path: Path to write the inventory JSON file
    """
    print("Scanning repository for time usage violations...")
    allowlist = load_allowlist()
    findings = _scan_repo_for_time_usage(repo_root, allowlist)

    print(f"Found {len(findings)} violations")

    # Group by file and rule
    by_file: dict[str, list[LintFinding]] = defaultdict(list)
    by_rule: dict[str, list[LintFinding]] = defaultdict(list)

    for finding in findings:
        by_file[finding.file].append(finding)
        by_rule[finding.rule].append(finding)

    # Classify each violation
    classified: dict[str, list[dict]] = {
        "safe-to-replace": [],
        "legitimate-exception": [],
        "needs-investigation": [],
    }

    for finding in findings:
        file_path = Path(finding.file)
        if not file_path.exists():
            # Handle Windows path normalization
            file_path = repo_root / finding.file.replace("C:/", "").lstrip("/")

        try:
            file_content = file_path.read_text(encoding="utf-8")
        except Exception:
            file_content = ""

        classification = classify_violation(finding, file_content)

        entry = {
            "file": finding.file,
            "line": finding.line,
            "column": finding.column,
            "rule": finding.rule,
            "message": finding.message,
            "classification": classification,
        }

        classified[classification].append(entry)

    # Create summary statistics
    summary = {
        "total_violations": len(findings),
        "by_rule": {rule: len(findings_list) for rule, findings_list in by_rule.items()},
        "by_file": {
            file: len(findings_list) for file, findings_list in by_file.items()
        },
        "by_classification": {
            classification: len(entries) for classification, entries in classified.items()
        },
    }

    # Create inventory structure
    inventory = {
        "summary": summary,
        "violations": {
            "safe-to-replace": sorted(
                classified["safe-to-replace"], key=lambda x: (x["file"], x["line"])
            ),
            "legitimate-exception": sorted(
                classified["legitimate-exception"], key=lambda x: (x["file"], x["line"])
            ),
            "needs-investigation": sorted(
                classified["needs-investigation"], key=lambda x: (x["file"], x["line"])
            ),
        },
    }

    # Write inventory
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")

    print(f"\nInventory created: {output_path}")
    print(f"  Total violations: {summary['total_violations']}")
    print(f"  Safe to replace: {summary['by_classification']['safe-to-replace']}")
    print(f"  Legitimate exceptions: {summary['by_classification']['legitimate-exception']}")
    print(f"  Needs investigation: {summary['by_classification']['needs-investigation']}")
    print("\nBy rule:")
    for rule, count in summary["by_rule"].items():
        print(f"  {rule}: {count}")


if __name__ == "__main__":
    output_path = repo_root / "dev" / "artifacts" / "time_usage_inventory.json"
    create_inventory(repo_root, output_path)

