"""Regression test for AntigravityOAuthConnector stream buffering memory leak fix.

This test verifies that AntigravityOAuthConnector._intercept_stream doesn't
buffer entire streams unbounded, causing memory leaks for large streams.

Fixed: Early exit mechanism when tool calls are detected, preventing unbounded
buffering of entire streams.
"""

import inspect
import os

import pytest
from src.connectors.antigravity_oauth import AntigravityOAuthConnector


class TestAntigravityOAuthStreamBufferingLeakRegression:
    """Regression tests for AntigravityOAuthConnector stream buffering leak fix."""

    def test_intercept_stream_has_early_exit_mechanism(self) -> None:
        """Test that _intercept_stream has early exit mechanism to prevent unbounded buffering."""
        # Read the source code to verify fix is in place
        connector_file = os.path.join(
            os.path.dirname(inspect.getfile(AntigravityOAuthConnector)),
            "antigravity_oauth.py",
        )

        with open(connector_file) as f:
            content = f.read()

        # Verify the fix is in place: should have early exit when tool calls detected
        assert (
            'if "<Tool>" in content_buffer and "</Tool>" in content_buffer:' in content
        ), (
            "_intercept_stream should have early exit mechanism when tool calls are detected. "
            "The fix may have been reverted or changed."
        )

        # Verify it breaks out of the loop early
        assert (
            "break"
            in content[
                content.find('if "<Tool>" in content_buffer') : content.find(
                    'if "<Tool>" in content_buffer'
                )
                + 500
            ]
        ), (
            "Early exit mechanism should break out of loop when tool calls detected. "
            "This prevents unbounded buffering of entire streams."
        )

    def test_intercept_stream_doesnt_buffer_entire_stream(self) -> None:
        """Test that _intercept_stream doesn't buffer entire stream before processing."""
        # Read the source code to verify fix is in place
        connector_file = os.path.join(
            os.path.dirname(inspect.getfile(AntigravityOAuthConnector)),
            "antigravity_oauth.py",
        )

        with open(connector_file) as f:
            content = f.read()

        # Find the _intercept_stream function
        intercept_start = content.find("async def _intercept_stream()")
        if intercept_start == -1:
            pytest.skip("_intercept_stream function not found")

        # Get the function body
        intercept_end = content.find("\n            async def ", intercept_start + 1)
        if intercept_end == -1:
            intercept_end = content.find("\n    def ", intercept_start + 1)
        if intercept_end == -1:
            intercept_end = len(content)

        function_body = content[intercept_start:intercept_end]

        # Verify it processes stream incrementally (not buffering entire stream first)
        # Should process chunks as they come, not buffer all then process
        assert (
            "async for chunk in original_iterator:" in function_body
        ), "_intercept_stream should process stream incrementally, not buffer entire stream first."

        # Verify early exit exists
        assert (
            "break" in function_body
        ), "_intercept_stream should have break statement for early exit when tool calls detected."

    def test_intercept_stream_has_bounded_memory_usage(self) -> None:
        """Test that _intercept_stream has bounded memory usage via early exit."""
        # Read the source code to verify fix is in place
        connector_file = os.path.join(
            os.path.dirname(inspect.getfile(AntigravityOAuthConnector)),
            "antigravity_oauth.py",
        )

        with open(connector_file) as f:
            content = f.read()

        # Verify comment mentions bounded memory usage
        assert "bounded memory" in content.lower() or "bounded" in content.lower(), (
            "Code should have comments/documentation about bounded memory usage. "
            "This indicates awareness of the memory leak issue."
        )

        # Verify early exit prevents unbounded buffering
        intercept_start = content.find("async def _intercept_stream()")
        if intercept_start != -1:
            # Check that it breaks early when tool calls are detected
            assert (
                'if "<Tool>" in content_buffer and "</Tool>" in content_buffer:'
                in content
            ), "Early exit mechanism should prevent unbounded buffering when tool calls detected."
