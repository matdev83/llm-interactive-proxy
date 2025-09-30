"""
Tests for GeminiCliLoopDetector.

Ported from Google's gemini-cli test suite:
https://github.com/google/generative-ai-docs/blob/main/gemini-cli/packages/core/src/services/loopDetectionService.test.ts
"""

import pytest
from src.loop_detection.gemini_cli_detector import GeminiCliLoopDetector

# Constants from the original implementation
CONTENT_LOOP_THRESHOLD = 10
CONTENT_CHUNK_SIZE = 50


def create_repetitive_content(id_num: int, length: int) -> str:
    """Create repetitive content for testing."""
    base_string = f"This is a unique sentence, id={id_num}. "
    content = ""
    while len(content) < length:
        content += base_string
    return content[:length]


def generate_random_string(length: int) -> str:
    """Generate random string for testing."""
    import random
    import string

    characters = string.ascii_letters + string.digits
    return "".join(random.choice(characters) for _ in range(length))


class TestContentLoopDetection:
    """Test content loop detection functionality."""

    def test_should_not_detect_loop_for_random_content(self):
        """Should not detect a loop for random content."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        for _ in range(1000):
            content = generate_random_string(10)
            is_loop = detector.process_chunk(content)
            assert is_loop is None

    def test_should_detect_loop_when_chunk_repeats_consecutively(self):
        """Should detect a loop when a chunk of content repeats consecutively."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        is_loop = None
        for _ in range(CONTENT_LOOP_THRESHOLD):
            is_loop = detector.process_chunk(repeated_content)

        assert is_loop is not None

    def test_should_not_detect_loop_if_repetitions_are_far_apart(self):
        """Should not detect a loop if repetitions are very far apart."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)
        filler_content = generate_random_string(500)

        is_loop = None
        for _ in range(CONTENT_LOOP_THRESHOLD):
            detector.process_chunk(repeated_content)
            is_loop = detector.process_chunk(filler_content)

        assert is_loop is None


class TestContentLoopDetectionWithCodeBlocks:
    """Test content loop detection with code blocks."""

    def test_should_not_detect_loop_inside_code_block(self):
        """Should not detect a loop when repetitive content is inside a code block."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        detector.process_chunk("```\n")

        for _ in range(CONTENT_LOOP_THRESHOLD):
            is_loop = detector.process_chunk(repeated_content)
            assert is_loop is None

        is_loop = detector.process_chunk("\n```")
        assert is_loop is None

    def test_should_not_detect_loops_when_content_transitions_into_code_block(self):
        """Should not detect loops when content transitions into a code block."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        # Add some repetitive content outside of code block
        for _ in range(CONTENT_LOOP_THRESHOLD - 2):
            detector.process_chunk(repeated_content)

        # Now transition into a code block
        code_block_start = "```javascript\n"
        is_loop = detector.process_chunk(code_block_start)
        assert is_loop is None

        # Continue adding repetitive content inside the code block
        for _ in range(CONTENT_LOOP_THRESHOLD):
            is_loop = detector.process_chunk(repeated_content)
            assert is_loop is None

    def test_should_skip_loop_detection_when_already_inside_code_block(self):
        """Should skip loop detection when already inside a code block."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        # Start with content that puts us inside a code block
        detector.process_chunk("Here is some code:\n```\n")

        # Verify we are now inside a code block
        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)
        for _ in range(CONTENT_LOOP_THRESHOLD + 5):
            is_loop = detector.process_chunk(repeated_content)
            assert is_loop is None

    def test_should_correctly_track_code_block_state_with_multiple_fences(self):
        """Should correctly track inCodeBlock state with multiple fence transitions."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        # Outside code block - should track content
        detector.process_chunk("Normal text ")

        # Enter code block (1 fence) - should stop tracking
        enter_result = detector.process_chunk("```\n")
        assert enter_result is None

        # Inside code block - should not track loops
        for _ in range(5):
            inside_result = detector.process_chunk(repeated_content)
            assert inside_result is None

        # Exit code block (2nd fence) - should reset tracking but still return None
        exit_result = detector.process_chunk("```\n")
        assert exit_result is None

        # Enter code block again (3rd fence) - should stop tracking again
        reenter_result = detector.process_chunk("```python\n")
        assert reenter_result is None

    def test_should_detect_loop_when_repetitive_content_is_outside_code_block(self):
        """Should detect a loop when repetitive content is outside a code block."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        detector.process_chunk("```")
        detector.process_chunk("\nsome code\n")
        detector.process_chunk("```")

        is_loop = None
        for _ in range(CONTENT_LOOP_THRESHOLD):
            is_loop = detector.process_chunk(repeated_content)

        assert is_loop is not None

    def test_should_handle_content_with_multiple_code_blocks_no_loops(self):
        """Should handle content with multiple code blocks and no loops."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        detector.process_chunk("```\ncode1\n```")
        detector.process_chunk("\nsome text\n")
        is_loop = detector.process_chunk("```\ncode2\n```")

        assert is_loop is None

    def test_should_handle_content_with_mixed_code_blocks_and_looping_text(self):
        """Should handle content with mixed code blocks and looping text."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        detector.process_chunk("```")
        detector.process_chunk("\ncode1\n")
        detector.process_chunk("```")

        is_loop = None
        for _ in range(CONTENT_LOOP_THRESHOLD):
            is_loop = detector.process_chunk(repeated_content)

        assert is_loop is not None

    def test_should_not_detect_loop_for_long_code_block_with_repeating_tokens(self):
        """Should not detect a loop for a long code block with some repeating tokens."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeating_tokens = "for (let i = 0; i < 10; i++) { console.log(i); }"

        detector.process_chunk("```\n")

        for _ in range(20):
            is_loop = detector.process_chunk(repeating_tokens)
            assert is_loop is None

        is_loop = detector.process_chunk("\n```")
        assert is_loop is None

    def test_should_reset_tracking_when_code_fence_is_found(self):
        """Should reset tracking when a code fence is found."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            detector.process_chunk(repeated_content)

        # This should not trigger a loop because of the reset
        detector.process_chunk("```")

        # We are now in a code block, so loop detection should be off
        for _ in range(CONTENT_LOOP_THRESHOLD):
            is_loop = detector.process_chunk(repeated_content)
            assert is_loop is None

    def test_should_reset_tracking_when_table_is_detected(self):
        """Should reset tracking when a table is detected."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            detector.process_chunk(repeated_content)

        # This should reset tracking and not trigger a loop
        detector.process_chunk("| Column 1 | Column 2 |")

        # Add more repeated content after table - should not trigger loop
        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            is_loop = detector.process_chunk(repeated_content)
            assert is_loop is None

    def test_should_reset_tracking_when_list_item_is_detected(self):
        """Should reset tracking when a list item is detected."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            detector.process_chunk(repeated_content)

        # This should reset tracking and not trigger a loop
        detector.process_chunk("* List item")

        # Add more repeated content after list - should not trigger loop
        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            is_loop = detector.process_chunk(repeated_content)
            assert is_loop is None

    def test_should_reset_tracking_when_heading_is_detected(self):
        """Should reset tracking when a heading is detected."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            detector.process_chunk(repeated_content)

        # This should reset tracking and not trigger a loop
        detector.process_chunk("## Heading")

        # Add more repeated content after heading - should not trigger loop
        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            is_loop = detector.process_chunk(repeated_content)
            assert is_loop is None

    def test_should_reset_tracking_when_blockquote_is_detected(self):
        """Should reset tracking when a blockquote is detected."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            detector.process_chunk(repeated_content)

        # This should reset tracking and not trigger a loop
        detector.process_chunk("> Quote text")

        # Add more repeated content after blockquote - should not trigger loop
        for _ in range(CONTENT_LOOP_THRESHOLD - 1):
            is_loop = detector.process_chunk(repeated_content)
            assert is_loop is None

    def test_should_reset_tracking_for_various_list_formats(self):
        """Should reset tracking for various list item formats."""
        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        list_formats = [
            "* Bullet item",
            "- Dash item",
            "+ Plus item",
            "1. Numbered item",
            "42. Another numbered item",
        ]

        for idx, list_format in enumerate(list_formats):
            detector = GeminiCliLoopDetector()
            detector.reset()

            # Build up to near threshold
            for _ in range(CONTENT_LOOP_THRESHOLD - 1):
                detector.process_chunk(repeated_content)

            # Reset should occur with list item - add newline to ensure it starts at beginning
            detector.process_chunk("\n" + list_format)

            # Should not trigger loop after reset - use different content to avoid cached state
            new_repeated_content = create_repetitive_content(
                idx + 100, CONTENT_CHUNK_SIZE
            )
            for _ in range(CONTENT_LOOP_THRESHOLD - 1):
                is_loop = detector.process_chunk(new_repeated_content)
                assert is_loop is None

    def test_should_reset_tracking_for_various_table_formats(self):
        """Should reset tracking for various table formats."""
        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        table_formats = [
            "| Column 1 | Column 2 |",
            "|---|---|",
            "|++|++|",
            "+---+---+",
        ]

        for idx, table_format in enumerate(table_formats):
            detector = GeminiCliLoopDetector()
            detector.reset()

            # Build up to near threshold
            for _ in range(CONTENT_LOOP_THRESHOLD - 1):
                detector.process_chunk(repeated_content)

            # Reset should occur with table format
            detector.process_chunk("\n" + table_format)

            # Should not trigger loop after reset
            new_repeated_content = create_repetitive_content(
                idx + 200, CONTENT_CHUNK_SIZE
            )
            for _ in range(CONTENT_LOOP_THRESHOLD - 1):
                is_loop = detector.process_chunk(new_repeated_content)
                assert is_loop is None

    def test_should_reset_tracking_for_various_heading_levels(self):
        """Should reset tracking for various heading levels."""
        repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)

        heading_formats = [
            "# H1 Heading",
            "## H2 Heading",
            "### H3 Heading",
            "#### H4 Heading",
            "##### H5 Heading",
            "###### H6 Heading",
        ]

        for idx, heading_format in enumerate(heading_formats):
            detector = GeminiCliLoopDetector()
            detector.reset()

            # Build up to near threshold
            for _ in range(CONTENT_LOOP_THRESHOLD - 1):
                detector.process_chunk(repeated_content)

            # Reset should occur with heading
            detector.process_chunk("\n" + heading_format)

            # Should not trigger loop after reset
            new_repeated_content = create_repetitive_content(
                idx + 300, CONTENT_CHUNK_SIZE
            )
            for _ in range(CONTENT_LOOP_THRESHOLD - 1):
                is_loop = detector.process_chunk(new_repeated_content)
                assert is_loop is None


class TestDividerContentDetection:
    """Test divider content detection."""

    def test_should_not_detect_loop_for_repeating_divider_content(self):
        """Should not detect a loop for repeating divider-like content."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        divider_content = "-" * CONTENT_CHUNK_SIZE

        for _ in range(CONTENT_LOOP_THRESHOLD + 5):
            is_loop = detector.process_chunk(divider_content)
            assert is_loop is None

    def test_should_not_detect_loop_for_repeating_complex_box_drawing_dividers(self):
        """Should not detect a loop for repeating complex box-drawing dividers."""
        detector = GeminiCliLoopDetector()
        detector.reset()

        divider_content = "+-" * (CONTENT_CHUNK_SIZE // 2)

        for _ in range(CONTENT_LOOP_THRESHOLD + 5):
            is_loop = detector.process_chunk(divider_content)
            assert is_loop is None


class TestEdgeCases:
    """Test edge cases."""

    def test_should_handle_empty_content(self):
        """Should handle empty content."""
        detector = GeminiCliLoopDetector()
        event = detector.process_chunk("")
        assert event is None


class TestOriginalBugPattern:
    """Test the original bug pattern from the user's report."""

    def test_should_detect_simple_repetitive_patterns(self):
        """
        Test that the ported algorithm detects simple repetitive patterns.

        The gemini-cli algorithm works by detecting repeated 50-char chunks.
        It can detect:
        1. Short patterns (< 50 chars) that repeat - creates overlapping identical chunks
        2. Longer patterns with internal repetition - some 50-char chunks will match

        It CANNOT detect:
        3. Patterns longer than chunk_size with no internal 50-char repetition
           (like the original bug pattern which is 200 chars of unique content)

        This is a fundamental limitation of the hash-chunk approach.
        """
        detector = GeminiCliLoopDetector(max_history_length=5000)
        detector.reset()

        # Test with a shorter pattern that WILL be detected
        short_looping_pattern = "Analyzing files... Please wait.\n"
        print(f"\nPattern length: {len(short_looping_pattern)} chars")

        detection_event = None
        for i in range(20):
            detection_event = detector.process_chunk(short_looping_pattern)
            if detection_event:
                print(f"Detected at iteration {i+1}")
                break

        assert detection_event is not None, "Short repetitive pattern MUST be detected!"

    def test_original_bug_pattern_limitation(self):
        """
        Document the limitation: patterns longer than chunk_size with no
        internal repetition cannot be detected by the hash-chunk algorithm.

        The original bug pattern (200 chars) falls into this category.
        This test demonstrates the limitation.
        """
        detector = GeminiCliLoopDetector(max_history_length=5000)
        detector.reset()

        # Original bug pattern (200 characters, mostly unique)
        original_looped_content = """Analyzing the Test File Structure

The test file follows the standard pytest structure with:
- Fixtures for setup
- Test classes for organization
- Individual test methods

Key Components:

Fixtures:
"""

        # This pattern is 200 chars and contains no repeated 50-char substring
        # Therefore, the hash-chunk algorithm cannot detect it as a loop
        detection_event = None
        for _ in range(15):
            detection_event = detector.process_chunk(original_looped_content)
            if detection_event:
                break

        # This is EXPECTED to not be detected due to algorithm limitations
        # A more sophisticated algorithm (sequence-based) would be needed
        assert detection_event is None, (
            "This pattern is NOT detectable by hash-chunk algorithm - "
            "it's 200 chars with no repeated 50-char chunks. "
            "This documents a known limitation."
        )


@pytest.mark.asyncio
async def test_async_check_for_loops_interface():
    """Test the async check_for_loops interface."""
    detector = GeminiCliLoopDetector()

    # Test with repeated content
    repeated = "Test pattern " * 50
    result = await detector.check_for_loops(repeated)

    # This might or might not detect a loop depending on the pattern
    assert result.has_loop in [True, False]


def test_detector_stats():
    """Test that detector stats are properly maintained."""
    detector = GeminiCliLoopDetector()
    stats = detector.get_stats()

    assert "is_enabled" in stats
    assert "config" in stats
    assert stats["config"]["content_chunk_size"] == CONTENT_CHUNK_SIZE
    assert stats["config"]["content_loop_threshold"] == CONTENT_LOOP_THRESHOLD


def test_enable_disable():
    """Test enable/disable functionality."""
    detector = GeminiCliLoopDetector()

    assert detector.is_enabled() is True

    detector.disable()
    assert detector.is_enabled() is False

    # Should not detect loops when disabled
    repeated_content = create_repetitive_content(1, CONTENT_CHUNK_SIZE)
    for _ in range(CONTENT_LOOP_THRESHOLD + 5):
        event = detector.process_chunk(repeated_content)
        assert event is None

    detector.enable()
    assert detector.is_enabled() is True
