#!/usr/bin/env python
"""
CBOR Replay Infrastructure for Streaming Fix Verification.

This module provides utilities for loading CBOR captures, filtering by direction,
extracting fields, and comparing before/after transformations for verifying
streaming pipeline fixes.

Usage:
    # As a module
    from scripts.verify_streaming_fix_base import (
        CborReplayUtilities,
        TransformationAnalyzer,
        VerificationResult,
    )

    # Load and analyze a capture
    utils = CborReplayUtilities()
    session = utils.load_capture("var/wire_captures_cbor/proxy-2005.cbor")
    
    # Filter entries by direction
    backend_responses = utils.filter_by_direction(
        session.entries, CaptureDirection.BACKEND_TO_PROXY
    )
    
    # Extract specific fields
    usage_data = utils.extract_field(backend_responses[0], "usage")
    
    # Analyze transformations
    analyzer = TransformationAnalyzer()
    result = analyzer.compare_backend_to_client(session)

Requirements: 9.1, 9.2, 9.3
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.domain.cbor_capture import (
    CaptureDirection,
    CaptureEntry,
    CaptureSession,
)
from src.core.simulation.capture_reader import CaptureReader

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of a verification check.
    
    Attributes:
        passed: Whether the verification passed
        message: Human-readable description of the result
        details: Additional details about the verification
        entry_index: Index of the entry that was checked (if applicable)
        field_path: Path to the field that was checked (if applicable)
    """
    
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    entry_index: int | None = None
    field_path: str | None = None
    
    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        result = f"[{status}] {self.message}"
        if self.entry_index is not None:
            result += f" (entry {self.entry_index})"
        if self.field_path:
            result += f" at {self.field_path}"
        return result


@dataclass
class TransformationComparison:
    """Comparison of data before and after transformation.
    
    Attributes:
        before: Data before transformation
        after: Data after transformation
        differences: List of differences found
        entry_indices: Tuple of (before_index, after_index)
    """
    
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    differences: list[str] = field(default_factory=list)
    entry_indices: tuple[int, int] | None = None
    
    @property
    def has_differences(self) -> bool:
        """Check if there are any differences."""
        return len(self.differences) > 0


class CborReplayUtilities:
    """Utilities for loading and processing CBOR capture files.
    
    Provides methods to:
    - Load CBOR capture files
    - Filter entries by direction
    - Extract specific fields from entries
    - Parse SSE data from entry bytes
    
    Requirements: 9.1, 9.2
    """
    
    def __init__(self) -> None:
        """Initialize the CBOR replay utilities."""
        self._reader = CaptureReader()
        self._session: CaptureSession | None = None
    
    def load_capture(self, path: str | Path) -> CaptureSession:
        """Load a CBOR capture file.
        
        Args:
            path: Path to the CBOR capture file
            
        Returns:
            CaptureSession containing header and entries
            
        Raises:
            FileNotFoundError: If the file doesn't exist
            InvalidCaptureFileError: If the file is invalid
        """
        self._session = self._reader.load(Path(path))
        return self._session
    
    def get_session(self) -> CaptureSession:
        """Get the currently loaded session.
        
        Returns:
            The loaded CaptureSession
            
        Raises:
            RuntimeError: If no session has been loaded
        """
        if self._session is None:
            raise RuntimeError("No capture session loaded. Call load_capture() first.")
        return self._session
    
    def filter_by_direction(
        self,
        entries: list[CaptureEntry],
        direction: CaptureDirection,
    ) -> list[CaptureEntry]:
        """Filter entries by traffic direction.
        
        Args:
            entries: List of capture entries to filter
            direction: Direction to filter by
            
        Returns:
            Filtered list of entries matching the direction
            
        Requirements: 9.1
        """
        return [e for e in entries if e.direction == direction]
    
    def filter_by_backend(
        self,
        entries: list[CaptureEntry],
        backend: str,
    ) -> list[CaptureEntry]:
        """Filter entries by backend name.
        
        Args:
            entries: List of capture entries to filter
            backend: Backend name to filter by
            
        Returns:
            Filtered list of entries matching the backend
        """
        return [e for e in entries if e.metadata.backend == backend]
    
    def parse_sse_data(self, data: bytes) -> list[dict[str, Any]]:
        """Parse SSE data from entry bytes.
        
        Handles multiple SSE events in a single data block.
        
        Args:
            data: Raw bytes from a capture entry
            
        Returns:
            List of parsed JSON objects from SSE data lines
        """
        if not data:
            return []
        
        results: list[dict[str, Any]] = []
        text = data.decode("utf-8", errors="replace")
        
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                json_str = line[6:].strip()
                if json_str and json_str != "[DONE]":
                    try:
                        parsed = json.loads(json_str)
                        if isinstance(parsed, dict):
                            results.append(parsed)
                    except json.JSONDecodeError:
                        continue
        
        return results
    
    def extract_field(
        self,
        entry: CaptureEntry,
        field_path: str,
        default: Any = None,
    ) -> Any:
        """Extract a specific field from an entry's parsed data.
        
        Supports dot-notation for nested fields (e.g., "choices.0.delta.content").
        
        Args:
            entry: Capture entry to extract from
            field_path: Dot-separated path to the field
            default: Default value if field not found
            
        Returns:
            The extracted field value or default
            
        Requirements: 9.2
        """
        parsed_list = self.parse_sse_data(entry.data)
        if not parsed_list:
            # Try parsing as raw JSON
            try:
                parsed = json.loads(entry.data.decode("utf-8", errors="replace"))
                if isinstance(parsed, dict):
                    parsed_list = [parsed]
            except json.JSONDecodeError:
                return default
        
        if not parsed_list:
            return default
        
        # Use the first parsed object
        data = parsed_list[0]
        return self._get_nested_field(data, field_path, default)
    
    def extract_all_fields(
        self,
        entry: CaptureEntry,
        field_path: str,
        default: Any = None,
    ) -> list[Any]:
        """Extract a field from all parsed SSE events in an entry.
        
        Args:
            entry: Capture entry to extract from
            field_path: Dot-separated path to the field
            default: Default value if field not found
            
        Returns:
            List of extracted field values from all events
        """
        parsed_list = self.parse_sse_data(entry.data)
        results = []
        
        for data in parsed_list:
            value = self._get_nested_field(data, field_path, default)
            results.append(value)
        
        return results
    
    def _get_nested_field(
        self,
        data: dict[str, Any],
        field_path: str,
        default: Any = None,
    ) -> Any:
        """Get a nested field from a dictionary using dot notation.
        
        Args:
            data: Dictionary to extract from
            field_path: Dot-separated path (e.g., "choices.0.delta.content")
            default: Default value if not found
            
        Returns:
            The field value or default
        """
        parts = field_path.split(".")
        current: Any = data
        
        for part in parts:
            if current is None:
                return default
            
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    index = int(part)
                    current = current[index] if 0 <= index < len(current) else None
                except (ValueError, IndexError):
                    return default
            else:
                return default
        
        return current if current is not None else default
    
    def get_backend_responses(self) -> list[CaptureEntry]:
        """Get all backend-to-proxy response entries.
        
        Returns:
            List of entries with direction BACKEND_TO_PROXY
        """
        session = self.get_session()
        return self.filter_by_direction(
            session.entries, CaptureDirection.BACKEND_TO_PROXY
        )
    
    def get_client_responses(self) -> list[CaptureEntry]:
        """Get all proxy-to-client response entries.
        
        Returns:
            List of entries with direction PROXY_TO_CLIENT
        """
        session = self.get_session()
        return self.filter_by_direction(
            session.entries, CaptureDirection.PROXY_TO_CLIENT
        )
    
    def get_streaming_chunks(
        self,
        direction: CaptureDirection | None = None,
    ) -> list[list[CaptureEntry]]:
        """Get streaming chunks grouped by stream session.
        
        Args:
            direction: Optional filter by direction
            
        Returns:
            List of lists, where each inner list is a complete stream
        """
        return self._reader.get_stream_chunks(direction)


class TransformationAnalyzer:
    """Analyzer for comparing before/after transformations in the pipeline.
    
    Provides methods to:
    - Compare backend responses to client responses
    - Detect usage data leaks
    - Verify content preservation
    - Generate diagnostic reports
    
    Requirements: 9.3
    """
    
    def __init__(self, utilities: CborReplayUtilities | None = None) -> None:
        """Initialize the transformation analyzer.
        
        Args:
            utilities: Optional CborReplayUtilities instance to use
        """
        self._utils = utilities or CborReplayUtilities()
    
    def compare_backend_to_client(
        self,
        session: CaptureSession,
    ) -> list[TransformationComparison]:
        """Compare backend responses to corresponding client responses.
        
        Pairs up backend-to-proxy entries with proxy-to-client entries
        and identifies differences in the transformation.
        
        Args:
            session: Capture session to analyze
            
        Returns:
            List of TransformationComparison objects
            
        Requirements: 9.3
        """
        backend_entries = self._utils.filter_by_direction(
            session.entries, CaptureDirection.BACKEND_TO_PROXY
        )
        client_entries = self._utils.filter_by_direction(
            session.entries, CaptureDirection.PROXY_TO_CLIENT
        )
        
        comparisons: list[TransformationComparison] = []
        
        # Simple pairing: match by sequence order
        # In a real scenario, you might want to match by request ID or timestamp
        for i, (backend, client) in enumerate(zip(backend_entries, client_entries)):
            backend_data = self._utils.parse_sse_data(backend.data)
            client_data = self._utils.parse_sse_data(client.data)
            
            before = backend_data[0] if backend_data else None
            after = client_data[0] if client_data else None
            
            differences = self._find_differences(before, after)
            
            comparisons.append(TransformationComparison(
                before=before,
                after=after,
                differences=differences,
                entry_indices=(backend.sequence, client.sequence),
            ))
        
        return comparisons
    
    def _find_differences(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> list[str]:
        """Find differences between before and after data.
        
        Args:
            before: Data before transformation
            after: Data after transformation
            
        Returns:
            List of difference descriptions
        """
        differences: list[str] = []
        
        if before is None and after is None:
            return differences
        
        if before is None:
            differences.append("Before data is missing")
            return differences
        
        if after is None:
            differences.append("After data is missing")
            return differences
        
        # Check for usage data location
        before_usage = before.get("usage")
        after_usage = after.get("usage")
        
        if before_usage and not after_usage:
            # Check if usage leaked into content
            after_content = self._get_delta_content(after)
            if after_content and "usage" in str(after_content):
                differences.append(
                    "Usage data leaked into delta.content instead of top-level"
                )
        
        # Check for content preservation
        before_content = self._get_delta_content(before)
        after_content = self._get_delta_content(after)
        
        if before_content and not after_content:
            differences.append("Content was lost in transformation")
        
        # Check for tool_calls preservation
        before_tool_calls = self._get_delta_tool_calls(before)
        after_tool_calls = self._get_delta_tool_calls(after)
        
        if before_tool_calls and not after_tool_calls:
            differences.append("Tool calls were lost in transformation")
        
        return differences
    
    def _get_delta_content(self, data: dict[str, Any] | None) -> str | None:
        """Extract delta.content from a chunk.
        
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
    
    def _get_delta_tool_calls(self, data: dict[str, Any] | None) -> list | None:
        """Extract delta.tool_calls from a chunk.
        
        Args:
            data: Parsed chunk data
            
        Returns:
            Tool calls list or None
        """
        if not data:
            return None
        
        choices = data.get("choices", [])
        if not choices:
            return None
        
        delta = choices[0].get("delta", {})
        return delta.get("tool_calls")
    
    def verify_usage_not_in_content(
        self,
        session: CaptureSession,
    ) -> list[VerificationResult]:
        """Verify that usage data does not appear in delta.content.
        
        Args:
            session: Capture session to verify
            
        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []
        client_entries = self._utils.filter_by_direction(
            session.entries, CaptureDirection.PROXY_TO_CLIENT
        )
        
        for i, entry in enumerate(client_entries):
            parsed_list = self._utils.parse_sse_data(entry.data)
            
            for parsed in parsed_list:
                content = self._get_delta_content(parsed)
                
                if content:
                    # Check if content contains usage-like JSON
                    if '"usage"' in content or '"prompt_tokens"' in content:
                        results.append(VerificationResult(
                            passed=False,
                            message="Usage data found in delta.content",
                            details={
                                "content_preview": content[:200],
                                "entry_sequence": entry.sequence,
                            },
                            entry_index=i,
                            field_path="choices.0.delta.content",
                        ))
                    else:
                        results.append(VerificationResult(
                            passed=True,
                            message="No usage data in delta.content",
                            entry_index=i,
                        ))
        
        return results
    
    def verify_usage_at_top_level(
        self,
        session: CaptureSession,
    ) -> list[VerificationResult]:
        """Verify that usage data appears at top level in final chunks.
        
        Args:
            session: Capture session to verify
            
        Returns:
            List of verification results
        """
        results: list[VerificationResult] = []
        client_entries = self._utils.filter_by_direction(
            session.entries, CaptureDirection.PROXY_TO_CLIENT
        )
        
        # Look for the final chunk (with finish_reason)
        for i, entry in enumerate(client_entries):
            parsed_list = self._utils.parse_sse_data(entry.data)
            
            for parsed in parsed_list:
                choices = parsed.get("choices", [])
                if choices:
                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason == "stop":
                        # This is a final chunk - check for usage
                        usage = parsed.get("usage")
                        if usage:
                            results.append(VerificationResult(
                                passed=True,
                                message="Usage data found at top level in final chunk",
                                details={"usage": usage},
                                entry_index=i,
                            ))
                        else:
                            results.append(VerificationResult(
                                passed=False,
                                message="Usage data missing from final chunk",
                                entry_index=i,
                            ))
        
        return results
    
    def generate_diagnostic_report(
        self,
        session: CaptureSession,
    ) -> str:
        """Generate a diagnostic report for the capture session.
        
        Args:
            session: Capture session to analyze
            
        Returns:
            Formatted diagnostic report string
            
        Requirements: 9.4
        """
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append("STREAMING PIPELINE DIAGNOSTIC REPORT")
        lines.append("=" * 70)
        lines.append("")
        
        # Summary
        summary = self._utils._reader.summarize()
        lines.append(f"Session ID: {summary.get('session_id', 'N/A')}")
        lines.append(f"Total Entries: {summary.get('total_entries', 0)}")
        lines.append(f"Duration: {summary.get('duration_seconds', 0):.2f}s")
        lines.append("")
        
        # Direction counts
        direction_counts = summary.get("direction_counts", {})
        lines.append("Direction Counts:")
        for direction, count in direction_counts.items():
            lines.append(f"  {direction}: {count}")
        lines.append("")
        
        # Verification results
        lines.append("Verification Results:")
        lines.append("-" * 40)
        
        usage_in_content = self.verify_usage_not_in_content(session)
        failures = [r for r in usage_in_content if not r.passed]
        if failures:
            lines.append(f"  Usage in content: {len(failures)} FAILURES")
            for f in failures[:3]:  # Show first 3
                lines.append(f"    - {f}")
        else:
            lines.append("  Usage in content: PASS")
        
        usage_at_top = self.verify_usage_at_top_level(session)
        failures = [r for r in usage_at_top if not r.passed]
        if failures:
            lines.append(f"  Usage at top level: {len(failures)} FAILURES")
            for f in failures[:3]:
                lines.append(f"    - {f}")
        else:
            lines.append("  Usage at top level: PASS")
        
        lines.append("")
        lines.append("=" * 70)
        
        return "\n".join(lines)


def main() -> int:
    """Main entry point for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="CBOR Replay Infrastructure for Streaming Fix Verification"
    )
    parser.add_argument(
        "capture_file",
        help="Path to the CBOR capture file",
    )
    parser.add_argument(
        "--report",
        "-r",
        action="store_true",
        help="Generate a diagnostic report",
    )
    parser.add_argument(
        "--verify-usage",
        "-u",
        action="store_true",
        help="Verify usage data handling",
    )
    parser.add_argument(
        "--compare",
        "-c",
        action="store_true",
        help="Compare backend to client transformations",
    )
    
    args = parser.parse_args()
    
    capture_path = Path(args.capture_file)
    if not capture_path.exists():
        print(f"Error: File not found: {capture_path}", file=sys.stderr)
        return 1
    
    utils = CborReplayUtilities()
    try:
        session = utils.load_capture(capture_path)
    except Exception as e:
        print(f"Error loading capture file: {e}", file=sys.stderr)
        return 1
    
    analyzer = TransformationAnalyzer(utils)
    
    if args.report:
        print(analyzer.generate_diagnostic_report(session))
    
    if args.verify_usage:
        print("\nUsage Data Verification:")
        print("-" * 40)
        
        results = analyzer.verify_usage_not_in_content(session)
        failures = [r for r in results if not r.passed]
        print(f"Usage not in content: {len(results) - len(failures)}/{len(results)} passed")
        for f in failures:
            print(f"  FAIL: {f}")
        
        results = analyzer.verify_usage_at_top_level(session)
        failures = [r for r in results if not r.passed]
        print(f"Usage at top level: {len(results) - len(failures)}/{len(results)} passed")
        for f in failures:
            print(f"  FAIL: {f}")
    
    if args.compare:
        print("\nTransformation Comparison:")
        print("-" * 40)
        
        comparisons = analyzer.compare_backend_to_client(session)
        for comp in comparisons:
            if comp.has_differences:
                print(f"Entry {comp.entry_indices}: {len(comp.differences)} differences")
                for diff in comp.differences:
                    print(f"  - {diff}")
    
    if not (args.report or args.verify_usage or args.compare):
        # Default: show summary
        summary = utils._reader.summarize()
        print(f"Loaded capture: {capture_path}")
        print(f"  Session ID: {summary.get('session_id', 'N/A')}")
        print(f"  Total Entries: {summary.get('total_entries', 0)}")
        print(f"  Duration: {summary.get('duration_seconds', 0):.2f}s")
        print("\nUse --report, --verify-usage, or --compare for detailed analysis.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
