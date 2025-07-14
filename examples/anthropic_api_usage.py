#!/usr/bin/env python3
"""
Example usage of the Anthropic API through the LLM Interactive Proxy.

This demonstrates how to use the official Anthropic SDK with the proxy
by simply changing the base_url parameter.
"""

import asyncio
import os
import logging
from anthropic import AsyncAnthropic

# Use application logger instead of print statements
logger = logging.getLogger(__name__)

# Example configuration
PROXY_BASE_URL = "http://localhost:8000/anthropic"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your-anthropic-api-key-here")


async def example_chat_completion():
    """Example of using Anthropic chat completion through the proxy."""
    
    # Initialize Anthropic client pointing to our proxy
    client = AsyncAnthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=PROXY_BASE_URL
    )
    
    try:
        # Simple chat completion
        response = await client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=100,
            temperature=0.7,
            messages=[
                {
                    "role": "user",
                    "content": "Hello! Can you tell me a short joke?"
                }
            ]
        )
        
        logger.info("Response:")
        for content_block in response.content:
            if content_block.type == "text":
                logger.info(content_block.text)
        
        logger.info("Usage: %s", response.usage)
        
    except Exception as e:
        logger.error("Error: %s", e)


async def example_streaming_completion():
    """Example of streaming chat completion through the proxy."""
    
    client = AsyncAnthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=PROXY_BASE_URL
    )
    
    try:
        logger.info("Streaming response:")
        
        async with client.messages.stream(
            model="claude-3-haiku-20240307",
            max_tokens=200,
            temperature=0.5,
            messages=[
                {
                    "role": "user", 
                    "content": "Write a haiku about programming."
                }
            ]
        ) as stream:
            async for event in stream:
                if hasattr(event, 'delta') and hasattr(event.delta, 'text'):
                    logger.info(event.delta.text)
        
        logger.info("Stream completed!")
        
    except Exception as e:
        logger.error("Streaming error: %s", e)


async def example_list_models():
    """Example of listing available models through the proxy."""
    
    client = AsyncAnthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=PROXY_BASE_URL
    )
    
    try:
        # Note: This would need to be implemented as a custom endpoint
        # since Anthropic SDK doesn't have a built-in models.list() method
        logger.info("Available models:")
        for mid in [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]:
            logger.info("- %s", mid)
        
    except Exception as e:
        logger.error("Models error: %s", e)


async def example_with_system_message():
    """Example using system message and advanced parameters."""
    
    client = AsyncAnthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=PROXY_BASE_URL
    )
    
    try:
        response = await client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=150,
            temperature=0.3,
            top_p=0.9,
            system="You are a helpful coding assistant. Provide concise, accurate answers.",
            messages=[
                {
                    "role": "user",
                    "content": "How do I reverse a string in Python?"
                }
            ],
            stop_sequences=["```"]
        )
        
        logger.info("Coding assistant response:")
        for content_block in response.content:
            if content_block.type == "text":
                logger.info(content_block.text)
                
    except Exception as e:
        logger.error("Error: %s", e)


async def main():
    """Run all examples."""
    logger.info("🤖 Anthropic API Proxy Examples")
    logger.info("=" * 40)
    
    logger.info("1. Basic Chat Completion:")
    await example_chat_completion()
    logger.info("\n" + "-" * 40 + "\n")
    
    logger.info("2. Streaming Completion:")
    await example_streaming_completion()
    logger.info("\n" + "-" * 40 + "\n")
    
    logger.info("3. Available Models:")
    await example_list_models()
    logger.info("\n" + "-" * 40 + "\n")
    
    logger.info("4. System Message Example:")
    await example_with_system_message()
    logger.info("\n" + "-" * 40 + "\n")
    
    logger.info("✅ All examples completed!")


if __name__ == "__main__":
    # Make sure you have:
    # 1. The proxy running on localhost:8000
    # 2. ANTHROPIC_API_KEY environment variable set
    # 3. anthropic package installed: pip install anthropic
    
    asyncio.run(main())