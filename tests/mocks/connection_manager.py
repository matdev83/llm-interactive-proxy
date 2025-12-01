"""Mock connection manager for testing."""

from datetime import datetime

from src.codebuff.schemas import SessionState


class MockConnectionManager:
    """Mock connection manager for testing."""

    def __init__(self):
        self._sessions = {}

    def connect(self, websocket, session_id: str):
        """Register a mock connection."""
        session = SessionState(
            session_id=session_id,
            created_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        self._sessions[websocket] = session

    def disconnect(self, websocket):
        """Remove a mock connection."""
        if websocket in self._sessions:
            del self._sessions[websocket]

    def get_session(self, websocket):
        """Get mock session."""
        return self._sessions.get(websocket)

    def update_last_seen(self, websocket):
        """Update mock last seen."""
        if websocket in self._sessions:
            self._sessions[websocket].last_seen = datetime.utcnow()

    def subscribe(self, websocket, topics: list[str]):
        """Add mock subscriptions."""
        if websocket in self._sessions:
            self._sessions[websocket].subscriptions.update(topics)

    def unsubscribe(self, websocket, topics: list[str]):
        """Remove mock subscriptions."""
        if websocket in self._sessions:
            for topic in topics:
                self._sessions[websocket].subscriptions.discard(topic)

    def get_subscribers(self, topic: str):
        """Get mock subscribers."""
        return []

    async def cleanup_stale_connections(self):
        """Mock cleanup."""
        pass

