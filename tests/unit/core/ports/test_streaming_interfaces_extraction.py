"""
Tests verifying streaming interfaces extraction to ports-only modules.

These tests ensure that interfaces have been correctly extracted to focused
modules and that they maintain no vendor/transport dependencies.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Test imports from new module locations
from src.core.ports.streaming.interfaces import (
    IProviderStreamNormalizer,
    IStreamAssembler,
    IStreamProcessor,
    StreamProducer,
)
from src.core.ports.streaming.normalizer_base import BaseStreamNormalizer

# IStreamNormalizer is re-exported from streaming_contracts.py for backward compatibility
from src.core.ports.streaming_contracts import IStreamNormalizer


class TestInterfacesExtraction:
    """Test that interfaces are correctly extracted to new modules."""

    def test_interfaces_importable_from_new_location(self):
        """Interfaces should be importable from src/core/ports/streaming/interfaces."""
        # IStreamNormalizer is still available for backward compatibility
        assert IStreamNormalizer is not None
        assert IProviderStreamNormalizer is not None
        assert IStreamProcessor is not None
        assert IStreamAssembler is not None
        assert StreamProducer is not None

    def test_base_normalizer_importable_from_new_location(self):
        """BaseStreamNormalizer should be importable from normalizer_base."""
        assert BaseStreamNormalizer is not None
        # BaseStreamNormalizer implements IProviderStreamNormalizer
        assert issubclass(BaseStreamNormalizer, IProviderStreamNormalizer)
        # For backward compatibility, IStreamNormalizer should also work
        assert issubclass(BaseStreamNormalizer, IStreamNormalizer)

    def test_interfaces_are_abc_or_protocol(self):
        """Interfaces should be ABCs or Protocols."""
        from abc import ABC

        assert issubclass(IProviderStreamNormalizer, ABC)
        # IStreamNormalizer should be the same as IProviderStreamNormalizer (re-export)
        assert issubclass(IStreamNormalizer, ABC)
        assert issubclass(IStreamProcessor, ABC)
        assert issubclass(IStreamAssembler, ABC)
        # StreamProducer is a Protocol, not ABC

        assert isinstance(StreamProducer, type)  # Protocol is a type


class TestInterfacesNoVendorDependencies:
    """Test that interfaces module has no vendor/transport dependencies."""

    def test_interfaces_no_httpx_import(self):
        """Interfaces module should not import httpx."""
        interfaces_path = Path("src/core/ports/streaming/interfaces.py")
        assert interfaces_path.exists()

        with open(interfaces_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=str(interfaces_path))

        # Check all import statements
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "httpx":
                        pytest.fail(
                            f"Interfaces module should not import httpx. Found: {ast.unparse(node)}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module == "httpx":
                pytest.fail(
                    f"Interfaces module should not import from httpx. Found: {ast.unparse(node)}"
                )

    def test_interfaces_no_fastapi_import(self):
        """Interfaces module should not import FastAPI/Starlette."""
        interfaces_path = Path("src/core/ports/streaming/interfaces.py")
        assert interfaces_path.exists()

        with open(interfaces_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=str(interfaces_path))

        forbidden_modules = ["fastapi", "starlette", "uvicorn"]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_modules:
                        pytest.fail(
                            f"Interfaces module should not import {alias.name}. Found: {ast.unparse(node)}"
                        )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and any(node.module.startswith(mod) for mod in forbidden_modules)
            ):
                pytest.fail(
                    f"Interfaces module should not import from {node.module}. Found: {ast.unparse(node)}"
                )

    def test_normalizer_base_no_httpx_import(self):
        """Normalizer base module should not import httpx."""
        normalizer_base_path = Path("src/core/ports/streaming/normalizer_base.py")
        assert normalizer_base_path.exists()

        with open(normalizer_base_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=str(normalizer_base_path))

        # Check all import statements
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "httpx":
                        pytest.fail(
                            f"Normalizer base module should not import httpx. Found: {ast.unparse(node)}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module == "httpx":
                pytest.fail(
                    f"Normalizer base module should not import from httpx. Found: {ast.unparse(node)}"
                )


class TestNormalizerBaseFunctionality:
    """Test that BaseStreamNormalizer works correctly after extraction."""

    def test_base_normalizer_can_be_instantiated(self):
        """BaseStreamNormalizer should be instantiable with provider."""
        normalizer = BaseStreamNormalizer(provider="test")
        assert normalizer.provider == "test"

    def test_base_normalizer_has_metadata_schema(self):
        """BaseStreamNormalizer should have METADATA_SCHEMA."""
        assert hasattr(BaseStreamNormalizer, "METADATA_SCHEMA")
        assert isinstance(BaseStreamNormalizer.METADATA_SCHEMA, dict)

    def test_base_normalizer_validate_chunk(self):
        """BaseStreamNormalizer.validate_chunk should work."""
        from src.core.domain.streaming.streaming_content import StreamingContent

        normalizer = BaseStreamNormalizer(provider="test")
        chunk = StreamingContent(
            content="test",
            metadata={"provider": "test"},
            is_done=False,
            is_empty=False,
        )
        assert normalizer.validate_chunk(chunk) is True

    def test_base_normalizer_create_normalized_chunk(self):
        """BaseStreamNormalizer.create_normalized_chunk should work."""
        normalizer = BaseStreamNormalizer(provider="test")
        chunk = normalizer.create_normalized_chunk(
            content="test", metadata={}, is_done=False
        )
        assert chunk.content == "test"
        assert chunk.metadata["provider"] == "test"
        assert chunk.is_done is False


class TestProviderNormalizerInterface:
    """Test that IProviderStreamNormalizer exists and is distinct from services-layer interface."""

    def test_iprovider_stream_normalizer_exists(self):
        """IProviderStreamNormalizer should exist in interfaces.py."""
        assert IProviderStreamNormalizer is not None
        assert isinstance(IProviderStreamNormalizer, type)
        from abc import ABC

        assert issubclass(IProviderStreamNormalizer, ABC)

    def test_iprovider_stream_normalizer_distinct_from_services_layer(self):
        """IProviderStreamNormalizer should be distinct from services-layer IStreamNormalizer."""
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer as ServicesIStreamNormalizer,
        )

        # They should be different classes
        assert IProviderStreamNormalizer is not ServicesIStreamNormalizer

        # They should have different method signatures
        assert hasattr(IProviderStreamNormalizer, "normalize_stream")
        assert hasattr(ServicesIStreamNormalizer, "process_stream")
        assert not hasattr(IProviderStreamNormalizer, "process_stream")
        assert not hasattr(ServicesIStreamNormalizer, "normalize_stream")

    def test_base_normalizer_implements_iprovider_stream_normalizer(self):
        """BaseStreamNormalizer should implement IProviderStreamNormalizer."""
        assert issubclass(BaseStreamNormalizer, IProviderStreamNormalizer)


class TestFacadeStillWorks:
    """Test that facade still re-exports interfaces correctly."""

    def test_facade_re_exports_interfaces(self):
        """Facade should re-export all interfaces."""
        # Verify they're the same objects
        from src.core.ports.streaming.interfaces import (
            IProviderStreamNormalizer,
        )
        from src.core.ports.streaming.interfaces import (
            IStreamAssembler as DirectIStreamAssembler,
        )
        from src.core.ports.streaming.interfaces import (
            IStreamProcessor as DirectIStreamProcessor,
        )
        from src.core.ports.streaming.interfaces import (
            StreamProducer as DirectStreamProducer,
        )
        from src.core.ports.streaming.normalizer_base import (
            BaseStreamNormalizer as DirectBaseStreamNormalizer,
        )
        from src.core.ports.streaming_contracts import (
            BaseStreamNormalizer,
            IStreamAssembler,
            IStreamNormalizer,
            IStreamProcessor,
            StreamProducer,
        )

        # IStreamNormalizer is re-exported as alias of IProviderStreamNormalizer
        assert IStreamNormalizer is IProviderStreamNormalizer
        assert IStreamProcessor is DirectIStreamProcessor
        assert IStreamAssembler is DirectIStreamAssembler
        assert StreamProducer is DirectStreamProducer
        assert BaseStreamNormalizer is DirectBaseStreamNormalizer

    def test_facade_re_exports_iprovider_as_istream_normalizer(self):
        """Facade should re-export IProviderStreamNormalizer as IStreamNormalizer."""
        from src.core.ports.streaming_contracts import IStreamNormalizer

        # IStreamNormalizer from facade should be IProviderStreamNormalizer
        assert IStreamNormalizer is IProviderStreamNormalizer


class TestStreamingInterfaceTypes:
    """Test that streaming interfaces use strongly typed contracts instead of Any."""

    def test_stream_producer_uses_canonical_chat_request(self):
        """StreamProducer.stream_completion should require CanonicalChatRequest."""
        import inspect
        from typing import get_type_hints

        from src.core.domain.chat import CanonicalChatRequest

        # Get the signature of stream_completion from the protocol
        sig = inspect.signature(StreamProducer.stream_completion)
        params = list(sig.parameters.values())

        # Should have 'request' parameter with type CanonicalChatRequest
        request_param = next((p for p in params if p.name == "request"), None)
        assert (
            request_param is not None
        ), "stream_completion should have 'request' parameter"

        # Handle string annotations (from __future__ import annotations)
        annotation = request_param.annotation
        if isinstance(annotation, str):
            # Resolve the annotation
            hints = get_type_hints(StreamProducer.stream_completion)
            annotation = hints.get("request", annotation)

        assert (
            annotation == CanonicalChatRequest or annotation is CanonicalChatRequest
        ), f"request parameter should be CanonicalChatRequest, got {annotation}"

    def test_stream_producer_returns_object_iterator(self):
        """StreamProducer.stream_completion should return AsyncIterator[object]."""
        import inspect
        from collections.abc import AsyncIterator
        from typing import get_type_hints

        sig = inspect.signature(StreamProducer.stream_completion)
        return_annotation = sig.return_annotation

        # Handle string annotations (from __future__ import annotations)
        if isinstance(return_annotation, str):
            hints = get_type_hints(StreamProducer.stream_completion)
            return_annotation = hints.get("return", return_annotation)

        # Should return AsyncIterator[object]
        # Compare string representation or actual type
        expected_str = "AsyncIterator[object]"
        actual_str = str(return_annotation)
        assert (
            return_annotation == AsyncIterator[object] or expected_str in actual_str
        ), f"stream_completion should return AsyncIterator[object], got {return_annotation}"

    def test_provider_normalizer_accepts_object_iterator(self):
        """IProviderStreamNormalizer.normalize_stream should accept AsyncIterator[object]."""
        import inspect
        from collections.abc import AsyncIterator
        from typing import get_type_hints

        sig = inspect.signature(IProviderStreamNormalizer.normalize_stream)
        params = list(sig.parameters.values())

        # Should have 'stream' parameter with type AsyncIterator[object]
        stream_param = next((p for p in params if p.name == "stream"), None)
        assert (
            stream_param is not None
        ), "normalize_stream should have 'stream' parameter"

        # Handle string annotations (from __future__ import annotations)
        annotation = stream_param.annotation
        if isinstance(annotation, str):
            hints = get_type_hints(IProviderStreamNormalizer.normalize_stream)
            annotation = hints.get("stream", annotation)

        # Compare string representation or actual type
        expected_str = "AsyncIterator[object]"
        actual_str = str(annotation)
        assert (
            annotation == AsyncIterator[object] or expected_str in actual_str
        ), f"stream parameter should be AsyncIterator[object], got {annotation}"

    def test_connectors_implement_typed_protocol(self):
        """Connectors should implement StreamProducer with correct types."""
        import inspect

        from src.connectors.anthropic import AnthropicBackend
        from src.connectors.gemini import GeminiBackend
        from src.connectors.openai import OpenAIConnector

        connectors = [OpenAIConnector, AnthropicBackend, GeminiBackend]

        for connector_class in connectors:
            if not hasattr(connector_class, "stream_completion"):
                continue

            sig = inspect.signature(connector_class.stream_completion)
            params = list(sig.parameters.values())

            # Should have 'request' parameter
            request_param = next((p for p in params if p.name == "request"), None)
            assert (
                request_param is not None
            ), f"{connector_class.__name__} should have 'request' parameter"

            # Check return type
            return_annotation = sig.return_annotation
            # Should return AsyncGenerator[object, None] or AsyncIterator[object]
            assert "object" in str(
                return_annotation
            ), f"{connector_class.__name__}.stream_completion should return AsyncGenerator[object, None] or AsyncIterator[object], got {return_annotation}"

    def test_normalizers_implement_typed_interface(self):
        """Normalizers should implement IProviderStreamNormalizer with correct types."""
        import inspect

        from src.core.ports.anthropic_normalizer import AnthropicStreamNormalizer
        from src.core.ports.gemini_normalizer import GeminiStreamNormalizer
        from src.core.ports.openai_normalizer import OpenAIStreamNormalizer

        normalizers = [
            OpenAIStreamNormalizer,
            AnthropicStreamNormalizer,
            GeminiStreamNormalizer,
        ]

        for normalizer_class in normalizers:
            sig = inspect.signature(normalizer_class.normalize_stream)
            params = list(sig.parameters.values())

            # Should have 'stream' parameter
            stream_param = next((p for p in params if p.name == "stream"), None)
            assert (
                stream_param is not None
            ), f"{normalizer_class.__name__} should have 'stream' parameter"

            # Check that stream parameter uses object type
            assert "object" in str(
                stream_param.annotation
            ), f"{normalizer_class.__name__}.normalize_stream stream parameter should be AsyncIterator[object], got {stream_param.annotation}"
