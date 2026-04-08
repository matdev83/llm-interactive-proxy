"""Launcher for the gemini-oauth-plan demo.

Sets up sys.path for both repos and executes the demo inline.

Usage (from anywhere):
    .\.venv\Scripts\python.exe dev\scripts\run_demo_gemini_oauth.py
"""
from __future__ import annotations

import asyncio
import os
import sys

LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_PROXY = os.path.normpath(os.path.join(LAUNCHER_DIR, "..", ".."))
ROOT_OAUTH_SRC = os.path.normpath(os.path.join(ROOT_PROXY, "..", "llm-interactive-proxy-oauth-connectors", "src"))

sys.path.insert(0, ROOT_PROXY)
sys.path.insert(0, ROOT_OAUTH_SRC)


# ─── imports (now resolvable) ───────────────────────────────────────────
import httpx

# Now import the connector from the sibling repo
from llm_proxy_oauth_connectors.gemini_oauth_plan import (
    GeminiOAuthPlanConnector,
)
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
    if not os.path.exists(config_path):
        print(f"[!] {config_path} not found.")
        sys.exit(1)
    config = load_app_config(config_path=config_path)
    print("[*] Config loaded.")

    # 2. Dependencies
    async with httpx.AsyncClient(timeout=120) as client:
        translation = TranslationService()

        # 3. Connector
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

        if response.content is None:
            print("[FAIL] StreamingResponseEnvelope.content is None.")
            sys.exit(1)

        print("\n--- Response ---\n")
        accumulated = ""
        async for chunk in response.content:
            text = _extract_text(chunk)
            if text:
                print(text, end="", flush=True)
                accumulated += text

        print("\n\n--- End ---")
        print(f"\nTotal: {len(accumulated)} chars")

        if not accumulated:
            print("[FAIL] No text from backend.")
            sys.exit(1)

        print("\n[*] Demo completed successfully.")


def _extract_text(chunk: ProcessedResponse) -> str:
    content = chunk.content
    if isinstance(content, dict):
        parts: list[str] = []
        for choice in content.get("choices", []):
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
