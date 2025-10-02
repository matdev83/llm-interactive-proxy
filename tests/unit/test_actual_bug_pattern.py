"""
Test that the actual pattern from the bug report is now detected.

This test uses the EXACT repetitive content from the user's bug report
to verify that our fixes (increased chunk_size + proper DI wiring) now catch it.
"""

from src.loop_detection.hybrid_detector import HybridLoopDetector


def test_actual_bug_pattern_is_now_detected():
    """Test that the exact pattern from the bug report is now detected with new config.

    The user observed this exact repetition 13 times without detection.
    With content_chunk_size increased from 50 to 100, this should now be caught.
    """
    # Exact pattern from the bug report
    repeated_block = """Examining the Test File

I'm now examining tests/unit/test_cli_di.py to understand how it uses the --disable-interactive-commands flag. I'm looking for any code that might generate a large number of commands, which would explain the "16 proxy command(s) detected" log message.

"""

    # The user observed 13 repetitions
    actual_looped_content = repeated_block * 13

    loop_detector = HybridLoopDetector()

    # Process the actual content
    detection_event = loop_detector.process_chunk(actual_looped_content)

    # This MUST be detected now
    assert (
        detection_event is not None
    ), f"Loop MUST be detected with new config! Pattern: {len(repeated_block)} chars, repeated 13 times, total: {len(actual_looped_content)} chars"

    assert detection_event.repetition_count >= 2, "Must detect multiple repetitions"

    print(f"[OK] SUCCESS! Detected {detection_event.repetition_count} repetitions")
    print(f"  Pattern length: {len(repeated_block)} chars")
    print(f"  Total content: {len(actual_looped_content)} chars")


def test_actual_bug_pattern_detected_by_long_pattern_path():
    """Ensure the hybrid detector catches long patterns when short path is strict."""
    # Exact pattern from the bug report
    repeated_block = """Examining the Test File

I'm now examining tests/unit/test_cli_di.py to understand how it uses the --disable-interactive-commands flag. I'm looking for any code that might generate a large number of commands, which would explain the "16 proxy command(s) detected" log message.

"""

    actual_looped_content = repeated_block * 13

    loop_detector = HybridLoopDetector(
        short_detector_config={"content_loop_threshold": 99, "content_chunk_size": 50}
    )

    detection_event = loop_detector.process_chunk(actual_looped_content)

    assert detection_event is not None, "Hybrid detector should catch long repetitions"
    assert (
        "Long pattern" in detection_event.pattern
    ), "Expected long-pattern path to trigger"


def test_pattern_characteristics():
    """Analyze the actual pattern to understand detection requirements."""
    repeated_block = """Examining the Test File

I'm now examining tests/unit/test_cli_di.py to understand how it uses the --disable-interactive-commands flag. I'm looking for any code that might generate a large number of commands, which would explain the "16 proxy command(s) detected" log message.

"""

    print("\nPattern Analysis:")
    print(f"  Pattern length: {len(repeated_block)} characters")
    print(f"  Lines in pattern: {repeated_block.count(chr(10))}")
    print(f"  First 100 chars: {repeated_block[:100]!r}")
    print("\nWith 13 repetitions:")
    print(f"  Total length: {len(repeated_block * 13)} characters")
    print("\nDetection requirements:")
    print(
        f"  - content_chunk_size should be <= {len(repeated_block)} to detect as repeating chunks"
    )
    print(
        f"  - With chunk_size=50: pattern is {len(repeated_block)/50:.1f}x larger than chunk"
    )
    print(
        f"  - With chunk_size=100: pattern is {len(repeated_block)/100:.1f}x larger than chunk"
    )
    print("  - chunk_size=100 is better aligned for detection")
