import os
import re

import pytest

# Comprehensive Unicode emoji and symbol regex
# Includes emoticons, symbols, pictographs, transport, maps, flags, and other common symbols.
EMOJI_REGEX = re.compile(
    r"""[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002500-\U00002BEF\U00002700-\U000027BF\U00002B50\U0000200D\U00002300-\U000023FF\U000024C2-\U0001F251\U0001f926-\U0001f937\U00010000-\U0010ffff\u2640-\u2642\u2600-\u2B55\u200d\u23cf\u23e9\u231a\ufe0f\u3030]+""",
    flags=re.UNICODE,
)

# List of files to skip due to legitimate use of Unicode characters
# Paths are normalized to use forward slashes and be relative to the project root
SKIPPED_FILES = {
    os.path.normpath("src/core/testing/example_usage.py"),
    os.path.normpath("tests/example_usage.py"),
    os.path.normpath("tests/integration_demo.py"),
    os.path.normpath("tests/integration/test_anthropic_frontend_integration.py"),
    os.path.normpath("tests/integration/test_real_world_loop_detection.py"),
    os.path.normpath("tests/unit/test_di_container_usage.py"),
    os.path.normpath("tests/unit/anthropic_frontend_tests/test_anthropic_router.py"),
    os.path.normpath(
        "tests/unit/core/app/controllers/test_usage_controller_comprehensive.py"
    ),
    os.path.normpath(
        "tests/unit/core/services/test_usage_tracking_service_comprehensive.py"
    ),
    os.path.normpath("tests/unit/loop_detection/test_analyzer_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_buffer_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_detector_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_hasher.py"),
    os.path.normpath("tests/unit/loop_detection/test_hasher_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_streaming_comprehensive.py"),
}


def find_files_with_emojis(directory: str) -> list[tuple[str, int, str]]:
    """
    Scans a directory for files containing Unicode emojis.

    Args:
        directory: The directory to scan.

    Returns:
        A list of tuples, where each tuple contains the file path,
        line number, and the line of code with the emoji.
    """
    files_with_emojis = []
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    for root, _, files in os.walk(directory):
        for file in files:
            # Only scan Python files
            if not file.endswith(".py"):
                continue

            file_path = os.path.join(root, file)
            relative_file_path = os.path.normpath(
                os.path.relpath(file_path, start=project_root)
            )

            # Ignore __pycache__ directories, .pyc files, and explicitly skipped files
            if (
                "__pycache__" in root
                or file.endswith(".pyc")
                or relative_file_path in SKIPPED_FILES
            ):
                continue

            try:
                with open(file_path, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if EMOJI_REGEX.search(line):
                            files_with_emojis.append((file_path, i + 1, line.strip()))
            except (UnicodeDecodeError, OSError):
                # Ignore binary files or files that cannot be read
                continue
    return files_with_emojis


def test_no_unicode_emojis_in_codebase() -> None:
    """
    Test that there are no Unicode emojis in the codebase.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    src_dir = os.path.join(project_root, "src")
    tests_dir = os.path.join(project_root, "tests")

    files_with_emojis = find_files_with_emojis(src_dir)
    files_with_emojis.extend(find_files_with_emojis(tests_dir))

    if files_with_emojis:
        error_message = "Unicode emojis found in the following files:\\n"
        for file_path, line_num, line in files_with_emojis:
            error_message += f'  - {file_path}, line {line_num}: "{line}"\\n'
        pytest.fail(error_message)
