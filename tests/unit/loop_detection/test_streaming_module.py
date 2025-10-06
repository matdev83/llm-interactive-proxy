"""Unit tests for the streaming loop detection helpers."""

from __future__ import annotations

from unittest.mock import Mock

from src.loop_detection.event import LoopDetectionEvent
from src.loop_detection.streaming import (
    _detect_simple_repetition,
    analyze_complete_response_for_loops,
)


class TestDetectSimpleRepetition:
    def test_detects_common_error_token(self) -> None:
        """Ensure the fast-path token detection reports repetitions."""

        text = "prefix ERROR ERROR ERROR "

        pattern, count = _detect_simple_repetition(text)

        assert pattern == "ERROR"
        assert count == 3

    def test_detects_generic_repeating_pattern(self) -> None:
        """Detect a short repeated substring when the fast path does not trigger."""

        text = "intro abcabcabc tail"

        pattern, count = _detect_simple_repetition(text)

        assert pattern == "abc"
        assert count == 3

    def test_returns_none_when_no_repetition_detected(self) -> None:
        """Return a neutral result when the text has no obvious repetition."""

        pattern, count = _detect_simple_repetition("unique content without loops")

        assert pattern is None
        assert count == 0


class TestAnalyzeCompleteResponseForLoops:
    def test_returns_none_when_detector_missing(self) -> None:
        """No detector means no analysis is performed."""

        assert analyze_complete_response_for_loops("text", None) is None

    def test_returns_none_when_detector_disabled(self) -> None:
        """Disabled detectors should not reset or process the response."""

        detector = Mock(spec=["is_enabled", "reset", "process_chunk"])
        detector.is_enabled.return_value = False

        result = analyze_complete_response_for_loops("some response", detector)

        assert result is None
        detector.reset.assert_not_called()
        detector.process_chunk.assert_not_called()

    def test_resets_and_processes_response(self) -> None:
        """The helper should reset the detector and process the entire response."""

        detector = Mock(spec=["is_enabled", "reset", "process_chunk"])
        detector.is_enabled.return_value = True

        expected_event = LoopDetectionEvent(
            pattern="abc",
            repetition_count=3,
            total_length=12,
            confidence=0.7,
            buffer_content="abcabcabc",
            timestamp=123.0,
        )
        detector.process_chunk.return_value = expected_event

        result = analyze_complete_response_for_loops("abcabcabc", detector)

        assert result is expected_event
        detector.reset.assert_called_once_with()
        detector.process_chunk.assert_called_once_with("abcabcabc")

        detector.is_enabled.assert_called_once_with()
