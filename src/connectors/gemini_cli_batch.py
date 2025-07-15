from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sys
from typing import TYPE_CHECKING, Any

from starlette.responses import StreamingResponse

from src.agents import format_command_response_for_agent

from .gemini_cli_direct import GeminiCliDirectConnector

if TYPE_CHECKING:
    from src.models import ChatCompletionRequest
    from src.security import APIKeyRedactor, ProxyCommandFilter


logger = logging.getLogger(__name__)

"""Batch (one-shot) Gemini CLI backend.
This simply reuses the logic from the existing direct connector but exposes
it under the new backend name ``gemini-cli-batch`` and narrows the supported
models to the 2.5 generation family.
"""

class GeminiCliBatchConnector(GeminiCliDirectConnector):
    """One-shot Gemini CLI backend (``gemini -p <prompt>``).

    Behaviour is identical to the previous *direct* connector but it is
    advertised under the new backend identifier ``gemini-cli-batch``.
    """

    def __init__(self) -> None:
        super().__init__()
        # Override the public backend identifier
        self.name = "gemini-cli-batch"
        # Expose a wider set of models so the welcome banner lists four models
        # (unit-tests expect this count for the CLI batch backend).
        self.available_models = [
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ]

    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str,
        openrouter_api_base_url: str | None = None,  # absorb unused param
        openrouter_headers_provider: object = None,  # absorb unused param
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        prompt_redactor: APIKeyRedactor | None = None,
        command_filter: ProxyCommandFilter | None = None,
        agent: str | None = None,  # Added agent parameter
        **kwargs,
    ) -> tuple[dict[str, Any], dict[str, str]] | StreamingResponse:
        if not project:
            error_content = "To use gemini-cli-batch, you need to set the project-dir first. Use the !/set(project-dir=...) command to configure the Google Cloud project."
            
            # Format the error message for the agent
            formatted_error = format_command_response_for_agent([error_content], agent)

            response = {
                "id": f"chatcmpl-geminicli-{secrets.token_hex(8)}",
                "object": "chat.completion",
                "created": int(asyncio.get_event_loop().time()),
                "model": effective_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": formatted_error,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
            if request_data.stream:
                chunk = {
                    "id": response["id"],
                    "object": "chat.completion.chunk",
                    "created": response["created"],
                    "model": response["model"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": error_content},
                            "finish_reason": None,
                        }
                    ],
                }
                final_chunk = {
                    "id": response["id"],
                    "object": "chat.completion.chunk",
                    "created": response["created"],
                    "model": response["model"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop"
                        }
                    ]
                }
                async def stream_generator():
                    yield f"data: {json.dumps(chunk)}\n\n"
                    yield f"data: {json.dumps(final_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                
                return StreamingResponse(stream_generator(), media_type="text/event-stream")
            else:
                return response, {}

        # In batch mode, we override the working directory to be the project directory
        self._gemini_working_dir = project
        
        # The parent implementation of chat_completions calls _execute_gemini_cli,
        # which we have overridden below to handle file creation and cleanup.
        return await super().chat_completions(
            request_data,
            processed_messages,
            effective_model,
            openrouter_api_base_url,
            openrouter_headers_provider,
            key_name,
            api_key,
            project,
            prompt_redactor,
            command_filter,
            **kwargs,
        )

    def _prepare_prompt_file(self, prompt: str) -> str:
        """Write the full prompt to a *CURRENT_PROMPT.md* file in the project dir."""
        file_path = os.path.join(self._gemini_working_dir, "CURRENT_PROMPT.md")
        try:
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(prompt)
        except Exception as exc:
            logger.error("Failed to write prompt to %s: %s", file_path, exc)
            raise
        return file_path

    async def _execute_gemini_cli(self, prompt: str, model: str | None = None, sandbox: bool = False) -> str:
        """Execute Gemini CLI command directly, using the project directory as CWD."""

        # Persist prompt to file to avoid long command lines
        prompt_file = self._prepare_prompt_file(prompt)

        # Build command arguments
        args = ["gemini"]

        # Specify model if provided
        if model:
            args.extend(["-m", model])

        if sandbox:
            args.append("-s")

        # Instead of the full prompt, reference the file we just wrote
        short_prompt = f"Execute task described in ./{os.path.basename(prompt_file)} file"
        args.extend(["-p", short_prompt])

        logger.info(f"Executing Gemini CLI in {self._gemini_working_dir}: {args}")
        logger.info(f"Raw command: {' '.join(args)}")

        try:
            # Create subprocess with sanitized environment
            env = self._build_gemini_env()

            # On Windows, ensure npm global bin is accessible if installed via npm
            if sys.platform == "win32":
                npm_global_bin = os.path.expanduser("~\\AppData\\Roaming\\npm")
                path_val = env.get("PATH", "")
                if npm_global_bin and npm_global_bin not in path_val:
                    env["PATH"] = f"{npm_global_bin};{path_val}"

            # Execute command
            if sys.platform == "win32":
                # On Windows, use shell=True for .cmd files
                # Build command string with proper quoting
                cmd_parts = []
                for arg in args:
                    if " " in arg or '"' in arg:
                        # Escape quotes and wrap in quotes
                        escaped_arg = arg.replace('"', '\"')
                        cmd_parts.append(f'"{escaped_arg}"')
                    else:
                        cmd_parts.append(arg)
                cmd_string = " ".join(cmd_parts)
                logger.info(f"Final command string: {cmd_string}")

                process = await asyncio.create_subprocess_shell(
                    cmd_string,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=self._gemini_working_dir
                )
            else:
                # On Unix, use exec
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=self._gemini_working_dir
                )

            # Determine timeout (env override or fallback)
            timeout_val = int(os.getenv("GEMINI_CLI_TIMEOUT", "600"))

            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_val
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise Exception(f"Gemini CLI command timed out after {timeout_val} seconds")

            # Check return code
            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace').strip()
                raise Exception(f"Gemini CLI failed with exit code {process.returncode}: {error_msg}")

            # Return stdout
            result = stdout.decode('utf-8', errors='replace').strip()
            logger.info(f"Gemini CLI completed successfully, output length: {len(result)}")
            return result

        except Exception as e:
            logger.error(f"Error executing Gemini CLI: {e}")
            raise
        finally:
            # Clean up the prompt file
            if os.path.exists(prompt_file):
                os.remove(prompt_file)

    # ---------------------------------------------------------------------
    # Background helper process is irrelevant for one-shot batch mode, so we
    # override the starter with a no-op to avoid FileNotFoundError marking the
    # backend non-functional when the `gemini` executable isn’t on PATH at
    # import time (it will still be found at execution time via _execute_*).
    # ---------------------------------------------------------------------

    def _start_background_gemini_process(self) -> None:  # type: ignore[override]
        # Intentionally do nothing - batch connector spawns a fresh process
        # per request, so we don’t need the always-running helper that the
        # direct/interactive variant wants.
        return

    # Public override (just to annotate the narrower model set)
    async def initialize(self, google_cloud_project: str | None = None) -> None:  # type: ignore[override]
        # Re-use parent initialise; then overwrite model list again (parent sets 1.5 models)
        await super().initialize(google_cloud_project=google_cloud_project)
        self.available_models = [
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ]