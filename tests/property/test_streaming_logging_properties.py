from __future__ import annotations

from pathlib import Path

HOT_PATH_FILES = [
    "src/core/ports/sse_assembler.py",
    "src/core/services/streaming/tool_call_repair_processor.py",
    "src/core/services/streaming/content_accumulation_processor.py",
]

STREAMING_MODULE_ROOT = Path("src/core/services/streaming")


def test_property_12_guarded_hot_path_logging() -> None:
    """
    Property 12: Guarded hot-path logging.

    Any logger.log TRACE statements in hot-path modules must be guarded with
    logger.isEnabledFor checks to avoid performance regressions.
    """

    for file_path in HOT_PATH_FILES:
        text = Path(file_path).read_text(encoding="utf-8")
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if "logger.log(" in line:
                window = "\n".join(lines[max(0, idx - 2) : idx + 1])
                assert (
                    "logger.isEnabledFor" in window
                ), f"{file_path} line {idx+1} logs without guard:\n{line}"


def test_property_29_async_path_purity() -> None:
    """
    Property 29: Async path purity.

    Streaming modules must not call blocking functions such as time.sleep.
    """

    blocking_patterns = ("time.sleep", "asyncio.get_event_loop().run_until_complete")
    for py_file in STREAMING_MODULE_ROOT.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for pattern in blocking_patterns:
            assert pattern not in text, f"{py_file} contains blocking call '{pattern}'"
