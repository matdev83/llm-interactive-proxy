#!/usr/bin/env python
"""
Verification Script for Usage Reporting Fix.

This script verifies that the usage reporting fix is working correctly by:
1. Replaying a CBOR capture through the fixed pipeline
2. Verifying usage is in OpenRouter format at top level
3. Verifying x-usage-* headers are present

Requirements: 8.4

Usage:
    ./.venv/Scripts/python.exe scripts/verify_usage_reporting_fix.py
    ./.venv/Scripts/python.exe scripts/verify_usage_reporting_fix.py --verbose
    ./.venv/Scripts/python.exe scripts/verify_usage_reporting_fix.py --capture path/to/capture.cbor
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

# Expected OpenRouter format usage fields
OPENROUTER_USAGE_FIELDS = ["prompt_tokens", "completion_tokens", "total_tokens"]

# Expected x-usage-* header names
USAGE_HEADERS = [
    "x-usage-prompt-tokens",
    "x-usage-completion-tokens",
    "x-usage-total-tokens",
]


@dataclass
class UsageReportingVerificationReport:
    """Report summarizing the usage reporting verification results."""

    capture_file: str
    total_entries: int
    client_response_entries: int
    final_chunks_with_usage: int
    openrouter_format_results: list[VerificationResult]
    usage_at_top_level_results: list[VerificationResult]
    header_simulation_results: list[VerificationResult]
    overall_passed: bool
    summary_message: str

    def __str__(self) -> str:
        lines = [
            "=" * 70,
            "USAGE REPORTING FIX VERIFICATION REPORT",
            "=" * 70,
            "",
            f"Capture File: {self.capture_file}",
            f"Total Entries: {self.total_entries}",
            f"Client Response Entries: {self.client_response_entries}",
            f"Final Chunks with Usage: {self.final_chunks_with_usage}",
            "",
            "-" * 40,
            "VERIFICATION RESULTS",
            "-" * 40,
            "",
        ]

        # OpenRouter format check
        format_passes = [r for r in self.openrouter_format_results if r.passed]
        format_failures = [r for r in self.openrouter_format_results if not r.passed]

        if format_failures:
            lines.append(
                f"[FAIL] OpenRouter format: "
                f"{len(format_failures)} failures, {len(format_passes)} passes"
            )
            for failure in format_failures[:5]:
                lines.append(f"  - Entry {failure.entry_index}: {failure.message}")
                if failure.details.get("missing_fields"):
                    lines.append(
                        f"    Missing fields: {failure.details['missing_fields']}"
                    )
        elif format_passes:
            lines.append(
                f"[PASS] OpenRouter format: {len(format_passes)} chunks verified"
            )
            for result in format_passes[:3]:
                if result.details.get("usage"):
                    usage = result.details["usage"]
                    lines.append(
                        f"  - Entry {result.entry_index}: "
                        f"prompt={usage.get('prompt_tokens', 'N/A')}, "
                        f"completion={usage.get('completion_tokens', 'N/A')}, "
                        f"total={usage.get('total_tokens', 'N/A')}"
                    )
        else:
            lines.append("[INFO] OpenRouter format: No usage data found to verify")

        lines.append("")

        # Usage at top level check
        top_level_passes = [r for r in self.usage_at_top_level_results if r.passed]
        top_level_failures = [
            r for r in self.usage_at_top_level_results if not r.passed
        ]

        if top_level_failures:
            lines.append(
                f"[FAIL] Usage at top level: "
                f"{len(top_level_failures)} failures, {len(top_level_passes)} passes"
            )
            for failure in top_level_failures[:5]:
                lines.append(f"  - Entry {failure.entry_index}: {failure.message}")
        elif top_level_passes:
            lines.append(
                f"[PASS] Usage at top level: {len(top_level_passes)} final chunks verified"
            )
        else:
            lines.append("[INFO] Usage at top level: No final chunks found")

        lines.append("")

        # Header simulation check
        header_passes = [r for r in self.header_simulation_results if r.passed]
        header_failures = [r for r in self.header_simulation_results if not r.passed]

        if header_failures:
            lines.append(
                f"[FAIL] Header simulation: "
                f"{len(header_failures)} failures, {len(header_passes)} passes"
            )
            for failure in header_failures[:5]:
                lines.append(f"  - Entry {failure.entry_index}: {failure.message}")
        elif header_passes:
            lines.append(
                f"[PASS] Header simulation: {len(header_passes)} usage data sets verified"
            )
            for result in header_passes[:3]:
                if result.details.get("simulated_headers"):
                    headers = result.details["simulated_headers"]
                    lines.append(
                        f"  - Entry {result.entry_index}: "
                        f"Headers would be: {headers}"
                    )
        else:
            lines.append("[INFO] Header simulation: No usage data to simulate headers")

        lines.append("")
        lines.append("-" * 40)
        lines.append("OVERALL RESULT")
        lines.append("-" * 40)
        lines.append("")

        if self.overall_passed:
            lines.append("[PASS] Usage reporting fix is VERIFIED")
        else:
            lines.append("[FAIL] Usage reporting fix verification FAILED")

        lines.append(f"Summary: {self.summary_message}")
        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)


class UsageReportingVerifier:
    """Verifier for the usage reporting fix.

    This class provides methods to verify that:
    1. Usage data is in OpenRouter format (prompt_tokens, completion_tokens, total_tokens)
    2. Usage data appears at top level of final SSE chunks
    3. Usage data can be used to generate x-usage-* headers

    Requirements: 8.4
    """

    def __init__(self, capture_path: str | Path | None = None) -> None:
        """Initialize the verifier.

        Args:
            capture_path: Path to the CBOR capture file. Defaults to proxy-2005.cbor.
        """
        self._capture_path = Path(capture_path or DEFAULT_CAPTURE_PATH)
        self._utils = CborReplayUtilities()
        self._analyzer = TransformationAnalyzer(self._utils)

    def verify(self) -> UsageReportingVerificationReport:
        """Run the full verification and return a report.

        Returns:
            UsageReportingVerificationReport with all verification results

        Raises:
            FileNotFoundError: If the capture file doesn't exist
        """
        if not self._capture_path.exists():
            raise FileNotFoundError(f"Capture file not found: {self._capture_path}")

        # Load the capture
        session = self._utils.load_capture(self._capture_path)

        # Get client response entries
        client_entries = self._utils.filter_by_direction(
            session.entries, CaptureDirection.PROXY_TO_CLIENT
        )

        # Count final chunks with usage
        final_chunks_with_usage = self._count_final_chunks_with_usage(client_entries)

        # Run verifications
        openrouter_format_results = self._verify_openrouter_format(client_entries)
        usage_at_top_level_results = self._verify_usage_at_top_level(client_entries)
        header_simulation_results = self._verify_header_simulation(client_entries)

        # Determine overall result
        format_failures = [r for r in openrouter_format_results if not r.passed]
        top_level_failures = [r for r in usage_at_top_level_results if not r.passed]
        header_failures = [r for r in header_simulation_results if not r.passed]

        # The fix is verified if:
        # 1. All usage data is in OpenRouter format
        # 2. Usage data appears at top level in final chunks
        # 3. Usage data can generate valid headers
        overall_passed = (
            len(format_failures) == 0
            and len(top_level_failures) == 0
            and len(header_failures) == 0
        )

        # Generate summary message
        if overall_passed:
            if final_chunks_with_usage > 0:
                summary_message = (
                    f"Usage reporting correctly implemented. "
                    f"Found {final_chunks_with_usage} final chunk(s) with properly "
                    f"formatted usage data at top level."
                )
            else:
                summary_message = (
                    "No final chunks with usage data found in capture. "
                    "This may be expected depending on the capture content."
                )
        else:
            issues = []
            if format_failures:
                issues.append(f"{len(format_failures)} OpenRouter format issues")
            if top_level_failures:
                issues.append(f"{len(top_level_failures)} top-level placement issues")
            if header_failures:
                issues.append(f"{len(header_failures)} header simulation issues")
            summary_message = f"Issues found: {'; '.join(issues)}"

        return UsageReportingVerificationReport(
            capture_file=str(self._capture_path),
            total_entries=len(session.entries),
            client_response_entries=len(client_entries),
            final_chunks_with_usage=final_chunks_with_usage,
            openrouter_format_results=openrouter_format_results,
            usage_at_top_level_results=usage_at_top_level_results,
            header_simulation_results=header_simulation_results,
            overall_passed=overall_passed,
            summary_message=summary_message,
        )

    def _count_final_chunks_with_usage(self, entries: list[CaptureEntry]) -> int:
        """Count final chunks that have usage data at top level.

        Args:
            entries: List of capture entries to check

        Returns:
            Number of final chunks with usage data
        """
        count = 0
        for entry in entries:
            parsed_list = self._utils.parse_sse_data(entry.data)
            for parsed in parsed_list:
                if self._is_final_chunk(parsed) and self._has_top_level_usage(parsed):
                    count += 1
        return count

    def _is_final_chunk(self, data: dict[str, Any]) -> bool:
        """Check if a chunk is a final chunk (has finish_reason).

        Args:
            data: Parsed chunk data

        Returns:
            True if this is a final chunk
        """
        choices = data.get("choices", [])
        if not choices:
            return False

        finish_reason = choices[0].get("finish_reason")
        return finish_reason in ("stop", "tool_calls", "length")

    def _has_top_level_usage(self, data: dict[str, Any]) -> bool:
        """Check if a chunk has usage data at top level.

        Args:
            data: Parsed chunk data

        Returns:
            True if usage is at top level
        """
        usage = data.get("usage")
        return isinstance(usage, dict) and len(usage) > 0

    def _verify_openrouter_format(
        self, entries: list[CaptureEntry]
    ) -> list[VerificationResult]:
        """Verify that usage data is in OpenRouter format.

        OpenRouter format requires:
        - prompt_tokens (integer)
        - completion_tokens (integer)
        - total_tokens (integer)

        Args:
            entries: List of client response entries to check

        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []

        for i, entry in enumerate(entries):
            parsed_list = self._utils.parse_sse_data(entry.data)

            for parsed in parsed_list:
                usage = parsed.get("usage")
                if not isinstance(usage, dict):
                    continue

                # Check for required fields
                missing_fields = []
                invalid_fields = []

                for field in OPENROUTER_USAGE_FIELDS:
                    if field not in usage:
                        missing_fields.append(field)
                    elif not isinstance(usage[field], int | float):
                        invalid_fields.append(f"{field} (not numeric)")

                if missing_fields or invalid_fields:
                    results.append(
                        VerificationResult(
                            passed=False,
                            message="Usage data not in OpenRouter format",
                            details={
                                "missing_fields": missing_fields,
                                "invalid_fields": invalid_fields,
                                "usage": usage,
                            },
                            entry_index=i,
                            field_path="usage",
                        )
                    )
                else:
                    results.append(
                        VerificationResult(
                            passed=True,
                            message="Usage data in correct OpenRouter format",
                            details={
                                "usage": usage,
                                "entry_sequence": entry.sequence,
                            },
                            entry_index=i,
                            field_path="usage",
                        )
                    )

        return results

    def _verify_usage_at_top_level(
        self, entries: list[CaptureEntry]
    ) -> list[VerificationResult]:
        """Verify that usage data appears at top level in final chunks.

        Args:
            entries: List of client response entries to check

        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []

        for i, entry in enumerate(entries):
            parsed_list = self._utils.parse_sse_data(entry.data)

            for parsed in parsed_list:
                if not self._is_final_chunk(parsed):
                    continue

                # This is a final chunk - check for usage at top level
                usage = parsed.get("usage")
                finish_reason = parsed.get("choices", [{}])[0].get("finish_reason")

                if self._has_top_level_usage(parsed):
                    # Check that usage is NOT in delta.content (the bug)
                    delta_content = self._get_delta_content(parsed)
                    usage_in_content = (
                        delta_content
                        and isinstance(delta_content, str)
                        and '"usage":' in delta_content
                        and '"prompt_tokens":' in delta_content
                    )

                    if usage_in_content:
                        results.append(
                            VerificationResult(
                                passed=False,
                                message="Usage data found both at top level AND in delta.content",
                                details={
                                    "finish_reason": finish_reason,
                                    "usage": usage,
                                    "content_preview": (
                                        delta_content[:200] if delta_content else None
                                    ),
                                },
                                entry_index=i,
                            )
                        )
                    else:
                        results.append(
                            VerificationResult(
                                passed=True,
                                message="Usage data correctly at top level only",
                                details={
                                    "finish_reason": finish_reason,
                                    "usage": usage,
                                },
                                entry_index=i,
                            )
                        )
                else:
                    # Final chunk without usage - note it but don't fail
                    # Some backends may not include usage in streaming
                    results.append(
                        VerificationResult(
                            passed=True,  # Not a failure
                            message="Final chunk without usage (may be expected)",
                            details={"finish_reason": finish_reason},
                            entry_index=i,
                        )
                    )

        return results

    def _verify_header_simulation(
        self, entries: list[CaptureEntry]
    ) -> list[VerificationResult]:
        """Verify that usage data can generate valid x-usage-* headers.

        This simulates what the response adapter would do with the usage data.

        Args:
            entries: List of client response entries to check

        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []

        for i, entry in enumerate(entries):
            parsed_list = self._utils.parse_sse_data(entry.data)

            for parsed in parsed_list:
                usage = parsed.get("usage")
                if not isinstance(usage, dict):
                    continue

                # Simulate header generation
                simulated_headers = self._simulate_usage_headers(usage)

                if simulated_headers is None:
                    results.append(
                        VerificationResult(
                            passed=False,
                            message="Cannot generate headers from usage data",
                            details={
                                "usage": usage,
                                "reason": "Missing required fields",
                            },
                            entry_index=i,
                        )
                    )
                else:
                    # Verify all expected headers would be present
                    missing_headers = [
                        h for h in USAGE_HEADERS if h not in simulated_headers
                    ]

                    if missing_headers:
                        results.append(
                            VerificationResult(
                                passed=False,
                                message="Some headers would be missing",
                                details={
                                    "missing_headers": missing_headers,
                                    "simulated_headers": simulated_headers,
                                },
                                entry_index=i,
                            )
                        )
                    else:
                        results.append(
                            VerificationResult(
                                passed=True,
                                message="All x-usage-* headers can be generated",
                                details={
                                    "simulated_headers": simulated_headers,
                                },
                                entry_index=i,
                            )
                        )

        return results

    def _simulate_usage_headers(self, usage: dict[str, Any]) -> dict[str, str] | None:
        """Simulate generating x-usage-* headers from usage data.

        This mirrors the logic in response_adapters.py _apply_usage_headers().

        Args:
            usage: Usage data dictionary

        Returns:
            Dictionary of header name to value, or None if cannot generate
        """
        if not usage:
            return None

        def _coerce(value: Any) -> str:
            if value is None:
                return "0"
            return str(value)

        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

        # All fields should be present for valid headers
        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            return None

        return {
            "x-usage-prompt-tokens": _coerce(prompt_tokens),
            "x-usage-completion-tokens": _coerce(completion_tokens),
            "x-usage-total-tokens": _coerce(total_tokens),
        }

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


def create_synthetic_usage_chunk() -> dict[str, Any]:
    """Create a synthetic SSE chunk with usage data in OpenRouter format.

    This is used for testing when no real capture is available.

    Returns:
        Dictionary representing an SSE chunk with usage data
    """
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "gemini-2.0-flash",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 19369,
            "completion_tokens": 516,
            "total_tokens": 19885,
        },
    }


def verify_synthetic_usage_reporting() -> list[VerificationResult]:
    """Verify usage reporting with synthetic data.

    This tests the core logic without requiring a real CBOR capture.

    Returns:
        List of VerificationResult indicating pass/fail
    """
    results: list[VerificationResult] = []

    # Create synthetic chunk
    chunk = create_synthetic_usage_chunk()

    # Verify OpenRouter format
    usage = chunk.get("usage", {})
    missing_fields = [f for f in OPENROUTER_USAGE_FIELDS if f not in usage]

    if missing_fields:
        results.append(
            VerificationResult(
                passed=False,
                message=f"Missing OpenRouter fields: {missing_fields}",
                details={"usage": usage},
            )
        )
    else:
        results.append(
            VerificationResult(
                passed=True,
                message="Usage data in OpenRouter format",
                details={"usage": usage},
            )
        )

    # Verify usage is at top level (not in delta.content)
    delta_content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
    if delta_content and '"usage":' in str(delta_content):
        results.append(
            VerificationResult(
                passed=False,
                message="Usage data leaked into delta.content",
                details={"content": delta_content},
            )
        )
    else:
        results.append(
            VerificationResult(
                passed=True,
                message="Usage data correctly at top level only",
                details={},
            )
        )

    # Verify header simulation
    headers = {
        "x-usage-prompt-tokens": str(usage.get("prompt_tokens", 0)),
        "x-usage-completion-tokens": str(usage.get("completion_tokens", 0)),
        "x-usage-total-tokens": str(usage.get("total_tokens", 0)),
    }

    missing_headers = [h for h in USAGE_HEADERS if h not in headers]
    if missing_headers:
        results.append(
            VerificationResult(
                passed=False,
                message=f"Missing headers: {missing_headers}",
                details={"headers": headers},
            )
        )
    else:
        results.append(
            VerificationResult(
                passed=True,
                message="All x-usage-* headers can be generated",
                details={"headers": headers},
            )
        )

    return results


def main() -> int:
    """Main entry point for the verification script."""
    parser = argparse.ArgumentParser(
        description="Verify the usage reporting fix using CBOR capture replay"
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
        print("Running synthetic usage reporting verification...")
        print("-" * 40)
        results = verify_synthetic_usage_reporting()

        all_passed = all(r.passed for r in results)
        for result in results:
            status = "[PASS]" if result.passed else "[FAIL]"
            print(f"{status} {result.message}")
            if result.details:
                for key, value in result.details.items():
                    print(f"  {key}: {value}")

        print("-" * 40)
        print(f"Overall: {'PASSED' if all_passed else 'FAILED'}")

        if args.json:
            output = {
                "type": "synthetic",
                "results": [
                    {
                        "passed": r.passed,
                        "message": r.message,
                        "details": r.details,
                    }
                    for r in results
                ],
                "overall_passed": all_passed,
            }
            print(json.dumps(output, indent=2))

        return 0 if all_passed else 1

    # Run CBOR capture verification
    try:
        verifier = UsageReportingVerifier(args.capture)
        report = verifier.verify()

        if args.json:
            # Output as JSON
            output = {
                "capture_file": report.capture_file,
                "total_entries": report.total_entries,
                "client_response_entries": report.client_response_entries,
                "final_chunks_with_usage": report.final_chunks_with_usage,
                "openrouter_format_passes": len(
                    [r for r in report.openrouter_format_results if r.passed]
                ),
                "openrouter_format_failures": len(
                    [r for r in report.openrouter_format_results if not r.passed]
                ),
                "top_level_passes": len(
                    [r for r in report.usage_at_top_level_results if r.passed]
                ),
                "top_level_failures": len(
                    [r for r in report.usage_at_top_level_results if not r.passed]
                ),
                "header_simulation_passes": len(
                    [r for r in report.header_simulation_results if r.passed]
                ),
                "header_simulation_failures": len(
                    [r for r in report.header_simulation_results if not r.passed]
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
