#!/usr/bin/env python
"""
Send test requests to the LLM Interactive Proxy.

This script allows for sending test chat requests to the LLM Interactive Proxy
with various configurations to test its functionality.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from typing import Any

import httpx


def setup_logging() -> logging.Logger:
    """Set up logging.

    Returns:
        A configured logger
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("test_client")


async def send_chat_request(
    url: str,
    model: str,
    messages: list[dict[str, Any]],
    stream: bool = False,
    session_id: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: int = 120,
    backend_type: str | None = None,
) -> dict[str, Any]:
    """Send a chat request to the proxy.

    Args:
        url: The URL to send the request to
        model: The model to use
        messages: The messages to send
        stream: Whether to stream the response
        session_id: Optional session ID
        api_key: Optional API key
        temperature: The temperature to use
        max_tokens: The maximum number of tokens
        timeout: The request timeout
        backend_type: Optional backend type

    Returns:
        The response data
    """
    # Prepare headers
    headers = {}
    if session_id:
        headers["X-Session-ID"] = session_id
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Prepare request data
    request_data = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
    }

    if max_tokens is not None:
        request_data["max_tokens"] = max_tokens

    if backend_type:
        request_data["backend_type"] = backend_type

    logger = logging.getLogger("test_client")
    logger.info(f"Sending request to {url}")
    logger.debug(f"Request data: {json.dumps(request_data, indent=2)}")

    # Send the request
    async with httpx.AsyncClient(timeout=timeout) as client:
        if not stream:
            response = await client.post(
                url,
                json=request_data,
                headers=headers,
            )

            if response.status_code != 200:
                logger.error(f"Request failed with status {response.status_code}")
                logger.error(f"Response: {response.text}")
                return {"error": response.text}

            return response.json()
        else:
            # Handle streaming responses
            response = await client.post(
                url,
                json=request_data,
                headers=headers,
                stream=True,
            )

            if response.status_code != 200:
                logger.error(f"Request failed with status {response.status_code}")
                logger.error(f"Response: {response.text}")
                return {"error": response.text}

            # Process the stream
            content = ""
            print("Streaming response:")
            async for chunk in response.aiter_lines():
                if chunk and chunk.strip() and chunk != "data: [DONE]":
                    # Process chunk
                    if chunk.startswith("data: "):
                        chunk_data = json.loads(chunk[6:])
                        if chunk_data.get("choices"):
                            delta = chunk_data["choices"][0].get("delta", {})
                            if "content" in delta:
                                content_chunk = delta["content"]
                                content += content_chunk
                                print(content_chunk, end="", flush=True)

            print()  # Add newline at the end
            return {"content": content}


def create_messages(
    prompt: str,
    system_prompt: str | None = None,
    conversation: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Create a list of messages for the request.

    Args:
        prompt: The user prompt
        system_prompt: Optional system prompt
        conversation: Optional existing conversation

    Returns:
        A list of message dictionaries
    """
    messages = []

    # Add system prompt if provided
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Add conversation if provided
    if conversation:
        messages.extend(conversation)

    # Add the user prompt
    messages.append({"role": "user", "content": prompt})

    return messages


async def main_async(args: list[str] | None = None) -> int:
    """Async main entry point.

    Args:
        args: Command line arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    logger = setup_logging()

    parser = argparse.ArgumentParser(description="Send test requests to the proxy")

    # Request parameters
    parser.add_argument(
        "--url",
        default="http://localhost:8000/v1/chat/completions",
        help="URL for the chat completions endpoint",
    )
    parser.add_argument(
        "--model",
        default="gpt-4",
        help="Model to use",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="The prompt to send",
    )
    parser.add_argument(
        "--system",
        help="System prompt to use",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        default=False,
        help="Whether to stream the response",
    )
    parser.add_argument(
        "--session",
        help="Session ID to use (generated if not provided)",
    )
    parser.add_argument(
        "--api-key",
        help="API key to use",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Temperature to use",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Maximum number of tokens",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds",
    )
    parser.add_argument(
        "--backend",
        help="Backend type to use",
    )

    # Parse arguments
    parsed_args = parser.parse_args(args)

    # Generate session ID if not provided
    session_id = parsed_args.session or str(uuid.uuid4())

    # Create messages
    messages = create_messages(parsed_args.prompt, parsed_args.system)

    # Send the request
    start_time = time.time()
    try:
        response = await send_chat_request(
            url=parsed_args.url,
            model=parsed_args.model,
            messages=messages,
            stream=parsed_args.stream,
            session_id=session_id,
            api_key=parsed_args.api_key,
            temperature=parsed_args.temperature,
            max_tokens=parsed_args.max_tokens,
            timeout=parsed_args.timeout,
            backend_type=parsed_args.backend,
        )

        # Print the response
        if not parsed_args.stream:
            if "error" in response:
                logger.error(f"Error: {response['error']}")
                return 1

            # Calculate response time
            elapsed = time.time() - start_time
            logger.info(f"Response time: {elapsed:.2f} seconds")

            # Print content from the response
            if response.get("choices"):
                content = response["choices"][0]["message"]["content"]
                print(f"\nResponse:\n{content}")

            # Print usage if available
            if "usage" in response:
                usage = response["usage"]
                logger.info(
                    f"Usage: {usage.get('prompt_tokens', 0)} prompt tokens, "
                    f"{usage.get('completion_tokens', 0)} completion tokens, "
                    f"{usage.get('total_tokens', 0)} total tokens"
                )

        return 0

    except Exception as e:
        logger.error(f"Error: {e!s}")
        return 1


def main(args: list[str] | None = None) -> int:
    """Main entry point.

    Args:
        args: Command line arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
