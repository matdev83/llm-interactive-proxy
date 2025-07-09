"""
Direct Gemini CLI connector that bypasses gemini-mcp-tool
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Dict, Any, Optional, AsyncGenerator, Union, TYPE_CHECKING, Tuple
import secrets

from .base import LLMBackend
from starlette.responses import StreamingResponse

if TYPE_CHECKING:
    from src.models import ChatCompletionRequest
    from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


class GeminiCliDirectConnector(LLMBackend):
    """Direct connector to Gemini CLI without MCP overhead"""

    def __init__(self):
        super().__init__()
        self.name = "gemini-cli-direct"
        self.available_models: list[str] = []
        self.is_functional = False
        self._cli_tested = False  # Track if we've tested CLI yet

    async def initialize(self) -> None:
        """Initialize backend - defer CLI testing until first use"""
        # Don't test CLI during initialization to avoid blocking server startup
        # Instead, set up default models and test CLI on first actual request
        logger.info("Gemini CLI Direct backend initialized (CLI test deferred)")
        self.available_models = [
            "gemini-2.5-flash",
            "gemini-1.5-pro",
        ]
        # Mark as functional by default - will be tested on first use
        self.is_functional = True

    async def _execute_gemini_cli_with_timeout(self, prompt: str, model: Optional[str] = None, timeout: int = 30) -> str:
        """Execute Gemini CLI with a specific timeout for initialization testing"""

        # Build command arguments
        args = ["gemini"]

        # Don't specify model - let Gemini CLI use its default
        # if model:
        #     args.extend(["-m", model])

        # Add prompt - use -p flag to pass prompt as argument
        args.extend(["-p", prompt])

        logger.info(f"Testing Gemini CLI with timeout {timeout}s: {args}")

        try:
            # Create subprocess with proper environment
            env = os.environ.copy()

            # On Windows, ensure npm global bin is in PATH
            if sys.platform == "win32":
                npm_global_bin = os.path.expanduser("~\\AppData\\Roaming\\npm")
                current_path = env.get("PATH", "")
                if npm_global_bin not in current_path:
                    env["PATH"] = f"{npm_global_bin};{current_path}"
                # Ensure PATHEXT includes .CMD for Windows batch files
                pathext = env.get("PATHEXT", "")
                if ".CMD" not in pathext.upper():
                    env["PATHEXT"] = f"{pathext};.CMD"

            # Execute command
            if sys.platform == "win32":
                # On Windows, use shell=True for .cmd files
                # Build command string with proper quoting
                cmd_parts = []
                for arg in args:
                    if " " in arg or '"' in arg:
                        # Escape quotes and wrap in quotes
                        escaped_arg = arg.replace('"', '\\"')
                        cmd_parts.append(f'"{escaped_arg}"')
                    else:
                        cmd_parts.append(arg)
                cmd_string = " ".join(cmd_parts)

                process = await asyncio.create_subprocess_shell(
                    cmd_string,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )
            else:
                # On Unix, use exec
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )

            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise Exception(f"Gemini CLI command timed out after {timeout} seconds")

            # Check return code
            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace').strip()
                raise Exception(f"Gemini CLI failed with exit code {process.returncode}: {error_msg}")

            # Return stdout
            result = stdout.decode('utf-8', errors='replace').strip()
            logger.info(f"Gemini CLI test completed successfully, output length: {len(result)}")
            return result

        except Exception as e:
            logger.error(f"Error testing Gemini CLI: {e}")
            raise

    def get_available_models(self) -> list[str]:
        """Return available Gemini models if functional"""
        return self.available_models if self.is_functional else []

    async def _execute_gemini_cli(self, prompt: str, model: Optional[str] = None, sandbox: bool = False) -> str:
        """Execute Gemini CLI command directly"""

        # Build command arguments
        args = ["gemini"]

        # Don't specify model - let Gemini CLI use its default
        # if model:
        #     args.extend(["-m", model])

        if sandbox:
            args.append("-s")

        # Add prompt - use -p flag to pass prompt as argument
        args.extend(["-p", prompt])

        logger.info(f"Executing Gemini CLI: {args}")
        logger.info(f"Raw command: {' '.join(args)}")

        try:
            # Create subprocess with proper environment
            env = os.environ.copy()

            # On Windows, ensure npm global bin is in PATH
            if sys.platform == "win32":
                npm_global_bin = os.path.expanduser("~\\AppData\\Roaming\\npm")
                current_path = env.get("PATH", "")
                if npm_global_bin not in current_path:
                    env["PATH"] = f"{npm_global_bin};{current_path}"
                # Ensure PATHEXT includes .CMD for Windows batch files
                pathext = env.get("PATHEXT", "")
                if ".CMD" not in pathext.upper():
                    env["PATHEXT"] = f"{pathext};.CMD"

            # Execute command
            if sys.platform == "win32":
                # On Windows, use shell=True for .cmd files
                # Build command string with proper quoting
                cmd_parts = []
                for arg in args:
                    if " " in arg or '"' in arg:
                        # Escape quotes and wrap in quotes
                        escaped_arg = arg.replace('"', '\\"')
                        cmd_parts.append(f'"{escaped_arg}"')
                    else:
                        cmd_parts.append(arg)
                cmd_string = " ".join(cmd_parts)
                logger.info(f"Final command string: {cmd_string}")

                process = await asyncio.create_subprocess_shell(
                    cmd_string,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )
            else:
                # On Unix, use exec
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )

            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=120  # 2 minutes timeout for regular operations
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise Exception("Gemini CLI command timed out after 2 minutes")

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

    async def chat_completions(
        self,
        request_data: "ChatCompletionRequest",
        processed_messages: list,
        effective_model: str,
        openrouter_api_base_url: Optional[str] = None,  # absorb unused param
        openrouter_headers_provider: object = None,  # absorb unused param
        key_name: Optional[str] = None,
        api_key: Optional[str] = None,
        project: Optional[str] = None,
        prompt_redactor: Optional["APIKeyRedactor"] = None,
        command_filter: Optional["ProxyCommandFilter"] = None,
        **kwargs
    ) -> Union[Tuple[Dict[str, Any], Dict[str, str]], StreamingResponse]:
        """Handle chat completions using direct Gemini CLI"""

        try:
            # Extract the last user message as the prompt
            user_messages = [msg for msg in processed_messages if msg.role == "user"]
            if not user_messages:
                raise ValueError("No user messages found")

            # Get the content from the last user message
            last_message = user_messages[-1]
            if isinstance(last_message.content, str):
                prompt = last_message.content
            elif isinstance(last_message.content, list):
                # Handle list of content parts (text + images)
                prompt = " ".join(
                    part.text for part in last_message.content
                    if hasattr(part, 'text')
                )
            else:
                prompt = str(last_message.content)

            if not prompt:
                raise ValueError("Empty prompt")

            # Apply emergency command filter if provided
            if command_filter:
                prompt = command_filter.filter_commands(prompt)

            # Apply API key redaction if provided
            if prompt_redactor:
                prompt = prompt_redactor.redact(prompt)

            # Check if sandbox mode is requested (could be a parameter)
            sandbox = kwargs.get("sandbox", False)

            # Execute Gemini CLI (let it use its default model)
            result = await self._execute_gemini_cli(prompt, model=None, sandbox=sandbox)

            # Create OpenAI-compatible response
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
                            "content": result
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt.split()),  # Rough estimate
                    "completion_tokens": len(result.split()),  # Rough estimate
                    "total_tokens": len(prompt.split()) + len(result.split())
                }
            }

            # Create dummy headers since CLI doesn't provide real headers
            dummy_headers = {
                "content-type": "application/json",
                "x-gemini-cli-direct": "true",
                "x-gemini-cli-version": "1.0.0"
            }

            if request_data.stream:
                return self._create_streaming_response(response)
            else:
                return response, dummy_headers

        except Exception as e:
            logger.error(f"Error in chat_completions: {e}")
            # Return error in OpenAI format
            return {
                "id": f"chatcmpl-geminicli-{secrets.token_hex(8)}",
                "object": "chat.completion",
                "created": int(asyncio.get_event_loop().time()),
                "model": effective_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Error: {str(e)}"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }

    async def _create_streaming_response(self, response: Dict[str, Any]) -> StreamingResponse:
        """Create streaming response from complete response"""

        async def stream_generator() -> AsyncGenerator[str, None]:
            # Split content into chunks for streaming
            content = response["choices"][0]["message"]["content"]
            words = content.split()

            # Send chunks
            for i, word in enumerate(words):
                chunk = {
                    "id": response["id"],
                    "object": "chat.completion.chunk",
                    "created": response["created"],
                    "model": response["model"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": word + " " if i < len(words) - 1 else word},
                            "finish_reason": None
                        }
                    ]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0.05)  # Small delay between chunks

            # Send final chunk
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
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            stream_generator(),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )
