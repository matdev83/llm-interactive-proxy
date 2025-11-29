#!/usr/bin/env python
"""
Verification Script for Text Content Fix.

This script verifies that the text content fix is working correctly by:
1. Loading a CBOR capture file with text content
2. Analyzing the captured traffic for text content handling
3. Verifying text content appears in client output
4. Verifying text content is preserved through the pipeline

Requirements: 8.2

Usage:
    ./.venv/Scripts/python.exe scripts/verify_text_content_fix.py
    ./.venv/Scripts/python.exe scripts/verify_text_content_fix.py --verbose
    ./.venv/Scripts/python.exe scripts/verify_text_content_fix.py --capture path/to/capture.cbor
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

from scripts.verify_streaming_fix_base import (
    CborReplayUtilities,
    TransformationAnalyzer,
    VerificationResult,
)
from src.core.domain.cbor_capture import CaptureDirection, CaptureEntry

logger = logging.getLogger(__name__)

# Default capture file path
DEFAULT_CAPTURE_PATH = "var/wire_captures_cbor/proxy-2005.cbor"


@dataclass
class TextContentVerificationReport:
    """Report summarizing the text content verification results."""

    capture_file: str
    total_entries: int
    backend_response_entries: int
    client_response_entries: int
    backend_text_chunks: int
    client_text_chunks: int
    text_preservation_results: list[VerificationResult]
    text_in_client_results: list[VerificationResult]
    overall_passed: bool
    summary_message: str

    def __str__(self) -> str:
        lines = [
            "=" * 70,
            "TEXT CONTENT FIX VERIFICATION REPORT",
            "=" * 70,
            "",
            f"Capture File: {self.capture_file}",
            f"Total Entries: {self.total_entries}",
            f"Backend Response Entries: {self.backend_response_entries}",
            f"Client Response Entries: {self.client_response_entries}",
            "",
            "-" * 40,
            "TEXT CONTENT STATISTICS",
            "-" * 40,
            "",
            f"Backend chunks with text content: {self.backend_text_chunks}",
            f"Client chunks with text content: {self.client_text_chunks}",
            "",
            "-" * 40,
            "VERIFICATION RESULTS",
            "-" * 40,
            "",
        ]

        # Text in client output check
        text_in_client_passes = [r for r in self.text_in_client_results if r.passed]
        text_in_client_failures = [r for r in self.text_in_client_results if not r.passed]

        if text_in_client_failures:
            lines.append(
                f"[FAIL] Text in client output: "
                f"{len(text_in_client_failures)} failures, {len(text_in_client_passes)} passes"
            )
            for failure in text_in_client_failures[:5]:
                lines.append(f"  - Entry {failure.entry_index}: {failure.message}")
        elif text_in_client_passes:
            lines.append(
                f"[PASS] Text in client output: {len(text_in_client_passes)} chunks verified"
            )
            for result in text_in_client_passes[:3]:
                if result.details.get("content_preview"):
                    preview = result.details["content_preview"][:60]
                    lines.append(f"  - Entry {result.entry_index}: \"{preview}...\"")
        else:
            lines.append("[INFO] Text in client output: No text chunks found")

        lines.append("")

        # Text preservation check
        preservation_passes = [r for r in self.text_preservation_results if r.passed]
        preservation_failures = [r for r in self.text_preservation_results if not r.passed]

        if preservation_failures:
            lines.append(
                f"[FAIL] Text preservation: "
                f"{len(preservation_failures)} failures, {len(preservation_passes)} passes"
            )
            for failure in preservation_failures[:5]:
                lines.append(f"  - {failure.message}")
                if failure.details.get("backend_content"):
                    lines.append(f"    Backend: \"{failure.details['backend_content'][:50]}...\"")
                if failure.details.get("client_content"):
                    lines.append(f"    Client: \"{failure.details['client_content'][:50]}...\"")
        elif preservation_passes:
            lines.append(
                f"[PASS] Text preservation: {len(preservation_passes)} comparisons verified"
            )
        else:
            lines.append("[INFO] Text preservation: No comparisons made")

        lines.append("")
        lines.append("-" * 40)
        lines.append("OVERALL RESULT")
        lines.append("-" * 40)
        lines.append("")

        if self.overall_passed:
            lines.append("[PASS] Text content fix is VERIFIED")
        else:
            lines.append("[FAIL] Text content fix verification FAILED")

        lines.append(f"Summary: {self.summary_message}")
        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)


class TextContentVerifier:
    """Verifier for the text content fix.

    This class provides methods to verify that:
    1. Text content appears in client output (not lost in pipeline)
    2. Text content is preserved from backend to client

    Requirements: 8.2
    """

    def __init__(self, capture_path: str | Path | None = None) -> None:
        """Initialize the verifier.

        Args:
            capture_path: Path to the CBOR capture file. Defaults to proxy-2005.cbor.
        """
        self._capture_path = Path(capture_path or DEFAULT_CAPTURE_PATH)
        self._utils = CborReplayUtilities()
        self._analyzer = TransformationAnalyzer(self._utils)

    def verify(self) -> TextContentVerificationReport:
        """Run the full verification and return a report.

        Returns:
            TextContentVerificationReport with all verification results

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

        # Count text chunks
        backend_text_chunks = self._count_text_chunks(backend_entries)
        client_text_chunks = self._count_text_chunks(client_entries)

        # Run verifications
        text_in_client_results = self._verify_text_in_client_output(client_entries)
        text_preservation_results = self._verify_text_preservation(
            backend_entries, client_entries
        )

        # Determine overall result
        text_in_client_failures = [r for r in text_in_client_results if not r.passed]
        preservation_failures = [r for r in text_preservation_results if not r.passed]

        # The fix is verified if:
        # 1. Text content appears in client output (if backend had text)
        # 2. Text content is preserved from backend to client
        overall_passed = (
            len(text_in_client_failures) == 0
            and len(preservation_failures) == 0
        )

        # Generate summary message
        if overall_passed:
            if client_text_chunks > 0:
                summary_message = (
                    f"Text content correctly transmitted to client. "
                    f"Found {client_text_chunks} text chunks in client output."
                )
            else:
                summary_message = (
                    "No text chunks found in capture. "
                    "This may be expected if the capture only contains tool calls."
                )
        else:
            issues = []
            if text_in_client_failures:
                issues.append(f"{len(text_in_client_failures)} text chunks missing from client")
            if preservation_failures:
                issues.append(f"{len(preservation_failures)} text preservation failures")
            summary_message = f"Issues found: {'; '.join(issues)}"

        return TextContentVerificationReport(
            capture_file=str(self._capture_path),
            total_entries=len(session.entries),
            backend_response_entries=len(backend_entries),
            client_response_entries=len(client_entries),
            backend_text_chunks=backend_text_chunks,
            client_text_chunks=client_text_chunks,
            text_preservation_results=text_preservation_results,
            text_in_client_results=text_in_client_results,
            overall_passed=overall_passed,
            summary_message=summary_message,
        )

    def _count_text_chunks(self, entries: list[CaptureEntry]) -> int:
        """Count the number of chunks with text content.

        Args:
            entries: List of capture entries to check

        Returns:
            Number of chunks containing text content
        """
        count = 0
        for entry in entries:
            parsed_list = self._utils.parse_sse_data(entry.data)
            for parsed in parsed_list:
                content = self._get_delta_content(parsed)
                if content and isinstance(content, str) and len(content.strip()) > 0:
                    # Exclude chunks where content is just JSON (usage leak)
                    if not self._looks_like_json_leak(content):
                        count += 1
        return count

    def _looks_like_json_leak(self, content: str) -> bool:
        """Check if content looks like a JSON leak (usage data in content).

        Args:
            content: The content string to check

        Returns:
            True if content appears to be leaked JSON
        """
        # Check for patterns that indicate JSON leak
        if '"usage":' in content and '"prompt_tokens":' in content:
            return True
        if '"chatcmpl-' in content and '"choices":' in content:
            return True
        return False

    def _verify_text_in_client_output(
        self, entries: list[CaptureEntry]
    ) -> list[VerificationResult]:
        """Verify that text content appears in client output.

        Args:
            entries: List of client response entries to check

        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []

        for i, entry in enumerate(entries):
            parsed_list = self._utils.parse_sse_data(entry.data)

            for parsed in parsed_list:
                content = self._get_delta_content(parsed)

                if content and isinstance(content, str) and len(content.strip()) > 0:
                    # Check if this is real text content (not JSON leak)
                    if not self._looks_like_json_leak(content):
                        results.append(
                            VerificationResult(
                                passed=True,
                                message="Text content found in client output",
                                details={
                                    "content_preview": content[:100],
                                    "content_length": len(content),
                                    "entry_sequence": entry.sequence,
                                },
                                entry_index=i,
                                field_path="choices.0.delta.content",
                            )
                        )
                    else:
                        # This is a JSON leak - mark as failure
                        results.append(
                            VerificationResult(
                                passed=False,
                                message="JSON leak detected in delta.content instead of text",
                                details={
                                    "content_preview": content[:200],
                                    "entry_sequence": entry.sequence,
                                },
                                entry_index=i,
                                field_path="choices.0.delta.content",
                            )
                        )

        return results

    def _verify_text_preservation(
        self,
        backend_entries: list[CaptureEntry],
        client_entries: list[CaptureEntry],
    ) -> list[VerificationResult]:
        """Verify that text content is preserved from backend to client.

        This compares text content in backend responses with corresponding
        client responses to ensure text is not lost in the pipeline.

        Args:
            backend_entries: List of backend response entries
            client_entries: List of client response entries

        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []

        # Extract all text content from backend
        backend_text_by_id: dict[str, list[str]] = {}
        for entry in backend_entries:
            parsed_list = self._utils.parse_sse_data(entry.data)
            for parsed in parsed_list:
                chunk_id = parsed.get("id", "")
                content = self._get_delta_content(parsed)
                if content and isinstance(content, str) and len(content.strip()) > 0:
                    if not self._looks_like_json_leak(content):
                        if chunk_id not in backend_text_by_id:
                            backend_text_by_id[chunk_id] = []
                        backend_text_by_id[chunk_id].append(content)

        # Extract all text content from client
        client_text_by_id: dict[str, list[str]] = {}
        for entry in client_entries:
            parsed_list = self._utils.parse_sse_data(entry.data)
            for parsed in parsed_list:
                chunk_id = parsed.get("id", "")
                content = self._get_delta_content(parsed)
                if content and isinstance(content, str) and len(content.strip()) > 0:
                    if not self._looks_like_json_leak(content):
                        if chunk_id not in client_text_by_id:
                            client_text_by_id[chunk_id] = []
                        client_text_by_id[chunk_id].append(content)

        # Compare backend text with client text
        for chunk_id, backend_texts in backend_text_by_id.items():
            client_texts = client_text_by_id.get(chunk_id, [])

            # Check if backend text appears in client
            backend_combined = "".join(backend_texts)
            client_combined = "".join(client_texts)

            if backend_combined and client_combined:
                # Both have text - check if they match or client contains backend text
                if backend_combined == client_combined or backend_combined in client_combined:
                    results.append(
                        VerificationResult(
                            passed=True,
                            message=f"Text preserved for chunk {chunk_id[:20]}...",
                            details={
                                "backend_content": backend_combined[:100],
                                "client_content": client_combined[:100],
                            },
                        )
                    )
                else:
                    # Text differs - might be transformation, check if similar
                    # Allow for some transformation (e.g., whitespace normalization)
                    backend_normalized = backend_combined.strip()
                    client_normalized = client_combined.strip()
                    if backend_normalized == client_normalized:
                        results.append(
                            VerificationResult(
                                passed=True,
                                message=f"Text preserved (normalized) for chunk {chunk_id[:20]}...",
                                details={
                                    "backend_content": backend_combined[:100],
                                    "client_content": client_combined[:100],
                                },
                            )
                        )
                    else:
                        results.append(
                            VerificationResult(
                                passed=False,
                                message=f"Text content differs for chunk {chunk_id[:20]}...",
                                details={
                                    "backend_content": backend_combined[:100],
                                    "client_content": client_combined[:100],
                                },
                            )
                        )
            elif backend_combined and not client_combined:
                # Backend has text but client doesn't - text was lost
                results.append(
                    VerificationResult(
                        passed=False,
                        message=f"Text lost in pipeline for chunk {chunk_id[:20]}...",
                        details={
                            "backend_content": backend_combined[:100],
                            "client_content": "(empty)",
                        },
                    )
                )

        return results

    def _get_delta_content(self, data: dict[str, Any] | None) -> str | None:
        """Extract delta.content from a parsed chunk.

        Args:
            data: Parsed chunk data

        Returns:
            Content string or None
        """
        if not data:
            return None

        choices = data.get("choices", [])
        if not choices:
            return None

        delta = choices[0].get("delta", {})
        return delta.get("content")


def main() -> int:
    """Main entry point for the verification script."""
    parser = argparse.ArgumentParser(
        description="Verify the text content fix using CBOR capture replay"
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

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run verification
    try:
        verifier = TextContentVerifier(args.capture)
        report = verifier.verify()

        if args.json:
            # Output as JSON
            output = {
                "capture_file": report.capture_file,
                "total_entries": report.total_entries,
                "backend_response_entries": report.backend_response_entries,
                "client_response_entries": report.client_response_entries,
                "backend_text_chunks": report.backend_text_chunks,
                "client_text_chunks": report.client_text_chunks,
                "text_in_client_passes": len(
                    [r for r in report.text_in_client_results if r.passed]
                ),
                "text_in_client_failures": len(
                    [r for r in report.text_in_client_results if not r.passed]
                ),
                "preservation_passes": len(
                    [r for r in report.text_preservation_results if r.passed]
                ),
                "preservation_failures": len(
                    [r for r in report.text_preservation_results if not r.passed]
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
        return 1
    except Exception as e:
        logger.exception("Verification failed with error")
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
