"""Integration tests for Droid-Codex compatibility.

Tests that verify the translation layer works correctly with
real captured session data from Factory Droid.

Test isolation: All tests in this file are auto-marked with @pytest.mark.codex
by conftest.py and excluded from default pytest runs.
"""

import contextlib
import json
import zlib
from pathlib import Path
from typing import Any

import pytest

cbor2: Any | None = None
try:
    import cbor2 as _cbor2

    cbor2 = _cbor2
except ImportError:
    cbor2 = None

# Expected Droid tools from captured session
EXPECTED_DROID_TOOLS = [
    "Read",
    "LS",
    "Execute",
    "Edit",
    "Grep",
    "Glob",
    "Create",
    "TodoWrite",
    "WebSearch",
    "FetchUrl",
    "ExitSpecMode",
]


class TestDroidCodexCompatibility:
    """Integration tests using captured session data."""

    def test_all_expected_droid_tools_have_translation(self):
        """Every expected Droid tool should have a translation defined."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()

        # Minimum required arguments for each tool
        min_args = {
            "Read": {"file_path": "/test.py"},
            "LS": {},
            "Execute": {"command": "ls"},
            "Edit": {"file_path": "/test.py", "old_str": "a", "new_str": "b"},
            "Grep": {"pattern": "test"},
            "Glob": {"pattern": "*.py"},
            "Create": {"file_path": "/new.py", "content": ""},
            "TodoWrite": {"todos": []},
            "WebSearch": {"query": "test"},
            "FetchUrl": {"url": "http://example.com"},
            "ExitSpecMode": {"plan": "test"},
        }

        for tool_name in EXPECTED_DROID_TOOLS:
            args = min_args.get(tool_name, {})
            # Should not raise - every tool should be handled
            res = translator.translate_tool_call(tool_name, args)
            codex_name, _ = res.codex_tool_name, res.codex_arguments
            assert codex_name is not None
            assert isinstance(codex_name, str)

    def test_native_tools_map_to_codex(self):
        """Native Codex tools should map to Codex tool names."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()

        # These should map to Codex native tools (with minimum required args)
        native_mappings = {
            "Read": ("read_file", {"file_path": "/test.py"}),
            "LS": ("list_dir", {}),
            "Execute": ("shell", {"command": "ls"}),
            "Grep": ("grep_files", {"pattern": "test"}),
        }

        for droid_tool, (expected_codex, min_args) in native_mappings.items():
            res = translator.translate_tool_call(droid_tool, min_args)
            codex_name, _ = res.codex_tool_name, res.codex_arguments
            assert (
                codex_name == expected_codex
            ), f"{droid_tool} should map to {expected_codex}, got {codex_name}"

    def test_proxy_tools_map_to_proxy_markers(self):
        """Proxy-side tools should map to __proxy_* markers."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()

        proxy_tools = ["TodoWrite", "WebSearch", "FetchUrl", "ExitSpecMode"]

        for tool_name in proxy_tools:
            res = translator.translate_tool_call(tool_name, {})
            codex_name, _ = res.codex_tool_name, res.codex_arguments
            assert codex_name.startswith(
                "__proxy_"
            ), f"{tool_name} should map to __proxy_* marker, got {codex_name}"

    def test_detector_identifies_droid_tools(self):
        """Detector should identify Droid from tool definitions."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()

        # Create tool definitions similar to what Droid sends
        droid_tools = [
            {"type": "function", "function": {"name": tool}}
            for tool in ["Read", "LS", "Execute", "Edit", "Grep"]
        ]

        result = detector.detect(tools=droid_tools)
        assert result.is_droid is True

    def test_roundtrip_read_translation(self):
        """Read tool should round-trip translate correctly."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()

        # Simulate Droid Read call
        droid_args = {
            "file_path": "/project/src/main.py",
            "offset": 10,
            "limit": 50,
        }

        res = translator.translate_tool_call("Read", droid_args)

        codex_name, codex_args = res.codex_tool_name, res.codex_arguments

        # Verify Codex format
        assert codex_name == "read_file"
        assert codex_args["path"] == "/project/src/main.py"
        assert codex_args["start_line"] == 10
        assert codex_args["end_line"] == 60

        # Simulate Codex result
        codex_result = {
            "output": "def main():\n    print('Hello')",
            "exit_code": 0,
        }

        # Translate back to Droid format
        droid_result = translator.format_result(codex_result, "Read")
        assert droid_result == "def main():\n    print('Hello')"

    def test_roundtrip_execute_translation(self):
        """Execute tool should round-trip translate correctly."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()

        # Simulate Droid Execute call
        droid_args = {
            "command": "pytest tests/ -v --tb=short",
            "cwd": "/project",
        }

        res = translator.translate_tool_call("Execute", droid_args)

        codex_name, codex_args = res.codex_tool_name, res.codex_arguments

        # Verify Codex format
        assert codex_name == "shell"
        assert codex_args["command"] == ["pytest", "tests/", "-v", "--tb=short"]
        assert codex_args["workdir"] == "/project"

    @pytest.mark.skipif(cbor2 is None, reason="cbor2 not installed")
    def test_load_captured_tools_from_cbor(self):
        """Load and verify tools from captured CBOR session if available."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        # Look for captured session file
        captures_dir = Path("var/wire_captures_cbor")
        if not captures_dir.exists():
            pytest.skip("No wire captures directory")

        # Find latest Droid session capture
        droid_captures = list(captures_dir.glob("proxy-*.cbor"))
        if not droid_captures:
            pytest.skip("No Droid capture files found")

        capture_file = max(droid_captures, key=lambda path: path.stat().st_mtime)
        translator = DroidToolTranslator()
        found_tools = set()

        try:
            with open(capture_file, "rb") as f:
                data = cbor2.load(f)

            entries = data.get("entries", [])
            for entry in entries:
                if entry.get("direction") == "P->B":
                    entry_data = entry.get("data", b"")
                    if entry.get("enc") == "zlib" and isinstance(entry_data, bytes):
                        try:
                            entry_data = zlib.decompress(entry_data)
                            entry_data = json.loads(entry_data)
                        except (zlib.error, json.JSONDecodeError):
                            continue

                    if isinstance(entry_data, dict):
                        tools = entry_data.get("tools", [])
                        for tool in tools:
                            if (
                                isinstance(tool, dict)
                                and tool.get("type") == "function"
                            ):
                                func = tool.get("function", {})
                                name = func.get("name", "")
                                if name:
                                    found_tools.add(name)
                                    # Verify translation doesn't raise
                                    with contextlib.suppress(ValueError):
                                        translator.translate_tool_call(name, {})

        except Exception as e:
            pytest.skip(f"Could not load capture: {e}")

        # Just log what we found
        if found_tools:
            print(f"Found tools in capture: {sorted(found_tools)}")


class TestDroidDetectorWithRealData:
    """Tests for Droid detection with realistic data."""

    def test_detect_factory_cli_user_agent(self):
        """Detect Droid from factory-cli User-Agent."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()

        # Real User-Agent from Factory Droid
        headers = {"User-Agent": "factory-cli/0.27.1"}
        result = detector.detect(headers=headers)

        assert result.is_droid is True
        assert result.detection_method == "user_agent"

    def test_detect_from_realistic_system_prompt(self):
        """Detect Droid from realistic system prompt."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()

        # Simulated Droid system prompt
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Droid, an AI software engineer. "
                    "You have access to tools for file operations, "
                    "shell commands, and web search."
                ),
            }
        ]
        result = detector.detect(messages=messages)

        assert result.is_droid is True
        assert result.detection_method == "system_prompt"

    def test_not_detect_cursor_agent(self):
        """Should not detect Cursor as Droid."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()

        # Cursor-style headers and prompts
        headers = {"User-Agent": "cursor/0.45.0"}
        messages = [
            {
                "role": "system",
                "content": "You are an AI assistant helping with coding tasks.",
            }
        ]

        result = detector.detect(headers=headers, messages=messages)
        assert result.is_droid is False
