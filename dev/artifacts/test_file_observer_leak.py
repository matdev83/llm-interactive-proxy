"""
Simple reproduction script for file observer resource leak in QwenOAuthConnector.

This script demonstrates that shutdown() does not stop watchdog Observer thread,
causing a resource leak when backends are restarted.

Run from project root:
  ./.venv/Scripts/python.exe dev/artifacts/test_file_observer_leak.py
"""
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, '.')


async def main():
    print("="*70)
    print("Testing for file observer resource leak in QwenOAuthConnector")
    print("="*70 + "\n")

    # Import after setting path
    import httpx
    from src.connectors.qwen_oauth import QwenOAuthConnector
    from src.core.config.app_config import AppConfig

    # Track thread count before
    initial_thread_count = threading.active_count()
    print(f"Initial thread count: {initial_thread_count}")

    # Create connector
    client = httpx.AsyncClient()
    config = AppConfig()
    connector = QwenOAuthConnector(client, config)

    try:
        # Set test credentials path
        script_dir = Path(__file__).parent
        connector._credentials_path = script_dir / "test_creds.json"

        # Create test credentials file
        test_creds = {
            "access_token": "test_token",
            "refresh_token": "test_refresh",
            "expiry_date": int((time.time() + 3600) * 1000)
        }
        with open(connector._credentials_path, "w") as f:
            json.dump(test_creds, f)

        # Start file watching
        connector._start_file_watching()

        # Check thread count after starting file watcher
        after_start_thread_count = threading.active_count()
        print(f"Thread count after starting file watcher: {after_start_thread_count}")

        # Verify file observer was created
        assert connector._file_observer is not None, "File observer should be created"
        print(f"File observer created: {connector._file_observer}")
        print(f"File observer is_alive: {connector._file_observer.is_alive()}")

        # Now call shutdown() - this is bug!
        print("\nCalling shutdown()...")
        await connector.shutdown()

        # Check thread count after shutdown
        after_shutdown_thread_count = threading.active_count()
        print(f"Thread count after shutdown: {after_shutdown_thread_count}")

        # Verify bug
        if connector._file_observer is not None:
            if connector._file_observer.is_alive():
                print("\n" + "!"*70)
                print("BUG CONFIRMED: File observer thread is still running after shutdown()!")
                print(f"  - Observer: {connector._file_observer}")
                print(f"  - Thread count increased by: {after_shutdown_thread_count - initial_thread_count}")
                print("  - This means shutdown() is missing _stop_file_watching() call")
                print("!"*70)
            else:
                print("File observer stopped (but still not cleaned up)")
        else:
            print("\nNo bug found: File observer was properly cleaned up")

    finally:
        # Cleanup
        await client.aclose()

        # Clean up test file
        test_creds_path = script_dir / "test_creds.json"
        if test_creds_path.exists():
            test_creds_path.unlink()

        # Manually stop observer if still running (to clean up our test)
        if hasattr(connector, "_file_observer") and connector._file_observer:
            try:
                connector._file_observer.stop()
                connector._file_observer.join(timeout=5.0)
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
