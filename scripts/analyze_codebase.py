import glob
import os

from radon.complexity import cc_visit  # type: ignore[import-untyped]
from radon.metrics import mi_visit  # type: ignore[import-untyped]
from radon.raw import analyze  # type: ignore[import-untyped]


def analyze_file(file_path):
    try:
        with open(file_path, encoding="utf-8") as f:
            code = f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None

    try:
        # Cyclomatic Complexity
        cc_blocks = cc_visit(code)
        total_cc = sum(block.complexity for block in cc_blocks)
        max_cc = max((block.complexity for block in cc_blocks), default=0)

        # Maintainability Index
        mi_score = mi_visit(code, multi=True)

        # Raw metrics
        raw_metrics = analyze(code)

        return {
            "path": file_path,
            "total_cc": total_cc,
            "max_cc": max_cc,
            "mi": mi_score,
            "loc": raw_metrics.loc,
            "sloc": raw_metrics.sloc,
        }
    except Exception:
        # print(f"Error analyzing {file_path}: {e}")
        return None


def main():
    source_dir = "src"
    files = glob.glob(os.path.join(source_dir, "**/*.py"), recursive=True)

    results = []

    print(f"Analyzing {len(files)} files in {source_dir}...")

    for file_path in files:
        metrics = analyze_file(file_path)
        if metrics:
            results.append(metrics)

    # Sort by various metrics to find "God Objects"

    # 1. High Complexity (Max CC)
    print("\n--- Top 10 Files by Max Cyclomatic Complexity ---")
    results.sort(key=lambda x: x["max_cc"], reverse=True)
    for r in results[:10]:
        print(
            f"{r['path']}: Max CC={r['max_cc']}, Total CC={r['total_cc']}, LOC={r['loc']}, MI={r['mi']:.2f}"
        )

    # 2. High LOC
    print("\n--- Top 10 Files by LOC ---")
    results.sort(key=lambda x: x["loc"], reverse=True)
    for r in results[:10]:
        print(f"{r['path']}: LOC={r['loc']}, Max CC={r['max_cc']}, MI={r['mi']:.2f}")

    # 3. Low Maintainability Index
    print("\n--- Top 10 Files by Lowest Maintainability Index ---")
    results.sort(key=lambda x: x["mi"])
    for r in results[:10]:
        print(f"{r['path']}: MI={r['mi']:.2f}, LOC={r['loc']}, Max CC={r['max_cc']}")

    # 4. Weighted Score (Custom God Object Score)
    # Heuristic: High LOC + High CC - Low MI
    # Normalized score could be better, but let's try a simple product or sum
    # Let's use: score = (LOC / 100) * Max_CC / (MI if MI > 0 else 1)

    print("\n--- Top 10 'God Object' Candidates (Heuristic Score) ---")

    def god_score(r):
        mi = r["mi"] if r["mi"] > 1 else 1
        return (r["loc"]) * r["max_cc"] / mi

    results.sort(key=god_score, reverse=True)
    for r in results[:10]:
        print(
            f"{r['path']}: Score={god_score(r):.2f} (LOC={r['loc']}, MaxCC={r['max_cc']}, MI={r['mi']:.2f})"
        )


if __name__ == "__main__":
    main()
