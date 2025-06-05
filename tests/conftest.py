import os
import pytest
from unittest.mock import AsyncMock
from src.connectors import OpenRouterBackend, GeminiBackend

# Ensure external API keys do not interfere with tests
for i in range(1, 21):
    os.environ.pop(f"GEMINI_API_KEY_{i}", None)
    os.environ.pop(f"OPENROUTER_API_KEY_{i}", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("LLM_BACKEND", None)

@pytest.fixture(autouse=True)
def patch_backend_discovery(monkeypatch):
    monkeypatch.setattr(
        OpenRouterBackend,
        "list_models",
        AsyncMock(return_value={"data": [{"id": "model-a"}]}),
    )
    monkeypatch.setattr(
        GeminiBackend,
        "list_models",
        AsyncMock(return_value={"models": [{"name": "model-a"}]}),
    )
    yield


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    yield
