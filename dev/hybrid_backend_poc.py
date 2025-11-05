#!/usr/bin/env python3
"""
Hybrid Backend Proof of Concept

This script demonstrates the hybrid reasoning approach:
1. Call reasoning model (minimax:MiniMax-M2) to capture reasoning output
2. Detect end of reasoning phase and cancel request
3. Call execution model (zai-coding-plan:glm-4.6) with augmented prompt
4. Display detailed debugging information

Usage:
    python dev/hybrid_backend_poc.py "Your prompt here"
"""

import asyncio
import json
import sys
from collections.abc import AsyncGenerator

import httpx

# Configuration
PROXY_BASE_URL = "http://127.0.0.1:8000/v1"
REASONING_MODEL = "minimax:MiniMax-M2"
EXECUTION_MODEL = "zai-coding-plan:glm-4.6"
TIMEOUT = 60.0


class Colors:
    """ANSI color codes for terminal output."""

    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


def print_section(title: str, color: str = Colors.CYAN) -> None:
    """Print a section header."""
    print(f"\n{color}{Colors.BOLD}{'=' * 80}{Colors.END}")
    print(f"{color}{Colors.BOLD}{title.center(80)}{Colors.END}")
    print(f"{color}{Colors.BOLD}{'=' * 80}{Colors.END}\n")


def print_info(label: str, value: str, color: str = Colors.BLUE) -> None:
    """Print labeled information."""
    print(f"{color}{Colors.BOLD}{label}:{Colors.END} {value}")


def print_content(content: str, color: str = Colors.GREEN) -> None:
    """Print content with color."""
    print(f"{color}{content}{Colors.END}")


async def parse_sse_stream(response: httpx.Response) -> AsyncGenerator[dict, None]:
    """Parse Server-Sent Events stream."""
    buffer = ""
    async for chunk in response.aiter_text():
        buffer += chunk
        while "\n\n" in buffer:
            message, buffer = buffer.split("\n\n", 1)
            for line in message.split("\n"):
                if line.startswith("data: "):
                    data = line[6:]  # Remove "data: " prefix
                    if data.strip() == "[DONE]":
                        return
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue


def detect_reasoning_end(chunk: dict, accumulated_content: str) -> tuple[bool, str]:
    """
    Detect if reasoning phase has ended using priority-based strategy.

    Priority order:
    1. Explicit closing tags: </think>, </thinking>, </reason>, </reasoning>
    2. finish_reason in response metadata
    3. Content transition markers (with caution)

    Returns:
        Tuple of (is_complete, detection_method)
    """
    # Priority 1: Check for explicit closing tags
    explicit_tags = ["</think>", "</thinking>", "</reason>", "</reasoning>"]
    content_lower = accumulated_content.lower()

    for tag in explicit_tags:
        if tag in content_lower:
            print_info("  ✓ Detected explicit tag", tag, Colors.YELLOW)
            return True, f"explicit_tag:{tag}"

    # Priority 2: Check for finish_reason in choices
    choices = chunk.get("choices", [])
    for choice in choices:
        finish_reason = choice.get("finish_reason")
        if finish_reason and finish_reason != "null":
            print_info("  ✓ Detected finish_reason", finish_reason, Colors.YELLOW)
            return True, f"finish_reason:{finish_reason}"

    # Priority 3: Check for content transition markers (with caution)
    transition_markers = [
        "therefore,",
        "in conclusion,",
        "to summarize,",
        "in summary,",
    ]

    for marker in transition_markers:
        if marker in content_lower and len(accumulated_content) > 1000:
            # Only trigger if we have substantial content (avoid premature cancellation)
            print_info("  ⚠️  Detected transition marker", marker, Colors.YELLOW)
            return True, f"transition_marker:{marker}"

    return False, ""


def extract_reasoning_content(chunks: list[dict]) -> str:
    """Extract reasoning text from captured chunks."""
    reasoning_parts = []

    for chunk in chunks:
        choices = chunk.get("choices", [])
        for choice in choices:
            delta = choice.get("delta", {})
            content = delta.get("content", "")
            if content:
                reasoning_parts.append(content)

    return "".join(reasoning_parts)


async def call_reasoning_model(prompt: str) -> str:
    """
    Phase 1: Call reasoning model and capture reasoning output.

    Returns:
        Captured reasoning text
    """
    print_section("PHASE 1: REASONING MODEL", Colors.CYAN)
    print_info("Model", REASONING_MODEL)
    print_info("Proxy", PROXY_BASE_URL)
    print_info("Prompt", f'"{prompt}"')

    request_payload = {
        "model": REASONING_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "temperature": 0.7,
    }

    print_info("\nRequest Payload", json.dumps(request_payload, indent=2), Colors.BLUE)

    captured_chunks = []
    accumulated_content = ""
    reasoning_complete = False
    detection_method = ""

    print(f"\n{Colors.GREEN}Streaming reasoning output:{Colors.END}\n")

    async with (
        httpx.AsyncClient(timeout=TIMEOUT) as client,
        client.stream(
            "POST",
            f"{PROXY_BASE_URL}/chat/completions",
            json=request_payload,
            headers={"Content-Type": "application/json"},
        ) as response,
    ):

        if response.status_code != 200:
            error_text = await response.aread()
            raise Exception(
                f"Reasoning model request failed: {response.status_code} - {error_text.decode()}"
            )

        print_info("Response Status", str(response.status_code), Colors.GREEN)
        print(f"\n{Colors.GREEN}{'─' * 80}{Colors.END}")

        chunk_count = 0
        async for chunk in parse_sse_stream(response):
            captured_chunks.append(chunk)
            chunk_count += 1

            # Extract and display content
            choices = chunk.get("choices", [])
            for choice in choices:
                delta = choice.get("delta", {})
                content = delta.get("content", "")
                if content:
                    accumulated_content += content
                    print(f"{Colors.GREEN}{content}{Colors.END}", end="", flush=True)

            # Check if reasoning is complete (with accumulated content)
            is_complete, method = detect_reasoning_end(chunk, accumulated_content)
            if is_complete:
                reasoning_complete = True
                detection_method = method
                print(
                    f"\n\n{Colors.YELLOW}🛑 Reasoning phase detected as complete!{Colors.END}"
                )
                print_info("Detection method", detection_method, Colors.YELLOW)
                print_info("Chunks captured", str(chunk_count), Colors.YELLOW)

                # Cancel the stream
                await response.aclose()
                print_info("Stream cancelled", "✓", Colors.YELLOW)
                break

        print(f"\n{Colors.GREEN}{'─' * 80}{Colors.END}\n")

    # Extract reasoning content
    reasoning_output = extract_reasoning_content(captured_chunks)

    print_info("Reasoning captured", f"{len(reasoning_output)} characters", Colors.CYAN)
    print_info("Reasoning complete", str(reasoning_complete), Colors.CYAN)
    if detection_method:
        print_info("Detection method", detection_method, Colors.CYAN)

    if not reasoning_output:
        print(f"{Colors.RED}⚠️  Warning: No reasoning content captured!{Colors.END}")

    return reasoning_output


async def call_execution_model(prompt: str, reasoning_output: str) -> str:
    """
    Phase 2: Call execution model with augmented prompt.

    Args:
        prompt: Original user prompt
        reasoning_output: Captured reasoning from phase 1

    Returns:
        Execution model response
    """
    print_section("PHASE 2: EXECUTION MODEL", Colors.BLUE)
    print_info("Model", EXECUTION_MODEL)
    print_info("Proxy", PROXY_BASE_URL)

    # Augment prompt with reasoning (using system message for models that support it)
    augmented_messages = [
        {
            "role": "system",
            "content": f"Consider this reasoning when formulating your response:\n\n<thinking>\n{reasoning_output}\n</thinking>",
        },
        {"role": "user", "content": prompt},
    ]

    request_payload = {
        "model": EXECUTION_MODEL,
        "messages": augmented_messages,
        "stream": True,
        "temperature": 0.7,
    }

    print_info("\nAugmented Messages", "", Colors.BLUE)
    print(
        f"{Colors.BLUE}System message length: {len(augmented_messages[0]['content'])} chars{Colors.END}"
    )
    print(f'{Colors.BLUE}User message: "{prompt}"{Colors.END}')

    print(f"\n{Colors.GREEN}Streaming execution output:{Colors.END}\n")

    response_parts = []

    async with (
        httpx.AsyncClient(timeout=TIMEOUT) as client,
        client.stream(
            "POST",
            f"{PROXY_BASE_URL}/chat/completions",
            json=request_payload,
            headers={"Content-Type": "application/json"},
        ) as response,
    ):

        if response.status_code != 200:
            error_text = await response.aread()
            raise Exception(
                f"Execution model request failed: {response.status_code} - {error_text.decode()}"
            )

        print_info("Response Status", str(response.status_code), Colors.GREEN)
        print(f"\n{Colors.GREEN}{'─' * 80}{Colors.END}")

        async for chunk in parse_sse_stream(response):
            choices = chunk.get("choices", [])
            for choice in choices:
                delta = choice.get("delta", {})
                content = delta.get("content", "")
                if content:
                    response_parts.append(content)
                    print(f"{Colors.GREEN}{content}{Colors.END}", end="", flush=True)

        print(f"\n{Colors.GREEN}{'─' * 80}{Colors.END}\n")

    execution_output = "".join(response_parts)
    print_info("Execution output", f"{len(execution_output)} characters", Colors.BLUE)

    return execution_output


async def main(prompt: str) -> None:
    """Main execution flow."""
    print_section("HYBRID BACKEND PROOF OF CONCEPT", Colors.HEADER)
    print_info("Reasoning Model", REASONING_MODEL, Colors.HEADER)
    print_info("Execution Model", EXECUTION_MODEL, Colors.HEADER)
    print_info("User Prompt", f'"{prompt}"', Colors.HEADER)

    try:
        # Phase 1: Capture reasoning
        reasoning_output = await call_reasoning_model(prompt)

        if not reasoning_output:
            print(
                f"\n{Colors.RED}❌ Failed to capture reasoning output. Aborting.{Colors.END}"
            )
            return

        # Phase 2: Execute with reasoning
        execution_output = await call_execution_model(prompt, reasoning_output)

        # Summary
        print_section("SUMMARY", Colors.HEADER)
        print_info(
            "Reasoning length", f"{len(reasoning_output)} characters", Colors.CYAN
        )
        print_info(
            "Execution length", f"{len(execution_output)} characters", Colors.BLUE
        )
        print(
            f"\n{Colors.GREEN}✓ Hybrid backend POC completed successfully!{Colors.END}\n"
        )

    except Exception as e:
        print(f"\n{Colors.RED}❌ Error: {e}{Colors.END}\n")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f'{Colors.RED}Usage: python {sys.argv[0]} "Your prompt here"{Colors.END}')
        print(f"\n{Colors.YELLOW}Example:{Colors.END}")
        print(f'  python {sys.argv[0]} "Explain how quantum entanglement works"')
        sys.exit(1)

    user_prompt = " ".join(sys.argv[1:])
    asyncio.run(main(user_prompt))
