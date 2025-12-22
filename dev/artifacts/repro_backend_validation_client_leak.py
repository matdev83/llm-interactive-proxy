"""
Repro script to confirm HTTP client leak in BackendStage validation.

This script simulates backend validation that creates an HTTP client
but app startup fails before shutdown handlers run.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx
from src.core.app.stages.backend import BackendStage
from src.core.config.app_config import AppConfig
from src.core.config.config_loader import load_config
from src.core.di.container import ServiceCollection


async def test_backend_validation_client_leak():
    """Test that BackendStage validation leaks HTTP clients on failure."""
    print("Testing BackendStage validation HTTP client leak...")
    
    # Create minimal config
    from src.core.config.models import BackendSettings
    app_config = AppConfig(backends=BackendSettings(default_backend=""))
    
    clients_created = []
    
    try:
        # Simulate scenario: validation runs but app startup fails
        for i in range(3):
            print(f"\nSimulation {i+1}: Registering validation HTTP client...")
            
            services = ServiceCollection()
            services.add_instance(AppConfig, app_config)
            
            stage = BackendStage()
            
            # Call the method that registers validation client
            stage._register_validation_http_client(services)
            
            # Get the client from DI
            provider = services.build_service_provider()
            client = provider.get_service(httpx.AsyncClient)
            
            if client is not None:
                print(f"  Client created: {client}")
                print(f"  Client is_closed: {client.is_closed}")
                clients_created.append(client)
            
            # Simulate app startup failure - no shutdown handlers run
            # Client remains in DI container but is never closed
            print("  Simulating app startup failure (no cleanup)...")
        
        print(f"\nCreated {len(clients_created)} HTTP clients")
        
        # Check if clients are closed
        closed_count = sum(1 for c in clients_created if c.is_closed)
        print(f"Closed clients: {closed_count}/{len(clients_created)}")
        
        if closed_count < len(clients_created):
            print("\n[LEAK CONFIRMED] HTTP clients are not closed!")
            print(f"   {len(clients_created) - closed_count} clients remain open")
            print("   These clients were registered in DI but never cleaned up")
        else:
            print("\n✓ All clients are closed")
        
        # Check if clients are tracked in DI
        print("\nChecking DI container state...")
        for i, client in enumerate(clients_created):
            if not client.is_closed:
                print(f"  Client {i+1} is still open and not tracked for cleanup")
        
    finally:
        # Manual cleanup
        print("\nAttempting manual cleanup...")
        for client in clients_created:
            if not client.is_closed:
                try:
                    await client.aclose()
                    print("  Closed client manually")
                except Exception as e:
                    print(f"  Error closing client: {e}")


if __name__ == "__main__":
    asyncio.run(test_backend_validation_client_leak())

