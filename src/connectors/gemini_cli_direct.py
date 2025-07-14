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
import tempfile

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
        self.google_cloud_project: Optional[str] = None

        # Background process handle and working directory
        self._gemini_process: Optional[subprocess.Popen] = None
        self._gemini_working_dir: str = self._create_gemini_working_dir()

    def __del__(self):
        """Ensure background Gemini process is terminated when connector is garbage collected."""
        try:
            if self._gemini_process and self._gemini_process.poll() is None:
                self._gemini_process.terminate()
                self._gemini_process.wait(timeout=5)
                logger.info("Background Gemini CLI process terminated during connector cleanup")
        except Exception:
            # Ignore cleanup errors – process may have already exited
            pass

    # --- Helper methods -------------------------------------------------

    @staticmethod
    def _create_gemini_working_dir() -> str:
        """Return path to the .gemini directory inside the system temp folder, creating it if necessary."""
        temp_dir = tempfile.gettempdir()
        gemini_dir = os.path.join(temp_dir, ".gemini")
        try:
            os.makedirs(gemini_dir, exist_ok=True)
        except Exception as exc:
            # If we fail to create directory, log and fallback to temp_dir
            logger.warning(f"Unable to create .gemini working dir at {gemini_dir}: {exc}. Falling back to temp dir.")
            gemini_dir = temp_dir
        return gemini_dir

    def _build_gemini_env(self) -> Dict[str, str]:
        """Build a sanitized environment for Gemini process without inheriting proxy-sensitive vars."""
        env: Dict[str, str] = {}

        # Minimal PATH so that subprocess can locate executables
        if "PATH" in os.environ:
            env["PATH"] = os.environ["PATH"]

        # Preserve user home directory variables for CLI config resolution
        if "HOME" in os.environ:
            env["HOME"] = os.environ["HOME"]
        if "USERPROFILE" in os.environ:
            env["USERPROFILE"] = os.environ["USERPROFILE"]

        # Preserve common proxy settings (uppercase and lowercase variants)
        for proxy_var in [
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
        ]:
            if proxy_var in os.environ:
                env[proxy_var] = os.environ[proxy_var]

        # Preserve temp directories (used by Node and Gemini CLI for downloads/logs)
        for tmp_var in ["TMP", "TEMP"]:
            if tmp_var in os.environ:
                env[tmp_var] = os.environ[tmp_var]

        # Preserve Windows-specific AppData paths – some Node tools rely on them for caching / auth
        for win_var in ["APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "SYSTEMROOT", "WINDIR"]:
            if win_var in os.environ:
                env[win_var] = os.environ[win_var]

        # Pass through a generic Google API key if present, **but intentionally NOT any GEMINI_API_KEY
        # variables** – the CLI authenticates via cached OAuth linked to the project ID.
        if "GOOGLE_API_KEY" in os.environ:
            env["GOOGLE_API_KEY"] = os.environ["GOOGLE_API_KEY"]

        # Windows-specific PATHEXT handling so
        if sys.platform == "win32" and "PATHEXT" in os.environ:
            env["PATHEXT"] = os.environ["PATHEXT"]

        # Propagate explicit Google Cloud project if supplied via config/initialize
        if self.google_cloud_project:
            env["GOOGLE_CLOUD_PROJECT"] = self.google_cloud_project

        return env

    def _start_background_gemini_process(self) -> None:
        """Spawn the Gemini CLI process in the background if not already running."""
        if self._gemini_process and self._gemini_process.poll() is None:
            # Already running
            return

        cmd = ["gemini"]

        env = self._build_gemini_env()

        # Ensure npm global bin is on PATH so the 'gemini' executable can be resolved
        if sys.platform == "win32":
            npm_global_bin = os.path.expanduser("~\\AppData\\Roaming\\npm")
            current_path = env.get("PATH", "")
            if npm_global_bin and npm_global_bin not in current_path:
                env["PATH"] = f"{npm_global_bin};{current_path}"

        # Spawn detached process so it is not terminated when proxy exits unless we explicitly terminate
        kwargs: Dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": self._gemini_working_dir,
            "env": env,
        }

        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            kwargs["creationflags"] = creationflags
        else:
            kwargs["start_new_session"] = True

        try:
            self._gemini_process = subprocess.Popen(cmd, **kwargs)
            logger.info(
                f"Spawned Gemini CLI background process with PID {self._gemini_process.pid} in {self._gemini_working_dir}"
            )
        except FileNotFoundError:
            logger.error("Gemini CLI executable not found. Background process not started.")
            self.is_functional = False
        except Exception as exc:
            logger.error(f"Failed to spawn Gemini CLI background process: {exc}")
            self.is_functional = False

    async def initialize(self, google_cloud_project: Optional[str] = None) -> None:
        """Initialize backend - defer CLI testing until first use"""
        # Don't test CLI during initialization to avoid blocking server startup
        # Instead, set up default models and test CLI on first actual request
        logger.info("Gemini CLI Direct backend initialized (CLI test deferred)")
        self.google_cloud_project = google_cloud_project
        self.available_models = [
            "gemini-2.5-flash",
            "gemini-1.5-pro",
        ]

        # Attempt to start background Gemini process early for better responsiveness
        self._start_background_gemini_process()

        # Mark as functional by default - will be tested on first use
        self.is_functional = True

    async def _execute_gemini_cli_with_timeout(self, prompt: str, model: Optional[str] = None, timeout: int = 30) -> str:
        """Execute Gemini CLI with a specific timeout for initialization testing"""

        # Build command arguments
        args = ["gemini"]

        # Specify model if provided
        if model:
            args.extend(["-m", model])

        # Add prompt - use -p flag to pass prompt as argument
        args.extend(["-p", prompt])

        logger.info(f"Testing Gemini CLI with timeout {timeout}s: {args}")

        try:
            # Build sanitized environment (do not inherit full proxy env)
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
                        escaped_arg = arg.replace('"', '\\"')
                        cmd_parts.append(f'"{escaped_arg}"')
                    else:
                        cmd_parts.append(arg)
                cmd_string = " ".join(cmd_parts)

                process = await asyncio.create_subprocess_shell(
                    cmd_string,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    cwd=self._gemini_working_dir
                )
            else:
                # On Unix, use exec
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    cwd=self._gemini_working_dir
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

    # ------------------------------------------------------------------
    def _prepare_prompt_file(self, prompt: str) -> str:
        """Write the full prompt to a *REQUEST.md* file in the working dir.

        Using a file avoids Windows "command line too long" errors when the
        prompt is large.  The CLI call will reference this file instead of
        passing the text via *-p* directly.
        """
        file_path = os.path.join(self._gemini_working_dir, "REQUEST.md")
        try:
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(prompt)
        except Exception as exc:
            logger.error("Failed to write prompt to %s: %s", file_path, exc)
            raise
        return file_path

    async def _execute_gemini_cli(self, prompt: str, model: Optional[str] = None, sandbox: bool = False) -> str:
        """Execute Gemini CLI command directly"""

        # Persist prompt to file to avoid long command lines
        self._prepare_prompt_file(prompt)

        # Build command arguments
        args = ["gemini"]

        # Specify model if provided
        if model:
            args.extend(["-m", model])

        if sandbox:
            args.append("-s")

        # Instead of the full prompt, reference the file we just wrote
        short_prompt = "Execute task described in ./REQUEST.md file"
        args.extend(["-p", short_prompt])

        logger.info(f"Executing Gemini CLI: {args}")
        logger.info(f"Raw command: {' '.join(args)}")

        try:
            # Create subprocess with sanitized environment
            env = self._build_gemini_env()

            # On Windows, ensure npm global bin is accessible if installed via npm
            if sys.platform == "win32":
                npm_global_bin = os.path.expanduser("~\AppData\Roaming\npm")
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
                        cmd_parts.append(f'""{escaped_arg}""')
                    else:
                        cmd_parts.append(arg)
                cmd_string = " ".join(cmd_parts)
                logger.info(f"Final command string: {cmd_string}")

                process = await asyncio.create_subprocess_shell(
                    cmd_string,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    cwd=self._gemini_working_dir
                )
            else:
                # On Unix, use exec
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
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
        agent: Optional[str] = None,  # Added agent parameter
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
                return await self._create_streaming_response(response)
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

            CHUNK_SIZE = 20  # words per SSE chunk
            for start in range(0, len(words), CHUNK_SIZE):
                part = " ".join(words[start:start + CHUNK_SIZE])
                is_last = start + CHUNK_SIZE >= len(words)
                chunk = {
                    "id": response["id"],
                    "object": "chat.completion.chunk",
                    "created": response["created"],
                    "model": response["model"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": part},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"

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
