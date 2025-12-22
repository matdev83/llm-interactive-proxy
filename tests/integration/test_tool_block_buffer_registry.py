from unittest.mock import patch

import src.core.transport.fastapi.response_adapters as response_adapters
from src.core.di.container import ServiceCollection
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.transport.fastapi.response_adapters import _get_content_converter


class TestToolBlockBufferRegistry:
    def setup_method(self):
        # Reset the singleton in response_adapters
        self.original_converter = response_adapters._content_converter
        response_adapters._content_converter = None

    def teardown_method(self):
        # Restore singleton
        response_adapters._content_converter = self.original_converter

    def test_get_content_converter_uses_di_registry(self):
        # Setup DI container
        services = ServiceCollection()
        services.add_singleton(StreamingContextRegistry, StreamingContextRegistry)

        provider = services.build_service_provider()

        # Get the registry instance from DI
        di_registry = provider.get_required_service(StreamingContextRegistry)

        # Mock get_service_provider to return our provider
        with patch("src.core.di.services.get_service_provider", return_value=provider):
            # Call the function under test
            converter = _get_content_converter()

            # Check if converter was created
            assert converter is not None

            # Check if tool_block_buffer exists
            assert converter._tool_block_buffer is not None

            # KEY CHECK: Check if tool_block_buffer uses the DI registry
            assert converter._tool_block_buffer._registry is di_registry
            assert converter._tool_block_buffer._registry is not None

            # Verify it's NOT the global registry (unless global happens to be the same, but here we control DI)
            # Note: We can't easily check against global registry without importing it,
            # but asserting identity with di_registry is sufficient proof it used DI.

    def test_get_content_converter_fallback_when_di_fails(self):
        # Setup empty provider (registry not registered)
        services = ServiceCollection()
        provider = services.build_service_provider()

        with patch("src.core.di.services.get_service_provider", return_value=provider):
            # Call the function under test
            converter = _get_content_converter()

            # Check if converter was created
            assert converter is not None

            # Check internal state is None (lazy init)
            assert converter._tool_block_buffer is None

            # Check if accessing property creates it with default
            buffer = converter._get_tool_block_buffer()
            assert buffer is not None
            # Default ToolBlockBuffer has _registry=None (uses global on demand)
            assert buffer._registry is None
