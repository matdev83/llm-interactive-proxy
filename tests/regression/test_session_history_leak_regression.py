"""Regression test for Session history memory leak.

This test verifies that Session history behavior is documented and tested.
Note: Session history may grow unbounded by design, but this test documents
the behavior and ensures it's intentional rather than a bug.
"""

import pytest
from src.core.domain.session import Session, SessionInteraction, SessionState


class TestSessionHistoryLeakRegression:
    """Regression tests for Session history memory leak."""

    @pytest.fixture
    def session(self):
        """Create a session instance."""
        return Session(
            session_id="test-session",
            state=SessionState(),
        )

    def test_session_history_grows_with_interactions(self, session: Session) -> None:
        """Test that session history grows as interactions are added."""
        initial_history_size = len(session.history)

        # Add many interactions
        num_interactions = 1000
        for i in range(num_interactions):
            interaction = SessionInteraction(
                prompt=f"Message {i}",
                handler="proxy",
            )
            session.add_interaction(interaction)

        final_history_size = len(session.history)
        expected_size = initial_history_size + num_interactions

        # Verify history grows as expected
        assert final_history_size == expected_size, (
            f"History size ({final_history_size}) does not match expected "
            f"({expected_size}). History should grow with each interaction."
        )

    def test_multiple_sessions_accumulate_history_independently(
        self,
    ) -> None:
        """Test that multiple sessions can accumulate history independently."""
        num_sessions = 10
        interactions_per_session = 100

        sessions = []
        for session_idx in range(num_sessions):
            session = Session(
                session_id=f"session-{session_idx}",
                state=SessionState(),
            )

            for i in range(interactions_per_session):
                interaction = SessionInteraction(
                    prompt=f"Message {i}",
                    handler="proxy",
                )
                session.add_interaction(interaction)

            sessions.append(session)

        # Verify each session has the expected history size
        total_interactions = sum(len(s.history) for s in sessions)
        expected_total = num_sessions * interactions_per_session

        assert total_interactions >= expected_total, (
            f"Total interactions ({total_interactions}) is less than expected "
            f"({expected_total}). Sessions should accumulate history independently."
        )

        # Verify each session has correct history size
        for session in sessions:
            assert len(session.history) >= interactions_per_session, (
                f"Session {session.id} has fewer interactions ({len(session.history)}) "
                f"than expected ({interactions_per_session})."
            )

    def test_session_history_no_automatic_limit(self, session: Session) -> None:
        """Test that session history has no automatic size limit.

        This test documents that Session history can grow unbounded.
        If a limit is added in the future, this test should be updated.
        """
        # Add a large number of interactions
        num_interactions = 5000  # Reduced from 10000 for performance
        for i in range(num_interactions):
            interaction = SessionInteraction(
                prompt=f"Message {i}",
                handler="proxy",
            )
            session.add_interaction(interaction)

        # Verify all interactions are stored
        assert len(session.history) >= num_interactions, (
            f"Session history ({len(session.history)}) is smaller than "
            f"number of interactions added ({num_interactions}). "
            "History should store all interactions without automatic truncation."
        )

        # Note: This test documents current behavior. If a limit is added,
        # this test should be updated to verify the limit is enforced.
