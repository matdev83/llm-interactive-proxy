#!/usr/bin/env python3
"""Analyze code complexity using radon and identify top complex files."""
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


def main():
    """Main function to analyze all Python files."""
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
