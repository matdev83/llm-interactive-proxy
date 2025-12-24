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
        "tests/unit/core/app/controllers/test_usage_controller_comprehensive.py",
    ),
    os.path.normpath(
        "tests/unit/core/services/test_usage_tracking_service_comprehensive.py",
    ),
    os.path.normpath("tests/unit/loop_detection/test_analyzer_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_buffer_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_detector_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_hasher.py"),
    os.path.normpath("tests/unit/loop_detection/test_hasher_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_streaming_comprehensive.py"),
    os.path.normpath("tests/unit/connectors/test_openai_codex_prompt_handling.py"),
    os.path.normpath("src/core/auth/sso/web_interface.py"),
    os.path.normpath("tests/unit/test_compaction_domain.py"),
    os.path.normpath("tests/unit/transport/fastapi/adapters/sse/test_sse_formatter.py"),
}
PY_EXT = ".py"
PYC_EXT = ".pyc"


def find_files_with_emojis(directories: list[str]) -> list[tuple[str, int, str]]:
    """
    Scans directories for files containing Unicode emojis.

    Args:
        directories: List of directories to scan.

    Returns:
        A list of tuples, where each tuple contains the file path,
        line number, and the line of code with the emoji.
    """
    files_with_emojis = []
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    for directory in directories:
        for root, _, files in os.walk(directory):
            if "__pycache__" in root:
                continue

            for file in files:
                if not file.endswith(PY_EXT) or file.endswith(PYC_EXT):
                    continue

                file_path = os.path.join(root, file)
                relative_file_path = os.path.normpath(
                    os.path.relpath(file_path, start=project_root)
                )

                if relative_file_path in SKIPPED_FILES:
                    continue

                try:
                    with open(file_path, encoding="utf-8") as f:
                        content = f.read()
                        match = EMOJI_REGEX.search(content)
                        if match:
                            line_start = content.rfind("\n", 0, match.start()) + 1
                            line_end = content.find("\n", match.start())
                            if line_end == -1:
                                line_end = len(content)
                            line_content = content[line_start:line_end].strip()
                            line_num = content[: match.start()].count("\n") + 1
                            files_with_emojis.append(
                                (file_path, line_num, line_content)
                            )
                except (UnicodeDecodeError, OSError):
                    continue
    return files_with_emojis


def test_no_unicode_emojis_in_codebase() -> None:
    """
    Test that there are no Unicode emojis in codebase.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    directories = [
        os.path.join(project_root, "src/core"),
        os.path.join(project_root, "src/connectors"),
        os.path.join(project_root, "src/codebuff"),
    ]

    files_with_emojis = find_files_with_emojis(directories)

    if files_with_emojis:
        error_message = "Unicode emojis found in following files:\\n"
        for file_path, line_num, line in files_with_emojis:
            error_message += f'  - {file_path}, line {line_num}: "{line}"\\n'
        pytest.fail(error_message)
