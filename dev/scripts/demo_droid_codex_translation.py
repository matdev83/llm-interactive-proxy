#!/usr/bin/env python
"""Demo script for Droid-Codex Tool Translation Layer.

Shows how Factory Droid tool calls are translated to OpenAI Codex format
and how results are translated back.

Run with: ./.venv/Scripts/python.exe scripts/demo_droid_codex_translation.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.connectors._openai_codex_droid_session_detector import DroidSessionDetector
from src.connectors._openai_codex_droid_tool_translator import DroidToolTranslator


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def print_translation(
    droid_tool: str, droid_args: dict, codex_tool: str, codex_args: dict
) -> None:
    """Print a tool translation result."""
    print(f"  Droid:  {droid_tool}({json.dumps(droid_args, indent=None)})")
    print(f"  Codex:  {codex_tool}({json.dumps(codex_args, indent=None)})")
    print()


def demo_tool_translations() -> None:
    """Demonstrate Droid to Codex tool translations."""
    print_header("DROID -> CODEX TOOL TRANSLATIONS")

    translator = DroidToolTranslator()

    # Demo translations
    demo_cases = [
        # Read tool
        ("Read", {"file_path": "C:\\project\\src\\main.py", "offset": 10, "limit": 50}),
        ("Read", {"file_path": "/home/user/project/README.md"}),
        # LS tool
        ("LS", {"directory_path": "C:\\project\\src"}),
        ("LS", {}),  # Current directory
        # Execute tool
        ("Execute", {"command": "pytest tests/ -v --tb=short", "cwd": "/project"}),
        ("Execute", {"command": "git status"}),
        # Grep tool
        ("Grep", {"pattern": "def test_", "path": "tests/", "type": "py"}),
        ("Grep", {"pattern": "TODO", "include": "*.md"}),
        # Glob tool
        (
            "Glob",
            {
                "patterns": ["**/*.py", "**/*.md"],
                "excludePatterns": ["**/node_modules/**"],
            },
        ),
        # Proxy-side tools (no Codex equivalent)
        (
            "TodoWrite",
            {
                "todos": [
                    {"id": "1", "content": "Implement feature", "status": "pending"}
                ]
            },
        ),
        ("WebSearch", {"query": "python asyncio best practices"}),
        ("FetchUrl", {"url": "https://docs.python.org/3/library/asyncio.html"}),
        (
            "ExitSpecMode",
            {
                "plan": "1. Add tests\n2. Implement feature\n3. Update docs",
                "title": "Feature X",
            },
        ),
    ]

    for droid_tool, droid_args in demo_cases:
        try:
            codex_tool, codex_args = translator.translate_tool_call(
                droid_tool, droid_args
            )
            print_translation(droid_tool, droid_args, codex_tool, codex_args)
        except Exception as e:
            print(f"  ERROR translating {droid_tool}: {e}\n")


def demo_result_formatting() -> None:
    """Demonstrate Codex to Droid result formatting."""
    print_header("CODEX -> DROID RESULT FORMATTING")

    translator = DroidToolTranslator()

    # Demo result cases
    demo_results = [
        # Successful read
        ({"output": "def main():\n    print('Hello, World!')", "exit_code": 0}, "Read"),
        # Error result
        ({"error": "File not found: /nonexistent.py", "exit_code": 1}, "Read"),
        # Shell output
        (
            {
                "output": "tests/test_main.py::test_hello PASSED\n\n1 passed in 0.05s",
                "exit_code": 0,
            },
            "Execute",
        ),
        # Directory listing
        ({"content": "src/\n  main.py\n  utils.py\ntests/\n  test_main.py"}, "LS"),
        # Grep results
        (
            {
                "result": "src/main.py:10: def test_something():\nsrc/main.py:25: def test_other():"
            },
            "Grep",
        ),
    ]

    for codex_result, original_tool in demo_results:
        droid_result = translator.format_result(codex_result, original_tool)
        print(f"  Tool: {original_tool}")
        print(f"  Codex result: {json.dumps(codex_result)}")
        print(
            f"  Droid result: {droid_result[:100]!r}{'...' if len(droid_result) > 100 else ''}"
        )
        print()


def demo_client_detection() -> None:
    """Demonstrate Droid client detection."""
    print_header("DROID CLIENT DETECTION")

    detector = DroidSessionDetector()

    # Demo detection cases
    demo_cases = [
        # Factory Droid User-Agent
        {
            "name": "Factory CLI User-Agent",
            "headers": {"User-Agent": "factory-cli/0.27.1"},
            "messages": None,
            "tools": None,
        },
        # Droid system prompt
        {
            "name": "Droid System Prompt",
            "headers": None,
            "messages": [
                {
                    "role": "system",
                    "content": "You are Droid, an AI software engineer...",
                }
            ],
            "tools": None,
        },
        # Droid tool names
        {
            "name": "Droid Tool Names",
            "headers": None,
            "messages": None,
            "tools": [
                {"type": "function", "function": {"name": "Read"}},
                {"type": "function", "function": {"name": "LS"}},
                {"type": "function", "function": {"name": "Execute"}},
            ],
        },
        # Non-Droid (Cursor)
        {
            "name": "Non-Droid (Cursor)",
            "headers": {"User-Agent": "cursor/0.45.0"},
            "messages": [{"role": "system", "content": "You are an AI assistant."}],
            "tools": None,
        },
        # Non-Droid (Cline)
        {
            "name": "Non-Droid (Cline/KiloCode)",
            "headers": {"User-Agent": "vscode-restclient"},
            "messages": [
                {
                    "role": "system",
                    "content": "You are Cline, a skilled software engineer...",
                }
            ],
            "tools": None,
        },
    ]

    for case in demo_cases:
        result = detector.detect(
            headers=case.get("headers"),
            messages=case.get("messages"),
            tools=case.get("tools"),
        )
        status = "DROID DETECTED" if result.is_droid else "Not Droid"
        method = f" (via {result.detection_method})" if result.is_droid else ""
        print(f"  {case['name']}: {status}{method}")
    print()


def demo_tool_mapping_table() -> None:
    """Show the complete tool mapping table."""
    print_header("COMPLETE TOOL MAPPING TABLE")

    translator = DroidToolTranslator()

    print("  Droid Tool     | Codex Tool        | Type")
    print("  " + "-" * 50)

    # Native tools
    for droid, codex in translator.CODEX_NATIVE_TOOLS.items():
        print(f"  {droid:14} | {codex:17} | Native")

    # Proxy-side tools
    for droid, codex in translator.PROXY_SIDE_TOOLS.items():
        print(f"  {droid:14} | {codex:17} | Proxy-side")

    print()


def main() -> None:
    """Run all demos."""
    print("\n" + "=" * 60)
    print("     DROID-CODEX TOOL TRANSLATION LAYER DEMO")
    print("=" * 60)

    demo_tool_mapping_table()
    demo_tool_translations()
    demo_result_formatting()
    demo_client_detection()

    print_header("DEMO COMPLETE")
    print("  The translation layer is ready to use!")
    print("  - Droid tools translate to Codex format for API calls")
    print("  - Results translate back to Droid's expected format")
    print("  - Proxy-side tools are handled locally when no Codex equivalent exists")
    print()


if __name__ == "__main__":
    main()
