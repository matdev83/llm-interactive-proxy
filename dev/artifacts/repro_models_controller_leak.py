"""Reproduction script for resource leak in models_controller.py

This script demonstrates the backend instance leak in the opencode-zen
credential check. A backend instance is created but never closed,
causing HTTP client resources to leak.
"""

import asyncio
import sys
from pathlib import Path


async def simulate_backend_leak():
    """Simulate the backend resource leak from models_controller.py.

    The issue is in the credential check for opencode-zen backend.
    A backend instance is created just to verify credential path existence,
    but it's never closed, leaking HTTP client connections.
    """
    print("=" * 70)
    print("Backend Instance Leak Demonstration")
    print("=" * 70)

    # Import after sys.path setup
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from src.core.config.app_config import (
        AppConfig,
        BackendSettings,
        LoggingConfig,
        LogLevel,
    )
    from src.core.di.services import get_service_collection, register_core_services
    from src.core.interfaces.backend_factory_interface import IBackendFactory

    # Create a minimal config
    config = AppConfig(
        host="localhost",
        port=8000,
        backends=BackendSettings(default_backend="opencode-zen"),
        logging=LoggingConfig(level=LogLevel.WARNING),
    )

    # Bootstrap DI with config
    services = get_service_collection()
    register_core_services(services, config)
    provider = services.build_service_provider()

    # Get backend factory from DI
    backend_factory = provider.get_required_service(IBackendFactory)  # type: ignore[type-abstract]

    print("\n=== Simulating leak scenario ===")
    print("Creating backend instances just for credential path check...")
    print("In models_controller.py line 293:")
    print("  _ = backend_factory.create_backend(backend_type, config)")
    print("  # Backend instance created but never closed!")
    print()

    # Simulate the problematic code from models_controller.py:293
    leaked_backends = []

    for i in range(5):  # Simulate 5 requests to /models endpoint
        try:
            # This is the vulnerable pattern - create backend without cleanup
            backend = backend_factory.create_backend("opencode-zen", config)
            leaked_backends.append(backend)
            print(f"Created backend instance #{i+1}: {type(backend).__name__}")

            # In the actual code, the backend is just checked for is_functional
            # and then discarded without closing

        except Exception as e:
            print(f"Failed to create backend: {e}")

    print(f"\nTotal backend instances created and leaked: {len(leaked_backends)}")

    # Try to show what resources might be leaked
    for i, backend in enumerate(leaked_backends):
        if hasattr(backend, "http_client"):
            print(f"  Backend #{i+1} has HTTP client: {backend.http_client}")

    print("\n=== Impact ===")
    print("Each backend instance has:")
    print("  - HTTP client (aiohttp/httpx) with connection pool")
    print("  - SSL context resources")
    print("  - Event loop references")
    print()
    print("With repeated /models requests:")
    print("  - Attackers can spam the /models endpoint")
    print("  - Each request creates a new backend instance for credential check")
    print("  - HTTP connections accumulate without being closed")
    print("  - Eventually causes 'Too many open files' or connection pool exhaustion")
    print()
    print("Denial of Service via resource exhaustion!")

    print("\n=== Correct cleanup pattern ===")
    print("Create backend with try/finally or use context manager:")
    print()
    print("  backend = backend_factory.create_backend(backend_type, config)")
    print("  try:")
    print("      # Use backend for credential check")
    print("      is_functional = getattr(backend, 'is_functional', lambda: False)()")
    print("  finally:")
    print("      # Properly close backend resources")
    print("      if hasattr(backend, 'close'):")
    print("          await backend.close()")
    print("      elif hasattr(backend, 'aclose'):")
    print("          await backend.aclose()")
    print()

    # Cleanup for demo purposes
    print("=== Cleaning up demo ===")
    for i, backend in enumerate(leaked_backends):
        if hasattr(backend, "close"):
            try:
                backend.close()
                print(f"Closed backend #{i+1}")
            except:
                pass
        elif hasattr(backend, "aclose"):
            try:
                await backend.aclose()
                print(f"Closed (async) backend #{i+1}")
            except:
                pass

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(simulate_backend_leak())
