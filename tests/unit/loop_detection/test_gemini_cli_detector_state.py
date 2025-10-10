"""State management tests for :mod:`src.loop_detection.gemini_cli_detector`."""

from src.loop_detection.gemini_cli_detector import GeminiCliLoopDetector


class TestGeminiCliLoopDetectorState:
    """Ensure internal state snapshots remain isolated from mutations."""

    def test_save_state_does_not_share_internal_lists(self) -> None:
        """Saving state should produce independent copies of tracked indices."""

        detector = GeminiCliLoopDetector(
            content_loop_threshold=5,
            content_chunk_size=3,
            max_history_length=100,
        )

        # Populate tracking structures with repeated content but stay below the
        # detection threshold so processing continues to update the same hashes.
        detector.process_chunk("abcabcabc")

        saved_state = detector._save_state()
        original_stats = {
            hash_hex: indices.copy()
            for hash_hex, indices in saved_state["content_stats"].items()
        }
        assert original_stats  # Sanity check: ensure we actually captured history.

        # Process more content that extends the previously observed hashes. If
        # the saved state retained references to the original lists it would be
        # mutated by these updates.
        detector.process_chunk("abcabcabc")

        assert saved_state["content_stats"] == original_stats

        detector._restore_state(saved_state)
        assert detector.content_stats == original_stats
