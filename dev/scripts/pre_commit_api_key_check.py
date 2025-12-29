import subprocess
import sys
from pathlib import Path

# Add the project root to the sys.path to import project modules
project_root = (
    Path(__file__).resolve().parents[2]
)  # Go up 2 levels to reach project root
sys.path.insert(0, str(project_root))

from src.core.common.logging_utils import (
    API_KEY_PATTERN,
    ZAI_KEY_PATTERN,
)


def _get_staged_file_paths() -> list[str]:
    """Get paths of files staged for commit (excluding deletions)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            check=True,
            cwd=project_root,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error getting staged files: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return []

    return [p for p in result.stdout.splitlines() if p.strip()]


def _read_staged_file_text(file_path: str) -> str | None:
    """Read file content from the git index (staged content), as UTF-8 text.

    Returns None if the file cannot be read from the index or appears to be binary.
    """
    try:
        result = subprocess.run(
            ["git", "show", f":{file_path}"],
            capture_output=True,
            check=True,
            cwd=project_root,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        print(
            f"Warning: Could not read staged content for {file_path}: {stderr}".strip(),
            file=sys.stderr,
        )
        return None

    data = result.stdout
    if b"\x00" in data:
        print(
            f"Skipping binary staged file during secret scan: {file_path}",
            file=sys.stderr,
        )
        return None

    return data.decode("utf-8", errors="replace")


def get_staged_files_content():
    """Returns a dictionary of staged file paths and their content."""
    staged_files = _get_staged_file_paths()
    if not staged_files:
        return {}

    file_contents: dict[str, str] = {}
    for file_path in staged_files:
        content = _read_staged_file_text(file_path)
        if content is not None:
            file_contents[file_path] = content

    return file_contents


def _scan_content_for_patterns(file_path: str, content: str) -> list[str]:
    """Scan content for generic API token patterns.

    Returns a list of matched sensitive snippets (masked) if any are found.
    """
    matches: list[str] = []
    try:
        for pat in (API_KEY_PATTERN, ZAI_KEY_PATTERN):
            for m in pat.finditer(content):
                token = m.group(0)
                # Mask token for output (first/last 4 chars)
                if len(token) > 10:
                    masked = f"{token[:4]}...{token[-4:]}"
                else:
                    masked = token
                matches.append(masked)
    except Exception as e:
        print(f"Warning: pattern scan failed for {file_path}: {e}", file=sys.stderr)
    return matches


def main():
    print("Running secret scan on staged files...")

    staged_files_content = get_staged_files_content()
    if not staged_files_content:
        print("No files staged for commit. Skipping check.")
        sys.exit(0)

    found_keys_in_staged_files = False

    for file_path, content in staged_files_content.items():
        # Skip pattern scan for files in 'dev/' directory and specific files with false positives
        excluded_files = {
            "src/core/commands/tool_call_text_parser.py",
            "src/core/services/universal_tool_executor.py",
            "config/backends/openai_codex/backend.example.yaml",
            "docs/user_guide/security/key-hygiene.md",
            "tests/unit/core/common/test_logging_utils.py",
            "tests/regression/test_api_key_redactor_memory_leak_regression.py",
            "tests/unit/test_compaction_domain.py",
            "tests/integration/test_history_compaction_integration.py",
            "test_scenario3_redaction.py",
            "MANUAL_TESTING_REPORT.md",
        }
        if file_path.startswith("dev/") or file_path in excluded_files:
            print(f"Skipping pattern scan for excluded file: {file_path}")
            continue
        pattern_hits = _scan_content_for_patterns(file_path, content)
        if pattern_hits:
            print(
                f"Error: Potential API token(s) detected by pattern scan in: {file_path}",
                file=sys.stderr,
            )
            for h in pattern_hits[:5]:  # show up to 5 masked hits
                print(f"  Token snippet: '{h}'", file=sys.stderr)
            print(
                "If these are false positives, consider excluding this file or revising the pattern.",
                file=sys.stderr,
            )
            found_keys_in_staged_files = True
            break  # one file is enough to fail the commit

    if found_keys_in_staged_files:
        print("\nCommit aborted: Sensitive API keys detected in staged files.")
        print("Please remove the API keys from the staged files before committing.")
        sys.exit(1)
    else:
        print("No secrets detected in staged files. Proceeding with commit.")
        sys.exit(0)


if __name__ == "__main__":
    main()
