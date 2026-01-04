import asyncio
import threading
import time


def test_anthropic_oauth_pending_reload_race():
    """Test race condition in _pending_reload_task in anthropic_oauth.py

    This simulates the actual scenario where watchdog calls _schedule_credentials_reload
    from a background thread, potentially concurrently.
    """

    # Need a real event loop to test with run_coroutine_threadsafe
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start event loop in background thread
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()

    time.sleep(0.1)  # Let loop start

    # Create a simple mock class with race condition
    class MockConnector:
        def __init__(self):
            self._pending_reload_task = None
            self.reload_count = 0
            self._event_loop = loop

        def _schedule_credentials_reload_race(self):
            """Original implementation with race condition"""
            pending = self._pending_reload_task
            if pending is not None and not pending.done():
                return  # Already have a reload pending

            async def reload_task():
                await asyncio.sleep(0.05)
                self.reload_count += 1

            # Simulate check-then-act race window
            time.sleep(0.001)

            try:
                future = asyncio.run_coroutine_threadsafe(
                    reload_task(), self._event_loop
                )
                self._pending_reload_task = future
            except RuntimeError:
                pass

    # Test race condition
    print("Testing race condition in _pending_reload_task (multi-threaded)...")
    connector_race = MockConnector()

    # Simulate multiple file watcher events from different threads
    threads = []
    for i in range(10):
        t = threading.Thread(target=connector_race._schedule_credentials_reload_race)
        threads.append(t)
        t.start()
        time.sleep(0.0001)  # Small delay to increase overlap

    for t in threads:
        t.join()

    time.sleep(0.1)  # Let async tasks complete

    print(f"  Race condition version: reload_count={connector_race.reload_count}")
    print(f"  Expected: 1, Actual: {connector_race.reload_count}")
    if connector_race.reload_count != 1:
        print("  RACE CONDITION DETECTED: Multiple reloads occurred!")
        loop.call_soon_threadsafe(loop.stop)
        return True
    print("  No race detected in this run")

    loop.call_soon_threadsafe(loop.stop)
    return False


if __name__ == "__main__":
    detected = False
    for i in range(10):
        print(f"\n--- Run {i+1}/10 ---")
        if test_anthropic_oauth_pending_reload_race():
            detected = True
            break

    if detected:
        print("\nRACE CONDITION CONFIRMED!")
        exit(1)
    else:
        print("\nNo race detected in multiple runs")
        exit(0)
