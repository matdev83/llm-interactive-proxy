"""Run a live Gemini CLI ACP demo against the current repository.

Usage:
    ./.venv/Scripts/python.exe dev/scripts/run_demo_gemini_cli_acp.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_base.command_resolution import (
    resolve_gemini_cli_executable,
)
from src.connectors.gemini_cli_acp import GeminiCliAcpConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService

MODEL = "google/gemini-3-flash-preview"
PROMPT = (
    "Use the workspace tools to inspect this repository and find the file that defines "
    "ConnectorChatCompletionsRequest. Reply with:\n"
    "1. the relative file path,\n"
    "2. the names of three fields declared on ConnectorChatCompletionsRequest,\n"
    "3. one short sentence proving you actually inspected the file contents.\n"
    "Do not guess."
)


def _resolve_gemini_cli_executable() -> str:
    resolved = resolve_gemini_cli_executable()
    if resolved:
        return resolved
    raise FileNotFoundError("gemini CLI executable not found on PATH")


async def main() -> int:
    print(f"[*] Workspace: {ROOT}")
    print(f"[*] Model: {MODEL}")
    print(f"[*] Prompt: {PROMPT}")
    gemini_executable = _resolve_gemini_cli_executable()
    print(f"[*] Gemini CLI: {gemini_executable}")

    async with httpx.AsyncClient(timeout=180) as client:
        connector = GeminiCliAcpConnector(
            client=client,
            config=AppConfig(),
            translation_service=TranslationService(),
        )

        await connector.initialize(
            workspace_path=str(ROOT),
            gemini_cli_executable=gemini_executable,
            model="gemini-3-flash-preview",
            auto_accept=True,
            process_timeout=180,
        )

        request = ConnectorChatCompletionsRequest(
            request=CanonicalChatRequest(
                model=MODEL,
                messages=[ChatMessage(role="user", content=PROMPT)],
                stream=False,
            ),
            processed_messages=[ChatMessage(role="user", content=PROMPT)],
            effective_model=MODEL,
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={"project_dir": str(ROOT)},
        )

        try:
            response = await connector.chat_completions(request)
        finally:
            await connector.shutdown()

    if not isinstance(response, ResponseEnvelope):
        print(f"[FAIL] Expected ResponseEnvelope, got {type(response).__name__}")
        return 1

    if not isinstance(response.content, dict):
        print("[FAIL] Response content is not a dict payload.")
        return 1

    content = response.content["choices"][0]["message"]["content"]
    print("\n--- Response ---\n")
    print(content)
    print("\n--- End ---")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
