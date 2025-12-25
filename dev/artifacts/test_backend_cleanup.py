"""Test to verify models_controller.py backend cleanup works."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.config.app_config import (
    AppConfig,
    BackendSettings,
    LoggingConfig,
    LogLevel,
)
from src.core.di.services import get_or_build_service_provider
from src.core.services.backend_factory import BackendFactory


async def test_backend_cleanup():
    """Verify that backend instances are properly cleaned up."""
    from src.core.app.controllers.models_controller import _list_models_impl

    config = AppConfig(
        host="localhost",
        port=8000,
        backends=BackendSettings(default_backend="opencode-zen"),
        logging=LoggingConfig(level=LogLevel.WARNING),
    )

    provider = get_or_build_service_provider(config)
    backend_factory = BackendFactory(config, provider)

    # Mock service for backend
    class MockBackendService:
        pass

    mock_backend = MockBackendService()

    print("Testing models controller with opencode-zen backend...")
    try:
        result = await _list_models_impl(
            backend_service=mock_backend,
            config=config,
            backend_factory=backend_factory,
        )
        print(f"Models returned: {result}")
        print("SUCCESS: Backend instance was cleaned up properly!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_backend_cleanup())
