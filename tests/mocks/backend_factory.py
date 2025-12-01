"""Mock backend factory for testing."""

from typing import Any
from unittest.mock import AsyncMock

from src.core.config.app_config import AppConfig, BackendConfig


class MockBackend:
    """Mock LLM backend for testing."""

    def __init__(self):
        self.backend_type = "mock"
        self.chat_completions = AsyncMock()
        self.initialize = AsyncMock()
        self.last_request_headers: dict[str, Any] = {}
        self.chat_completions.side_effect = self.chat_completions_impl

    async def chat_completions_impl(self, *args, **kwargs):
        """Mock chat completions implementation."""
        identity = kwargs.get("identity")
        if identity and hasattr(identity, "get_resolved_headers"):
            try:
                self.last_request_headers = identity.get_resolved_headers(None)
            except Exception:
                self.last_request_headers = {}
        else:
            self.last_request_headers = {}
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Mock response",
                    }
                }
            ]
        }


class MockBackendFactory:
    """Mock backend factory for testing."""

    def __init__(self):
        self._config = AppConfig()
        self._backends = {}

    def create_backend(self, backend_type: str, config: AppConfig | None = None):
        """Create a mock backend."""
        backend = MockBackend()
        backend.backend_type = backend_type
        self._backends[backend_type] = backend
        return backend

    def get_backend(self, backend_type: str) -> MockBackend:
        """Retrieve a previously created backend for assertions."""
        return self._backends[backend_type]

    async def initialize_backend(self, backend, init_config: dict[str, Any]):
        """Initialize a mock backend."""
        await backend.initialize(**init_config)

    async def ensure_backend(
        self,
        backend_type: str,
        app_config: AppConfig,
        backend_config: BackendConfig | None = None,
    ):
        """Ensure a mock backend exists."""
        if backend_type not in self._backends:
            backend = self.create_backend(backend_type, app_config)
            await self.initialize_backend(backend, {})
            self._backends[backend_type] = backend
        return self._backends[backend_type]
