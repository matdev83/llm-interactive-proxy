import os
import socket
import subprocess
import sys
import time

import pytest
import requests
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

pytestmark = pytest.mark.live


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_server(port, timeout=10):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            requests.get(f"http://127.0.0.1:{port}/internal/health")
            return True
        except requests.exceptions.ConnectionError:
            time.sleep(0.1)
    return False


@pytest.fixture(scope="module")
def proxy_server(live_openai_key, live_anthropic_key, live_gemini_key):
    """Start the proxy server for E2E tests."""
    port = _find_free_port()

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["DISABLE_AUTH"] = "true"

    # Pass API keys if they exist
    if live_openai_key:
        env["OPENAI_API_KEY"] = live_openai_key
    if live_anthropic_key:
        env["ANTHROPIC_API_KEY"] = live_anthropic_key
    if live_gemini_key:
        env["GEMINI_API_KEY"] = live_gemini_key

    # Start server
    cmd = [
        sys.executable,
        "-m",
        "src.core.cli",
        "--port",
        str(port),
        "--host",
        "127.0.0.1",
        "--disable-auth",
    ]

    proc = subprocess.Popen(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    if not _wait_for_server(port):
        proc.terminate()
        stdout, stderr = proc.communicate()
        with open("server_startup_error.log", "w") as f:
            f.write(f"Stdout:\n{stdout}\nStderr:\n{stderr}")
        raise RuntimeError(
            f"Server failed to start.\nStdout: {stdout}\nStderr: {stderr}"
        )

    yield f"http://127.0.0.1:{port}"

    proc.terminate()
    proc.wait()


class TestE2EFlows:
    """
    Verify that the proxy correctly handles requests from clients
    and routes them to real backends.
    """

    @pytest.mark.asyncio
    async def test_openai_client_through_proxy(self, proxy_server, require_openai):
        """Test OpenAI client connecting through proxy."""
        client = AsyncOpenAI(
            api_key="dummy-key", base_url=f"{proxy_server}/v1"  # Auth disabled on proxy
        )

        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Say 'proxy works'"}],
            max_tokens=10,
        )

        content = response.choices[0].message.content
        assert content is not None
        assert len(content) > 0

    @pytest.mark.asyncio
    async def test_anthropic_client_through_proxy(
        self, proxy_server, require_anthropic
    ):
        """Test Anthropic client connecting through proxy."""
        client = AsyncAnthropic(
            api_key="dummy-key", base_url=f"{proxy_server}/anthropic"
        )

        response = await client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say 'proxy works'"}],
        )

        assert len(response.content) > 0
        assert response.content[0].text is not None

    @pytest.mark.asyncio
    async def test_gemini_routing_through_openai_interface(
        self, proxy_server, require_gemini
    ):
        """Test routing to Gemini using OpenAI client interface (proxy feature)."""
        client = AsyncOpenAI(api_key="dummy-key", base_url=f"{proxy_server}/v1")

        # Request a Gemini model via OpenAI interface
        response = await client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[{"role": "user", "content": "Say 'gemini works'"}],
            max_tokens=10,
        )

        content = response.choices[0].message.content
        assert content is not None
        assert len(content) > 0
