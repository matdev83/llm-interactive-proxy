from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import subprocess
import sys
from asyncio.subprocess import Process
from typing import TYPE_CHECKING, Any, AsyncGenerator

from starlette.responses import StreamingResponse

from .base import LLMBackend
from .gemini_cli_batch import GeminiCliBatchConnector  # for helpers

if TYPE_CHECKING:
    from src.models import ChatCompletionRequest
    # API key redaction and command filtering are now handled by middleware
# from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)

"""Interactive (long-lived) Gemini CLI backend.

This backend starts a single `gemini` process in interactive mode (no `-p` flag)
and keeps it alive for the lifetime of the proxy. Each prompt is written to
stdin and the textual response is read back from stdout.

NOTE: the current implementation makes a *best-effort* attempt to detect the end
of the model’s response by waiting for the next CLI prompt line that starts
with "> ". If the upstream CLI changes its prompt format this detector may
need adjustments.
"""

_PROMPT_RE = re.compile(br"^> ")  # bytes pattern for prompt line


class GeminiCliInteractiveConnector(LLMBackend):
    """Long-running interactive Gemini CLI backend."""

    def __init__(self):
        super().__init__()
        self.name = "gemini-cli-interactive"
        self.available_models: list[str] = [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ]
        self.is_functional: bool = False

        # Re-use env / working-dir helpers from the batch connector
        self._helper = GeminiCliBatchConnector()
        self._process: Process | None = None

    # ---------------------------------------------------------------------
    async def initialize(self, google_cloud_project: str | None = None) -> None:
        """Spawn the interactive `gemini` process once."""
        self._helper.google_cloud_project = google_cloud_project
        env = self._helper._build_gemini_env()
        cwd = self._helper._gemini_working_dir

        try:
            if sys.platform == "win32":
                # On Windows use shell=True so that gemini.cmd on PATH is resolved via PATHEXT
                self._process = await asyncio.create_subprocess_shell(
                    "gemini",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    env=env,
                    cwd=cwd,
                )
            else:
                # POSIX – exec directly
                self._process = await asyncio.create_subprocess_exec(
                    "gemini",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    env=env,
                    cwd=cwd,
                )
            self.is_functional = True
            logger.info(
                "Started interactive Gemini CLI backend (PID %s) in %s",
                self._process.pid,
                cwd,
            )
        except FileNotFoundError:
            logger.warning("Gemini CLI executable not found - interactive backend disabled")
            self.is_functional = False
        except Exception as exc:
            logger.warning("Failed to spawn interactive Gemini CLI: %s", exc)
            self.is_functional = False

    # ------------------------------------------------------------------
    def get_available_models(self) -> list[str]:
        return self.available_models if self.is_functional else []

    # ------------------------------------------------------------------
    async def _send_prompt(self, prompt: str, model: str) -> str:
        if not self._process or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("Interactive Gemini CLI process is not running")

        # Send prompt (model switch handled via command prefix)
        cmd = prompt.strip()
        if model:
            cmd = f"/model {model}\n{cmd}"
        # Write and flush
        self._process.stdin.write(cmd.encode("utf-8") + b"\n")
        await self._process.stdin.drain()

        # Read until next prompt line
        response_chunks = []
        while True:
            line = await self._process.stdout.readline()
            if not line:
                break  # EOF - process exited
            if _PROMPT_RE.match(line):
                break  # reached CLI prompt again - end of response
            response_chunks.append(line.decode("utf-8", "replace"))
        return "".join(response_chunks).strip()

    # ------------------------------------------------------------------
    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str,
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: object = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        **kwargs,
    ) -> tuple[dict[str, Any], dict[str, str]] | StreamingResponse:
        """Send a single prompt through the interactive process."""
        if not self.is_functional:
            raise RuntimeError("Interactive Gemini backend is not functional")

        # Extract last user prompt
        user_content = ""
        for m in reversed(processed_messages):
            if m.role == "user":
                user_content = m.content if isinstance(m.content, str) else str(m.content)
                break
        if not user_content:
            raise ValueError("No user message provided")

        # Prompt content is already processed by middleware
        # Apply filters / redaction

        # Send to CLI & get result
        # Normalize OpenRouter-style names like 'google/gemini-2.5-flash'
        normalized_model = effective_model
        if "/" in normalized_model:
            logger.debug("Detected provider prefix in model name '%s' for CLI. Using last segment only.", normalized_model)
            normalized_model = normalized_model.rsplit("/", 1)[-1]

        result = await self._send_prompt(user_content, normalized_model)

        # Build OpenAI-compatible response (non-streaming only)
        response = {
            "id": "chatcmpl-geminicli-int",
            "object": "chat.completion",
            "created": int(asyncio.get_event_loop().time()),
            "model": effective_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(user_content.split()),
                "completion_tokens": len(result.split()),
                "total_tokens": len(user_content.split()) + len(result.split()),
            },
        }
        headers = {
            "content-type": "application/json",
            "x-gemini-cli": "interactive",
        }
        if request_data.stream:
            # Very simple streaming: word-by-word
            async def generator() -> AsyncGenerator[str, None]:
                for w in result.split():
                    yield w + " "
            return StreamingResponse(generator(), media_type="text/plain")
        return response, headers

    # ------------------------------------------------------------------
    def __del__(self) -> None:
        if self._process and self._process.returncode is None:
            with contextlib.suppress(Exception):
                self._process.terminate()

    # ------------------------------------------------------------------
    async def shutdown(self) -> None:
        """Terminate the interactive subprocess gracefully (used by FastAPI lifespan)."""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
                # Explicitly close pipes to avoid ResourceWarnings on Windows
                if self._process.stdout:
                    self._process.stdout.close()
                if self._process.stderr:
                    self._process.stderr.close()
                if self._process.stdin:
                    self._process.stdin.close()
                logger.info("Interactive Gemini CLI backend (PID %s) terminated", self._process.pid)
            except Exception as exc:
                logger.debug("Failed to terminate interactive Gemini CLI backend: %s", exc)
            finally:
                self._process = None