"""Regression test for DoS vulnerability in RollingHashTracker.

This test verifies that RollingHashTracker._check_pattern_length doesn't
cause excessive CPU usage through nested loops when processing malicious input.
"""

import pytest
from src.loop_detection.hybrid_detector import LongPatternMatch, RollingHashTracker
from tests.unit.fixtures.markers import real_time


class TestDosHybridDetectorRegression:
    """Regression tests for DoS vulnerability in RollingHashTracker."""

    @real_time(reason="Measures actual processing time to detect DoS vulnerabilities.")
    def test_dos_vulnerability_processing_time(self) -> None:
        """Test that processing doesn't take excessive time (DoS vulnerability check)."""
        import time

        tracker = RollingHashTracker(
            min_pattern_length=60,  # Default: MIN_LONG_PATTERN_LENGTH
            max_pattern_length=500,  # Default: MAX_LONG_PATTERN_LENGTH
            min_repetitions=3,
            max_history=2000,
        )

        # Craft malicious content that triggers maximum iterations
        # Content that will NOT trigger early detection but still requires full processing
        # Use content that has no clear repetitions but is at the threshold
        malicious_content = "".join(
            chr(65 + (i % 26)) for i in range(1800)
        )  # 1800 unique-ish chars

        # Measure time taken
        start_time = time.time()
        result = tracker.add_content(malicious_content)
        end_time = time.time()

        processing_time = end_time - start_time

        # If it takes more than 1 second for a simple operation, it's potentially vulnerable
        assert processing_time < 1.0, (
            f"Processing took {processing_time:.4f} seconds, which exceeds "
            "acceptable threshold (1.0s). Potential DoS vulnerability detected!"
        )

        # Verify processing completed successfully
        assert result is None or isinstance(
            result, tuple | LongPatternMatch
        ), "Processing should complete successfully without errors"

    @real_time(
        reason="Measures actual processing time for edge cases to detect DoS vulnerabilities."
    )
    def test_edge_cases_processing_time(self) -> None:
        """Test edge cases that could trigger the vulnerability."""
        import time

        tracker = RollingHashTracker(max_pattern_length=500)

        test_cases = [
            # Case 1: Content just at the threshold for triggering detection
            ("A" * 180, "Minimum threshold content"),
            # Case 2: Content with many different pattern lengths
            (
                "A" * 100 + "B" * 100 + "C" * 100 + "D" * 100 + "E" * 100,
                "Multi-pattern content",
            ),
            # Case 3: Content that maximizes pattern length checks
            ("A" * 250 + "B" * 250, "Two long patterns"),
            # Case 4: Content with varying character frequencies
            (
                "A" * 50
                + "B" * 50
                + "C" * 50
                + "D" * 50
                + "E" * 50
                + "F" * 50
                + "G" * 50
                + "H" * 50,
                "8 different chars",
            ),
        ]

        for content, description in test_cases:
            tracker.reset()  # Reset for each test

            start_time = time.time()
            try:
                result = tracker.add_content(content)
                end_time = time.time()

                processing_time = end_time - start_time

                # Lower threshold for edge cases (0.5 seconds)
                assert processing_time < 0.5, (
                    f"Edge case '{description}' took {processing_time:.4f} seconds, "
                    "which exceeds acceptable threshold (0.5s). Slow processing detected."
                )

                # Verify processing completed successfully
                assert result is None or isinstance(
                    result, tuple | LongPatternMatch
                ), f"Processing should complete successfully for '{description}'"

            except Exception as e:
                pytest.fail(
                    f"Error processing edge case '{description}': {e}. "
                    "Errors that could be induced by malformed input are also vulnerabilities."
                )

    @real_time(reason="Measures actual processing time to detect DoS vulnerabilities.")
    def test_pattern_length_range_does_not_cause_excessive_iterations(self) -> None:
        """Test that pattern length range doesn't cause excessive iterations."""
        import time

        tracker = RollingHashTracker(
            min_pattern_length=60,
            max_pattern_length=500,
            min_repetitions=3,
            max_history=2000,
        )

        # Content that would cause many pattern length checks
        content = "".join(chr(65 + (i % 26)) for i in range(1800))

        start_time = time.time()
        result = tracker.add_content(content)
        end_time = time.time()

        processing_time = end_time - start_time

        # Calculate expected iterations
        pattern_length_range = tracker.max_pattern_length - tracker.min_pattern_length
        expected_max_iterations = pattern_length_range * len(content)

        # Verify processing time is reasonable
        assert processing_time < 1.0, (
            f"Processing took {processing_time:.4f} seconds. "
            f"Pattern length range ({pattern_length_range}) * content length "
            f"({len(content)}) = {expected_max_iterations} potential iterations, "
            "but processing should still complete quickly."
        )

        # Verify result is valid
        assert result is None or isinstance(
            result, tuple | LongPatternMatch
        ), "Processing should complete successfully"
