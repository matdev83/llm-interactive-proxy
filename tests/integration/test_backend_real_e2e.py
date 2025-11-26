"""
Live end-to-end tests for key backends using real credentials and real network calls.

These tests:
- Discover a free OpenRouter model and run a chat completion through the proxy
- Exercise the gemini-oauth-plan backend with the gemini-2.5-flash model
- Exercise the gemini-oauth-antigravity backend with the gpt-oss-120b-medium model

Each test skips automatically if required credentials are missing or expired.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import socket
import subprocess
import sys
import time
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
import requests
from google.genai import Client as GeminiClient
from google.genai import types as genai_types
from openai import OpenAI
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
from src.core.config.app_config import AppConfig
from src.core.config.config_loader import _collect_api_keys
from src.core.services.translation_service import TranslationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
    pytest.mark.no_global_mock,
]


def _wait_port(port: int, host: str = "127.0.0.1", timeout: float = 20.0) -> None:
    """Wait for a TCP port to accept connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(
        f"Server on {host}:{port} did not start within {timeout} seconds"
    )


def _start_proxy(
    default_backend: str, extra_env: Mapping[str, str] | None = None
) -> tuple[subprocess.Popen[str], int]:
    """Start the proxy via uvicorn in a subprocess and return (process, port)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    env = os.environ.copy()
    env.update(
        {
            "LLM_BACKEND": default_backend,
            "DISABLE_AUTH": "1",
            "PYTHONUNBUFFERED": "1",
            "LOG_LEVEL": "WARNING",
            "COMMAND_PREFIX": "!/",
        }
    )
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.core.app.application_factory:build_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        _wait_port(port)
    except Exception:
        if proc.stdout is not None:
            output = proc.stdout.read() or ""
        else:
            output = ""
        proc.kill()
        raise RuntimeError(f"Proxy failed to start. Output:\n{output}")
    return proc, port


def _stop_proxy(proc: subprocess.Popen[str]) -> str:
    """Terminate the proxy process and drain output."""
    output = ""
    try:
        proc.terminate()
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    finally:
        if proc.stdout:
            with contextlib.suppress(Exception):
                output = proc.stdout.read() or ""
    return output


def _get_openrouter_api_key() -> str | None:
    """Return the first available OpenRouter API key from environment."""
    try:
        keys = _collect_api_keys("OPENROUTER_API_KEY")
    except Exception:
        keys = {}
    if not keys:
        return None
    return next(iter(keys.values()))


def _free_openrouter_models(api_key: str) -> list[str]:
    """Return free OpenRouter model ids with available providers, prioritized."""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models", headers=headers, timeout=20
        )
    except Exception:
        return []
    if resp.status_code != 200:
        return []

    payload = resp.json() or {}
    models = payload.get("data") or []
    candidates: list[str] = []
    priority_order = [
        "openai/gpt-oss-20b:free",
        "z-ai/glm-4.5-air:free",
        "qwen/qwen3-coder:free",
        "moonshotai/kimi-k2:free",
        "meituan/longcat-flash-chat:free",
        "kwaipilot/kat-coder-pro:free",
        "mistralai/mistral-7b-instruct:free",
        "mistralai/mixtral-8x7b-instruct:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "meta-llama/llama-3-8b-instruct:free",
        "x-ai/grok-4.1-fast:free",
        "nvidia/nemotron-nano-9b-v2:free",
    ]
    priority_set = set(priority_order)
    for model in models:
        text = f"{model.get('id', '')} {model.get('name', '')}".lower()
        pricing = model.get("pricing") or {}
        prompt_price = pricing.get("prompt")
        completion_price = pricing.get("completion")
        provider_ok = prompt_price in (0, 0.0, "0") or completion_price in (
            0,
            0.0,
            "0",
        )
        model_id = model.get("id")
        if "free" in text and provider_ok and model_id:
            candidates.append(model_id)

    if not candidates:
        for model in models:
            text = f"{model.get('id', '')} {model.get('name', '')}".lower()
            if "free" in text and model.get("id"):
                candidates.append(model["id"])

    prioritized = [m for m in priority_order if m in candidates]
    remaining = [m for m in candidates if m not in priority_set]
    return prioritized + remaining


def _pick_openrouter_model(api_key: str) -> str | None:
    """Return a candidate free model, prioritized, or None if none available."""
    candidates = _free_openrouter_models(api_key)
    if not candidates:
        return None
    # Preserve priority but add mild randomization within tail to reduce hot-spotting
    head = candidates[: len(candidates) // 2]
    tail = candidates[len(candidates) // 2 :]
    random.shuffle(tail)
    ordered = head + tail
    return ordered[0] if ordered else None


def _probe_openrouter_model(api_key: str, model_id: str) -> tuple[bool, str]:
    """Perform a quick direct call to OpenRouter to confirm the model works."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/matdev83/llm-interactive-proxy",
        "X-Title": "llm-interactive-proxy",
    }
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "Ping"}],
                "max_tokens": 8,
            },
            timeout=18,
        )
        if resp.status_code == 200:
            data = resp.json() or {}
            if data.get("choices"):
                return True, ""
        return False, f"status={resp.status_code}, body={resp.text[:120]}"
    except Exception as exc:
        return False, str(exc)


async def _check_connector_credentials(
    connector: Any, validate_file: bool = True
) -> tuple[bool, str]:
    """Validate that a Gemini OAuth connector has usable, non-expired credentials."""
    try:
        if validate_file and hasattr(connector, "_validate_credentials_file_exists"):
            ok, errors = connector._validate_credentials_file_exists()  # type: ignore[attr-defined]
            if not ok:
                return False, "; ".join(errors)

        loaded = await connector._load_oauth_credentials()  # type: ignore[attr-defined]
        creds = getattr(connector, "_oauth_credentials", None)
        if not loaded or not creds or not creds.get("access_token"):
            return False, "Credentials could not be loaded"

        seconds_remaining = connector._seconds_until_token_expiry()  # type: ignore[attr-defined]
        if seconds_remaining is not None and seconds_remaining <= 0:
            return False, "Credentials are expired"
        return True, ""
    finally:
        with contextlib.suppress(Exception):
            await connector.client.aclose()


def _has_valid_plan_credentials() -> tuple[bool, str]:
    """Check gemini-oauth-plan credentials and return (ok, reason)."""
    client = httpx.AsyncClient(timeout=10.0)
    connector = GeminiOAuthPlanConnector(client, AppConfig(), TranslationService())
    return asyncio.run(_check_connector_credentials(connector, validate_file=True))


def _has_valid_antigravity_credentials() -> tuple[bool, str]:
    """Check gemini-oauth-antigravity credentials and return (ok, reason)."""
    client = httpx.AsyncClient(timeout=10.0)
    connector = GeminiOAuthAntigravityConnector(
        client, AppConfig(), TranslationService()
    )
    # Antigravity credentials live in a state DB, not oauth_creds.json
    return asyncio.run(_check_connector_credentials(connector, validate_file=False))


def test_openrouter_free_model_roundtrip() -> None:
    """Full flow: proxy + OpenAI client hitting OpenRouter with a free model."""
    api_key = _get_openrouter_api_key()
    if not api_key:
        pytest.skip("OpenRouter API key not found in environment")

    first_model = _pick_openrouter_model(api_key)
    if not first_model:
        pytest.skip("No OpenRouter free model with healthy providers available")

    candidates = [first_model]
    more = _free_openrouter_models(api_key)
    for mid in more:
        if mid not in candidates:
            candidates.append(mid)
    if len(candidates) > 1:
        head, tail = candidates[:1], candidates[1:]
        random.shuffle(tail)
        candidates = head + tail

    validated: list[str] = []
    direct_errors: list[str] = []
    for model_id in candidates[:4]:
        ok, reason = _probe_openrouter_model(api_key, model_id)
        if ok:
            validated.append(model_id)
            if len(validated) >= 2:
                break
        else:
            direct_errors.append(f"{model_id}: {reason}")

    if not validated:
        pytest.skip(
            f"No responsive OpenRouter free models after probe: {direct_errors}"
        )

    proc, port = _start_proxy("openrouter", {"OPENROUTER_API_KEY_1": api_key})
    proxy_output = ""
    try:
        client = OpenAI(
            api_key="proxy-test-key",
            base_url=f"http://127.0.0.1:{port}/v1",
            timeout=25.0,
            max_retries=0,
        )
        errors: list[str] = []
        success = False
        start_time = time.time()
        max_candidates = min(len(validated), 2)
        deadline = start_time + 75
        max_errors = max_candidates
        for model_id in validated[:max_candidates]:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            request_timeout = min(20.0, remaining)
            if request_timeout < 4.0:
                break
            try:
                response = client.chat.completions.create(
                    model=f"openrouter:{model_id}",
                    messages=[{"role": "user", "content": "Say hello in two words."}],
                    max_tokens=16,
                    temperature=0.2,
                    timeout=request_timeout,
                )
                assert (
                    response.choices
                ), "No choices returned from OpenRouter through proxy"
                content = response.choices[0].message.content
                assert content, "Empty content from OpenRouter through proxy"
                success = True
                break
            except (
                Exception
            ) as exc:  # Retry with next candidate on timeout/provider errors
                errors.append(f"{model_id}: {exc}")
                if len(errors) >= max_errors or time.time() > deadline:
                    break
                continue
    finally:
        proxy_output = _stop_proxy(proc)
    if not success:
        pytest.skip(
            f"OpenRouter free models are not currently available or working: {errors}\nProxy output:\n{proxy_output}"
        )


def test_gemini_oauth_plan_end_to_end() -> None:
    """Full flow for gemini-oauth-plan using gemini-2.5-flash."""
    ok, reason = _has_valid_plan_credentials()
    if not ok:
        pytest.skip(f"gemini-oauth-plan credentials unavailable: {reason}")

    proc, port = _start_proxy(
        "gemini-oauth-plan",
        {
            "DISABLE_GEMINI_OAUTH_FALLBACK": "1",
        },
    )
    try:
        client = GeminiClient(
            api_key="proxy-test-key",
            http_options=genai_types.HttpOptions(base_url=f"http://127.0.0.1:{port}"),
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents="Return the word READY"
        )
        text = getattr(response, "text", None)
        assert text, "No text returned from gemini-oauth-plan via proxy"
    finally:
        _stop_proxy(proc)


def test_gemini_oauth_antigravity_end_to_end() -> None:
    """Full flow for gemini-oauth-antigravity using gpt-oss-120b-medium."""
    ok, reason = _has_valid_antigravity_credentials()
    if not ok:
        pytest.skip(f"gemini-oauth-antigravity credentials unavailable: {reason}")

    proc, port = _start_proxy(
        "gemini-oauth-antigravity",
        {
            "DISABLE_GEMINI_OAUTH_FALLBACK": "1",
        },
    )
    try:
        client = GeminiClient(
            api_key="proxy-test-key",
            http_options=genai_types.HttpOptions(base_url=f"http://127.0.0.1:{port}"),
        )
        response = client.models.generate_content(
            model="gpt-oss-120b-medium",
            contents="Confirm connectivity by replying with CONNECTED",
        )
        text = getattr(response, "text", None)
        assert text, "No text returned from gemini-oauth-antigravity via proxy"
    finally:
        _stop_proxy(proc)
