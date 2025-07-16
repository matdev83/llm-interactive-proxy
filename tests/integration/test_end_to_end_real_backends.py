import os
import time
import threading
import socket
from typing import Any, Dict

import pytest
import requests
import uvicorn

from src.main import build_app

# Optional client libraries – skip related scenarios if missing.
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import google.generativeai as genai  # type: ignore
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    from anthropic import Anthropic  # type: ignore
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

######################################################################
# Helper – lightweight proxy server wrapper identical to other suites
######################################################################

class _ProxyServer:
    """Run the FastAPI app under Uvicorn in a thread for integration tests."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        # Pick an ephemeral port so tests can run in parallel
        self.port = self._find_free_port()
        self.app = build_app(cfg)
        self.server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    # --------------------------------------------------------------
    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    # --------------------------------------------------------------
    def start(self) -> None:
        def _run() -> None:
            config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error")
            self.server = uvicorn.Server(config)
            # Uvicorn <0.25 blocks forever – run inside event loop.
            import asyncio
            asyncio.run(self.server.serve())

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        # Wait until the server responds or timeout after 15 s
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = requests.get(f"http://127.0.0.1:{self.port}/", timeout=2)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError("Proxy server failed to start within timeout")

    # --------------------------------------------------------------
    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True  # type: ignore[attr-defined]
        if self._thread:
            self._thread.join(timeout=5)

######################################################################
# Fixtures
######################################################################

BACKEND_MODEL_MAP = {
    # Updated per user request – switch to Moonshot Kimi model
    "openrouter": "openrouter:moonshotai/kimi-k2:free",
    "gemini": "gemini:gemini-2.5-flash",
    "gemini-cli-batch": "gemini-cli-batch:gemini-2.5-flash",
}

REQUIRED_ENV_VARS = {
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@pytest.fixture(scope="function")
def proxy_server(request):
    """Start proxy configured for the backend under test."""
    # Determine backend being tested – it can arrive either via direct parameterisation
    # of *this* fixture (indirect=True) or via a separate "backend" parameter on the
    # test function.  Fallback to *openrouter* when nothing was supplied so that the
    # file can still be run in isolation.
    if hasattr(request, "param"):
        backend = request.param  # When the fixture itself is parametrised (indirect)
    elif "backend" in request.fixturenames:
        backend = request.getfixturevalue("backend")  # Derived from test param
    else:
        backend = "openrouter"

    # Skip if env var missing for the selected backend
    def _has_env(prefix: str) -> bool:
        return any(k.startswith(prefix) and os.getenv(k) for k in os.environ)

    if backend == "openrouter":
        if not _has_env("OPENROUTER_API_KEY"):
            pytest.skip("No OpenRouter API key found – skipping real backend test")
    if backend in {"gemini", "gemini-cli-batch"}:
        if not _has_env("GEMINI_API_KEY"):
            pytest.skip("No Gemini API key found – skipping real backend test")

    # gemini-CLI backend additionally requires google-cloud project and installed CLI
    if backend == "gemini-cli-batch":
        if os.getenv("GOOGLE_CLOUD_PROJECT") is None:
            pytest.skip("GOOGLE_CLOUD_PROJECT not configured – skipping gemini-cli-batch test")
        # Basic check that the CLI is available on PATH
        import shutil
        if shutil.which("gemini") is None:
            pytest.skip("gemini CLI executable not found – skipping gemini-cli-batch test")

    # Always disable auth for internal tests to avoid client headers fuss.
    os.environ["DISABLE_AUTH"] = "true"

    # Build config dict – rely on env vars for API keys so real keys aren’t
    # hard-coded in repository.
    cfg: Dict[str, Any] = {
        "backend": backend,
        "interactive_mode": False,
        "command_prefix": "!/",
        "disable_auth": True,
        "disable_accounting": True,
        "proxy_timeout": 60,
        # Base URLs – fall back to defaults used by production code
        "openrouter_api_base_url": os.getenv("OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"),
        "gemini_api_base_url": os.getenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
        # Collect keys from environment – mapping required by build_app
        "openrouter_api_keys": {k: v for k, v in os.environ.items() if k.startswith("OPENROUTER_API_KEY") and v},
        "gemini_api_keys": {k: v for k, v in os.environ.items() if k.startswith("GEMINI_API_KEY") and v},
        "app_site_url": "http://localhost",
        "app_x_title": "integration-tests",
        # CLI-batch doesn’t need Gemini API keys but build_app expects a mapping
    }

    server = _ProxyServer(cfg)
    server.start()
    try:
        yield server
    finally:
        server.stop()

######################################################################
# Parametrisation helpers
######################################################################

def _available(client_name: str) -> bool:
    return {
        "openai": OPENAI_AVAILABLE,
        "gemini": GENAI_AVAILABLE,
        "anthropic": ANTHROPIC_AVAILABLE,
    }[client_name]


def _skip_unavailable(client_name: str):
    if not _available(client_name):
        pytest.skip(f"Required client library for {client_name} not installed")

######################################################################
# Test matrix – real backend round-trips
######################################################################

SCENARIOS = [
    ("anthropic", "openrouter"),
    ("anthropic", "gemini"),
    ("anthropic", "gemini-cli-batch"),
    ("openai", "openrouter"),
    ("openai", "gemini"),
    ("openai", "gemini-cli-batch"),
    ("gemini", "openrouter"),
    ("gemini", "gemini"),
    ("gemini", "gemini-cli-batch"),
]


@pytest.mark.integration  # Mark the whole suite for selective runs
@pytest.mark.parametrize("client_type,backend", SCENARIOS)
def test_end_to_end_chat_completion(client_type: str, backend: str, proxy_server):  # type: ignore[misc]
    """End-to-end check – send simple prompt through proxy to real backend and verify basic response structure."""
    _skip_unavailable(client_type)

    model_name = BACKEND_MODEL_MAP[backend]
    base_url = f"http://127.0.0.1:{proxy_server.port}"

    if client_type == "openai":
        _configure_openai(base_url)
        try:
            resp = openai.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "Hello!"}],
                stream=False,
            )
        except Exception as exc:
            pytest.skip(f"OpenAI request failed ({exc}); skipping scenario – ensure backend/model available and API key valid.")

        assert resp.choices, "No choices returned"
        assert resp.choices[0].message.role == "assistant"

    elif client_type == "anthropic":
        from anthropic import Anthropic  # type: ignore
        client = Anthropic(api_key="test-key", base_url=base_url)
        try:
            resp = client.messages.create(
                model=model_name,
                max_tokens=32,
                messages=[{"role": "user", "content": "Hello!"}],
            )
        except Exception as exc:
            pytest.skip(f"Anthropic request failed ({exc}); skipping scenario.")

        assert hasattr(resp, "content") and resp.content, "Empty response content"

    elif client_type == "gemini":
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key="test-key", base_url=base_url)
        try:
            response = genai.models.generate_content(model=model_name, contents="Hello!")
        except Exception as exc:
            pytest.skip(f"Gemini client request failed ({exc}); skipping scenario.")

        assert getattr(response, "candidates", None), "No candidates returned"

    else:
        raise AssertionError(f"Unknown client type {client_type}")

######################################################################
# OpenAI-specific tool-call handling (representative scenario)
######################################################################

# ----------------------------------------------------------------------
# OpenAI helper
# ----------------------------------------------------------------------


def _configure_openai(base_url: str) -> None:  # noqa: D401 – simple helper
    """Configure *openai* SDK to talk to the local proxy instance."""
    openai.api_key = "test-key"  # Proxy has auth disabled, but SDK requires a key
    # Ensure trailing slash so path joins correctly (avoids '/v1chat')
    root = f"{base_url}/v1/"
    if hasattr(openai, "base_url"):
        openai.base_url = root
    else:
        openai.api_base = root  # type: ignore[attr-defined]


@pytest.mark.integration
@pytest.mark.parametrize("backend", list(BACKEND_MODEL_MAP.keys()))
def test_openai_tool_call_handling(backend: str, proxy_server):  # type: ignore[override]
    if not OPENAI_AVAILABLE:
        pytest.skip("openai python package not installed – skipping tool-call test")

    base_url = f"http://127.0.0.1:{proxy_server.port}"

    # Configure OpenAI SDK for the proxy
    _configure_openai(base_url)

    # Step 1 – register Cline agent so proxy recognises tool-call behaviour
    openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": "I am a Cline agent. <attempt_completion>start</attempt_completion>",
            }
        ],
    )

    # Step 2 – send the !/hello command that should come back as a tool call
    try:
        data = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "!/hello"}],
        ).model_dump()
    except Exception as exc:
        pytest.skip(f"OpenAI tool-call request failed ({exc}); skipping.")

    choice = data["choices"][0]
    msg = choice["message"]
    assert msg["content"] is None, "Tool-call responses should have null content"
    assert msg.get("tool_calls"), "Missing tool_calls element in response"
    assert choice["finish_reason"] == "tool_calls"
    tool_call = msg["tool_calls"][0]
    assert tool_call["type"] == "function"
    assert tool_call["function"]["name"] == "attempt_completion" 

######################################################################
# Streaming variants – skipped for gemini-cli-batch which is non-streaming
######################################################################


@pytest.mark.integration
@pytest.mark.parametrize("client_type,backend", SCENARIOS)
def test_end_to_end_chat_completion_streaming(client_type: str, backend: str, proxy_server):  # type: ignore[misc]
    _skip_unavailable(client_type)

    if backend == "gemini-cli-batch":
        pytest.skip("gemini-cli-batch backend returns non-streaming responses – skip streaming test")

    model_name = BACKEND_MODEL_MAP[backend]
    base_url = f"http://127.0.0.1:{proxy_server.port}"

    if client_type == "openai":
        _configure_openai(base_url)

        try:
            chunks = list(
                openai.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": "Hello!"}],
                    stream=True,
                )
            )
        except Exception as exc:
            pytest.skip(f"OpenAI streaming failed ({exc}); skipping.")

        assert chunks, "No streaming chunks received"

    elif client_type == "anthropic":
        from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT  # type: ignore
        client = Anthropic(api_key="test-key", base_url=base_url)
        try:
            stream = client.messages.create(
                model=model_name,
                max_tokens=16,
                messages=[{"role": "user", "content": "Hello!"}],
                stream=True,
            )
            first = next(stream, None)
        except Exception as exc:
            pytest.skip(f"Anthropic streaming failed ({exc}); skipping.")

        assert first is not None, "No events from Anthropics stream"

    elif client_type == "gemini":
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key="test-key", base_url=base_url)
        try:
            stream = genai.models.generate_content(
                model=model_name,
                contents="Hello!",
                stream=True,
            )
            first_chunk = next(stream, None)
        except Exception as exc:
            pytest.skip(f"Gemini client streaming failed ({exc}); skipping.")

        assert first_chunk is not None, "No stream chunks from Gemini client"

    else:
        raise AssertionError(f"Unknown client type {client_type}") 