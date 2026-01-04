"""Script to detect potential memory leak patterns in the codebase.

This script searches for common patterns that could lead to memory leaks.
"""

import re
from collections.abc import Iterator
from pathlib import Path


def find_unbounded_dicts(file_path: Path) -> Iterator[tuple[int, str]]:
    """Find dictionary initializations that might grow unbounded."""
    pattern = re.compile(
        r"self\._[a-zA-Z_]+:\s*dict\[.*?\]\s*=\s*\{\}|"
        r"self\._[a-zA-Z_]+\s*=\s*\{\}|"
        r"self\._[a-zA-Z_]+\s*=\s*dict\(\)"
    )

    with open(file_path, encoding="utf-8") as f:
        lines = f.readlines()
        for line_num, line in enumerate(lines, 1):
            if pattern.search(line):
                # Skip if it's a test file
                if "test" in str(file_path).lower():
                    continue

                # Check if next 30 lines have maxsize, TTL, or cleanup logic
                context = "".join(lines[line_num : min(len(lines), line_num + 30)])
                has_protection = any(
                    re.search(pattern, context, re.IGNORECASE)
                    for pattern in [
                        r"maxsize|max_size|max_entries|max_[a-z_]+|_MAX_",
                        r"ttl|timeout|expire|cleanup|evict",
                        r"TTLCache|LRUCache|cachetools",
                        r"limit|bound|_limit|_bound",
                    ]
                )

                if not has_protection:
                    yield (line_num, line.strip())


def find_list_append_without_bounds(file_path: Path) -> Iterator[tuple[int, str]]:
    """Find list append operations that might grow unbounded."""
    pattern = re.compile(r"\.append\(|\.extend\(")

    with open(file_path, encoding="utf-8") as f:
        lines = f.readlines()
        for line_num, line in enumerate(lines, 1):
            if pattern.search(line):
                # Skip if it's a test file or obvious safe patterns
                if any(
                    skip in line.lower()
                    for skip in ["test", "assert", "mock", "fixture"]
                ):
                    continue

                # Check context - is there cleanup logic nearby?
                context_start = max(0, line_num - 20)
                context_end = min(len(lines), line_num + 20)
                context = "".join(lines[context_start:context_end])

                # Look for cleanup patterns
                has_cleanup = any(
                    re.search(pattern, context, re.IGNORECASE)
                    for pattern in [
                        r"maxsize|max_size|max_entries|max_[a-z_]+|_MAX_",
                        r"ttl|timeout|expire|cleanup|evict|remove|pop\(|clear\(\)",
                        r"limit|bound|cap|_limit|_bound",
                        r"while.*len\(.*\)\s*>\s*|if.*len\(.*\)\s*>",
                    ]
                )

                # Check if it's a class attribute that might accumulate
                is_class_attr = "self." in line or "cls." in line

                if not has_cleanup and is_class_attr:
                    yield (line_num, line.strip())


def find_event_subscriptions(file_path: Path) -> Iterator[tuple[int, str]]:
    """Find event subscriptions that might not be cleaned up."""
    pattern = re.compile(r"\.subscribe\(|event_bus\.subscribe\(")

    with open(file_path, encoding="utf-8") as f:
        lines = f.readlines()
        for line_num, line in enumerate(lines, 1):
            if pattern.search(line):
                # Check if there's a corresponding unsubscribe
                remaining_lines = "".join(lines[line_num : line_num + 50])
                has_unsubscribe = "unsubscribe" in remaining_lines.lower()

                if not has_unsubscribe:
                    yield (line_num, line.strip())


def find_async_task_creation(file_path: Path) -> Iterator[tuple[int, str]]:
    """Find async task creation that might not be tracked."""
    pattern = re.compile(r"asyncio\.create_task\(")

    with open(file_path, encoding="utf-8") as f:
        lines = f.readlines()
        for line_num, line in enumerate(lines, 1):
            if pattern.search(line):
                # Check if task is tracked or awaited
                remaining_lines = "".join(lines[line_num : line_num + 20])
                has_tracking = any(
                    keyword in remaining_lines.lower()
                    for keyword in [
                        "await",
                        "add_background_task",
                        "track",
                        "done_callback",
                    ]
                )

                if not has_tracking:
                    yield (line_num, line.strip())


def find_generator_creation(file_path: Path) -> Iterator[tuple[int, str]]:
    """Find generator creation that might not be consumed."""
    pattern = re.compile(r"yield\s+")

    with open(file_path, encoding="utf-8") as f:
        lines = f.readlines()
        for line_num, line in enumerate(lines, 1):
            if pattern.search(line):
                # Check if generator is consumed
                remaining_lines = "".join(lines[line_num : line_num + 30])
                has_consumption = any(
                    keyword in remaining_lines.lower()
                    for keyword in ["async for", "for", "await", "next(", "send("]
                )

                if not has_consumption and "def " in line:
                    yield (line_num, line.strip())


def scan_file(file_path: Path) -> dict:
    """Scan a file for potential memory leak patterns."""
    results = {
        "file": str(file_path),
        "unbounded_dicts": list(find_unbounded_dicts(file_path)),
        "unbounded_appends": list(find_list_append_without_bounds(file_path)),
        "event_subscriptions": list(find_event_subscriptions(file_path)),
        "async_tasks": list(find_async_task_creation(file_path)),
        "generators": list(find_generator_creation(file_path)),
    }

    # Only return if there are findings
    if any(results.values()):
        return results
    return None


def main():
    """Main entry point."""
    src_dir = Path(__file__).parent.parent.parent / "src"

    print("=" * 70)
    print("Memory Leak Pattern Detection")
    print("=" * 70)
    print()

    findings = []

    # Scan Python files in src/
    for py_file in src_dir.rglob("*.py"):
        # Skip cache and test files
        if any(
            skip in str(py_file)
            for skip in ["__pycache__", ".pyc", "test_", "_test.py", "tests/"]
        ):
            continue

        result = scan_file(py_file)
        if result:
            # Only include if there are actual findings (not just empty lists)
            if any(result[key] for key in result if key != "file"):
                findings.append(result)

    # Report findings
    if not findings:
        print("No obvious memory leak patterns detected.")
        print("(Note: This is a heuristic check - manual review still recommended)")
        return

    print(f"Found potential issues in {len(findings)} files:\n")

    for finding in findings:
        print(f"\n[FILE] {finding['file']}")
        print("-" * 70)

        if finding["unbounded_dicts"]:
            print(
                f"  [WARN] Unbounded dictionaries ({len(finding['unbounded_dicts'])}):"
            )
            for line_num, line in finding["unbounded_dicts"][:5]:
                print(f"     Line {line_num}: {line[:60]}")

        if finding["unbounded_appends"]:
            print(
                f"  [WARN] List append without bounds ({len(finding['unbounded_appends'])}):"
            )
            for line_num, line in finding["unbounded_appends"][:5]:
                print(f"     Line {line_num}: {line[:60]}")

        if finding["event_subscriptions"]:
            print(
                f"  [WARN] Event subscriptions without cleanup ({len(finding['event_subscriptions'])}):"
            )
            for line_num, line in finding["event_subscriptions"][:5]:
                print(f"     Line {line_num}: {line[:60]}")

        if finding["async_tasks"]:
            print(
                f"  [WARN] Async tasks without tracking ({len(finding['async_tasks'])}):"
            )
            for line_num, line in finding["async_tasks"][:5]:
                print(f"     Line {line_num}: {line[:60]}")

        if finding["generators"]:
            print(
                f"  [WARN] Generators without consumption ({len(finding['generators'])}):"
            )
            for line_num, line in finding["generators"][:5]:
                print(f"     Line {line_num}: {line[:60]}")

    print("\n" + "=" * 70)
    print("Note: These are heuristic checks. False positives are possible.")
    print("Manual review recommended for flagged areas.")
    print("=" * 70)


if __name__ == "__main__":
    main()
