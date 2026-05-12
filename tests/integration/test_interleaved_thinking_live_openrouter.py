from __future__ import annotations

import importlib
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from src.connectors.openai import OpenAIConnector
from src.core.app.application_builder import build_app_async
from src.core.config import _collect_api_keys
from src.core.config.app_config import AppConfig
from src.core.config.models.auth import AuthConfig
from src.core.config.models.backends import BackendConfig, BackendSettings
from src.core.config.models.notification import NotificationConfig
from src.core.config.models.session import SessionConfig
from src.core.interfaces.session_service_interface import ISessionService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
    pytest.mark.slow,
]

THINKER_MODEL = "arcee-ai/trinity-large-thinking:free"
WORKHORSE_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
THINKER_MODEL_MATCH = "arcee-ai/trinity-large-thinking"
ROUTE = (
    f"[thinker]openrouter:{THINKER_MODEL}" f"^[weight=2]openrouter:{WORKHORSE_MODEL}"
)

THINKER_MARKER = "THINKER_LIVE_E2E_V1"
CUSTOM_MARKER = "CUSTOM_THINKER_PROMPT_SEEN_7139"
ACTION_TOKEN = "EXECUTOR_CONFIRMED_FROM_THINKER_2468"
WORKHORSE_PASS_MARKER = "WORKHORSE_E2E_PASS"
SESSION_FACT_ALPHA = "BLUE-ORCHID-914"
SESSION_FACT_BETA = "SILVER-LANTERN-207"


def _openrouter_api_key() -> str | None:
    keys = _collect_api_keys("OPENROUTER_API_KEY")
    return next(iter(keys.values()), None)


def _response_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []

    def _collect_strings(value: Any) -> None:
        if isinstance(value, str) and value:
            parts.append(value)
            return
        if isinstance(value, dict):
            for nested in value.values():
                _collect_strings(nested)
            return
        if isinstance(value, list):
            for nested in value:
                _collect_strings(nested)

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                for key in ("content", "reasoning_content", "reasoning"):
                    value = message.get(key)
                    if isinstance(value, str) and value:
                        parts.append(value)
            delta = first.get("delta")
            if isinstance(delta, dict):
                for key in ("content", "reasoning_content", "reasoning"):
                    value = delta.get(key)
                    if isinstance(value, str) and value:
                        parts.append(value)
    if not parts:
        _collect_strings(payload)
    return "\n".join(parts)


def _assert_chat_ok(response_payload: dict[str, Any]) -> None:
    choices = response_payload.get("choices")
    assert isinstance(choices, list) and choices, response_payload
    assert isinstance(choices[0], dict), response_payload
    assert isinstance(choices[0].get("message"), dict), response_payload


def _messages_with_attempt_nonce(
    messages: list[dict[str, str]],
    *,
    phase: str,
    attempt: int,
) -> list[dict[str, str]]:
    copied = [dict(message) for message in messages]
    copied.append(
        {
            "role": "user",
            "content": f"Live E2E routing sample nonce: {phase}-{attempt}.",
        }
    )
    return copied


def _install_deterministic_weighted_rolls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_indexes = iter([0, 1])

    def _select_index_from_weights(_self: Any, weights: Any) -> int:
        _ = weights
        return next(selected_indexes, 1)

    monkeypatch.setattr(
        "src.core.services.weighted_branch_selector.WeightedBranchSelector.select_index_from_weights",
        _select_index_from_weights,
    )


def _install_payload_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    captured_payloads: list[dict[str, Any]] = []
    original_prepare_payload = OpenAIConnector._prepare_payload

    async def _capture_prepare_payload(
        self: OpenAIConnector,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        context: Any = None,
    ) -> dict[str, Any]:
        payload = await original_prepare_payload(
            self,
            request_data,
            processed_messages,
            effective_model,
            context,
        )
        captured_payloads.append(deepcopy(payload))
        return payload

    monkeypatch.setattr(OpenAIConnector, "_prepare_payload", _capture_prepare_payload)
    return captured_payloads


def _payload_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []

    def _collect(value: Any) -> None:
        if isinstance(value, str) and value:
            parts.append(value)
            return
        if isinstance(value, dict):
            for nested in value.values():
                _collect(nested)
            return
        if isinstance(value, list):
            for nested in value:
                _collect(nested)

    _collect(payload)
    return "\n".join(parts)


def _post_chat(
    client: TestClient,
    *,
    session_id: str,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": ROUTE,
        "messages": messages,
        "session_id": session_id,
        "temperature": 0,
        "stream": False,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    response = client.post(
        "/v1/chat/completions",
        json=body,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    _assert_chat_ok(payload)
    return payload


async def _build_live_app(api_key: str, instructions_file: Path):
    importlib.import_module("src.connectors.openrouter")
    cfg = AppConfig(
        host="127.0.0.1",
        port=8000,
        proxy_timeout=180,
        disable_health_checks=True,
        auth=AuthConfig(disable_auth=True),
        notifications=NotificationConfig(enabled=None),
        session=SessionConfig(
            project_dir_resolution_mode="disabled",
            disable_default_openrouter_project_dir_resolution_fallback=True,
        ),
        backends=BackendSettings.model_validate(
            {
                "default_backend": "openrouter",
                "interleaved_thinking_instructions_file": str(instructions_file),
                "openrouter": BackendConfig(
                    api_key=api_key,
                    api_url="https://openrouter.ai/api/v1",
                    timeout=180,
                ),
            }
        ),
    )
    app = await build_app_async(cfg)
    app.state.app_config = cfg
    return app


def _session_service(app: Any) -> ISessionService:
    provider = app.state.service_provider
    return cast(
        ISessionService, provider.get_required_service(cast(type, ISessionService))
    )


async def _interleaved_thinking_state(app: Any) -> dict[str, Any] | None:
    service = _session_service(app)
    sessions = await service.get_all_sessions()
    for session in sessions:
        raw_state = getattr(session.state, "interleaved_thinking_state", None)
        if isinstance(raw_state, dict) and raw_state.get("memo"):
            return raw_state
    return None


async def _session_debug(app: Any) -> list[dict[str, Any]]:
    service = _session_service(app)
    sessions = await service.get_all_sessions()
    debug: list[dict[str, Any]] = []
    for session in sessions:
        backend_config = getattr(session.state, "backend_config", None)
        raw_state = getattr(session.state, "interleaved_thinking_state", None)
        if raw_state is None:
            to_dict = getattr(session.state, "to_dict", None)
            if callable(to_dict):
                state_dict = to_dict()
                if isinstance(state_dict, dict):
                    raw_state = state_dict.get("interleaved_thinking_state")
        debug.append(
            {
                "session_id": getattr(session, "session_id", None),
                "backend": getattr(backend_config, "backend_type", None),
                "model": getattr(backend_config, "model", None),
                "interleaved_thinking_state": raw_state,
            }
        )
    return debug


@pytest.mark.skipif(
    _openrouter_api_key() is None,
    reason="OPENROUTER_API_KEY or OPENROUTER_API_KEY_<n> is required",
)
@pytest.mark.asyncio
async def test_interleaved_thinking_live_openrouter_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real proxy plus OpenRouter weighted thinker/workhorse route.

    This live test proves:
    - the [thinker] branch receives custom instructions;
    - the thinker sees the caller-provided session context;
    - a later workhorse turn receives the captured thinker memo and acts on it.
    """

    api_key = _openrouter_api_key()
    assert api_key is not None
    _install_deterministic_weighted_rolls(monkeypatch)
    captured_payloads = _install_payload_capture(monkeypatch)

    instructions_file = tmp_path / "live_thinker_prompt.md"
    instructions_file.write_text(
        "\n".join(
            [
                "You are the live interleaved-thinking E2E verifier.",
                f"Custom instruction marker: {CUSTOM_MARKER}.",
                "You must prove that you received these custom instructions and "
                "the caller-provided session context.",
                "Do not ask questions.",
                "Do not put the required markers only in hidden reasoning. "
                "Your final visible assistant message must contain all markers.",
                "Never return empty content.",
                "Return exactly this one visible line, with no extra text:",
                f"{THINKER_MARKER} {CUSTOM_MARKER} ACTION_TOKEN={ACTION_TOKEN} "
                f"FACTS={SESSION_FACT_ALPHA}|{SESSION_FACT_BETA} "
                f"NEXT={WORKHORSE_PASS_MARKER}",
            ]
        ),
        encoding="utf-8",
    )

    app = await _build_live_app(api_key, instructions_file)
    session_id = "live-interleaved-thinking-e2e"
    thinker_text: str | None = None

    with TestClient(app) as client:
        thinker_messages = [
            {
                "role": "system",
                "content": (
                    "Session context fact alpha is "
                    f"{SESSION_FACT_ALPHA}. Keep it available."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Earlier session context fact beta is "
                    f"{SESSION_FACT_BETA}. This fact must be visible to the "
                    "thinker."
                ),
            },
            {
                "role": "assistant",
                "content": "Acknowledged both live E2E session facts.",
            },
            {
                "role": "user",
                "content": (
                    "If this request is routed to the thinker, follow the custom "
                    "thinker instructions exactly."
                ),
            },
        ]

        payload = _post_chat(
            client,
            session_id=session_id,
            messages=_messages_with_attempt_nonce(
                thinker_messages,
                phase="thinker",
                attempt=0,
            ),
        )
        assert captured_payloads, payload
        thinker_payload = captured_payloads[-1]
        thinker_upstream_text = _payload_text(thinker_payload)
        assert thinker_payload.get("model") == THINKER_MODEL, thinker_payload
        assert CUSTOM_MARKER in thinker_upstream_text, thinker_payload
        assert SESSION_FACT_ALPHA in thinker_upstream_text, thinker_payload
        assert SESSION_FACT_BETA in thinker_upstream_text, thinker_payload

        text = _response_text(payload)
        if THINKER_MARKER in text:
            thinker_text = text

        assert thinker_text is not None, {
            "route": ROUTE,
            "response_text": text,
            "payload": payload,
            "upstream_payload": thinker_payload,
            "sessions": await _session_debug(app),
        }
        assert THINKER_MARKER in thinker_text
        assert CUSTOM_MARKER in thinker_text
        assert SESSION_FACT_ALPHA in thinker_text
        assert SESSION_FACT_BETA in thinker_text
        assert ACTION_TOKEN in thinker_text

        workhorse_payload: dict[str, Any] | None = None
        workhorse_messages = [
            {
                "role": "user",
                "content": (
                    "Executor validation turn. The proxy may have inserted a "
                    "thinker memo before this message. Extract the NEXT, "
                    "ACTION_TOKEN, and FACTS values from that injected memo. "
                    "The memo uses KEY=VALUE fields. Output the extracted NEXT "
                    "value, then a space, then ACTION_TOKEN= plus the extracted "
                    "ACTION_TOKEN value, then a space, then FACTS= plus the "
                    "extracted FACTS value. "
                    "Return no extra text."
                ),
            }
        ]

        payload = _post_chat(
            client,
            session_id=session_id,
            messages=workhorse_messages,
        )
        assert len(captured_payloads) >= 2, payload
        workhorse_upstream_payload = captured_payloads[-1]
        workhorse_upstream_text = _payload_text(workhorse_upstream_payload)
        assert (
            workhorse_upstream_payload.get("model") == WORKHORSE_MODEL
        ), workhorse_upstream_payload
        assert (
            "The proxy captured this thinker memo" in workhorse_upstream_text
        ), workhorse_upstream_payload
        assert ACTION_TOKEN in workhorse_upstream_text, workhorse_upstream_payload
        assert SESSION_FACT_ALPHA in workhorse_upstream_text, workhorse_upstream_payload
        assert SESSION_FACT_BETA in workhorse_upstream_text, workhorse_upstream_payload

        text = _response_text(payload)
        if (
            WORKHORSE_PASS_MARKER in text
            and ACTION_TOKEN in text
            and SESSION_FACT_ALPHA in text
            and SESSION_FACT_BETA in text
        ):
            workhorse_payload = payload

    if workhorse_payload is None:
        pytest.fail(
            "Workhorse did not act on injected thinker memo.\n"
            f"route={ROUTE}\n"
            f"response_text={text}\n"
            f"payload={payload}\n"
            f"upstream_payload={workhorse_upstream_payload}\n"
            f"sessions={await _session_debug(app)}"
        )
    workhorse_text = _response_text(workhorse_payload)
    assert WORKHORSE_PASS_MARKER in workhorse_text
    assert ACTION_TOKEN in workhorse_text
    assert SESSION_FACT_ALPHA in workhorse_text
    assert SESSION_FACT_BETA in workhorse_text
