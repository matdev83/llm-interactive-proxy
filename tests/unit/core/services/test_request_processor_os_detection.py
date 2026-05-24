"""
Unit tests for OS detection logic extracted into SessionEnricher.

This file exists to preserve coverage and ensure OS detection behavior remains stable
after the RequestProcessor refactoring.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.domain.chat import ChatMessage, ChatRequest, MessageContentPartText
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.services.session_enricher import SessionEnricher


def _make_enricher() -> SessionEnricher:
    return SessionEnricher(session_manager=MagicMock(spec=ISessionManager))


def test_detect_client_os_from_string_content() -> None:
    """Detect OS when message content is a simple string."""
    enricher = _make_enricher()
    request = ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="User system info (win32 10.0.19045)")
        ],
    )
    assert enricher._detect_client_os(request) == "windows"


def test_detect_client_os_from_list_content() -> None:
    """Detect OS when message content is a list of multimodal blocks."""
    enricher = _make_enricher()
    request = ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartText(text="User system info (win32 10.0.19045)")
                ],
            )
        ],
    )
    assert enricher._detect_client_os(request) == "windows"


def test_detect_client_os_macos() -> None:
    """Detect OS for macOS."""
    enricher = _make_enricher()
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="User system info (darwin 22.0.0)")],
    )
    assert enricher._detect_client_os(request) == "macos"


def test_detect_client_os_linux() -> None:
    """Detect OS for Linux."""
    enricher = _make_enricher()
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="User system info (linux x86_64)")],
    )
    assert enricher._detect_client_os(request) == "linux"


def test_detect_client_os_none() -> None:
    """Return None when OS info is missing."""
    enricher = _make_enricher()
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    assert enricher._detect_client_os(request) is None
