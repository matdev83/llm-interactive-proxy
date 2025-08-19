"""
Test-specific initialization stages.

This module provides stages that are specifically designed for testing,
replacing production services with mocks and test doubles.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection

from .base import InitializationStage

logger = logging.getLogger(__name__)


class MockBackendStage(InitializationStage):
    """
    Test stage that provides mock backend services.

    This stage replaces real backend services with mocks that return
    predictable responses for testing.
    """

    @property
    def name(self) -> str:
        return "backends"

    def get_dependencies(self) -> list[str]:
        return ["infrastructure"]

    def get_description(self) -> str:
        return "Register mock backend services for testing"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register mock backend services."""
        logger.info("Initializing mock backend services...")

        # Register mock backend service
        self._register_mock_backend_service(services)

        # Register mock backend factory
        self._register_mock_backend_factory(services)

        logger.info("Mock backend services initialized successfully")

    def _register_mock_backend_service(self, services: ServiceCollection) -> None:
        """Register a comprehensive mock backend service."""
        try:
            from src.core.domain.responses import (
                ResponseEnvelope,
                StreamingResponseEnvelope,
            )
            from src.core.interfaces.backend_service_interface import IBackendService

            # Create mock backend service
            mock_backend_service = MagicMock(spec=IBackendService)

            # Mock chat completion method
            async def mock_chat_completions(
                *args: Any, **kwargs: Any
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                """Mock chat completions that returns a standard response."""
                request = kwargs.get("request_data") or (args[0] if args else None)

                response_data = {
                    "id": "mock-response-1",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": (
                        getattr(request, "model", "mock-model")
                        if request
                        else "mock-model"
                    ),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Mock response from test backend",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 15,
                        "total_tokens": 25,
                    },
                }

                # Handle streaming requests
                if request and getattr(request, "stream", False):

                    async def mock_stream() -> AsyncGenerator[bytes, None]:
                        import asyncio
                        import json

                        # Yield streaming chunks
                        for i, word in enumerate(["Mock", "streaming", "response"]):
                            chunk = {
                                "id": f"mock-chunk-{i}",
                                "object": "chat.completion.chunk",
                                "created": 1234567890,
                                "model": response_data["model"],
                                "choices": [
                                    {"index": 0, "delta": {"content": f"{word} "}}
                                ],
                            }
                            yield f"data: {json.dumps(chunk)}\n\n".encode()
                            await asyncio.sleep(0.01)  # Small delay for realism

                        # Final chunk
                        yield b"data: [DONE]\n\n"

                    return StreamingResponseEnvelope(
                        content=mock_stream(),
                        media_type="text/event-stream",
                        headers={"content-type": "text/event-stream"},
                    )

                return ResponseEnvelope(
                    content=response_data,
                    headers={"content-type": "application/json"},
                    status_code=200,
                )

            # Configure mock methods
            mock_backend_service.process_request = AsyncMock(
                side_effect=mock_chat_completions
            )
            mock_backend_service.call_completion = AsyncMock(
                side_effect=mock_chat_completions
            )
            mock_backend_service.chat_completions = AsyncMock(
                side_effect=mock_chat_completions
            )
            mock_backend_service.get_available_models = AsyncMock(
                return_value=[
                    "mock-model-1",
                    "mock-model-2",
                    "mock-gpt-4",
                    "mock-claude-3",
                ]
            )
            mock_backend_service.validate_backend = AsyncMock(return_value=(True, None))
            mock_backend_service.validate_backend_and_model = AsyncMock(
                return_value=(True, None)
            )
            mock_backend_service.get_backend_status = AsyncMock(
                return_value={"status": "healthy"}
            )

            # Add _backends attribute for caching
            mock_backend_service._backends = {}

            # Add _get_or_create_backend method that respects test-specific mocks
            async def mock_get_or_create_backend(backend_type: str):
                from src.connectors.base import LLMBackend

                # First check if a test has injected a specific backend implementation
                # This allows tests to override specific backends while using global mocks for others
                if (
                    hasattr(mock_backend_service, "_backends")
                    and backend_type in mock_backend_service._backends
                ):
                    # Test has provided a specific backend - use it
                    return mock_backend_service._backends[backend_type]

                # Check if backend was already created and cached
                if not hasattr(mock_backend_service, "_backend_cache"):
                    mock_backend_service._backend_cache = {}

                if backend_type in mock_backend_service._backend_cache:
                    return mock_backend_service._backend_cache[backend_type]

                # Create new mock backend with the global mock behavior
                mock_backend = MagicMock(spec=LLMBackend)
                mock_backend.chat_completions = AsyncMock(
                    side_effect=mock_chat_completions
                )
                mock_backend.validate = AsyncMock(return_value=(True, None))
                mock_backend.get_available_models = AsyncMock(
                    return_value=["mock-model"]
                )
                mock_backend.available_models = ["mock-model"]

                # Cache in our internal cache (not _backends which tests use)
                mock_backend_service._backend_cache[backend_type] = mock_backend
                return mock_backend

            mock_backend_service._get_or_create_backend = AsyncMock(
                side_effect=mock_get_or_create_backend
            )

            # Register the mock service
            services.add_instance(IBackendService, mock_backend_service)

            logger.debug("Registered mock backend service with full method coverage")
        except ImportError as e:
            logger.warning(f"Could not register mock backend service: {e}")

    def _register_mock_backend_factory(self, services: ServiceCollection) -> None:
        """Register a mock backend factory."""
        try:
            from src.connectors.base import LLMBackend
            from src.core.services.backend_factory import BackendFactory

            # Create mock backend factory
            mock_factory = MagicMock(spec=BackendFactory)

            # Create mock backend instance
            mock_backend = MagicMock(spec=LLMBackend)
            mock_backend.chat_completions = AsyncMock()
            mock_backend.validate = AsyncMock(return_value=(True, None))
            mock_backend.get_available_models = AsyncMock(return_value=["mock-model"])
            mock_backend.available_models = ["mock-model"]

            # Configure factory methods
            mock_factory.create_backend = MagicMock(return_value=mock_backend)
            mock_factory.ensure_backend = AsyncMock(return_value=mock_backend)
            mock_factory.initialize_backend = AsyncMock()

            # Register the mock factory
            services.add_instance(BackendFactory, mock_factory)

            logger.debug("Registered mock backend factory")
        except ImportError as e:
            logger.warning(f"Could not register mock backend factory: {e}")


class MinimalTestStage(InitializationStage):
    """
    Minimal test stage that provides only essential services.

    This stage is useful for unit tests that only need basic functionality
    without the overhead of full application initialization.
    """

    @property
    def name(self) -> str:
        return "minimal_test"

    def get_dependencies(self) -> list[str]:
        return ["core_services"]

    def get_description(self) -> str:
        return "Register minimal services for lightweight testing"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register minimal test services."""
        logger.info("Initializing minimal test services...")

        # Register mock command service
        self._register_mock_command_service(services)

        # Register mock request processor
        self._register_mock_request_processor(services)

        logger.info("Minimal test services initialized successfully")

    def _register_mock_command_service(self, services: ServiceCollection) -> None:
        """Register a simple mock command service."""
        try:
            from src.core.interfaces.command_service_interface import ICommandService

            mock_command_service = MagicMock(spec=ICommandService)
            mock_command_service.process_command = AsyncMock(return_value=None)
            mock_command_service.is_command = MagicMock(return_value=False)

            services.add_instance(ICommandService, mock_command_service)

            logger.debug("Registered mock command service")
        except ImportError as e:
            logger.warning(f"Could not register mock command service: {e}")

    def _register_mock_request_processor(self, services: ServiceCollection) -> None:
        """Register a simple mock request processor."""
        try:
            from src.core.domain.responses import ResponseEnvelope
            from src.core.interfaces.request_processor_interface import (
                IRequestProcessor,
            )

            mock_request_processor = MagicMock(spec=IRequestProcessor)

            async def mock_process(*args: Any, **kwargs: Any) -> ResponseEnvelope:
                return ResponseEnvelope(
                    content={"message": "Mock response"},
                    headers={"content-type": "application/json"},
                    status_code=200,
                )

            mock_request_processor.process_request = AsyncMock(side_effect=mock_process)

            services.add_instance(IRequestProcessor, mock_request_processor)

            logger.debug("Registered mock request processor")
        except ImportError as e:
            logger.warning(f"Could not register mock request processor: {e}")


class CustomTestStage(InitializationStage):
    """
    Customizable test stage that allows injection of specific services.

    This stage is useful for tests that need to inject specific mock
    implementations or test doubles.
    """

    def __init__(
        self,
        name: str,
        services_to_register: dict,
        dependencies: list[str] | None = None,
    ):
        """
        Initialize custom test stage.

        Args:
            name: Name for this stage
            services_to_register: Dict mapping service types to instances
            dependencies: List of stage dependencies
        """
        self._stage_name = name
        self._services_to_register = services_to_register
        self._dependencies = dependencies or []

    @property
    def name(self) -> str:
        return self._stage_name

    def get_dependencies(self) -> list[str]:
        return self._dependencies

    def get_description(self) -> str:
        return f"Custom test stage: {self._stage_name}"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register custom services."""
        logger.info(f"Initializing custom test stage: {self._stage_name}")

        for service_type, instance in self._services_to_register.items():
            services.add_instance(service_type, instance)
            logger.debug(f"Registered custom service: {service_type.__name__}")

        logger.info(f"Custom test stage '{self._stage_name}' initialized successfully")
