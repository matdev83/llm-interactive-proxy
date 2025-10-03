import pytest
from src.loop_detection.analyzer import PatternAnalyzer
from src.loop_detection.config import LoopDetectionConfig
from src.loop_detection.hasher import ContentHasher


@pytest.fixture
def mock_config() -> LoopDetectionConfig:
    return LoopDetectionConfig(
        content_chunk_size=3,
        content_loop_threshold=3,
        max_history_length=20,
    )


@pytest.fixture
def mock_hasher() -> ContentHasher:
    return ContentHasher()


@pytest.fixture
def analyzer(
    mock_config: LoopDetectionConfig, mock_hasher: ContentHasher
) -> PatternAnalyzer:
    return PatternAnalyzer(mock_config, mock_hasher)


def test_pattern_analyzer_init(analyzer: PatternAnalyzer) -> None:
    assert analyzer._stream_history == ""
    assert analyzer._content_stats == {}
    assert analyzer._last_chunk_index == 0
    assert analyzer._in_code_block is False


def test_pattern_analyzer_code_block_detection(analyzer: PatternAnalyzer) -> None:
    # Enter code block
    analyzer.analyze_chunk("```python", "```python")
    assert analyzer._in_code_block is True
    # History is reset, then '```python' is appended.
    # But if it's in a code block, it returns None before appending.
    # So, the history should be empty if a fence is encountered and it enters a code block.
    # This test case implies that the fence itself is part of the history, which is not correct when entering a code block.
    # The logic in analyzer.py:analyze_chunk should prevent appending to _stream_history if _in_code_block is True.
    # Let's re-verify the logic in PatternAnalyzer.analyze_chunk.
    # Ah, the `if self._in_code_block: return None` is *before* `self._stream_history += new_content`.
    # So if it enters a code block, new_content is *not* added to _stream_history.
    # And if it exits a code block, the fence characters *are* added.
    # So, the test's expectation for _stream_history after exiting the code block should be the fence itself.
    assert analyzer._stream_history == ""

    # Inside code block, no detection
    event = analyzer.analyze_chunk("some code", "some code")
    assert event is None
    assert analyzer._in_code_block is True
    assert analyzer._stream_history == ""  # Still empty as it's in code block

    # Exit code block
    analyzer.analyze_chunk("```", "```")
    assert analyzer._in_code_block is False
    assert analyzer._stream_history == "```"  # The fence itself is added to history

    # Enter code block mid-chunk
    analyzer.analyze_chunk("text```python", "text```python")
    assert analyzer._in_code_block is True
    assert analyzer._stream_history == ""  # History reset on fence


def test_pattern_analyzer_truncation(analyzer: PatternAnalyzer) -> None:
    # Max history is 20, chunk size 3, threshold 3
    analyzer.analyze_chunk("a" * 10, "a" * 10)  # 'aaaaaaaaaa'
    assert analyzer._stream_history == "a" * 10
    analyzer.analyze_chunk(
        "b" * 15, "a" * 10 + "b" * 15
    )  # 'aaaaaaaaaabbbbbbbbbbbbbbb' (25 chars)
    # Should truncate to last 20 chars: 'aaaaabbbbbbbbbbbbbbb'
    assert analyzer._stream_history == "aaaaabbbbbbbbbbbbbbb"
    assert len(analyzer._stream_history) == 20


def test_pattern_analyzer_loop_detection_basic(analyzer: PatternAnalyzer) -> None:
    # Config: chunk_size=3, loop_threshold=3
    # Pattern: "abc" repeated 3 times
    event = None
    event = analyzer.analyze_chunk("abc", "abc")  # 'abc'
    assert event is None
    event = analyzer.analyze_chunk("abc", "abcabc")  # 'abcabc'
    assert event is None
    event = analyzer.analyze_chunk("abc", "abcabcabc")  # 'abcabcabc'
    assert event is not None
    assert event.pattern == "abc"
    assert event.repetition_count == 3
    assert event.total_length == 9  # 3 * 3
    assert event.confidence == 1.0
    assert (
        event.buffer_content == "abcabcabc"
    )  # Full buffer content at time of detection


def test_pattern_analyzer_loop_detection_with_noise(analyzer: PatternAnalyzer) -> None:
    # Config: chunk_size=3, loop_threshold=3
    # Pattern: "abc" repeated 3 times with some noise
    event = None
    event = analyzer.analyze_chunk("abc", "abc")
    assert event is None
    event = analyzer.analyze_chunk("xyz", "abcxyz")  # Noise
    assert event is None
    event = analyzer.analyze_chunk("abc", "abcxyzabc")
    assert event is None
    event = analyzer.analyze_chunk("xyz", "abcxyzabcxyz")  # Noise
    assert event is None
    event = analyzer.analyze_chunk(
        "abc", "abcxyzabcxyzabc"
    )  # Should detect loop of "abc"
    assert event is not None
    assert event.pattern == "abc"
    assert event.repetition_count == 3
    assert event.confidence == 1.0


def test_pattern_analyzer_reset(analyzer: PatternAnalyzer) -> None:
    analyzer.analyze_chunk("some content", "some content")
    analyzer.analyze_chunk("```", "```")  # Enter code block and reset history
    assert analyzer._stream_history == ""
    assert analyzer._in_code_block is True

    analyzer.reset()
    assert analyzer._stream_history == ""
    assert analyzer._content_stats == {}
    assert analyzer._last_chunk_index == 0
    assert analyzer._in_code_block is False  # Reset code block state as well


def test_pattern_analyzer_no_loop_detection(analyzer: PatternAnalyzer) -> None:
    # Content that should not trigger a loop
    event = analyzer.analyze_chunk(
        "The quick brown fox jumps over the lazy dog.",
        "The quick brown fox jumps over the lazy dog.",
    )
    assert event is None
    event = analyzer.analyze_chunk(
        "This is a unique sentence.", "This is a unique sentence."
    )
    assert event is None
    event = analyzer.analyze_chunk(
        "Hello. World. Hello. Universe.", "Hello. World. Hello. Universe."
    )
    assert (
        event is None
    )  # "Hello." is repeated, but distance might be too large or not enough repetitions


def test_pattern_analyzer_min_repetition_and_length_config(
    mock_hasher: ContentHasher,
) -> None:
    # Test with different config for loop threshold
    config = LoopDetectionConfig(
        content_chunk_size=2,
        content_loop_threshold=2,  # Only 2 repetitions needed
        max_history_length=100,
    )
    analyzer = PatternAnalyzer(config, mock_hasher)

    event = analyzer.analyze_chunk("ab", "ab")
    assert event is None
    event = analyzer.analyze_chunk("ab", "abab")  # Should detect "ab"
    assert event is not None
    assert event.pattern == "ab"
    assert event.repetition_count == 2
