"""Demo: send a real chat completion to gemini-oauth-plan:google/gemini-3-flash-preview.

Run from the proxy root:
    cd C:\Users\Mateusz\source\repos\llm-interactive-proxy
    set PYTHONPATH=C:\Users\Mateusz\source\repos\llm-interactive-proxy;C:\Users\Mateusz\source\repos\llm-interactive-proxy-oauth-connectors\src
    .\.venv\Scripts\python.exe dev\scripts\demo_gemini_oauth_plan.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# ── path setup ──────────────────────────────────────────────────────────
ROOT_PROXY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ROOT_OAUTH = os.path.join(ROOT_PROXY, "..", "llm-interactive-proxy-oauth-connectors", "src")
sys.path.insert(0, ROOT_PROXY)
sys.path.insert(0, ROOT_OAUTH)

import httpx

from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.core.config.app_config import load_config as load_app_config
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService

MODEL = "gemini-oauth-plan:google/gemini-3-flash-preview"
USER_PROMPT = (
    "Write a short Python function that computes the n-th Fibonacci number "
    "using memoization. Include type hints and a docstring. "
    "Keep it under 20 lines total."
)


async def main() -> None:
    # 1. Load config
    config_path = os.path.join(ROOT_PROXY, "config", "config.yaml")
    if os.path.exists(config_path):
        config = load_app_config(config_path=config_path)
        print(f"[*] Config loaded from {config_path}")
    else:
        print("[!] config.yaml not found.  Cannot proceed.")
        sys.exit(1)

    # 2. Instantiate dependencies
    async with httpx.AsyncClient(timeout=120) as client:
        translation = TranslationService()

        # 3. Create the concrete connector
        from llm_proxy_oauth_connectors.gemini_oauth_plan import (
            GeminiOAuthPlanConnector,
        )

        connector = GeminiOAuthPlanConnector(
            client=client,
            config=config,
            translation_service=translation,
            name="gemini-oauth-plan",
        )

        connector._enable_gemini_oauth_plan_backend_debugging_override = True  # type: ignore[assignment]

        # 4. Initialize
        print(f"\n[*] Initializing {MODEL} ...")
        await connector.initialize()
        print("[*] Initialized.  Checking credentials ...")

        cred_ok = await connector._validate_runtime_credentials()  # type: ignore[attr-defined]
        if not cred_ok:
            errs = connector._credential_validation_errors  # type: ignore[attr-defined]
            print(f"[!] Credentials invalid: {'; '.join(errs)}")
            sys.exit(1)
        print("[*] Credentials OK.")

        # 5. Build request
        request = ConnectorChatCompletionsRequest(
            request=CanonicalChatRequest(
                model=MODEL,
                messages=[ChatMessage(role="user", content=USER_PROMPT)],
                stream=True,
            ),
            processed_messages=[ChatMessage(role="user", content=USER_PROMPT)],
            effective_model="google/gemini-3-flash-preview",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=ConnectorRequestContext(
                request_id="demo-001",
                session_id="demo-session",
                client_host="127.0.0.1",
                extensions={},
            ),
            options={},
        )

        # 6. Send
        print(f"\n[*] Prompt: {USER_PROMPT!r}")
        print(f"\n[*] Sending request to {MODEL} ...")
        response = await connector.chat_completions(request)

        if not isinstance(response, StreamingResponseEnvelope):
            print(f"[FAIL] Expected StreamingResponseEnvelope, got {type(response).__name__}.")
            sys.exit(1)

        # Ensure stream is iterable
        if response.content is None:
            print("[FAIL] StreamingResponseEnvelope.content is None.  Streaming pipeline broke.")
            sys.exit(1)

        print(f"\n--- Response (streamed) ---\n")
        accumulated = ""
        finish_reason = None
        async for chunk in response.content:
            if chunk.metadata:
                finish_reason = chunk.metadata.get("finish_reason")
            text = _extract_text(chunk)
            if text:
                print(text, end="", flush=True)
                accumulated += text

        print(f"\n\n--- End of stream (finish_reason={finish_reason}) ---")
        print(f"\nTotal: {len(accumulated)} chars")

        if not accumulated:
            print("[FAIL] No text received from backend.")
            sys.exit(1)

        print("\n[*] Demo completed successfully.")


def _extract_text(chunk: ProcessedResponse) -> str:
    content = chunk.content
    if isinstance(content, dict):
        parts: list[str] = []
        choices = content.get("choices", [])
        if choices:
            for choice in choices:
                delta = choice.get("delta", {})
                t = delta.get("content", "") or delta.get("reasoning_content", "")
                if t:
                    parts.append(t)
        return "".join(parts)
    if isinstance(content, bytes):
        return content.decode(errors="replace")
    if isinstance(content, str):
        return content
    return ""


if __name__ == "__main__":
    asyncio.run(main())
