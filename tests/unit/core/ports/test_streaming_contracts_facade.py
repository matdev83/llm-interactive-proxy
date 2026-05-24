"""
Tests verifying streaming_contracts.py compatibility facade.

These tests ensure the facade re-exports all public symbols and maintains
backward compatibility after refactoring.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from src.core.ports.streaming_contracts import (
    BaseStreamNormalizer,
    IStreamAssembler,
    IStreamNormalizer,
    IStreamProcessor,
    SentinelManager,
    StopChunkWithUsage,
    StreamingContent,
    StreamingErrorMapper,
    UsageChunkLeakError,
    handle_streaming_error,
)


class TestFacadeReExports:
    """Test that facade re-exports all public symbols."""

    def test_streaming_content_exported(self):
        """StreamingContent should be importable from facade."""
        assert StreamingContent is not None
        assert isinstance(StreamingContent, type)

    def test_stop_chunk_with_usage_exported(self):
        """StopChunkWithUsage should be importable from facade."""
        assert StopChunkWithUsage is not None
        assert isinstance(StopChunkWithUsage, type)

    def test_usage_chunk_leak_error_exported(self):
        """UsageChunkLeakError should be importable from facade."""
        assert UsageChunkLeakError is not None
        assert isinstance(UsageChunkLeakError, type)

    def test_istream_normalizer_exported(self):
        """IStreamNormalizer should be importable from facade."""
        assert IStreamNormalizer is not None
        assert isinstance(IStreamNormalizer, type)

    def test_base_stream_normalizer_exported(self):
        """BaseStreamNormalizer should be importable from facade."""
        assert BaseStreamNormalizer is not None
        assert isinstance(BaseStreamNormalizer, type)

    def test_istream_processor_exported(self):
        """IStreamProcessor should be importable from facade."""
        assert IStreamProcessor is not None
        assert isinstance(IStreamProcessor, type)

    def test_istream_assembler_exported(self):
        """IStreamAssembler should be importable from facade."""
        assert IStreamAssembler is not None
        assert isinstance(IStreamAssembler, type)

    def test_sentinel_manager_exported(self):
        """SentinelManager should be importable from facade."""
        assert SentinelManager is not None
        assert isinstance(SentinelManager, type)

    def test_streaming_error_mapper_exported(self):
        """StreamingErrorMapper should be importable from facade."""
        assert StreamingErrorMapper is not None
        assert isinstance(StreamingErrorMapper, type)

    def test_handle_streaming_error_exported(self):
        """handle_streaming_error should be importable from facade."""
        assert handle_streaming_error is not None
        assert callable(handle_streaming_error)


class TestFacadeNoHttpxImport:
    """Test that facade has no httpx imports (boundary enforcement)."""

    def test_facade_no_httpx_import(self):
        """Facade should not import httpx."""
        facade_path = Path("src/core/ports/streaming_contracts.py")
        assert facade_path.exists()

        # Parse the file and check for httpx imports
        with open(facade_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=str(facade_path))

        # Check all import statements
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "httpx":
                        pytest.fail(
                            f"Facade should not import httpx directly. Found: {ast.unparse(node)}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module == "httpx":
                pytest.fail(
                    f"Facade should not import from httpx. Found: {ast.unparse(node)}"
                )


class TestFacadeLineCount:
    """Test that facade meets LOC requirement (< 600 lines)."""

    def test_facade_under_600_lines(self):
        """Facade should be under 600 lines (requirement 1.1)."""
        facade_path = Path("src/core/ports/streaming_contracts.py")
        assert facade_path.exists()

        with open(facade_path, encoding="utf-8") as f:
            lines = f.readlines()

        line_count = len(lines)
        assert (
            line_count < 600
        ), f"Facade has {line_count} lines, must be < 600 (requirement 1.1)"


class TestFacadeBackwardCompatibility:
    """Test that existing import patterns continue to work."""

    def test_all_symbols_importable_together(self):
        """All symbols should be importable in a single import statement."""
        # This simulates how many files import from streaming_contracts
        from src.core.ports.streaming_contracts import (
            BaseStreamNormalizer,
            IStreamAssembler,
            IStreamNormalizer,
            IStreamProcessor,
            SentinelManager,
            StopChunkWithUsage,
            StreamingContent,
            StreamingErrorMapper,
            UsageChunkLeakError,
            handle_streaming_error,
        )

        # Verify all are accessible
        assert StreamingContent is not None
        assert StopChunkWithUsage is not None
        assert UsageChunkLeakError is not None
        assert IStreamNormalizer is not None
        assert BaseStreamNormalizer is not None
        assert IStreamProcessor is not None
        assert IStreamAssembler is not None
        assert SentinelManager is not None
        assert StreamingErrorMapper is not None
        assert handle_streaming_error is not None

    def test_istream_normalizer_is_re_export_of_iprovider_stream_normalizer(self):
        """IStreamNormalizer from facade should be IProviderStreamNormalizer."""
        from src.core.ports.streaming.interfaces import IProviderStreamNormalizer

        # IStreamNormalizer from facade should be the same as IProviderStreamNormalizer
        assert IStreamNormalizer is IProviderStreamNormalizer

    def test_istream_normalizer_distinct_from_services_layer(self):
        """IStreamNormalizer from facade should be distinct from services-layer interface."""
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer as ServicesIStreamNormalizer,
        )

        # They should be different classes
        assert IStreamNormalizer is not ServicesIStreamNormalizer

        # Verify they have different method signatures
        assert hasattr(IStreamNormalizer, "normalize_stream")
        assert hasattr(ServicesIStreamNormalizer, "process_stream")
        assert not hasattr(IStreamNormalizer, "process_stream")
        assert not hasattr(ServicesIStreamNormalizer, "normalize_stream")
