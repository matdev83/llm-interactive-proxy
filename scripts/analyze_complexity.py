#!/usr/bin/env python3
"""Analyze code complexity using radon and identify top complex files."""
import argparse
import json
import sys
from pathlib import Path

from radon.complexity import cc_visit  # type: ignore[import-untyped]
from radon.metrics import mi_visit  # type: ignore[import-untyped]
from radon.raw import analyze  # type: ignore[import-untyped]


def analyze_file(file_path: Path):
    """Analyze a single file and return complexity metrics."""
    try:
        with open(file_path, encoding="utf-8") as f:
            code = f.read()

        # Cyclomatic complexity
        cc_results = cc_visit(code)
        max_complexity = 0
        total_complexity = 0
        function_count = 0

        from radon.visitors import Class, Function  # type: ignore[import-untyped]

        for block in cc_results:
            if hasattr(block, "complexity"):
                complexity = block.complexity
                max_complexity = max(max_complexity, complexity)
                total_complexity += complexity
                function_count += 1

        # Raw metrics (lines, LOC, etc.)
        raw_metrics = analyze(code)

        # Maintainability index
        mi_score = mi_visit(code, multi=True)

        # Build complexity blocks info
        complexity_blocks = []
        for block in cc_results:
            if hasattr(block, "complexity"):
                block_type = (
                    "class"
                    if isinstance(block, Class)
                    else (
                        "method"
                        if (isinstance(block, Function) and block.is_method)
                        else "function"
                    )
                )
                block_name = block.name
                if isinstance(block, Function) and block.classname:
                    block_name = f"{block.classname}.{block.name}"

                complexity_blocks.append(
                    {
                        "name": block_name,
                        "complexity": block.complexity,
                        "type": block_type,
                        "lineno": block.lineno,
                    }
                )

        return {
            "file": str(file_path),
            "lines": raw_metrics.loc,
            "lloc": raw_metrics.lloc,
            "sloc": raw_metrics.sloc,
            "comments": raw_metrics.comments,
            "max_complexity": max_complexity,
            "total_complexity": total_complexity,
            "function_count": function_count,
            "avg_complexity": (
                total_complexity / function_count if function_count > 0 else 0
            ),
            "maintainability_index": mi_score,
            "complexity_blocks": complexity_blocks,
        }
    except Exception as e:
        return {"file": str(file_path), "error": str(e)}


def get_streaming_contracts_scope_files(base_path: Path | None = None) -> list[Path]:
    """
    Get all files in the streaming-contracts refactor scope.

    Scope definition per design.md (single-level patterns only):
    - src/core/ports/streaming_contracts.py
    - src/core/ports/streaming/*.py (single level, no subdirectories)
    - src/core/domain/streaming/*.py (single level, no subdirectories)
    - src/core/domain/streaming/parsing/*.py (single level, explicit subdirectory)
    - src/core/transport/streaming/*.py (single level, no subdirectories)
    - src/core/services/streaming/error_mapping.py

    Args:
        base_path: Base path for file discovery. Defaults to current directory.

    Returns:
        Sorted list of Path objects for files in scope.
    """
    if base_path is None:
        base_path = Path(".")

    # Define refactor scope modules per design.md specification (single-level patterns)
    scope_patterns = [
        "src/core/ports/streaming_contracts.py",  # Facade
        "src/core/ports/streaming/*.py",  # Single level
        "src/core/domain/streaming/*.py",  # Single level
        "src/core/domain/streaming/parsing/*.py",  # Single level (explicit subdirectory)
        "src/core/transport/streaming/*.py",  # Single level
        "src/core/services/streaming/error_mapping.py",  # Error mapping only
    ]

    # Collect all files in scope
    scope_files = []

    for pattern in scope_patterns:
        # Handle glob patterns (single-level only per spec)
        for py_file in base_path.glob(pattern):
            if "__pycache__" not in str(py_file) and py_file.suffix == ".py":
                scope_files.append(py_file)

    # Remove duplicates and sort
    return sorted(set(scope_files))


def get_tool_call_reactor_scope_files(base_path: Path | None = None) -> list[Path]:
    """
    Get all files in the tool-call-reactor refactor scope.

    Scope definition per design.md:
    - All production files in src/core/services/tool_call_reactor/ (excluding __init__.py and README.md)
    - Thin adapter file src/core/services/tool_call_reactor_middleware.py

    Args:
        base_path: Base path for file discovery. Defaults to current directory.

    Returns:
        Sorted list of Path objects for files in scope.
    """
    if base_path is None:
        base_path = Path(".")

    scope_files = []

    # Add all production files in tool_call_reactor directory
    reactor_dir = base_path / "src/core/services/tool_call_reactor"
    if reactor_dir.exists():
        for py_file in reactor_dir.rglob("*.py"):
            # Exclude __init__.py and README.md
            if (
                "__pycache__" not in str(py_file)
                and py_file.name != "__init__.py"
                and py_file.suffix == ".py"
            ):
                scope_files.append(py_file)

    # Add thin adapter file
    middleware_file = base_path / "src/core/services/tool_call_reactor_middleware.py"
    if middleware_file.exists() and middleware_file.suffix == ".py":
        scope_files.append(middleware_file)

    # Remove duplicates and sort
    return sorted(set(scope_files))


def get_di_services_scope_files(base_path: Path | None = None) -> list[Path]:
    """
    Get all files in the DI services refactor scope.

    Scope definition per design.md:
    - src/core/di/services.py (facade)
    - src/core/di/provider_lifecycle.py (lifecycle module)
    - src/core/di/diagnostics.py (diagnostics module)
    - src/core/di/registrations/**/*.py (all registrar modules, recursive)
    - src/core/di/registration_helpers/**/*.py (all helper modules, recursive)

    Args:
        base_path: Base path for file discovery. Defaults to current directory.

    Returns:
        Sorted list of Path objects for files in scope.
    """
    if base_path is None:
        base_path = Path(".")

    # Define refactor scope modules per design.md specification
    scope_patterns = [
        "src/core/di/services.py",  # Facade
        "src/core/di/provider_lifecycle.py",  # Lifecycle module
        "src/core/di/diagnostics.py",  # Diagnostics module
        "src/core/di/registrations/**/*.py",  # All registrar modules (recursive)
        "src/core/di/registration_helpers/**/*.py",  # All helper modules (recursive)
    ]

    # Collect all files in scope
    scope_files = []

    for pattern in scope_patterns:
        if "**" in pattern:
            # Handle glob patterns (recursive)
            for py_file in base_path.glob(pattern):
                if "__pycache__" not in str(py_file) and py_file.suffix == ".py":
                    scope_files.append(py_file)
        else:
            # Single file pattern
            py_file = base_path / pattern
            if py_file.exists() and py_file.suffix == ".py":
                scope_files.append(py_file)

    # Remove duplicates and sort
    return sorted(set(scope_files))


# Thresholds from requirements.md
MAX_LOC = 600
MAX_FUNCTION_CC = 50
MAX_MODULE_CC = 200


def validate_streaming_contracts_files(
    scope_files: list[Path], base_path: Path
) -> tuple[list[dict], int]:
    """
    Validate a list of files against streaming contracts thresholds.

    Args:
        scope_files: List of file paths to validate
        base_path: Base path for relative path calculation

    Returns:
        Tuple of (violations list, passed count)
    """
    violations = []
    passed_count = 0

    for file_path in scope_files:
        result = analyze_file(file_path)
        if "error" in result:
            violations.append(
                {
                    "file": str(file_path),
                    "error": result["error"],
                    "type": "analysis_error",
                }
            )
            continue

        file_violations = []
        rel_path = str(file_path.relative_to(base_path))

        # Check LOC threshold
        if result["lines"] >= MAX_LOC:
            file_violations.append(
                f"LOC violation: {result['lines']} lines (threshold: < {MAX_LOC})"
            )

        # Check max function CC threshold
        if result["max_complexity"] >= MAX_FUNCTION_CC:
            file_violations.append(
                f"Max function CC violation: {result['max_complexity']} "
                f"(threshold: < {MAX_FUNCTION_CC})"
            )
            # Find the violating function
            max_block = max(
                result["complexity_blocks"],
                key=lambda x: x["complexity"],
                default=None,
            )
            if max_block:
                file_violations.append(
                    f"  Violating function: {max_block['type']} {max_block['name']} "
                    f"(line {max_block['lineno']})"
                )

        # Check total module CC threshold
        if result["total_complexity"] >= MAX_MODULE_CC:
            file_violations.append(
                f"Total module CC violation: {result['total_complexity']} "
                f"(threshold: < {MAX_MODULE_CC})"
            )

        if file_violations:
            violations.append(
                {
                    "file": rel_path,
                    "violations": file_violations,
                    "metrics": {
                        "lines": result["lines"],
                        "max_complexity": result["max_complexity"],
                        "total_complexity": result["total_complexity"],
                    },
                }
            )
        else:
            passed_count += 1

    return violations, passed_count


def validate_streaming_refactor_scope() -> int:
    """
    Validate complexity and LOC thresholds for streaming refactor scope.

    Checks all modules in the refactor scope against thresholds:
    - LOC < 600 per file (Requirements 1.1, 1.2)
    - Max function CC < 50 (Requirement 1.3)
    - Total module CC < 200 (Requirement 1.5)

    Returns:
        0 if all thresholds pass, 1 if any violations found
    """
    base_path = Path(".")
    scope_files = get_streaming_contracts_scope_files(base_path)

    if not scope_files:
        print("Warning: No files found in refactor scope")
        return 1

    print("=" * 100)
    print("STREAMING REFACTOR SCOPE VALIDATION")
    print("=" * 100)
    print(f"\nChecking {len(scope_files)} files against thresholds:")
    print(f"  - LOC per file: < {MAX_LOC}")
    print(f"  - Max function CC: < {MAX_FUNCTION_CC}")
    print(f"  - Total module CC: < {MAX_MODULE_CC}")
    print()

    violations, passed_count = validate_streaming_contracts_files(
        scope_files, base_path
    )

    # Report results
    if violations:
        print("=" * 100)
        print(f"VALIDATION FAILED: {len(violations)} file(s) with violations")
        print("=" * 100)
        print()

        for violation in violations:
            print(f"[FAIL] {violation['file']}")
            if "error" in violation:
                print(f"   Error: {violation['error']}")
            else:
                if "metrics" in violation:
                    metrics = violation["metrics"]
                    print(
                        f"   Metrics: {metrics['lines']} lines, "
                        f"max CC: {metrics['max_complexity']}, "
                        f"total CC: {metrics['total_complexity']}"
                    )
                print("   Violations:")
                for v in violation["violations"]:
                    print(f"     - {v}")
            print()

        print(f"[PASS] Passed: {passed_count}/{len(scope_files)} files")
        return 1
    else:
        print("=" * 100)
        print(f"[PASS] VALIDATION PASSED: All {len(scope_files)} files meet thresholds")
        print("=" * 100)
        return 0


def validate_tool_call_reactor_files(
    scope_files: list[Path], base_path: Path
) -> tuple[list[dict], int]:
    """
    Validate a list of files against tool-call-reactor thresholds.

    Args:
        scope_files: List of file paths to validate
        base_path: Base path for relative path calculation

    Returns:
        Tuple of (violations list, passed count)
    """
    violations = []
    passed_count = 0

    for file_path in scope_files:
        result = analyze_file(file_path)
        if "error" in result:
            violations.append(
                {
                    "file": str(file_path),
                    "error": result["error"],
                    "type": "analysis_error",
                }
            )
            continue

        file_violations = []
        rel_path = str(file_path.relative_to(base_path))

        # Check LOC threshold
        if result["lines"] >= MAX_LOC:
            file_violations.append(
                f"LOC violation: {result['lines']} lines (threshold: < {MAX_LOC})"
            )

        # Check max function CC threshold
        if result["max_complexity"] >= MAX_FUNCTION_CC:
            file_violations.append(
                f"Max function CC violation: {result['max_complexity']} "
                f"(threshold: < {MAX_FUNCTION_CC})"
            )
            # Find the violating function
            max_block = max(
                result["complexity_blocks"],
                key=lambda x: x["complexity"],
                default=None,
            )
            if max_block:
                file_violations.append(
                    f"  Violating function: {max_block['type']} {max_block['name']} "
                    f"(line {max_block['lineno']})"
                )

        if file_violations:
            violations.append(
                {
                    "file": rel_path,
                    "violations": file_violations,
                    "metrics": {
                        "lines": result["lines"],
                        "max_complexity": result["max_complexity"],
                        "total_complexity": result["total_complexity"],
                    },
                }
            )
        else:
            passed_count += 1

    return violations, passed_count


def validate_di_services_files(
    scope_files: list[Path], base_path: Path
) -> tuple[list[dict], int]:
    """
    Validate a list of files against DI services refactor thresholds.

    Args:
        scope_files: List of file paths to validate
        base_path: Base path for relative path calculation

    Returns:
        Tuple of (violations list, passed count)
    """
    violations = []
    passed_count = 0

    for file_path in scope_files:
        result = analyze_file(file_path)
        if "error" in result:
            violations.append(
                {
                    "file": str(file_path),
                    "error": result["error"],
                    "type": "analysis_error",
                }
            )
            continue

        file_violations = []
        rel_path = str(file_path.relative_to(base_path))

        # Check LOC threshold
        if result["lines"] >= MAX_LOC:
            file_violations.append(
                f"LOC violation: {result['lines']} lines (threshold: < {MAX_LOC})"
            )

        # Check max function CC threshold
        if result["max_complexity"] >= MAX_FUNCTION_CC:
            file_violations.append(
                f"Max function CC violation: {result['max_complexity']} "
                f"(threshold: < {MAX_FUNCTION_CC})"
            )
            # Find the violating function
            max_block = max(
                result["complexity_blocks"],
                key=lambda x: x["complexity"],
                default=None,
            )
            if max_block:
                file_violations.append(
                    f"  Violating function: {max_block['type']} {max_block['name']} "
                    f"(line {max_block['lineno']})"
                )

        if file_violations:
            violations.append(
                {
                    "file": rel_path,
                    "violations": file_violations,
                    "metrics": {
                        "lines": result["lines"],
                        "max_complexity": result["max_complexity"],
                        "total_complexity": result["total_complexity"],
                    },
                }
            )
        else:
            passed_count += 1

    return violations, passed_count


def validate_tool_call_reactor_refactor_scope() -> int:
    """
    Validate complexity and LOC thresholds for tool-call-reactor refactor scope.

    Checks all modules in the refactor scope against thresholds:
    - LOC < 600 per file (Requirement 8.1)
    - Max function CC < 50 (Requirement 8.2)

    Returns:
        0 if all thresholds pass, 1 if any violations found
    """
    base_path = Path(".")
    scope_files = get_tool_call_reactor_scope_files(base_path)

    if not scope_files:
        print("Warning: No files found in refactor scope")
        return 1

    print("=" * 100)
    print("TOOL-CALL-REACTOR REFACTOR SCOPE VALIDATION")
    print("=" * 100)
    print(f"\nChecking {len(scope_files)} files against thresholds:")
    print(f"  - LOC per file: < {MAX_LOC}")
    print(f"  - Max function CC: < {MAX_FUNCTION_CC}")
    print()

    violations, passed_count = validate_tool_call_reactor_files(scope_files, base_path)

    # Report results
    if violations:
        print("=" * 100)
        print(f"VALIDATION FAILED: {len(violations)} file(s) with violations")
        print("=" * 100)
        print()

        for violation in violations:
            print(f"[FAIL] {violation['file']}")
            if "error" in violation:
                print(f"   Error: {violation['error']}")
            else:
                if "metrics" in violation:
                    metrics = violation["metrics"]
                    print(
                        f"   Metrics: {metrics['lines']} lines, "
                        f"max CC: {metrics['max_complexity']}, "
                        f"total CC: {metrics['total_complexity']}"
                    )
                print("   Violations:")
                for v in violation["violations"]:
                    print(f"     - {v}")
            print()

        print(f"[PASS] Passed: {passed_count}/{len(scope_files)} files")
        return 1
    else:
        print("=" * 100)
        print(f"[PASS] VALIDATION PASSED: All {len(scope_files)} files meet thresholds")
        print("=" * 100)
        return 0


def validate_di_services_refactor_scope() -> int:
    """
    Validate complexity and LOC thresholds for DI services refactor scope.

    Checks all modules in the refactor scope against thresholds:
    - LOC < 600 per file (Requirement 4.1)
    - Max function CC < 50 (Requirement 4.2)

    Returns:
        0 if all thresholds pass, 1 if any violations found
    """
    base_path = Path(".")
    scope_files = get_di_services_scope_files(base_path)

    if not scope_files:
        print("Warning: No files found in refactor scope")
        return 1

    print("=" * 100)
    print("DI SERVICES REFACTOR SCOPE VALIDATION")
    print("=" * 100)
    print(f"\nChecking {len(scope_files)} files against thresholds:")
    print(f"  - LOC per file: < {MAX_LOC}")
    print(f"  - Max function CC: < {MAX_FUNCTION_CC}")
    print()

    violations, passed_count = validate_di_services_files(scope_files, base_path)

    # Report results
    if violations:
        print("=" * 100)
        print(f"VALIDATION FAILED: {len(violations)} file(s) with violations")
        print("=" * 100)
        print()

        for violation in violations:
            print(f"[FAIL] {violation['file']}")
            if "error" in violation:
                print(f"   Error: {violation['error']}")
            else:
                if "metrics" in violation:
                    metrics = violation["metrics"]
                    print(
                        f"   Metrics: {metrics['lines']} lines, "
                        f"max CC: {metrics['max_complexity']}, "
                        f"total CC: {metrics['total_complexity']}"
                    )
                print("   Violations:")
                for v in violation["violations"]:
                    print(f"     - {v}")
            print()

        print(f"[PASS] Passed: {passed_count}/{len(scope_files)} files")
        return 1
    else:
        print("=" * 100)
        print(f"[PASS] VALIDATION PASSED: All {len(scope_files)} files meet thresholds")
        print("=" * 100)
        return 0


def main():
    """Main function to analyze all Python files."""
    parser = argparse.ArgumentParser(
        description="Analyze code complexity using radon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--validate-refactor-scope",
        action="store_true",
        help="Validate streaming refactor scope against LOC/CC thresholds and exit",
    )
    parser.add_argument(
        "--validate-tool-call-reactor-scope",
        action="store_true",
        help="Validate tool-call-reactor refactor scope against LOC/CC thresholds and exit",
    )
    parser.add_argument(
        "--validate-di-services-scope",
        action="store_true",
        help="Validate DI services refactor scope against LOC/CC thresholds and exit",
    )

    args = parser.parse_args()

    # If validation mode requested, run validation and exit
    if args.validate_di_services_scope:
        exit_code = validate_di_services_refactor_scope()
        sys.exit(exit_code)

    if args.validate_tool_call_reactor_scope:
        exit_code = validate_tool_call_reactor_refactor_scope()
        sys.exit(exit_code)

    if args.validate_refactor_scope:
        exit_code = validate_streaming_refactor_scope()
        sys.exit(exit_code)

    # Default: existing analysis/reporting behavior
    src_dir = Path("src")
    if not src_dir.exists():
        print(f"Error: {src_dir} does not exist")
        sys.exit(1)

    results = []

    # Find all Python files
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file) or ".pyc" in str(py_file):
            continue

        result = analyze_file(py_file)
        if "error" not in result:
            results.append(result)

    # Filter out files with no complexity (constants, empty __init__.py, etc.)
    results_with_complexity = [r for r in results if r.get("max_complexity", 0) > 0]

    # Sort by multiple criteria
    # Primary: max complexity, Secondary: total complexity, Tertiary: lines
    results_with_complexity.sort(
        key=lambda x: (-x["max_complexity"], -x["total_complexity"], -x["lines"])
    )

    # Also sort all results by lines for reference
    results_by_lines = sorted(results, key=lambda x: -x["lines"])

    # Print top 20 most complex files (with actual complexity)
    print("=" * 100)
    print("TOP 20 MOST COMPLEX FILES (with actual complexity)")
    print("=" * 100)
    print(
        f"{'File':<60} {'Lines':<8} {'Max CC':<8} {'Total CC':<10} {'Funcs':<8} {'Avg CC':<8} {'MI':<8}"
    )
    print("-" * 100)

    for _i, result in enumerate(results_with_complexity[:20], 1):
        print(
            f"{result['file']:<60} {result['lines']:<8} {result['max_complexity']:<8} "
            f"{result['total_complexity']:<10} {result['function_count']:<8} "
            f"{result['avg_complexity']:<8.2f} {result['maintainability_index']:<8.2f}"
        )

    # Print top 20 largest files (by lines)
    print("\n" + "=" * 100)
    print("TOP 20 LARGEST FILES (by lines of code)")
    print("=" * 100)
    print(
        f"{'File':<60} {'Lines':<8} {'LLOC':<8} {'SLOC':<8} {'Max CC':<8} {'Total CC':<10}"
    )
    print("-" * 100)

    for _i, result in enumerate(results_by_lines[:20], 1):
        print(
            f"{result['file']:<60} {result['lines']:<8} {result['lloc']:<8} "
            f"{result['sloc']:<8} {result['max_complexity']:<8} {result['total_complexity']:<10}"
        )

    # Save detailed results to JSON
    output_file = Path("complexity_analysis.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "by_complexity": results_with_complexity,
                "by_lines": results_by_lines,
                "all": results,
            },
            f,
            indent=2,
        )

    print(f"\nDetailed results saved to: {output_file}")

    # Print top 5 files with their most complex functions
    print("\n" + "=" * 100)
    print("TOP 5 MOST COMPLEX FILES - DETAILED BREAKDOWN")
    print("=" * 100)

    for i, result in enumerate(results_with_complexity[:5], 1):
        print(f"\n{i}. {result['file']}")
        print(
            f"   Lines: {result['lines']}, LLOC: {result['lloc']}, SLOC: {result['sloc']}"
        )
        print(
            f"   Max Complexity: {result['max_complexity']}, Total: {result['total_complexity']}"
        )
        print(
            f"   Functions: {result['function_count']}, Avg Complexity: {result['avg_complexity']:.2f}"
        )
        print(f"   Maintainability Index: {result['maintainability_index']:.2f}")

        # Show top 5 most complex functions/methods
        complex_blocks = sorted(
            result["complexity_blocks"], key=lambda x: x["complexity"], reverse=True
        )
        print("   Top complex functions:")
        for block in complex_blocks[:5]:
            print(
                f"     - {block['type']} {block['name']} (line {block['lineno']}): complexity {block['complexity']}"
            )


if __name__ == "__main__":
    main()
