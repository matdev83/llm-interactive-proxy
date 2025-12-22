"""
Repro script to confirm HTTP client leak in AntigravityOAuthConnector.

This script creates multiple connector instances and verifies that HTTP clients
are not properly closed, leading to resource leaks.
"""

import asyncio
import gc
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.config.app_config import AppConfig
from dev.artifacts.di_helper import get_translation_service


async def test_antigravity_client_leak():
    """Test that AntigravityOAuthConnector leaks HTTP clients."""
    print("Testing AntigravityOAuthConnector HTTP client leak...")

    # Create minimal config
    from src.core.config.models import BackendSettings

    app_config = AppConfig(backends=BackendSettings(default_backend=""))

    # Create a shared client (as would be done in normal operation)
    shared_client = httpx.AsyncClient()
    translation_service = get_translation_service()

    connectors = []
    clients_created = []

    try:
        # Create multiple connector instances
        for i in range(5):
            print(f"\nCreating connector instance {i+1}...")
            connector = AntigravityOAuthConnector(
                client=shared_client,
                config=app_config,
                translation_service=translation_service,
            )

            # Initialize (this creates a new client and assigns to self.client)
            try:
                await connector.initialize()
            except Exception as e:
                print(f"  Initialization failed (expected): {e}")

            # Check if connector has its own client
            if hasattr(connector, "client") and connector.client is not None:
                print(f"  Connector has client: {connector.client}")
                print(f"  Client is_closed: {connector.client.is_closed}")
                clients_created.append(connector.client)

            connectors.append(connector)

        print(f"\nCreated {len(connectors)} connectors")
        print(f"Created {len(clients_created)} HTTP clients")

        # Check if clients are closed
        closed_count = sum(1 for c in clients_created if c.is_closed)
        print(f"Closed clients: {closed_count}/{len(clients_created)}")

        if closed_count < len(clients_created):
            print("\n[LEAK CONFIRMED] HTTP clients are not closed!")
            print(f"   {len(clients_created) - closed_count} clients remain open")
        else:
            print("\n✓ All clients are closed")

        # Try to manually close clients
        print("\nAttempting manual cleanup...")
        for connector in connectors:
            if hasattr(connector, "client") and connector.client is not None:
                if not connector.client.is_closed:
                    try:
                        await connector.client.aclose()
                        print("  Closed client manually")
                    except Exception as e:
                        print(f"  Error closing client: {e}")

        # Force garbage collection
        del connectors
        gc.collect()

        # Check again
        remaining_open = sum(1 for c in clients_created if not c.is_closed)
        if remaining_open > 0:
            print(f"\n[WARNING] After cleanup: {remaining_open} clients still open")
        else:
            print("\n✓ All clients closed after manual cleanup")

    finally:
        # Cleanup shared client
        if not shared_client.is_closed:
            await shared_client.aclose()


if __name__ == "__main__":
    asyncio.run(test_antigravity_client_leak())
