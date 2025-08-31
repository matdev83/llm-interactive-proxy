from typing import Any

from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_factory import BackendFactory


class MockBackend(LLMBackend):
    def __init__(self) -> None:
        self.last_request_headers: dict[str, str] = {}
        self.identity: AppIdentityConfig | None = None

    async def chat_completions(
        self,
        request_data: Any,  # type: ignore
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,  # type: ignore
        **kwargs: Any,
    ) -> ResponseEnvelope:
        self.identity = identity  # type: ignore
        self.last_request_headers = self.get_headers()
        return ResponseEnvelope(content={}, status_code=200, headers={})

    async def initialize(self, **kwargs: Any) -> None:
        pass

    def get_headers(self) -> dict[str, str]:
        if not self.identity:
            return {}
        return {"HTTP-Referer": self.identity.url, "X-Title": self.identity.title}


import httpx
from src.core.services.backend_registry import BackendRegistry
from src.core.services.translation_service import TranslationService


class MockBackendFactory(BackendFactory):
    def __init__(self) -> None:
        super().__init__(
            httpx.AsyncClient(),
            BackendRegistry(),
            AppConfig(),
            TranslationService(),
        )
        self._backends: dict[str, MockBackend] = {}

    async def ensure_backend(
        self,
        backend_type: str,
        app_config: AppConfig,
        backend_config: BackendConfig | None = None,
    ) -> LLMBackend:
        if backend_type not in self._backends:
            self._backends[backend_type] = MockBackend()
        return self._backends[backend_type]

    def get_backend(self, backend_type: str) -> MockBackend:
        return self._backends[backend_type]
