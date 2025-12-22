"""Repro script to test ConnectionManager memory leak.

This script tests if ConnectionManager connections and subscriptions
accumulate without bounds when connections aren't properly cleaned up.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.codebuff.connection_manager import ConnectionManager


async def main() -> None:
    """Test ConnectionManager connection accumulation."""
    manager = ConnectionManager(heartbeat_timeout_seconds=60)

    print("Testing ConnectionManager connection accumulation...")
    print("=" * 60)

    # Simulate many connections without cleanup
    num_connections = 10000
    print(f"Creating {num_connections} mock connections...")

    mock_websockets = []
    for i in range(num_connections):
        mock_ws = MagicMock()
        mock_ws.close = MagicMock()
        session_id = f"session-{i}"
        manager.connect(mock_ws, session_id)

        # Subscribe to some topics
        topics = [f"topic-{j}" for j in range(5)]
        manager.subscribe(mock_ws, topics)

        mock_websockets.append((mock_ws, session_id))

        if (i + 1) % 1000 == 0:
            print(f"  Created {i + 1} connections")
            print(f"    _connections size: {len(manager._connections)}")
            print(f"    _session_id_to_websocket size: {len(manager._session_id_to_websocket)}")
            print(f"    _subscriptions size: {len(manager._subscriptions)}")

    # Check final sizes
    print(f"\nFinal sizes:")
    print(f"  _connections: {len(manager._connections)}")
    print(f"  _session_id_to_websocket: {len(manager._session_id_to_websocket)}")
    print(f"  _subscriptions: {len(manager._subscriptions)}")

    # Count total subscriptions
    total_subscriptions = sum(len(subs) for subs in manager._subscriptions.values())
    print(f"  Total subscription entries: {total_subscriptions}")

    if len(manager._connections) == num_connections:
        print("\n[CONFIRMED] ConnectionManager connections accumulate without bounds")
        print("  Issue: No max limit on _connections, _session_id_to_websocket, or _subscriptions")
        print("  Risk: If cleanup_stale_connections() isn't called regularly or")
        print("        connections fail to disconnect properly, memory grows unbounded")
    else:
        print(f"\n[UNEXPECTED] Connection count doesn't match")

    # Test cleanup
    print("\nTesting cleanup_stale_connections()...")
    # Make connections stale by setting old last_seen
    for mock_ws, session_id in mock_websockets[:100]:
        session = manager.get_session(mock_ws)
        if session:
            session.last_seen = datetime.utcnow() - timedelta(seconds=120)

    await manager.cleanup_stale_connections()
    print(f"  After cleanup:")
    print(f"    _connections: {len(manager._connections)}")
    print(f"    _session_id_to_websocket: {len(manager._session_id_to_websocket)}")
    print(f"    _subscriptions: {len(manager._subscriptions)}")


if __name__ == "__main__":
    asyncio.run(main())
