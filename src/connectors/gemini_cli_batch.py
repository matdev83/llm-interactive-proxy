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
    # API key redaction and command filtering are now handled by middleware
    # from src.security import APIKeyRedactor, ProxyCommandFilter


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
        # Batch backend only supports the *2.5* generation family.  Keep the
        # public list limited to those two models so both the /models endpoint
        # and the interactive banner report the correct capability set.
        self.available_models = [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ]

        # Fast lookup set for validation
        self._allowed_models = set(self.available_models)

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
        agent: str | None = None,  # Added agent parameter
        **kwargs,
    ) -> tuple[dict[str, Any], dict[str, str]] | StreamingResponse:
        if not project:
            error_content = "To use gemini-cli-batch, you need to set the project-dir first. Use the !/set(project-dir=...) command to configure the Google Cloud project."
            
            # Format the error message for the agent
            formatted_error = format_command_response_for_agent([error_content], agent)
            
            return {
                "id": "error",
                "object": "chat.completion",
                "created": 0,
                "model": effective_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": formatted_error,
                        },
                        "finish_reason": "error",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "error": error_content,
            }

        # Validate model is in the supported set
        if effective_model not in self._allowed_models:
            # Map common aliases to the official 2.5 names
            model_aliases = {
                "gemini-2.5-pro-latest": "gemini-2.5-pro",
                "gemini-2.5-flash-latest": "gemini-2.5-flash",
                "gemini-pro-2.5": "gemini-2.5-pro",
                "gemini-flash-2.5": "gemini-2.5-flash",
            }
            effective_model = model_aliases.get(effective_model, effective_model)

        if effective_model not in self._allowed_models:
            raise ValueError(
                f"Model '{effective_model}' is not supported by the batch backend. "
                f"Supported models: {', '.join(self.available_models)}"
            )

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
            args.extend(["--model", model])

        # Add the prompt file as input
        args.extend(["-f", prompt_file])

        # Execute the command
        try:
            logger.debug("Executing Gemini CLI: %s", " ".join(args))
            
            # Create a unique output file for this execution to avoid conflicts
            output_file = os.path.join(
                self._gemini_working_dir, 
                f"gemini_output_{secrets.token_hex(8)}.md"
            )
            
            # Redirect output to file
            args.extend([">", output_file])
            
            # Join command and execute via shell
            cmd = " ".join(args)
            process = await asyncio.create_subprocess_shell(
                cmd,
                cwd=self._gemini_working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
            
            stdout, stderr = await process.communicate()
            
            # Read the output file
            try:
                with open(output_file, "r", encoding="utf-8") as f:
                    result = f.read()
            except FileNotFoundError:
                # If output file doesn't exist, use stdout
                result = stdout.decode("utf-8") if stdout else ""
            
            # Clean up temporary files
            try:
                os.remove(prompt_file)
                if os.path.exists(output_file):
                    os.remove(output_file)
            except Exception as cleanup_exc:
                logger.warning("Failed to clean up temporary files: %s", cleanup_exc)
            
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8") if stderr else "Unknown error"
                logger.error("Gemini CLI failed with code %d: %s", process.returncode, error_msg)
                raise RuntimeError(f"Gemini CLI failed: {error_msg}")
            
            return result
            
        except Exception as exc:
            logger.error("Failed to execute Gemini CLI: %s", exc, exc_info=True)
            raise