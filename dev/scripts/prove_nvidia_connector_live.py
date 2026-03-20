#!/usr/bin/env python3
"""Prove NvidiaConnector in-process: ``list_models()`` + non-streaming ``chat_completions``.

Uses the same HTTP surface as other OpenAI-compatible connectors (``GET .../v1/models``,
``POST .../v1/chat/completions``) via ``NvidiaConnector.list_models`` and the canonical
chat path.

Environment
-------------
- ``NVIDIA_API_KEY`` (required for chat; listing may work without it on the hosted catalog).
- ``NV_PROVE_MODEL`` (optional): upstream model id to call.
  If unset, the script prefers ``stepfun-ai/step-3.5-flash`` (see `NVIDIA Build
  <https://build.nvidia.com/stepfun-ai/step-3.5-flash>`_), then other small models, then any
  catalog id containing ``free``, then the first listed id.
- ``NV_PROVE_READ_TIMEOUT`` (optional): httpx read timeout in seconds for chat (default ``120``).
  Hosted inference can be slow; raise this if you hit ``ReadTimeout``.
- ``NV_PROVE_CONNECT_TIMEOUT`` (optional): connect timeout in seconds (default ``30``).

Exit codes: 0 success, 2 missing key, 3 list failure, 4 no model to try, 5 chat failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.nvidia import NvidiaConnector, _normalize_nvidia_api_key
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.models_listing import ModelsListingResponse
from src.core.services.translation_service import TranslationService

# Default when ``NV_PROVE_MODEL`` is unset (fast on hosted NIM per NVIDIA Build).
_DEFAULT_DEMO_UPSTREAM_MODEL = "stepfun-ai/step-3.5-flash"


def _pick_model_id(listing: ModelsListingResponse, explicit: str | None) -> str | None:
    if explicit and explicit.strip():
        want = explicit.strip()
        for m in listing.data:
            if m.id == want:
                return m.id
        # Allow calling a model not returned by this listing (user override).
        return want

    ids = [m.id for m in listing.data]
    if _DEFAULT_DEMO_UPSTREAM_MODEL in ids:
        return _DEFAULT_DEMO_UPSTREAM_MODEL
    for mid in ids:
        if "free" in mid.lower():
            return mid
    # Prefer other small / fast instruct endpoints if the default id is absent.
    preference_substrings = (
        _DEFAULT_DEMO_UPSTREAM_MODEL,
        "step-3.5-flash",
        "llama-3.2-1b",
        "llama-3.2-3b",
        "gemma-2-2b",
        "gemma-3-1b",
        "nemotron-nano",
        "mistral-7b-instruct",
        "llama-3.1-8b-instruct",
    )
    lower_ids = [(i, i.lower()) for i in ids]
    for needle in preference_substrings:
        for orig, low in lower_ids:
            if needle in low:
                return orig
    return ids[0] if ids else None


async def _run() -> int:
    raw_key = os.environ.get("NVIDIA_API_KEY", "")
    if not raw_key.strip():
        print(
            "ERROR: Set NVIDIA_API_KEY to run chat completion proof.",
            file=sys.stderr,
        )
        return 2
    os.environ["NVIDIA_API_KEY"] = _normalize_nvidia_api_key(raw_key)

    def _fenv(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    read_timeout = _fenv("NV_PROVE_READ_TIMEOUT", 120.0)
    connect_timeout = _fenv("NV_PROVE_CONNECT_TIMEOUT", 30.0)
    timeout = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=read_timeout,
        pool=30.0,
    )

    async with httpx.AsyncClient(timeout=timeout) as http:
        connector = NvidiaConnector(
            http, AppConfig(), translation_service=TranslationService()
        )
        await connector.initialize()
        # Avoid a duplicate GET /models before chat (OpenAIConnector first-use health check);
        # the user already waited for list_models above, and the extra call looked like a hang.
        connector.disable_health_check()

        print("=== NvidiaConnector.list_models() ===", flush=True)
        try:
            listing = await connector.list_models()
        except httpx.HTTPStatusError as e:
            print(e.response.text[:2000], file=sys.stderr)
            print(f"list_models failed: HTTP {e.response.status_code}", file=sys.stderr)
            return 3
        except httpx.HTTPError as e:
            print(str(e), file=sys.stderr)
            return 3

        ids = [m.id for m in listing.data]
        print(f"object={listing.object!r} count={len(ids)}", flush=True)
        preview_n = min(40, len(ids))
        if preview_n:
            print(f"First {preview_n} model ids from enumeration:", flush=True)
            print(json.dumps(ids[:preview_n], indent=2), flush=True)
        if len(ids) > preview_n:
            print(f"... and {len(ids) - preview_n} more.", flush=True)

        in_memory = connector.get_available_models()
        print(
            f"get_available_models() count (post-init cache): {len(in_memory)}",
            flush=True,
        )
        if in_memory:
            print("get_available_models() preview (up to 15):", flush=True)
            print(json.dumps(in_memory[:15], indent=2), flush=True)

        explicit = os.environ.get("NV_PROVE_MODEL", "").strip() or None
        model_id = _pick_model_id(listing, explicit)
        if not model_id:
            print("No model id available to call.", file=sys.stderr)
            return 4

        chat_url = f"{connector.api_base_url.rstrip('/')}/chat/completions"
        print(f"\n=== chat_completions (non-stream) model={model_id!r} ===", flush=True)
        print(
            f"POST {chat_url}\n"
            f"(read_timeout={read_timeout}s, connect_timeout={connect_timeout}s) — "
            "waiting for upstream response...",
            flush=True,
        )
        user_text = (
            "Reply with exactly one short word: OK. No punctuation or other words."
        )
        domain = CanonicalChatRequest(
            model=model_id,
            messages=[ChatMessage(role="user", content=user_text)],
            stream=False,
            max_completion_tokens=32,
        )
        req = ConnectorChatCompletionsRequest(
            request=domain,
            processed_messages=list(domain.messages),
            effective_model=model_id,
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )
        try:
            env = await connector.chat_completions(req)
        except BackendError as e:
            if (e.details or {}).get("reason") == "read_timeout":
                print(e.message, file=sys.stderr)
                print(
                    f"Configured read_timeout was {read_timeout}s. "
                    "Set NV_PROVE_READ_TIMEOUT (e.g. 300) for slow or cold-started models, "
                    "or use streaming from the proxy for long generations.",
                    file=sys.stderr,
                )
                return 5
            print(f"chat_completions raised: {e!r}", file=sys.stderr)
            return 5
        except httpx.ReadTimeout:
            print(
                f"ReadTimeout after {read_timeout}s. "
                "Increase NV_PROVE_READ_TIMEOUT (e.g. 300) if the model is slow or cold-starting.",
                file=sys.stderr,
            )
            return 5
        except httpx.TimeoutException as e:
            print(f"HTTP timeout: {e!r}", file=sys.stderr)
            return 5
        except Exception as e:
            print(f"chat_completions raised: {e!r}", file=sys.stderr)
            return 5

        from src.core.domain.responses import ResponseEnvelope

        if not isinstance(env, ResponseEnvelope):
            print(f"Unexpected return type: {type(env)}", file=sys.stderr)
            return 5
        content = env.content
        if not isinstance(content, dict):
            print(f"Unexpected content type: {type(content)}", file=sys.stderr)
            return 5
        choices = content.get("choices")
        if not isinstance(choices, list) or not choices:
            print(json.dumps(content, indent=2)[:3000], file=sys.stderr)
            return 5
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        text = (msg or {}).get("content") if isinstance(msg, dict) else None
        if not isinstance(text, str) or not text.strip():
            print(json.dumps(content, indent=2)[:3000], file=sys.stderr)
            return 5

        print("--- assistant message ---", flush=True)
        print(text.strip(), flush=True)
        print("--- raw usage (if any) ---", flush=True)
        print(json.dumps(content.get("usage"), indent=2), flush=True)
        return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
