"""
Test to prevent duplicate API requests in Gemini OAuth connectors.

This test ensures that streaming implementations only make a single request
to the Gemini API, preventing quota exhaustion and 429 errors caused by
duplicate requests.
"""

import glob
import importlib.util
import re
from pathlib import Path

import pytest


class TestGeminiDuplicateRequestPrevention:
    """Test suite to prevent duplicate API requests."""

    @staticmethod
    def _resolve_streaming_files() -> list[Path]:
        """Resolve streaming implementation files available in current environment."""
        files = [Path("src/connectors/gemini_cloud_project.py")]
        plugin_spec = importlib.util.find_spec(
            "llm_proxy_oauth_connectors.gemini_oauth_base"
        )
        if plugin_spec and plugin_spec.origin:
            plugin_file = Path(plugin_spec.origin)
            if plugin_file.exists():
                files.insert(0, plugin_file)
        return files

    def test_request_deduplication_pattern_detection(self):
        """
        Static analysis test to detect duplicate request patterns in code.

        This test scans the source code for patterns that might indicate
        duplicate requests.
        """
        # Check all Gemini connector files
        gemini_files = glob.glob("src/connectors/gemini*.py")

        total_duplicate_requests = 0
        problematic_files = []

        for file_path in gemini_files:
            with open(file_path) as f:
                source_code = f.read()

            # Look for multiple auth_session.request calls in the same method
            # This pattern was the root cause of the duplicate request bug
            request_pattern = r"auth_session\.request\s*\("

            # Count occurrences in streaming methods
            streaming_method_pattern = (
                r"(async def.*streaming.*?(?=async def|class|\Z))"
            )
            streaming_methods = re.findall(
                streaming_method_pattern, source_code, re.DOTALL
            )

            file_duplicate_requests = 0
            for method in streaming_methods:
                method_requests = re.findall(request_pattern, method)
                if len(method_requests) > 1:
                    file_duplicate_requests += len(method_requests) - 1

            if file_duplicate_requests > 0:
                problematic_files.append(
                    f"{file_path}: {file_duplicate_requests} duplicates"
                )
                total_duplicate_requests += file_duplicate_requests

        assert total_duplicate_requests == 0, (
            f"Found {total_duplicate_requests} potential duplicate requests "
            f"in streaming methods across Gemini connectors. "
            f"This pattern caused the 429 error bug. "
            f"Each streaming method should make exactly one API request. "
            f"Problematic files: {problematic_files}"
        )

    def test_streaming_delegation_pattern(self):
        """
        Test that streaming implementation delegates correctly to avoid duplicates.

        Verifies that main streaming methods delegate to stream_generator
        rather than making direct requests.
        """
        files_to_check = self._resolve_streaming_files()

        for file_path in files_to_check:
            with file_path.open(encoding="utf-8") as f:
                source_code = f.read()

            # Look for the streaming method
            streaming_method_pattern = (
                r"(async def.*streaming.*?(?=async def|def [^_]|class|\Z))"
            )
            streaming_methods = re.findall(
                streaming_method_pattern, source_code, re.DOTALL
            )

            for method in streaming_methods:
                # Count auth_session.request calls in this method
                request_pattern = r"auth_session\.request\s*\("
                request_matches = re.findall(request_pattern, method)

                # Get method name
                method_name_match = re.search(r"async def\s+(\w+)", method)
                method_name = (
                    method_name_match.group(1) if method_name_match else "unknown"
                )

                if "stream_generator" in method_name:
                    # stream_generator should have exactly 1 request
                    assert len(request_matches) == 1, (
                        f"stream_generator in {file_path} should make exactly 1 request, "
                        f"but found {len(request_matches)}. This indicates duplicate requests."
                    )
                else:
                    # Main streaming methods should delegate to stream_generator (0 requests)
                    assert len(request_matches) == 0, (
                        f"Streaming method {method_name} in {file_path} should not make "
                        f"direct requests (should delegate to stream_generator), "
                        f"but found {len(request_matches)} requests. This indicates duplicate requests."
                    )

    def test_no_duplicate_sse_parsing(self):
        """
        Test that there's no duplicate SSE parsing logic that indicates duplicate requests.
        """
        files_to_check = self._resolve_streaming_files()

        for file_path in files_to_check:
            with file_path.open(encoding="utf-8") as f:
                source_code = f.read()

            # Look for SSE parsing patterns that might indicate duplicate processing
            sse_patterns = [
                r"response\.text",
                r"data_str = line\[6:\]\.strip\(\)",
                r'for line in.*split\("\\n"\)',
            ]

            # Count SSE parsing blocks in non-streaming methods
            non_streaming_pattern = (
                r"(def _chat_completions_(?!.*streaming).*?(?=def |class |\Z))"
            )
            non_streaming_methods = re.findall(
                non_streaming_pattern, source_code, re.DOTALL
            )

            for method in non_streaming_methods:
                sse_count = 0
                for pattern in sse_patterns:
                    sse_count += len(re.findall(pattern, method))

                # Non-streaming methods should not have SSE parsing (indicates duplicate processing)
                assert sse_count == 0, (
                    f"Found SSE parsing in non-streaming method in {file_path}. "
                    f"This indicates duplicate request processing that was causing 429 errors."
                )


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])
