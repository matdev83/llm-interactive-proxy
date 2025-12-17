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
    IStreamAssembler,
    IStreamNormalizer,
    IStreamProcessor,
    StreamProducer,
)
from src.core.ports.streaming.normalizer_base import BaseStreamNormalizer


class TestInterfacesExtraction:
    """Test that interfaces are correctly extracted to new modules."""

    def test_interfaces_importable_from_new_location(self):
        """Interfaces should be importable from src/core/ports/streaming/interfaces."""
        assert IStreamNormalizer is not None
        assert IStreamProcessor is not None
        assert IStreamAssembler is not None
        assert StreamProducer is not None

    def test_base_normalizer_importable_from_new_location(self):
        """BaseStreamNormalizer should be importable from normalizer_base."""
        assert BaseStreamNormalizer is not None
        assert issubclass(BaseStreamNormalizer, IStreamNormalizer)

    def test_interfaces_are_abc_or_protocol(self):
        """Interfaces should be ABCs or Protocols."""
        from abc import ABC

        assert issubclass(IStreamNormalizer, ABC)
        assert issubclass(IStreamProcessor, ABC)
        assert issubclass(IStreamAssembler, ABC)
        # StreamProducer is a Protocol, not ABC
        from typing import Protocol

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
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(
                    node.module.startswith(mod) for mod in forbidden_modules
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


class TestFacadeStillWorks:
    """Test that facade still re-exports interfaces correctly."""

    def test_facade_re_exports_interfaces(self):
        """Facade should re-export all interfaces."""
        from src.core.ports.streaming_contracts import (
            BaseStreamNormalizer,
            IStreamAssembler,
            IStreamNormalizer,
            IStreamProcessor,
            StreamProducer,
        )

        # Verify they're the same objects
        from src.core.ports.streaming.interfaces import (
            IStreamAssembler as DirectIStreamAssembler,
            IStreamNormalizer as DirectIStreamNormalizer,
            IStreamProcessor as DirectIStreamProcessor,
            StreamProducer as DirectStreamProducer,
        )
        from src.core.ports.streaming.normalizer_base import (
            BaseStreamNormalizer as DirectBaseStreamNormalizer,
        )

        assert IStreamNormalizer is DirectIStreamNormalizer
        assert IStreamProcessor is DirectIStreamProcessor
        assert IStreamAssembler is DirectIStreamAssembler
        assert StreamProducer is DirectStreamProducer
        assert BaseStreamNormalizer is DirectBaseStreamNormalizer

