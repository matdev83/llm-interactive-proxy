"""
Unit tests for OS detection in RequestProcessor.

NOTE: OS detection has been moved from RequestProcessor to SessionEnricher.
These tests are now obsolete and should be rewritten to test SessionEnricher directly,
or deleted entirely since the behavior is tested via integration tests.
"""

import pytest

# All tests in this file are skipped as OS detection has been refactored
# into SessionEnricher component
pytestmark = pytest.mark.skip(reason="OS detection moved to SessionEnricher component")


def test_detect_client_os_from_string_content():
    """Test OS detection when message content is a simple string."""


def test_detect_client_os_from_list_content():
    """Test OS detection when message content is a list of blocks (multimodal)."""


def test_detect_client_os_macos():
    """Test OS detection for macOS."""


def test_detect_client_os_linux():
    """Test OS detection for Linux."""


def test_detect_client_os_none():
    """Test OS detection returns None when info is missing."""
