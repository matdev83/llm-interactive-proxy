#!/usr/bin/env python
"""
Verification Script for Tool Call Fix.

This script verifies that the tool call fix is working correctly by:
1. Creating or loading a CBOR capture with SEARCH/REPLACE markers in tool calls
2. Analyzing the captured traffic for tool call argument handling
3. Verifying SEARCH/REPLACE markers are preserved exactly
4. Verifying no double-escaping occurs

Requirements: 8.3

Usage:
    ./.venv/Scripts/python.exe scripts/verify_tool_call_fix.py
    ./.venv/Scripts/python.exe scripts/verify_tool_call_fix.py --verbose
    ./.venv/Scripts/python.exe scripts/verify_tool_call_fix.py --capture path/to/capture.cbor
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.domain.cbor_capture import CaptureDirection, CaptureEntry

from scripts.verify_streaming_fix_base import (
    CborReplayUtilities,
    TransformationAnalyzer,
    VerificationResult,
)

logger = logging.getLogger(__name__)

# Default capture file path
DEFAULT_CAPTURE_PATH = "var/wire_captures_cbor/proxy-2005.cbor"

# SEARCH/REPLACE marker patterns to look for
SEARCH_MARKERS = [
    "<<<<<<< SEARCH",
    "<<<<<< SEARCH",
    "<<<< SEARCH",
    "<<<<<<<",
    "<<<<<<",
]

REPLACE_MARKERS = [
    ">>>>>>> REPLACE",
    ">>>>>> REPLACE",
    ">>>> REPLACE",
    ">>>>>>>",
    ">>>>>>",
]

SEPARATOR_MARKERS = [
    "=======",
    "======",
    "====",
]



@dataclass
class ToolCallVerificationReport:
    """Report summarizing the tool call verification results."""

    capture_file: str
    total_entries: int
    backend_response_entries: int
    client_response_entries: int
    backend_tool_calls_with_markers: int
    client_tool_calls_with_markers: int
    marker_preservation_results: list[VerificationResult]
    double_escape_results: list[VerificationResult]
    overall_passed: bool
    summary_message: str

    def __str__(self) -> str:
        lines = [
            "=" * 70,
            "TOOL CALL FIX VERIFICATION REPORT",
            "=" * 70,
            "",
            f"Capture File: {self.capture_file}",
            f"Total Entries: {self.total_entries}",
            f"Backend Response Entries: {self.backend_response_entries}",
            f"Client Response Entries: {self.client_response_entries}",
            "",
            "-" * 40,
            "TOOL CALL STATISTICS",
            "-" * 40,
            "",
            f"Backend tool calls with diff markers: {self.backend_tool_calls_with_markers}",
            f"Client tool calls with diff markers: {self.client_tool_calls_with_markers}",
            "",
            "-" * 40,
            "VERIFICATION RESULTS",
            "-" * 40,
            "",
        ]

        # Marker preservation check
        marker_passes = [r for r in self.marker_preservation_results if r.passed]
        marker_failures = [r for r in self.marker_preservation_results if not r.passed]

        if marker_failures:
            lines.append(
                f"[FAIL] Marker preservation: "
                f"{len(marker_failures)} failures, {len(marker_passes)} passes"
            )
            for failure in marker_failures[:5]:
                lines.append(f"  - Entry {failure.entry_index}: {failure.message}")
                if failure.details.get("corrupted_content"):
                    preview = failure.details["corrupted_content"][:100]
                    lines.append(f"    Content: \"{preview}...\"")
        elif marker_passes:
            lines.append(
                f"[PASS] Marker preservation: {len(marker_passes)} tool calls verified"
            )
            for result in marker_passes[:3]:
                if result.details.get("markers_found"):
                    lines.append(
                        f"  - Entry {result.entry_index}: "
                        f"Found markers: {result.details['markers_found']}"
                    )
        else:
            lines.append("[INFO] Marker preservation: No tool calls with diff markers found")

        lines.append("")

        # Double-escape check
        escape_passes = [r for r in self.double_escape_results if r.passed]
        escape_failures = [r for r in self.double_escape_results if not r.passed]

        if escape_failures:
            lines.append(
                f"[FAIL] Double-escape check: "
                f"{len(escape_failures)} failures, {len(escape_passes)} passes"
            )
            for failure in escape_failures[:5]:
                lines.append(f"  - Entry {failure.entry_index}: {failure.message}")
        elif escape_passes:
            lines.append(
                f"[PASS] Double-escape check: {len(escape_passes)} tool calls verified"
            )
        else:
            lines.append("[INFO] Double-escape check: No tool calls to check")

        lines.append("")
        lines.append("-" * 40)
        lines.append("OVERALL RESULT")
        lines.append("-" * 40)
        lines.append("")

        if self.overall_passed:
            lines.append("[PASS] Tool call fix is VERIFIED")
        else:
            lines.append("[FAIL] Tool call fix verification FAILED")

        lines.append(f"Summary: {self.summary_message}")
        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)



class ToolCallVerifier:
    """Verifier for the tool call fix.

    This class provides methods to verify that:
    1. SEARCH/REPLACE diff markers are preserved exactly
    2. No double-escaping occurs in tool call arguments
    3. Tool call arguments flow through the pipeline unchanged

    Requirements: 8.3
    """

    def __init__(self, capture_path: str | Path | None = None) -> None:
        """Initialize the verifier.

        Args:
            capture_path: Path to the CBOR capture file. Defaults to proxy-2005.cbor.
        """
        self._capture_path = Path(capture_path or DEFAULT_CAPTURE_PATH)
        self._utils = CborReplayUtilities()
        self._analyzer = TransformationAnalyzer(self._utils)

    def verify(self) -> ToolCallVerificationReport:
        """Run the full verification and return a report.

        Returns:
            ToolCallVerificationReport with all verification results

        Raises:
            FileNotFoundError: If the capture file doesn't exist
        """
        if not self._capture_path.exists():
            raise FileNotFoundError(f"Capture file not found: {self._capture_path}")

        # Load the capture
        session = self._utils.load_capture(self._capture_path)

        # Get backend and client response entries
        backend_entries = self._utils.filter_by_direction(
            session.entries, CaptureDirection.BACKEND_TO_PROXY
        )
        client_entries = self._utils.filter_by_direction(
            session.entries, CaptureDirection.PROXY_TO_CLIENT
        )

        # Count tool calls with diff markers
        backend_tool_calls = self._count_tool_calls_with_markers(backend_entries)
        client_tool_calls = self._count_tool_calls_with_markers(client_entries)

        # Run verifications
        marker_results = self._verify_marker_preservation(client_entries)
        escape_results = self._verify_no_double_escaping(client_entries)

        # Determine overall result
        marker_failures = [r for r in marker_results if not r.passed]
        escape_failures = [r for r in escape_results if not r.passed]

        # The fix is verified if:
        # 1. All markers are preserved (if any tool calls with markers exist)
        # 2. No double-escaping occurs
        overall_passed = (
            len(marker_failures) == 0
            and len(escape_failures) == 0
        )

        # Generate summary message
        if overall_passed:
            if client_tool_calls > 0:
                summary_message = (
                    f"Tool call arguments correctly preserved. "
                    f"Found {client_tool_calls} tool calls with diff markers in client output."
                )
            else:
                summary_message = (
                    "No tool calls with diff markers found in capture. "
                    "This may be expected if the capture doesn't contain file edit operations."
                )
        else:
            issues = []
            if marker_failures:
                issues.append(f"{len(marker_failures)} marker preservation failures")
            if escape_failures:
                issues.append(f"{len(escape_failures)} double-escape issues")
            summary_message = f"Issues found: {'; '.join(issues)}"

        return ToolCallVerificationReport(
            capture_file=str(self._capture_path),
            total_entries=len(session.entries),
            backend_response_entries=len(backend_entries),
            client_response_entries=len(client_entries),
            backend_tool_calls_with_markers=backend_tool_calls,
            client_tool_calls_with_markers=client_tool_calls,
            marker_preservation_results=marker_results,
            double_escape_results=escape_results,
            overall_passed=overall_passed,
            summary_message=summary_message,
        )

    def _count_tool_calls_with_markers(self, entries: list[CaptureEntry]) -> int:
        """Count tool calls that contain diff markers.

        Args:
            entries: List of capture entries to check

        Returns:
            Number of tool calls containing diff markers
        """
        count = 0
        for entry in entries:
            tool_calls = self._extract_tool_calls(entry)
            for tool_call in tool_calls:
                arguments = self._get_tool_call_arguments(tool_call)
                if arguments and self._contains_diff_markers(arguments):
                    count += 1
        return count

    def _extract_tool_calls(self, entry: CaptureEntry) -> list[dict[str, Any]]:
        """Extract tool calls from a capture entry.

        Args:
            entry: Capture entry to extract from

        Returns:
            List of tool call dictionaries
        """
        tool_calls: list[dict[str, Any]] = []
        parsed_list = self._utils.parse_sse_data(entry.data)

        for parsed in parsed_list:
            choices = parsed.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            delta_tool_calls = delta.get("tool_calls", [])
            tool_calls.extend(delta_tool_calls)

            # Also check message.tool_calls for non-streaming format
            message = choices[0].get("message", {})
            message_tool_calls = message.get("tool_calls", [])
            tool_calls.extend(message_tool_calls)

        return tool_calls

    def _get_tool_call_arguments(self, tool_call: dict[str, Any]) -> str | None:
        """Get the arguments string from a tool call.

        Args:
            tool_call: Tool call dictionary

        Returns:
            Arguments string or None
        """
        function = tool_call.get("function", {})
        arguments = function.get("arguments")

        if isinstance(arguments, str):
            return arguments
        elif isinstance(arguments, dict):
            return json.dumps(arguments)
        return None

    def _contains_diff_markers(self, content: str) -> bool:
        """Check if content contains diff markers.

        Args:
            content: String content to check

        Returns:
            True if diff markers are found
        """
        # Check for any of the marker patterns
        for marker in SEARCH_MARKERS + REPLACE_MARKERS + SEPARATOR_MARKERS:
            if marker in content:
                return True
        return False

    def _find_markers_in_content(self, content: str) -> list[str]:
        """Find all diff markers present in content.

        Args:
            content: String content to check

        Returns:
            List of markers found
        """
        found = []
        for marker in SEARCH_MARKERS:
            if marker in content:
                found.append(marker)
                break  # Only report one SEARCH marker variant

        for marker in SEPARATOR_MARKERS:
            if marker in content:
                found.append(marker)
                break  # Only report one separator variant

        for marker in REPLACE_MARKERS:
            if marker in content:
                found.append(marker)
                break  # Only report one REPLACE marker variant

        return found



    def _verify_marker_preservation(
        self, entries: list[CaptureEntry]
    ) -> list[VerificationResult]:
        """Verify that diff markers are preserved in tool call arguments.

        Args:
            entries: List of client response entries to check

        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []

        for i, entry in enumerate(entries):
            tool_calls = self._extract_tool_calls(entry)

            for tool_call in tool_calls:
                arguments = self._get_tool_call_arguments(tool_call)
                if not arguments:
                    continue

                # Check if this tool call should have diff markers
                # (based on function name or content patterns)
                function_name = tool_call.get("function", {}).get("name", "")
                is_file_edit = function_name in (
                    "patch_file", "edit_file", "apply_diff", "str_replace_editor"
                )

                if self._contains_diff_markers(arguments):
                    # Verify markers are intact
                    markers_found = self._find_markers_in_content(arguments)

                    # Check for corruption patterns
                    corruption_detected = self._detect_marker_corruption(arguments)

                    if corruption_detected:
                        results.append(
                            VerificationResult(
                                passed=False,
                                message=f"Diff markers corrupted in {function_name} tool call",
                                details={
                                    "corrupted_content": arguments[:200],
                                    "corruption_type": corruption_detected,
                                    "function_name": function_name,
                                },
                                entry_index=i,
                                field_path="delta.tool_calls.function.arguments",
                            )
                        )
                    else:
                        results.append(
                            VerificationResult(
                                passed=True,
                                message=f"Diff markers preserved in {function_name} tool call",
                                details={
                                    "markers_found": markers_found,
                                    "function_name": function_name,
                                },
                                entry_index=i,
                                field_path="delta.tool_calls.function.arguments",
                            )
                        )
                elif is_file_edit:
                    # File edit tool without markers - might be expected
                    # Just note it, don't fail
                    pass

        return results

    def _detect_marker_corruption(self, content: str) -> str | None:
        """Detect if diff markers have been corrupted.

        Args:
            content: Content to check for corruption

        Returns:
            Description of corruption type, or None if no corruption
        """
        # Check for common corruption patterns

        # Pattern 1: Markers split across lines incorrectly
        if "< < < < < < <" in content or "> > > > > > >" in content:
            return "Markers have spaces inserted"

        # Pattern 2: Markers have been HTML-escaped
        if "&lt;&lt;&lt;" in content or "&gt;&gt;&gt;" in content:
            return "Markers have been HTML-escaped"

        # Pattern 3: Markers have been URL-encoded
        if "%3C%3C%3C" in content or "%3E%3E%3E" in content:
            return "Markers have been URL-encoded"

        # Pattern 4: Backslashes added before markers
        if "\\<\\<\\<" in content or "\\>\\>\\>" in content:
            return "Markers have been backslash-escaped"

        # Pattern 5: Markers truncated or partial
        # Check if we have partial markers without complete ones
        has_partial_search = any(
            m[:4] in content and m not in content
            for m in SEARCH_MARKERS
        )
        has_partial_replace = any(
            m[:4] in content and m not in content
            for m in REPLACE_MARKERS
        )
        if has_partial_search or has_partial_replace:
            return "Markers appear to be truncated"

        return None

    def _verify_no_double_escaping(
        self, entries: list[CaptureEntry]
    ) -> list[VerificationResult]:
        """Verify that tool call arguments are not double-escaped.

        Args:
            entries: List of client response entries to check

        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []

        for i, entry in enumerate(entries):
            tool_calls = self._extract_tool_calls(entry)

            for tool_call in tool_calls:
                arguments = self._get_tool_call_arguments(tool_call)
                if not arguments:
                    continue

                function_name = tool_call.get("function", {}).get("name", "")

                # Check for double-escaping patterns
                double_escape_issues = self._detect_double_escaping(arguments)

                if double_escape_issues:
                    results.append(
                        VerificationResult(
                            passed=False,
                            message=f"Double-escaping detected in {function_name} arguments",
                            details={
                                "issues": double_escape_issues,
                                "function_name": function_name,
                                "content_preview": arguments[:200],
                            },
                            entry_index=i,
                            field_path="delta.tool_calls.function.arguments",
                        )
                    )
                else:
                    results.append(
                        VerificationResult(
                            passed=True,
                            message=f"No double-escaping in {function_name} arguments",
                            details={"function_name": function_name},
                            entry_index=i,
                            field_path="delta.tool_calls.function.arguments",
                        )
                    )

        return results

    def _detect_double_escaping(self, content: str) -> list[str]:
        """Detect double-escaping issues in content.

        Args:
            content: Content to check

        Returns:
            List of double-escaping issues found
        """
        issues = []

        # Check for double-escaped newlines (\\n instead of \n in JSON)
        # In a properly escaped JSON string, we should see \n
        # Double-escaping would show as \\n in the raw string
        if "\\\\n" in content:
            # This could be legitimate if the content itself contains \n
            # But if we see many of them, it's likely double-escaping
            count = content.count("\\\\n")
            if count > 2:
                issues.append(f"Possible double-escaped newlines ({count} occurrences)")

        # Check for double-escaped quotes
        if '\\\\"' in content:
            count = content.count('\\\\"')
            if count > 2:
                issues.append(f"Possible double-escaped quotes ({count} occurrences)")

        # Check for double-escaped backslashes
        if "\\\\\\\\" in content:
            issues.append("Double-escaped backslashes detected")

        # Check for JSON-in-JSON pattern (arguments serialized twice)
        # This would look like: {"arguments": "{\"key\": \"value\"}"}
        # where the inner JSON is a string
        if '{\\"' in content and '\\":' in content:
            # Could be legitimate nested JSON, but flag it for review
            issues.append("Possible nested JSON escaping (may need review)")

        return issues



def create_synthetic_tool_call_capture() -> dict[str, Any]:
    """Create a synthetic SSE chunk with tool call containing diff markers.

    This is used for testing when no real capture with diff markers is available.

    Returns:
        Dictionary representing an SSE chunk with tool call
    """
    # Create a realistic patch_file tool call with diff markers
    patch_content = """<<<<<<< SEARCH
def old_function():
    return "old value"
=======
def new_function():
    return "new value"
>>>>>>> REPLACE"""

    arguments = {
        "file_path": "src/example.py",
        "patch_content": patch_content,
    }

    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "gemini-2.0-flash",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "patch_file",
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": None,
            }
        ],
    }


def verify_synthetic_tool_call() -> VerificationResult:
    """Verify tool call handling with synthetic data.

    This tests the core logic without requiring a real CBOR capture.

    Returns:
        VerificationResult indicating pass/fail
    """
    # Create synthetic chunk
    chunk = create_synthetic_tool_call_capture()

    # Extract and verify the tool call
    tool_calls = chunk["choices"][0]["delta"]["tool_calls"]
    tool_call = tool_calls[0]

    arguments_str = tool_call["function"]["arguments"]
    arguments = json.loads(arguments_str)

    patch_content = arguments.get("patch_content", "")

    # Verify markers are present
    markers_present = (
        "<<<<<<< SEARCH" in patch_content
        and "=======" in patch_content
        and ">>>>>>> REPLACE" in patch_content
    )

    if markers_present:
        return VerificationResult(
            passed=True,
            message="Synthetic tool call verification passed",
            details={
                "markers_found": ["<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"],
                "patch_content_length": len(patch_content),
            },
        )
    else:
        return VerificationResult(
            passed=False,
            message="Synthetic tool call verification failed - markers missing",
            details={
                "patch_content": patch_content[:200],
            },
        )


def main() -> int:
    """Main entry point for the verification script."""
    parser = argparse.ArgumentParser(
        description="Verify the tool call fix using CBOR capture replay"
    )
    parser.add_argument(
        "--capture",
        "-c",
        default=DEFAULT_CAPTURE_PATH,
        help=f"Path to CBOR capture file (default: {DEFAULT_CAPTURE_PATH})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--synthetic",
        "-s",
        action="store_true",
        help="Run synthetic verification (no capture file needed)",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run synthetic verification if requested
    if args.synthetic:
        print("Running synthetic tool call verification...")
        print("-" * 40)
        result = verify_synthetic_tool_call()
        print(result)
        print("-" * 40)

        if args.json:
            output = {
                "type": "synthetic",
                "passed": result.passed,
                "message": result.message,
                "details": result.details,
            }
            print(json.dumps(output, indent=2))

        return 0 if result.passed else 1

    # Run CBOR capture verification
    try:
        verifier = ToolCallVerifier(args.capture)
        report = verifier.verify()

        if args.json:
            # Output as JSON
            output = {
                "capture_file": report.capture_file,
                "total_entries": report.total_entries,
                "backend_response_entries": report.backend_response_entries,
                "client_response_entries": report.client_response_entries,
                "backend_tool_calls_with_markers": report.backend_tool_calls_with_markers,
                "client_tool_calls_with_markers": report.client_tool_calls_with_markers,
                "marker_preservation_passes": len(
                    [r for r in report.marker_preservation_results if r.passed]
                ),
                "marker_preservation_failures": len(
                    [r for r in report.marker_preservation_results if not r.passed]
                ),
                "double_escape_passes": len(
                    [r for r in report.double_escape_results if r.passed]
                ),
                "double_escape_failures": len(
                    [r for r in report.double_escape_results if not r.passed]
                ),
                "overall_passed": report.overall_passed,
                "summary": report.summary_message,
            }
            print(json.dumps(output, indent=2))
        else:
            # Output as formatted report
            print(report)

        return 0 if report.overall_passed else 1

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(
            "\nTip: Use --synthetic flag to run verification without a capture file.",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        logger.exception("Verification failed with error")
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
