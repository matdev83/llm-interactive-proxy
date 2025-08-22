"""Test fixtures for multimodal content tests.

This module provides fixtures for setting up multimodal content tests.
"""

import pytest
from typing import Any, Dict, List, Optional, Union

from src.core.domain.chat import (
    ChatMessage,
    MessageContentPartImage,
    MessageContentPartText,
    ImageURL,
)


@pytest.fixture
def text_content_part(text="This is a text part"):
    """Create a text content part.
    
    Args:
        text: The text content
        
    Returns:
        MessageContentPartText: A text content part
    """
    return MessageContentPartText(type="text", text=text)


@pytest.fixture
def image_content_part(url="https://example.com/image.jpg", detail=None):
    """Create an image content part.
    
    Args:
        url: The image URL
        detail: The image detail level
        
    Returns:
        MessageContentPartImage: An image content part
    """
    return MessageContentPartImage(
        type="image_url",
        image_url=ImageURL(url=url, detail=detail),
    )


@pytest.fixture
def multimodal_message(text_content_part, image_content_part, role="user"):
    """Create a multimodal message.
    
    Args:
        text_content_part: A text content part
        image_content_part: An image content part
        role: The message role
        
    Returns:
        ChatMessage: A multimodal message
    """
    return ChatMessage(
        role=role,
        content=[text_content_part, image_content_part],
    )


@pytest.fixture
def text_message(text="This is a text message", role="user"):
    """Create a text message.
    
    Args:
        text: The message text
        role: The message role
        
    Returns:
        ChatMessage: A text message
    """
    return ChatMessage(role=role, content=text)


@pytest.fixture
def image_message(image_content_part, role="user"):
    """Create an image-only message.
    
    Args:
        image_content_part: An image content part
        role: The message role
        
    Returns:
        ChatMessage: An image-only message
    """
    return ChatMessage(role=role, content=[image_content_part])


@pytest.fixture
def message_with_command(command_text="!/set(model=openrouter:test-model)", role="user"):
    """Create a message with a command.
    
    Args:
        command_text: The command text
        role: The message role
        
    Returns:
        ChatMessage: A message with a command
    """
    return ChatMessage(role=role, content=command_text)


@pytest.fixture
def multimodal_message_with_command(command_text="!/set(model=openrouter:test-model)", image_content_part=None, role="user"):
    """Create a multimodal message with a command.
    
    Args:
        command_text: The command text
        image_content_part: An image content part (created if None)
        role: The message role
        
    Returns:
        ChatMessage: A multimodal message with a command
    """
    if image_content_part is None:
        image_content_part = MessageContentPartImage(
            type="image_url",
            image_url=ImageURL(url="https://example.com/image.jpg", detail=None),
        )
    
    return ChatMessage(
        role=role,
        content=[
            MessageContentPartText(type="text", text=command_text),
            image_content_part,
        ],
    )


