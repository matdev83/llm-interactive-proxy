"""Analyze time usage violations and generate categorized report."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Add project root to path
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from tests.unit.test_time_usage_linter import _scan_repo_for_time_usage
from tests.utils.time_policy import load_allowlist


def main() -> None:
    """Generate categorized violation report."""
    cache_path = repo_root / ".pytest_cache" / "time_usage_lint_cache.json"
    
    # Clear cache to get fresh results
    if cache_path.exists():
        cache_path.unlink()
    
    allowlist = load_allowlist()
    findings = _scan_repo_for_time_usage(repo_root, allowlist)
    
    # Categorize by file and type
    by_file: dict[str, list[dict[str, any]]] = defaultdict(list)
    by_type: dict[str, int] = defaultdict(int)
    
    for finding in findings:
        by_file[finding.file].append({
            "line": finding.line,
            "column": finding.column,
            "rule": finding.rule,
            "message": finding.message,
        })
        by_type[finding.rule] += 1
    
    # Generate report
    report = {
        "summary": {
            "total_violations": len(findings),
            "by_type": dict(by_type),
            "files_affected": len(by_file),
        },
        "by_file": {
            file: {
                "count": len(violations),
                "violations": violations,
            }
            for file, violations in sorted(by_file.items())
        },
    }
    
    # Write report
    report_path = repo_root / "var" / "time_violations_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    
    print(f"Total violations: {len(findings)}")
    print(f"By type: {dict(by_type)}")
    print(f"Files affected: {len(by_file)}")
    print(f"\nReport written to: {report_path}")
    
    # Print top files by violation count
    print("\nTop 10 files by violation count:")
    sorted_files = sorted(by_file.items(), key=lambda x: len(x[1]), reverse=True)
    for file, violations in sorted_files[:10]:
        print(f"  {file}: {len(violations)} violations")


if __name__ == "__main__":
    main()

