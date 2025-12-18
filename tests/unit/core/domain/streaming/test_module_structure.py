"""
Tests verifying the new module directory structure exists.

These tests ensure the refactored module boundaries are in place
before migrating code from streaming_contracts.py.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


class TestDomainModuleStructure:
    """Test domain module structure exists."""

    def test_domain_streaming_directory_exists(self):
        """src/core/domain/streaming/ directory should exist."""
        domain_dir = Path("src/core/domain/streaming")
        assert domain_dir.exists(), f"Directory {domain_dir} should exist"
        assert domain_dir.is_dir()

    def test_domain_streaming_init_exists(self):
        """src/core/domain/streaming/__init__.py should exist."""
        init_file = Path("src/core/domain/streaming/__init__.py")
        assert init_file.exists(), f"File {init_file} should exist"
        assert init_file.is_file()

    def test_domain_streaming_content_module_exists(self):
        """src/core/domain/streaming/streaming_content.py should exist."""
        module_file = Path("src/core/domain/streaming/streaming_content.py")
        assert module_file.exists(), f"File {module_file} should exist"
        assert module_file.is_file()

    def test_domain_stop_chunk_module_exists(self):
        """src/core/domain/streaming/stop_chunk_with_usage.py should exist."""
        module_file = Path("src/core/domain/streaming/stop_chunk_with_usage.py")
        assert module_file.exists(), f"File {module_file} should exist"
        assert module_file.is_file()

    def test_domain_sentinels_module_exists(self):
        """src/core/domain/streaming/sentinels.py should exist."""
        module_file = Path("src/core/domain/streaming/sentinels.py")
        assert module_file.exists(), f"File {module_file} should exist"
        assert module_file.is_file()

    def test_domain_parsing_directory_exists(self):
        """src/core/domain/streaming/parsing/ directory should exist."""
        parsing_dir = Path("src/core/domain/streaming/parsing")
        assert parsing_dir.exists(), f"Directory {parsing_dir} should exist"
        assert parsing_dir.is_dir()

    def test_domain_parsing_init_exists(self):
        """src/core/domain/streaming/parsing/__init__.py should exist."""
        init_file = Path("src/core/domain/streaming/parsing/__init__.py")
        assert init_file.exists(), f"File {init_file} should exist"
        assert init_file.is_file()


class TestPortsModuleStructure:
    """Test ports module structure exists."""

    def test_ports_streaming_directory_exists(self):
        """src/core/ports/streaming/ directory should exist."""
        ports_dir = Path("src/core/ports/streaming")
        assert ports_dir.exists(), f"Directory {ports_dir} should exist"
        assert ports_dir.is_dir()

    def test_ports_streaming_init_exists(self):
        """src/core/ports/streaming/__init__.py should exist."""
        init_file = Path("src/core/ports/streaming/__init__.py")
        assert init_file.exists(), f"File {init_file} should exist"
        assert init_file.is_file()

    def test_ports_interfaces_module_exists(self):
        """src/core/ports/streaming/interfaces.py should exist."""
        module_file = Path("src/core/ports/streaming/interfaces.py")
        assert module_file.exists(), f"File {module_file} should exist"
        assert module_file.is_file()

    def test_ports_normalizer_base_module_exists(self):
        """src/core/ports/streaming/normalizer_base.py should exist."""
        module_file = Path("src/core/ports/streaming/normalizer_base.py")
        assert module_file.exists(), f"File {module_file} should exist"
        assert module_file.is_file()


class TestTransportModuleStructure:
    """Test transport module structure exists."""

    def test_transport_streaming_directory_exists(self):
        """src/core/transport/streaming/ directory should exist."""
        transport_dir = Path("src/core/transport/streaming")
        assert transport_dir.exists(), f"Directory {transport_dir} should exist"
        assert transport_dir.is_dir()

    def test_transport_streaming_init_exists(self):
        """src/core/transport/streaming/__init__.py should exist."""
        init_file = Path("src/core/transport/streaming/__init__.py")
        assert init_file.exists(), f"File {init_file} should exist"
        assert init_file.is_file()

    def test_transport_sse_serializer_module_exists(self):
        """src/core/transport/streaming/sse_serializer.py should exist."""
        module_file = Path("src/core/transport/streaming/sse_serializer.py")
        assert module_file.exists(), f"File {module_file} should exist"
        assert module_file.is_file()


class TestServicesModuleStructure:
    """Test services module structure exists."""

    def test_services_streaming_directory_exists(self):
        """src/core/services/streaming/ directory should exist."""
        services_dir = Path("src/core/services/streaming")
        assert services_dir.exists(), f"Directory {services_dir} should exist"
        assert services_dir.is_dir()

    def test_services_streaming_init_exists(self):
        """src/core/services/streaming/__init__.py should exist."""
        init_file = Path("src/core/services/streaming/__init__.py")
        assert init_file.exists(), f"File {init_file} should exist"
        assert init_file.is_file()

    def test_services_error_mapping_module_exists(self):
        """src/core/services/streaming/error_mapping.py should exist."""
        module_file = Path("src/core/services/streaming/error_mapping.py")
        assert module_file.exists(), f"File {module_file} should exist"
        assert module_file.is_file()


class TestModuleImports:
    """Test that skeleton modules can be imported."""

    def test_domain_streaming_init_importable(self):
        """Domain streaming __init__ should be importable."""
        try:
            importlib.import_module("src.core.domain.streaming")
        except ImportError as e:
            pytest.fail(f"Failed to import src.core.domain.streaming: {e}")

    def test_ports_streaming_init_importable(self):
        """Ports streaming __init__ should be importable."""
        try:
            importlib.import_module("src.core.ports.streaming")
        except ImportError as e:
            pytest.fail(f"Failed to import src.core.ports.streaming: {e}")

    def test_transport_streaming_init_importable(self):
        """Transport streaming __init__ should be importable."""
        try:
            importlib.import_module("src.core.transport.streaming")
        except ImportError as e:
            pytest.fail(f"Failed to import src.core.transport.streaming: {e}")

    def test_services_streaming_init_importable(self):
        """Services streaming __init__ should be importable."""
        try:
            importlib.import_module("src.core.services.streaming")
        except ImportError as e:
            pytest.fail(f"Failed to import src.core.services.streaming: {e}")



