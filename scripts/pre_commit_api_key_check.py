import subprocess
import sys
from pathlib import Path

# Add the project root to the sys.path to import project modules
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.core.common.logging_utils import (
    API_KEY_PATTERN,
    ZAI_KEY_PATTERN,
)


def get_staged_files_content():
    """Returns a dictionary of staged file paths and their content."""
    try:
        # Get names of staged files
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        staged_files = result.stdout.strip().split("\n")
        if not staged_files or staged_files == [
            ""
        ]:  # Handle case where no files are staged
            return {}

        file_contents = {}
        for file_path in staged_files:
            if file_path:
                full_path = project_root / file_path
                if full_path.is_file():
                    try:
                        with open(full_path, encoding="utf-8") as f:
                            file_contents[file_path] = f.read()
                    except Exception as e:
                        print(
                            f"Warning: Could not read file {file_path}: {e}",
                            file=sys.stderr,
                        )
        return file_contents
    except subprocess.CalledProcessError as e:
        print(f"Error getting staged files: {e}", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        return {}


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
        # Skip pattern scan for files in the 'dev/' directory and specific files with false positives
        excluded_files = {
            "src/core/commands/tool_call_text_parser.py",
            "src/core/services/universal_tool_executor.py",
            "config/backends/openai_codex/backend.example.yaml",
            "docs/user_guide/security/key-hygiene.md",
            "tests/unit/core/common/test_logging_utils.py",
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
