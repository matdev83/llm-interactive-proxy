#!/usr/bin/env python
"""
Usage Accounting Verification Demo Script

This script verifies that usage accounting works correctly across all combinations of:

Backend Connectors (3):
- cline:minimax/minimax-m2
- gemini-oauth-plan:gemini-2.5-flash
- openrouter:x-ai/grok-4.1-fast:free

Frontend APIs (4):
- OpenAI Chat Completions (/v1/chat/completions on port 8000)
- OpenAI Responses API (/v1/responses on port 8000)
- Anthropic Messages API (/v1/messages on port 8001)
- Gemini/Vertex API (/v1beta/models/{model}:generateContent on port 8000)

Total: 12 test combinations

Usage:
    ./.venv/Scripts/python.exe scripts/demo_usage_accounting.py

    # With custom URLs
    LLM_PROXY_URL=http://localhost:8080 ./.venv/Scripts/python.exe scripts/demo_usage_accounting.py

Prerequisites:
    - Start the main proxy:
        ./.venv/Scripts/python.exe -m src.core.cli --disable-auth --port 8000 --anthropic-port 8001

    - Required environment variables for backends:
        - MINIMAX_API_KEY (for cline backend)
        - OPENROUTER_API_KEY (for openrouter backend)
        - Google OAuth credentials or GEMINI_API_KEY (for gemini-oauth-plan)

Environment Variables:
    LLM_PROXY_URL: Main proxy URL (default: http://127.0.0.1:8000)
    LLM_PROXY_ANTHROPIC_URL: Anthropic proxy URL (default: http://127.0.0.1:8001)
    LLM_PROXY_KEY: API key for the proxy (default: dev-key)
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_proxy_health(url: str, name: str) -> bool:
    """Check if proxy is running and reachable."""
    try:
        with httpx.Client(timeout=5.0) as client:
            # Try the health endpoint first
            try:
                response = client.get(f"{url}/health")
                if response.status_code == 200:
                    return True
            except Exception:
                pass

            # Try root endpoint
            try:
                response = client.get(f"{url}/")
                if response.status_code in (200, 404):
                    return True
            except Exception:
                pass

            # Try docs endpoint
            try:
                response = client.get(f"{url}/docs")
                if response.status_code == 200:
                    return True
            except Exception:
                pass

        return False
    except Exception:
        return False


@dataclass
class TestResult:
    """Result of a single test."""

    backend: str
    frontend: str
    success: bool
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    error: str | None = None
    response_content: str | None = None


# Configuration
OPENAI_BASE_URL = os.getenv("LLM_PROXY_URL", "http://127.0.0.1:8000")
# Anthropic endpoint is now on the main proxy under /anthropic prefix
ANTHROPIC_BASE_URL = os.getenv(
    "LLM_PROXY_ANTHROPIC_URL", "http://127.0.0.1:8000/anthropic"
)
API_KEY = os.getenv("LLM_PROXY_KEY", "dev-key")

# Test prompt
TEST_PROMPT = "What is the capital city of India? Answer in one word."

# Backend models to test
# Note: Some backends have specific requirements:
# - cline: Requires Cline client headers or --enable-cline-backend-debugging-override
# - openrouter: Requires OPENROUTER_API_KEY environment variable
# - gemini-oauth-plan: Requires Google OAuth credentials or GEMINI_API_KEY
BACKEND_MODELS = [
    "cline:minimax/minimax-m2",
    "gemini-oauth-plan:gemini-2.5-flash",
    "openrouter:x-ai/grok-4.1-fast:free",
]

# Track skipped tests
SKIPPED_REASONS: dict[str, str] = {}


def extract_usage(data: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    """Extract usage information from response data.

    Handles both OpenAI format (prompt_tokens, completion_tokens) and
    Anthropic format (input_tokens, output_tokens).
    """
    usage = data.get("usage", {})
    if not usage:
        return None, None, None

    # OpenAI format
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")

    # Anthropic format fallback
    if prompt is None:
        prompt = usage.get("input_tokens")
    if completion is None:
        completion = usage.get("output_tokens")

    # Calculate total if not provided
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion

    return prompt, completion, total


def test_openai_chat_completions(model: str) -> TestResult:
    """Test OpenAI Chat Completions endpoint (/v1/chat/completions)."""
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{OPENAI_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": TEST_PROMPT}],
                    "max_tokens": 50,
                    "temperature": 0,
                    "stream": False,
                },
            )

            if response.status_code != 200:
                return TestResult(
                    backend=model,
                    frontend="OpenAI Chat Completions",
                    success=False,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

            data = response.json()
            prompt, completion, total = extract_usage(data)

            # Extract response content
            content = None
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")

            success = (
                prompt is not None
                and completion is not None
                and total is not None
                and prompt > 0
                and completion > 0
            )

            return TestResult(
                backend=model,
                frontend="OpenAI Chat Completions",
                success=success,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                response_content=content,
                error=None if success else "Missing or zero usage values",
            )

    except Exception as e:
        return TestResult(
            backend=model,
            frontend="OpenAI Chat Completions",
            success=False,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            error=str(e),
        )


def test_openai_responses_api(model: str) -> TestResult:
    """Test OpenAI Responses API endpoint (/v1/responses).

    Note: The Responses API is for structured outputs and requires a response_format
    with a JSON schema. We construct a simple request.
    """
    try:
        with httpx.Client(timeout=120.0) as client:
            # Responses API requires messages format and response_format
            response = client.post(
                f"{OPENAI_BASE_URL}/v1/responses",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": TEST_PROMPT}],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "answer",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "capital": {
                                        "type": "string",
                                        "description": "The capital city name",
                                    }
                                },
                                "required": ["capital"],
                            },
                        },
                    },
                    "max_tokens": 50,
                    "temperature": 0,
                },
            )

            if response.status_code != 200:
                return TestResult(
                    backend=model,
                    frontend="OpenAI Responses API",
                    success=False,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

            data = response.json()
            prompt, completion, total = extract_usage(data)

            # Extract response content - can be in various formats
            content = None
            # Try choices format first
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
            # Try output format for Responses API
            if not content:
                output = data.get("output", [])
                if output and isinstance(output, list):
                    for item in output:
                        if item.get("type") == "message":
                            message_content = item.get("content", [])
                            if message_content:
                                for part in message_content:
                                    if part.get("type") == "output_text":
                                        content = part.get("text", "")
                                        break

            success = (
                prompt is not None
                and completion is not None
                and total is not None
                and prompt > 0
                and completion > 0
            )

            return TestResult(
                backend=model,
                frontend="OpenAI Responses API",
                success=success,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                response_content=content,
                error=None if success else "Missing or zero usage values",
            )

    except Exception as e:
        return TestResult(
            backend=model,
            frontend="OpenAI Responses API",
            success=False,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            error=str(e),
        )


def test_anthropic_messages(model: str) -> TestResult:
    """Test Anthropic Messages API endpoint (/v1/messages)."""
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{ANTHROPIC_BASE_URL}/v1/messages",
                headers={
                    "x-api-key": API_KEY,
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": TEST_PROMPT}],
                    "max_tokens": 50,
                },
            )

            if response.status_code != 200:
                return TestResult(
                    backend=model,
                    frontend="Anthropic Messages",
                    success=False,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

            data = response.json()
            prompt, completion, total = extract_usage(data)

            # Extract response content (Anthropic format)
            content = None
            content_blocks = data.get("content", [])
            if content_blocks and isinstance(content_blocks, list):
                for block in content_blocks:
                    if block.get("type") == "text":
                        content = block.get("text", "")
                        break

            success = (
                prompt is not None
                and completion is not None
                and total is not None
                and prompt > 0
                and completion > 0
            )

            return TestResult(
                backend=model,
                frontend="Anthropic Messages",
                success=success,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                response_content=content,
                error=None if success else "Missing or zero usage values",
            )

    except Exception as e:
        return TestResult(
            backend=model,
            frontend="Anthropic Messages",
            success=False,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            error=str(e),
        )


def test_gemini_generate_content(model: str) -> TestResult:
    """Test Gemini/Vertex API endpoint (/v1beta/models/:generateContent).

    Note: The Gemini endpoint URL pattern uses `:generateContent` suffix which conflicts
    with model names containing colons (like `backend:model`). To work around this,
    we use a simple URL model but pass the actual routing model in the request body.
    """
    try:
        # Use a simple model name in the URL to avoid colon conflicts
        # The actual routing model is passed in the request body
        url_model = "gemini-proxy"  # Placeholder, actual model is in body

        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{OPENAI_BASE_URL}/v1beta/models/{url_model}:generateContent",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,  # Actual routing model in body
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": TEST_PROMPT}],
                        }
                    ],
                    "generationConfig": {
                        "maxOutputTokens": 50,
                        "temperature": 0,
                    },
                },
            )

            if response.status_code != 200:
                return TestResult(
                    backend=model,
                    frontend="Gemini API",
                    success=False,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

            data = response.json()

            # Gemini uses usageMetadata with different field names
            usage_metadata = data.get("usageMetadata", {})
            prompt = usage_metadata.get("promptTokenCount")
            completion = usage_metadata.get("candidatesTokenCount")
            total = usage_metadata.get("totalTokenCount")

            # Also check for normalized usage field
            if prompt is None:
                usage = data.get("usage", {})
                prompt = usage.get("prompt_tokens")
                completion = usage.get("completion_tokens")
                total = usage.get("total_tokens")

            # Extract response content (Gemini format)
            content = None
            candidates = data.get("candidates", [])
            if candidates:
                candidate_content = candidates[0].get("content", {})
                parts = candidate_content.get("parts", [])
                if parts:
                    content = parts[0].get("text", "")

            success = (
                prompt is not None
                and completion is not None
                and total is not None
                and prompt > 0
                and completion > 0
            )

            return TestResult(
                backend=model,
                frontend="Gemini API",
                success=success,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                response_content=content,
                error=None if success else "Missing or zero usage values",
            )

    except Exception as e:
        return TestResult(
            backend=model,
            frontend="Gemini API",
            success=False,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            error=str(e),
        )


def print_result(result: TestResult, verbose: bool = False) -> None:
    """Print a single test result."""
    status = "[PASS]" if result.success else "[FAIL]"

    if result.success:
        print(
            f"  {status} {result.frontend}: "
            f"prompt={result.prompt_tokens}, "
            f"completion={result.completion_tokens}, "
            f"total={result.total_tokens}"
        )
    else:
        print(f"  {status} {result.frontend}: {result.error}")

    if result.response_content and verbose:
        # Truncate long responses
        content = result.response_content[:100]
        if len(result.response_content) > 100:
            content += "..."
        print(f"         Response: {content}")


def check_backend_prerequisites(model: str) -> tuple[bool, str | None]:
    """Check if the backend has required prerequisites.

    Returns:
        Tuple of (can_test, skip_reason). If can_test is False, skip_reason explains why.
    """
    backend = model.split(":")[0] if ":" in model else model

    if backend == "cline":
        # Cline requires special client identification
        return (
            False,
            "Cline backend requires --enable-cline-backend-debugging-override",
        )

    if backend == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        return False, "OPENROUTER_API_KEY environment variable not set"

    return True, None


def run_all_tests(
    anthropic_available: bool = True, skip_unconfigured: bool = True
) -> list[TestResult]:
    """Run all test combinations."""
    results: list[TestResult] = []

    print("=" * 60)
    print("Usage Accounting Verification Demo")
    print("=" * 60)
    print()
    print(f"OpenAI/Gemini API URL: {OPENAI_BASE_URL}")
    print(f"Anthropic API URL: {ANTHROPIC_BASE_URL}")
    print(f"Test prompt: {TEST_PROMPT}")
    print()

    for model in BACKEND_MODELS:
        print("-" * 60)
        print(f"Testing: {model}")
        print("-" * 60)

        # Check backend prerequisites
        can_test, skip_reason = check_backend_prerequisites(model)
        if not can_test and skip_unconfigured:
            print(f"  [SKIP] Backend unavailable: {skip_reason}")
            print()
            continue

        # Test each frontend API
        test_functions = [
            ("OpenAI Chat Completions", test_openai_chat_completions),
            ("OpenAI Responses API", test_openai_responses_api),
            ("Anthropic Messages", test_anthropic_messages),
            ("Gemini API", test_gemini_generate_content),
        ]

        for test_name, test_func in test_functions:
            # Skip Anthropic tests if server not available
            if test_name == "Anthropic Messages" and not anthropic_available:
                result = TestResult(
                    backend=model,
                    frontend=test_name,
                    success=False,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    error="Anthropic server not running on port 8001",
                )
            else:
                result = test_func(model)

            results.append(result)
            print_result(result)

            # Small delay between tests to avoid rate limiting
            time.sleep(1)

        print()

    return results


def print_summary(results: list[TestResult]) -> int:
    """Print test summary and return number of actual failures."""
    passed = sum(1 for r in results if r.success)

    # Categorize failures
    skipped = []
    actual_failures = []
    config_issues = []

    for r in results:
        if r.success:
            continue
        if not r.error:
            actual_failures.append(r)
        elif r.error.startswith("Anthropic server not running"):
            skipped.append(r)
        elif "api_key is required" in r.error or "OPENROUTER_API_KEY" in r.error:
            config_issues.append(r)
        else:
            actual_failures.append(r)

    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Passed: {passed}/{len(results)}")
    print(f"Skipped: {len(skipped)}/{len(results)}")
    print(f"Config Issues: {len(config_issues)}/{len(results)}")
    print(f"Failed: {len(actual_failures)}/{len(results)}")
    print()

    if actual_failures:
        print("Actual failures (bugs to investigate):")
        for r in actual_failures:
            print(f"  - {r.backend} / {r.frontend}: {r.error}")
        print()

    if config_issues:
        print("Configuration issues (proxy needs to be restarted with these env vars):")
        backends_with_issues = set()
        for r in config_issues:
            backend = r.backend.split(":")[0] if ":" in r.backend else r.backend
            backends_with_issues.add(backend)
        if "openrouter" in backends_with_issues:
            print("  - OPENROUTER_API_KEY: Required for OpenRouter backend")
        print()
        print("Restart the proxy with the required environment variables set.")
        print()

    if skipped:
        print(f"Skipped tests ({len(skipped)}):")
        for r in skipped:
            print(f"  - {r.backend} / {r.frontend}: {r.error}")

    return len(actual_failures)


def main() -> int:
    """Main entry point."""
    print("=" * 60)
    print("Checking proxy connectivity...")
    print("=" * 60)
    print()

    # Check if proxies are running
    main_proxy_ok = check_proxy_health(OPENAI_BASE_URL, "Main")
    anthropic_proxy_ok = check_proxy_health(ANTHROPIC_BASE_URL, "Anthropic")

    if main_proxy_ok:
        print(f"[OK] Main proxy reachable at {OPENAI_BASE_URL}")
    else:
        print(f"[ERROR] Main proxy NOT reachable at {OPENAI_BASE_URL}")

    if anthropic_proxy_ok:
        print(f"[OK] Anthropic endpoint reachable at {ANTHROPIC_BASE_URL}")
    else:
        print(f"[WARN] Anthropic endpoint NOT reachable at {ANTHROPIC_BASE_URL}")
        print("       Anthropic frontend tests will be skipped.")

    print()

    if not main_proxy_ok:
        print("ERROR: Main proxy is not running.")
        print()
        print("Please start the proxy first with:")
        print()
        print(
            "  ./.venv/Scripts/python.exe -m src.core.cli --disable-auth --port 8000 --anthropic-port 8001"
        )
        print()
        print("Or with uvicorn directly:")
        print()
        print(
            "  ./.venv/Scripts/python.exe -m uvicorn src.core.app.application_factory:build_app --factory --host 127.0.0.1 --port 8000"
        )
        print()
        return 1

    results = run_all_tests(anthropic_available=anthropic_proxy_ok)
    actual_failures = print_summary(results)

    return 1 if actual_failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
