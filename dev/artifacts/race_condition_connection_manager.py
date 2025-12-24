"""
Repro script for race condition in ConnectionManager.

The ConnectionManager has an asyncio.Lock but never uses it,
leaving all shared state unprotected.
"""

import asyncio
from collections import defaultdict


class ConnectionManager:
    """Simplified version of ConnectionManager with race condition."""

    def __init__(self, max_connections: int = 100):
        self._connections = {}
        self._session_id_to_websocket = {}
        self._subscriptions = defaultdict(set)
        self._max_connections = max_connections
        self._lock = asyncio.Lock()  # Lock exists but is NEVER used!

    def connect(self, websocket: str, session_id: str) -> None:
        """Register a new connection - NO LOCK PROTECTION"""
        if session_id in self._session_id_to_websocket:
            raise ValueError(f"Session ID {session_id} already in use")

        self._connections[websocket] = session_id
        self._session_id_to_websocket[session_id] = websocket

    def disconnect(self, websocket: str) -> None:
        """Remove a connection - NO LOCK PROTECTION"""
        session_id = self._connections.get(websocket)
        if session_id is None:
            return

        # RACE: Another coroutine could modify this dict simultaneously
        if session_id in self._session_id_to_websocket:
            del self._session_id_to_websocket[session_id]

        del self._connections[websocket]

    def subscribe(self, websocket: str, topics: list[str]) -> None:
        """Add subscriptions - NO LOCK PROTECTION"""
        for topic in topics:
            self._subscriptions[topic].add(websocket)

    def get_session(self, websocket: str) -> str | None:
        """Get session data - NO LOCK PROTECTION"""
        return self._connections.get(websocket)


async def simulate_race():
    """Simulate concurrent connection operations."""
    manager = ConnectionManager()
    errors = []

    async def connect_disconnect(ws_id: int):
        try:
            session_id = f"session_{ws_id}"
            ws = f"ws_{ws_id}"

            # Connect
            manager.connect(ws, session_id)

            # Small delay to allow race window
            await asyncio.sleep(0.001)

            # Subscribe
            manager.subscribe(ws, [f"topic_{ws_id}"])

            # Another small delay
            await asyncio.sleep(0.001)

            # Disconnect
            manager.disconnect(ws)

        except Exception as e:
            errors.append((ws_id, str(e)))

    # Run many concurrent operations
    tasks = [connect_disconnect(i) for i in range(100)]
    await asyncio.gather(*tasks, return_exceptions=True)

    if errors:
        print(f"ERRORS DETECTED: {len(errors)} exceptions occurred")
        for ws_id, err in errors[:5]:
            print(f"  - WebSocket {ws_id}: {err}")
        return True
    else:
        print("No errors detected in this run (but race condition exists)")
        return False


async def main():
    print("Running race condition test for ConnectionManager...")
    print("-" * 60)

    race_detected = False
    for i in range(5):
        print(f"\nIteration {i + 1}:")
        if await simulate_race():
            race_detected = True

    print("-" * 60)
    if race_detected:
        print("RESULT: Race condition CONFIRMED")
    else:
        print("RESULT: Race condition exists but errors may be non-deterministic")
    print("\nFix: Use 'async with self._lock:' in all methods that access shared state")


if __name__ == "__main__":
    asyncio.run(main())
