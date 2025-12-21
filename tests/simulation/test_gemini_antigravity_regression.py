"""
Regression test for antigravity-oauth backend issues.

This test uses a captured CBOR wire capture session to verify the proxy's
handling of:
1. Empty responses from the primary backend
2. Model name masking in responses
3. Fallback mechanism activation

The capture file documents real-world issues discovered during testing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.domain.cbor_capture import CaptureDirection
from src.core.simulation import CaptureReader

# Path to the captured session with known issues
CAPTURE_FILE = Path("var/wire_captures_cbor/c6095b51b3b844769f17469fefea2d89.cbor")


@pytest.fixture
def capture_session():
    """Load the captured session for analysis."""
    if not CAPTURE_FILE.exists():
        pytest.skip(f"Capture file not found: {CAPTURE_FILE}")
    reader = CaptureReader()
    return reader.load(CAPTURE_FILE)


@pytest.fixture
def capture_entries(capture_session):
    """Get all entries from the capture."""
    return capture_session.entries


def parse_sse_data(data: bytes) -> dict | None:
    """Parse SSE data chunk into JSON if valid.

    SSE chunks may contain multiple events separated by blank lines.
    This function parses the first non-[DONE] JSON event.
    """
    if not data:
        return None
    text = data.decode("utf-8", errors="replace").strip()

    # SSE format: events are separated by blank lines
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            json_str = line[6:].strip()
            if json_str and json_str != "[DONE]":
                try:
                    result: dict = json.loads(json_str)  # type: ignore[type-arg]
                    return result
                except json.JSONDecodeError:
                    continue
    return None


@pytest.mark.skip(reason="Requires specific complex capture file")
class TestAntigravityOAuthRegression:
    """Test cases for antigravity-oauth backend issues."""

    def test_capture_file_loads_successfully(self, capture_session):
        """Verify the capture file can be loaded and parsed."""
        assert capture_session is not None
        assert len(capture_session.entries) > 0
        assert capture_session.header.session_id

    def test_capture_has_expected_structure(self, capture_entries):
        """Verify the capture has the expected request/response structure."""
        # Count entries by direction
        directions = {}
        for e in capture_entries:
            dir_name = e.direction.name
            directions[dir_name] = directions.get(dir_name, 0) + 1

        # Should have client requests
        assert directions.get("CLIENT_TO_PROXY", 0) > 0
        # Should have proxy forwarding to backend
        assert directions.get("PROXY_TO_BACKEND", 0) > 0
        # Should have backend responses
        assert directions.get("BACKEND_TO_PROXY", 0) > 0
        # Should have proxy responses to client
        assert directions.get("PROXY_TO_CLIENT", 0) > 0

    def test_detects_empty_response_issue(self, capture_entries):
        """Test that we can detect empty responses from the backend.

        Issue: The first two requests receive usage-only chunks followed by
        immediate finish_reason="stop" with no actual content.
        """
        # Find backend responses for first request
        backend_responses = []
        in_first_request = False
        request_count = 0

        for e in capture_entries:
            if e.direction == CaptureDirection.CLIENT_TO_PROXY:
                request_count += 1
                if request_count == 1:
                    in_first_request = True
                elif request_count == 2:
                    break  # Stop at second request
            elif in_first_request and e.direction == CaptureDirection.BACKEND_TO_PROXY:
                backend_responses.append(e)

        # Check for empty response pattern
        usage_only = False
        has_content = False
        immediate_stop = False

        for entry in backend_responses:
            data = parse_sse_data(entry.data)
            if data:
                # Check for usage-only chunk (completion_tokens=0)
                usage = data.get("usage", {})
                if usage and usage.get("completion_tokens", 0) == 0:
                    usage_only = True

                # Check for immediate stop without content
                choices = data.get("choices", [])
                for choice in choices:
                    if choice.get("finish_reason") == "stop":
                        immediate_stop = True
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        has_content = True

        # This documents the known issue
        assert usage_only, "Expected to find usage-only chunk"
        assert immediate_stop, "Expected immediate finish_reason=stop"
        assert not has_content, "First request should have no content (known issue)"

    def test_detects_model_name_leak(self, capture_entries):
        """Test that we can detect internal model name leakage.

        Issue: Backend returns model='code-assist-model' instead of the
        requested model name 'gemini-2.5-pro'.
        """
        internal_model_names = set()
        requested_models = set()

        for e in capture_entries:
            if e.direction == CaptureDirection.CLIENT_TO_PROXY and e.data:
                try:
                    req = json.loads(e.data.decode("utf-8"))
                    if "model" in req:
                        requested_models.add(req["model"])
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

            if e.direction == CaptureDirection.BACKEND_TO_PROXY:
                data = parse_sse_data(e.data)
                if data and "model" in data:
                    model = data["model"]
                    # Check for internal model names that don't match request
                    if model and "code-assist" in model.lower():
                        internal_model_names.add(model)

        # Document the known issue - internal model name exposed
        assert (
            "code-assist-model" in internal_model_names
        ), "Expected to find internal model name leak"
        assert any(
            "gemini" in m for m in requested_models
        ), "Expected gemini model in requests"

    def test_detects_fallback_activation(self, capture_entries):
        """Test that we can detect when fallback mechanism activates.

        Issue: After empty responses, the fallback mechanism kicks in
        with chatcmpl-fallback-* IDs.
        """
        fallback_ids = []
        regular_ids = []

        for e in capture_entries:
            if e.direction == CaptureDirection.BACKEND_TO_PROXY:
                data = parse_sse_data(e.data)
                if data and "id" in data:
                    msg_id = data["id"]
                    if "fallback" in msg_id:
                        fallback_ids.append(msg_id)
                    else:
                        regular_ids.append(msg_id)

        # Document the fallback behavior
        assert len(fallback_ids) > 0, "Expected fallback mechanism to activate"
        assert len(regular_ids) > 0, "Expected some regular (non-fallback) responses"

    def test_fallback_produces_content(self, capture_entries):
        """Test that fallback responses actually contain content.

        The fallback mechanism should produce usable responses when
        the primary backend fails.
        """
        fallback_content = []

        for e in capture_entries:
            if e.direction == CaptureDirection.BACKEND_TO_PROXY:
                data = parse_sse_data(e.data)
                if data and "id" in data:
                    msg_id = data["id"]
                    if "fallback" in msg_id:
                        choices = data.get("choices", [])
                        for choice in choices:
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            tool_calls = delta.get("tool_calls", [])
                            if content:
                                fallback_content.append(content)
                            if tool_calls:
                                fallback_content.append(f"tool_calls:{len(tool_calls)}")

        # Fallback should produce actual content
        assert len(fallback_content) > 0, "Fallback should produce content"

    def test_client_receives_responses_after_fallback(self, capture_entries):
        """Test that client receives responses after fallback activates.

        Verify that the proxy forwards responses to the client even after
        the fallback mechanism kicks in. The response IDs may be transformed.
        """
        # Find all non-empty client responses after request 3
        client_responses_after_fallback = []
        request_count = 0

        for e in capture_entries:
            if e.direction == CaptureDirection.CLIENT_TO_PROXY:
                request_count += 1
            elif (
                request_count >= 3
                and e.direction == CaptureDirection.PROXY_TO_CLIENT
                and e.data
            ):
                data = parse_sse_data(e.data)
                if data and data.get("choices"):
                    client_responses_after_fallback.append(data)

        # Client should receive responses after fallback activates
        assert (
            len(client_responses_after_fallback) > 0
        ), "Client should receive responses after fallback activates"

        # Check that responses have useful content
        has_useful_content = False
        for resp in client_responses_after_fallback:
            choices = resp.get("choices", [])
            for choice in choices:
                if choice.get("finish_reason"):
                    has_useful_content = True
                delta = choice.get("delta", {})
                if delta.get("tool_calls") or delta.get("content"):
                    has_useful_content = True

        assert has_useful_content, "Client responses should have useful content"


class TestCaptureAnalysisUtilities:
    """Test the CBOR capture analysis utilities work correctly."""

    def test_capture_reader_summarize(self):
        """Test that CaptureReader can generate summary statistics."""
        if not CAPTURE_FILE.exists():
            pytest.skip(f"Capture file not found: {CAPTURE_FILE}")

        reader = CaptureReader()
        reader.load(CAPTURE_FILE)
        summary = reader.summarize()

        assert "total_entries" in summary
        assert "total_bytes" in summary
        assert "duration_seconds" in summary
        assert "direction_counts" in summary
        assert summary["total_entries"] > 0

    def test_capture_timing_analysis(self, capture_session):
        """Test that timing deltas can be extracted and analyzed."""
        deltas = capture_session.get_timing_deltas()

        # Should have timing data
        assert len(deltas) > 0
        # All deltas should be non-negative (time moves forward)
        assert all(d >= 0 for d in deltas)

    def test_direction_filtering(self, capture_session):
        """Test that entries can be filtered by direction."""
        client_entries = capture_session.get_client_entries()
        backend_entries = capture_session.get_backend_entries()

        # Should have entries in both directions
        assert len(client_entries) > 0
        assert len(backend_entries) > 0

        # Verify filtering is correct
        for e in client_entries:
            assert e.direction in (
                CaptureDirection.CLIENT_TO_PROXY,
                CaptureDirection.PROXY_TO_CLIENT,
            )
        for e in backend_entries:
            assert e.direction in (
                CaptureDirection.PROXY_TO_BACKEND,
                CaptureDirection.BACKEND_TO_PROXY,
            )
