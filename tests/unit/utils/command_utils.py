"""Utility functions for command handling in tests.

This module provides utility functions for handling commands in tests,
ensuring consistent behavior across all tests.
"""

import re
from typing import List, Optional, Tuple, Union, cast

from src.core.domain.chat import ChatMessage, MessageContentPartImage, MessageContentPartText


def strip_commands_from_text(text: str, command_prefix: str = "!/") -> str:
    """Strip commands from text.
    
    This function removes all commands from the given text.
    If any command is found, the entire text is replaced with an empty string
    to ensure consistent behavior across tests.
    
    Args:
        text: The text to strip commands from
        command_prefix: The command prefix to look for
        
    Returns:
        Empty string if commands are found, otherwise the original text
    """
    # Pattern to match commands with or without parentheses
    pattern = re.compile(f"{re.escape(command_prefix)}\\w+(?:\\([^)]*\\))?")
    
    # Find all commands in the text
    matches = list(pattern.finditer(text))
    
    # If there are any commands, return an empty string for consistency
    if matches:
        return ""
    
    # If there are no matches, return the original text
    return text


def strip_commands_from_message(
    message: ChatMessage, command_prefix: str = "!/"
) -> Optional[ChatMessage]:
    """Strip commands from a message.
    
    This function removes all commands from the given message.
    If any command is found, the message content is replaced with an empty string
    for string content, or the text parts are removed for multimodal content.
    
    Args:
        message: The message to strip commands from
        command_prefix: The command prefix to look for
        
    Returns:
        A new message with commands stripped, or None if the message would be empty
    """
    # Pattern to match commands with or without parentheses
    pattern = re.compile(f"{re.escape(command_prefix)}\\w+(?:\\([^)]*\\))?")
    
    # Check if there are any commands in the message
    has_commands = False
    
    # Handle string content
    if isinstance(message.content, str):
        # Check if there are any commands in the content
        if pattern.search(message.content):
            has_commands = True
            # Return a message with empty content
            return ChatMessage(
                role=message.role,
                content="",
                name=message.name,
                tool_calls=message.tool_calls,
                tool_call_id=message.tool_call_id,
            )
        else:
            # No commands found, return the original message
            return message
    
    # Handle multimodal content (list of parts)
    elif isinstance(message.content, list):
        # Check if any text part contains commands
        for part in message.content:
            if isinstance(part, MessageContentPartText) and pattern.search(part.text):
                has_commands = True
                break
        
        if has_commands:
            # If commands were found, keep only non-text parts
            new_parts = []
            for part in message.content:
                if not isinstance(part, MessageContentPartText):
                    new_parts.append(part)
            
            # If there are no parts left, return a message with empty string content
            if not new_parts:
                return ChatMessage(
                    role=message.role,
                    content="",
                    name=message.name,
                    tool_calls=message.tool_calls,
                    tool_call_id=message.tool_call_id,
                )
            
            # Otherwise, create a new message with only the non-text parts
            return ChatMessage(
                role=message.role,
                content=new_parts,
                name=message.name,
                tool_calls=message.tool_calls,
                tool_call_id=message.tool_call_id,
            )
        else:
            # No commands found, return the original message
            return message
    
    # If the content is not a string or list, return the original message
    return message


def strip_commands_from_messages(
    messages: List[ChatMessage], command_prefix: str = "!/"
) -> List[ChatMessage]:
    """Strip commands from a list of messages.
    
    This function removes all commands from the given messages.
    If any message would be empty after stripping, it is kept with empty content
    to maintain the same number of messages.
    
    Args:
        messages: The messages to strip commands from
        command_prefix: The command prefix to look for
        
    Returns:
        A new list of messages with commands stripped
    """
    result = []
    
    # Process each message
    for message in messages:
        stripped_message = strip_commands_from_message(message, command_prefix)
        
        # Always add the stripped message, even if it's empty
        # This ensures we maintain the same number of messages
        if stripped_message:
            result.append(stripped_message)
        else:
            # If stripping would remove the message entirely, add an empty message instead
            result.append(ChatMessage(
                role=message.role,
                content="",
                name=message.name,
                tool_calls=message.tool_calls,
                tool_call_id=message.tool_call_id,
            ))
    
    return result
