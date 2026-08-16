"""Reproduction and verification script for AGY subagent concurrency.

Simulates a parent agent turn spawning/invoking a subagent concurrently
in the same workspace directory using the ACP connector.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.connectors.acp_core.types import ACPNotification
from src.connectors.agy_cli_acp import AgyCliAcpConnector
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def make_request(
    workspace_path: Path,
    session_id: str,
    prompt: str = "Test prompt",
    model: str = "google/gemini-3.7-flash",
) -> ConnectorChatCompletionsRequest:
    request = CanonicalChatRequest(
        model=model,
        stream=True,
        messages=[ChatMessage(role="user", content=prompt)],
    )
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=[ChatMessage(role="user", content=prompt)],
        effective_model=model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={"workspace_path": str(workspace_path), "session_id": session_id},
    )


async def main() -> None:
    logger.info("Starting AGY subagent concurrency reproduction test...")

    with tempfile.TemporaryDirectory() as tmpdir:
        shared_workspace = Path(tmpdir) / "shared_project"
        shared_workspace.mkdir()

        app_config = AppConfig()
        translation_service = TranslationService()

        # Instantiate connector
        import httpx

        async with httpx.AsyncClient() as client:
            connector = AgyCliAcpConnector(client, app_config, translation_service)
            connector._default_project_dir = shared_workspace

            parent_req = make_request(
                shared_workspace,
                session_id="llm-b2bua-b-parent-356",
                prompt="Parent agent executing tool...",
            )
            subagent_req = make_request(
                shared_workspace,
                session_id="llm-b2bua-b-subagent-366",
                prompt="Subagent performing delegated task...",
            )

            # 1. Acquire runtime for parent
            parent_runtime = await connector._acquire_runtime(parent_req)
            # 2. Acquire runtime for subagent (same workspace, different session)
            subagent_runtime = await connector._acquire_runtime(subagent_req)

            logger.info("Parent runtime key: %s (session=%s)", parent_runtime.project_dir, parent_runtime.client_session_id)
            logger.info("Subagent runtime key: %s (session=%s)", subagent_runtime.project_dir, subagent_runtime.client_session_id)

            assert parent_runtime is not subagent_runtime, "Runtimes should be isolated per session"
            assert parent_runtime.project_dir == subagent_runtime.project_dir, "Workspaces must match"

            # 3. Simulate parent acquiring request lock
            assert parent_runtime.request_lock is not None
            await parent_runtime.request_lock.acquire()
            logger.info("Parent acquired request lock for turn 356.")

            # 4. In the fixed architecture, subagent has its own runtime & request lock
            assert subagent_runtime.request_lock is not None
            try:
                await asyncio.wait_for(subagent_runtime.request_lock.acquire(), timeout=2.0)
                logger.info("Subagent successfully acquired its own request lock immediately without blocking on parent!")
            except asyncio.TimeoutError:
                logger.error("DEADLOCK DETECTED: Subagent was blocked by parent request lock!")
                sys.exit(1)
            finally:
                if subagent_runtime.request_lock.locked():
                    subagent_runtime.request_lock.release()
                if parent_runtime.request_lock.locked():
                    parent_runtime.request_lock.release()

            # 5. Clean up all runtimes
            await connector._kill_all_runtimes()
            logger.info("All runtimes cleaned up successfully.")

    logger.info("SUCCESS: Subagent concurrency verified with zero deadlocks.")


if __name__ == "__main__":
    asyncio.run(main())
