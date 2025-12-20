#!/usr/bin/env python3
"""Find files over 1000 lines and rank them by size and complexity."""
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

        # Count total lines
        total_lines = len(code.splitlines())

        # Cyclomatic complexity
        cc_results = cc_visit(code)
        max_complexity = 0
        total_complexity = 0
        function_count = 0

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

        return {
            "file": str(file_path),
            "total_lines": total_lines,
            "lines": raw_metrics.loc,
            "lloc": raw_metrics.lloc,
            "sloc": raw_metrics.sloc,
            "max_complexity": max_complexity,
            "total_complexity": total_complexity,
            "function_count": function_count,
            "avg_complexity": (
                total_complexity / function_count if function_count > 0 else 0
            ),
            "maintainability_index": mi_score,
        }
    except Exception as e:
        return {"file": str(file_path), "error": str(e)}


def main():
    """Main function to find and analyze large files."""
    src_dir = Path("src")
    if not src_dir.exists():
        print(f"Error: {src_dir} does not exist")
        sys.exit(1)

    # First pass: find files with > 1000 lines
    large_files = []
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file) or ".pyc" in str(py_file):
            continue

        try:
            with open(py_file, encoding="utf-8") as f:
                line_count = len(f.readlines())
            if line_count > 1000:
                large_files.append((py_file, line_count))
        except Exception:
            continue

    print(f"Found {len(large_files)} files with over 1000 lines\n")

    # Analyze all large files
    results = []
    for file_path, _line_count in large_files:
        result = analyze_file(file_path)
        if "error" not in result:
            results.append(result)
        else:
            print(f"Warning: Error analyzing {file_path}: {result['error']}")

    if not results:
        print("No files could be analyzed.")
        sys.exit(1)

    # Sort by total lines (size)
    results_by_size = sorted(results, key=lambda x: -x["total_lines"])

    # Sort by max complexity
    results_by_complexity = sorted(
        results, key=lambda x: (-x["max_complexity"], -x["total_complexity"])
    )

    # Combined score: prioritize files that are both large AND complex
    # Score = (lines/1000) * (max_complexity/10) + total_complexity/100
    for result in results:
        result["combined_score"] = (result["total_lines"] / 1000) * (
            result["max_complexity"] / 10
        ) + result["total_complexity"] / 100

    results_by_combined = sorted(results, key=lambda x: -x["combined_score"])

    # Print top 5 by size
    print("=" * 120)
    print("TOP 5 LARGEST FILES (>1000 lines)")
    print("=" * 120)
    print(
        f"{'Rank':<6} {'File':<70} {'Lines':<8} {'Max CC':<10} {'Total CC':<12} {'MI':<8}"
    )
    print("-" * 120)

    for i, result in enumerate(results_by_size[:5], 1):
        print(
            f"{i:<6} {result['file']:<70} {result['total_lines']:<8} "
            f"{result['max_complexity']:<10} {result['total_complexity']:<12} "
            f"{result['maintainability_index']:<8.2f}"
        )

    # Print top 5 by complexity
    print("\n" + "=" * 120)
    print("TOP 5 MOST COMPLEX FILES (>1000 lines)")
    print("=" * 120)
    print(
        f"{'Rank':<6} {'File':<70} {'Lines':<8} {'Max CC':<10} {'Total CC':<12} {'MI':<8}"
    )
    print("-" * 120)

    for i, result in enumerate(results_by_complexity[:5], 1):
        print(
            f"{i:<6} {result['file']:<70} {result['total_lines']:<8} "
            f"{result['max_complexity']:<10} {result['total_complexity']:<12} "
            f"{result['maintainability_index']:<8.2f}"
        )

    # Print top 5 by combined score (large AND complex)
    print("\n" + "=" * 120)
    print("TOP 5 LARGEST AND MOST COMPLEX FILES (>1000 lines)")
    print("=" * 120)
    print(
        f"{'Rank':<6} {'File':<70} {'Lines':<8} {'Max CC':<10} {'Total CC':<12} {'Score':<10}"
    )
    print("-" * 120)

    for i, result in enumerate(results_by_combined[:5], 1):
        print(
            f"{i:<6} {result['file']:<70} {result['total_lines']:<8} "
            f"{result['max_complexity']:<10} {result['total_complexity']:<12} "
            f"{result['combined_score']:<10.2f}"
        )


if __name__ == "__main__":
    main()
