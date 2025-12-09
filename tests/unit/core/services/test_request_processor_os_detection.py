"""
Unit tests for OS detection in RequestProcessor.
"""
from unittest.mock import MagicMock

from src.core.domain.chat import ChatRequest
from src.core.services.request_processor_service import RequestProcessor


def test_detect_client_os_from_string_content():
    """Test OS detection when message content is a simple string."""
    processor = RequestProcessor(
        command_processor=MagicMock(),
        session_manager=MagicMock(),
        backend_request_manager=MagicMock(),
        response_manager=MagicMock(),
    )
    
    messages = [
        {"role": "user", "content": "User system info (win32 10.0.19045)"}
    ]
    request = ChatRequest(messages=messages, model="test-model")
    
    client_os = processor._detect_client_os(request)
    assert client_os == "windows"


def test_detect_client_os_from_list_content():
    """Test OS detection when message content is a list of blocks (multimodal)."""
    processor = RequestProcessor(
        command_processor=MagicMock(),
        session_manager=MagicMock(),
        backend_request_manager=MagicMock(),
        response_manager=MagicMock(),
    )
    
    messages = [
        {
            "role": "user", 
            "content": [
                {
                    "type": "text", 
                    "text": "<system-reminder>\n\nUser system info (win32 10.0.19045)\nModel: px-ag:gemini-3-pro-high"
                }
            ]
        }
    ]
    request = ChatRequest(messages=messages, model="test-model")
    
    client_os = processor._detect_client_os(request)
    assert client_os == "windows"


def test_detect_client_os_macos():
    """Test OS detection for macOS."""
    processor = RequestProcessor(
        command_processor=MagicMock(),
        session_manager=MagicMock(),
        backend_request_manager=MagicMock(),
        response_manager=MagicMock(),
    )
    
    messages = [
        {"role": "user", "content": "User system info (darwin 20.0.0)"}
    ]
    request = ChatRequest(messages=messages, model="test-model")
    
    client_os = processor._detect_client_os(request)
    assert client_os == "macos"


def test_detect_client_os_linux():
    """Test OS detection for Linux."""
    processor = RequestProcessor(
        command_processor=MagicMock(),
        session_manager=MagicMock(),
        backend_request_manager=MagicMock(),
        response_manager=MagicMock(),
    )
    
    messages = [
        {"role": "user", "content": "User system info (linux 5.4.0)"}
    ]
    request = ChatRequest(messages=messages, model="test-model")
    
    client_os = processor._detect_client_os(request)
    assert client_os == "linux"


def test_detect_client_os_none():
    """Test OS detection returns None when info is missing."""
    processor = RequestProcessor(
        command_processor=MagicMock(),
        session_manager=MagicMock(),
        backend_request_manager=MagicMock(),
        response_manager=MagicMock(),
    )
    
    messages = [
        {"role": "user", "content": "Hello world"}
    ]
    request = ChatRequest(messages=messages, model="test-model")
    
    client_os = processor._detect_client_os(request)
    assert client_os is None
