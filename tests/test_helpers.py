"""
Helper functions for tests.

This module provides utilities to simplify testing.
"""

import json
import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import respx
from src.core.domain.session import Session, SessionState


def generate_random_id(prefix: str = "", length: int = 8) -> str:
    """Generate a random ID for testing.
    
    Args:
        prefix: Optional prefix for the ID
        length: Length of the random part
        
    Returns:
        A random string ID
    """
    random_part = "".join(random.choices(string.ascii_lowercase + string.digits, k=length))
    return f"{prefix}{random_part}"


def generate_session_id() -> str:
    """Generate a random session ID for testing.
    
    Returns:
        A random session ID
    """
    return str(uuid.uuid4())


def create_test_session(session_id: str | None = None) -> Session:
    """Create a test session.
    
    Args:
        session_id: Optional session ID (generated if not provided)
        
    Returns:
        A test session
    """
    from src.core.domain.configuration.backend_config import BackendConfiguration
    from src.core.domain.configuration.loop_detection_config import (
        LoopDetectionConfiguration,
    )
    from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
    
    return Session(
        session_id=session_id or generate_session_id(),
        state=SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            reasoning_config=ReasoningConfiguration(temperature=0.7),
            loop_config=LoopDetectionConfiguration(),
            project="test-project",
        ),
    )


def create_test_messages(num_messages: int = 2) -> list[dict[str, Any]]:
    """Create test messages for API requests.
    
    Args:
        num_messages: Number of messages to create
        
    Returns:
        List of message dictionaries
    """
    messages = []
    
    # Add system message if more than one message
    if num_messages > 1:
        messages.append({
            "role": "system",
            "content": "You are a helpful assistant for testing."
        })
    
    # Add user message
    messages.append({
        "role": "user",
        "content": "Hello, this is a test message."
    })
    
    # Add assistant messages if needed
    for i in range(num_messages - len(messages)):
        messages.append({
            "role": "assistant",
            "content": f"Hello! I'm here to help with test #{i+1}."
        })
    
    return messages


def create_test_request_json(
    model: str = "gpt-4",
    stream: bool = False,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a test request JSON payload.
    
    Args:
        model: The model to use
        stream: Whether to stream the response
        messages: List of messages (generated if not provided)
        
    Returns:
        A request dictionary
    """
    if messages is None:
        messages = create_test_messages()
        
    return {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": 0.7,
        "max_tokens": None,
    }


def create_chat_response_json(
    content: str = "Hello! This is a test response.",
    model: str = "gpt-4",
) -> dict[str, Any]:
    """Create a test response JSON payload.
    
    Args:
        content: The response content
        model: The model name
        
    Returns:
        A response dictionary
    """
    return {
        "id": f"resp-{generate_random_id()}",
        "object": "chat.completion",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
    }


def create_streaming_response_chunks(
    content: str = "Hello! This is a test response.",
    model: str = "gpt-4",
    chunk_size: int = 10,
) -> list[dict[str, Any]]:
    """Create test streaming response chunks.
    
    Args:
        content: The response content
        model: The model name
        chunk_size: Size of each content chunk
        
    Returns:
        List of response chunk dictionaries
    """
    response_id = f"resp-{generate_random_id()}"
    created = int(datetime.now(timezone.utc).timestamp())
    chunks = []
    
    # Split content into chunks
    content_chunks = [
        content[i:i+chunk_size]
        for i in range(0, len(content), chunk_size)
    ]
    
    # Create a chunk for each part
    for i, content_part in enumerate(content_chunks):
        chunks.append({
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": content_part,
                    },
                    "finish_reason": None if i < len(content_chunks) - 1 else "stop",
                }
            ],
        })
    
    return chunks


class MockSessionService:
    """Mock session service for testing."""
    
    def __init__(self):
        """Initialize the mock service."""
        self.sessions: dict[str, Session] = {}
        
    async def get_session(self, session_id: str) -> Session:
        """Get or create a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            The session
        """
        if session_id not in self.sessions:
            self.sessions[session_id] = create_test_session(session_id)
        
        return self.sessions[session_id]
    
    async def update_session(self, session: Session) -> None:
        """Update a session.
        
        Args:
            session: The session to update
        """
        self.sessions[session.session_id] = session
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            True if the session was deleted, False if it didn't exist
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False
    
    async def get_all_sessions(self) -> list[Session]:
        """Get all sessions.
        
        Returns:
            List of all sessions
        """
        return list(self.sessions.values())


def mock_backend_api(respx_mock: respx.Router, base_url: str = "https://api.openai.com/v1") -> None:
    """Mock backend API calls for testing.
    
    Args:
        respx_mock: The respx mock router
        base_url: The base URL for the API
    """
    # Mock chat completions endpoint
    respx_mock.post(f"{base_url}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json=create_chat_response_json(),
        )
    )
    
    # Mock streaming chat completions
    stream_chunks = create_streaming_response_chunks()
    
    async def streaming_response(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(200, headers={"Content-Type": "text/event-stream"})
        
        async def stream():
            for chunk in stream_chunks:
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            yield b"data: [DONE]\n\n"
            
        response.extensions["http_stream"] = stream()
        return response
    
    # Add streaming route when 'stream': True is in the request
    respx_mock.post(f"{base_url}/chat/completions").mock(
        side_effect=streaming_response
    ).where(json__stream=True)
