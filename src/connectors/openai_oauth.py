r"""
OpenAI OAuth connector that uses ChatGPT/Codex auth.json tokens instead of API keys.

This backend reads a local `auth.json` file (created by Codex CLI via ChatGPT login)
and uses `tokens.access_token` as the bearer for OpenAI API requests. If the file
also contains `OPENAI_API_KEY`, that is used as a fallback.

Default credential file locations (first that exists is used):
- Windows: %USERPROFILE%\.codex\auth.json
- Cross-platform: ~/.codex/auth.json

Configuration:
- `openai_oauth_path`: optional directory that contains `auth.json` (overrides defaults)
- `openai_api_base_url`: optional base URL override (default: https://api.openai.com/v1)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class OpenAICredentialsFileHandler(FileSystemEventHandler):
    """File watcher handler for OpenAI OAuth credentials."""

    def __init__(self, connector: OpenAIOAuthConnector) -> None:
        super().__init__()
        self.connector = connector

    def on_modified(self, event) -> None:  # type: ignore[no-untyped-def]
        """Handle file modification events."""
        if not event.is_directory:
            # Compare paths using Path objects to handle Windows/Unix differences
            try:
                event_path = Path(event.src_path).resolve()
                auth_path = (
                    self.connector._auth_path.resolve()
                    if self.connector._auth_path
                    else None
                )

                if auth_path and event_path == auth_path:
                    logger.debug(
                        "OpenAI OAuth credentials file changed, scheduling reload"
                    )
                    self.connector._schedule_credentials_reload()
            except Exception as e:
                logger.error(f"Error processing file modification event: {e}")


class OpenAIOAuthConnector(OpenAIConnector):
    backend_type: str = "openai-oauth"
    # Copied from the official Codex CLI prompt (codex-rs/core/gpt_5_codex_prompt.md)
    CODex_SYSTEM_PROMPT: str = """You are Codex, based on GPT-5. You are running as a coding agent in the Codex CLI on a user's computer.

## General

- The arguments to `shell` will be passed to execvp(). Most terminal commands should be prefixed with ["bash", "-lc"].
- Always set the `workdir` param when using the shell function. Do not use `cd` unless absolutely necessary.
- When searching for text or files, prefer using `rg` or `rg --files` respectively because `rg` is much faster than alternatives like `grep`. (If the `rg` command is not found, then use alternatives.)

## Editing constraints

- Default to ASCII when editing or creating files. Only introduce non-ASCII or other Unicode characters when there is a clear justification and the file already uses them.
- Add succinct code comments that explain what is going on if code is not self-explanatory. You should not add comments like "Assigns the value to the variable", but a brief comment might be useful ahead of a complex code block that the user would otherwise have to spend time parsing out. Usage of these comments should be rare.
- Try to use apply_patch for single file edits, but it is fine to explore other options to make the edit if it does not work well. Do not use apply_patch for changes that are auto-generated (i.e. generating package.json or running a lint or format command like gofmt) or when scripting is more efficient (such as search and replacing a string across a codebase).
- You may be in a dirty git worktree.
    * NEVER revert existing changes you did not make unless explicitly requested, since these changes were made by the user.
    * If asked to make a commit or code edits and there are unrelated changes to your work or changes that you didn't make in those files, don't revert those changes.
    * If the changes are in files you've touched recently, you should read carefully and understand how you can work with the changes rather than reverting them.
    * If the changes are in unrelated files, just ignore them and don't revert them.
- While you are working, you might notice unexpected changes that you didn't make. If this happens, STOP IMMEDIATELY and ask the user how they would like to proceed.
- **NEVER** use destructive commands like `git reset --hard` or `git checkout --` unless specifically requested or approved by the user.

## Plan tool

When using the planning tool:
- Skip using the planning tool for straightforward tasks (roughly the easiest 25%).
- Do not make single-step plans.
- When you made a plan, update it after having performed one of the sub-tasks that you shared on the plan.

## Codex CLI harness, sandboxing, and approvals

The Codex CLI harness supports several different configurations for sandboxing and escalation approvals that the user can choose from.

Filesystem sandboxing defines which files can be read or written. The options for `sandbox_mode` are:
- **read-only**: The sandbox only permits reading files.
- **workspace-write**: The sandbox permits reading files, and editing files in `cwd` and `writable_roots`. Editing files in other directories requires approval.
- **danger-full-access**: No filesystem sandboxing - all commands are permitted.

Network sandboxing defines whether network can be accessed without approval. Options for `network_access` are:
- **restricted**: Requires approval
- **enabled**: No approval needed

Approvals are your mechanism to get user consent to run shell commands without the sandbox. Possible configuration options for `approval_policy` are
- **untrusted**: The harness will escalate most commands for user approval, apart from a limited allowlist of safe "read" commands.
- **on-failure**: The harness will allow all commands to run in the sandbox (if enabled), and failures will be escalated to the user for approval to run again without the sandbox.
- **on-request**: Commands will be run in the sandbox by default, and you can specify in your tool call if you want to escalate a command to run without sandboxing. (Note that this mode is not always available. If it is, you'll see parameters for it in the `shell` command description.)
- **never**: This is a non-interactive mode where you may NEVER ask for user approval before running commands. Instead, you must always persist and work around constraints to solve the task for the user. You MUST do your utmost best to finish the task and validate your work before yielding. If this mode is paired with `danger-full-access`, take advantage of it to deliver the best outcome for the user. Further, in this mode, your default testing philosophy is overridden: Even if you don't see local patterns for testing, you may add tests and scripts to validate your work. Just remove them before yielding.

When you are running with `approval_policy == on-request`, and sandboxing enabled, here are scenarios where you'll need to request approval:
- You need to run a command that writes to a directory that requires it (e.g. running tests that write to /var)
- You need to run a GUI app (e.g., open/xdg-open/osascript) to open browsers or files.
- You are running sandboxed and need to run a command that requires network access (e.g. installing packages)
- If you run a command that is important to solving the user's query, but it fails because of sandboxing, rerun the command with approval. ALWAYS proceed to use the `with_escalated_permissions` and `justification` parameters - do not message the user before requesting approval for the command.
- You are about to take a potentially destructive action such as an `rm` or `git reset` that the user did not explicitly ask for
- (for all of these, you should weigh alternative paths that do not require approvals)

When `sandbox_mode` is set to read-only, you'll need to request approval for any command that isn't a read.

Although they introduce friction to the user because your work is paused until the user responds, you should leverage them when necessary to accomplish important work. If the completing the task requires escalated permissions, Do not let these settings or the sandbox deter you from attempting to accomplish the user's task unless it is set to "never", in which case never ask for approvals.

## Special user requests

- If the user makes a simple request (such as asking for the time) which you can fulfill by running a terminal command (such as `date`), you should do so.
- If the user asks for a "review", default to a code review mindset: prioritise identifying bugs, risks, behavioural regressions, and missing tests. Findings must be the primary focus of the response - keep summaries or overviews brief and only after enumerating the issues. Present findings first (ordered by severity with file/line references), follow with open questions or assumptions, and offer a change-summary only as a secondary detail. If no findings are discovered, state that explicitly and mention any residual risks or testing gaps.

## Presenting your work and final message

You are producing plain text that will later be styled by the CLI. Follow these rules exactly. Formatting should make results easy to scan, but not feel mechanical. Use judgment to decide how much structure adds value.

- Default: be very concise; friendly coding teammate tone.
- Ask only when needed; suggest ideas; mirror the user's style.
- For substantial work, summarize clearly; follow final-answer formatting.
- Skip heavy formatting for simple confirmations.
- Don't dump large files you've written; reference paths only.
- No "save/copy this file" - User is on the same machine.
- Offer logical next steps (tests, commits, build) briefly; add verify steps if you couldn't do something.
- For code changes:
  * Lead with a quick explanation of the change, and then give more details on the context covering where and why a change was made. Do not start this explanation with "summary", just jump right in.
  * If there are natural next steps the user may want to take, suggest them at the end of your response. Do not make suggestions if there are no natural next steps.
  * When suggesting multiple options, use numeric lists for the suggestions so the user can quickly respond with a single number.
- The user does not command execution outputs. When asked to show the output of a command (e.g. `git show`), relay the important details in your answer or summarize the key lines so the user understands the result.

### Final answer structure and style guidelines

- Plain text; CLI handles styling. Use structure only when it helps scanability.
- Headers: optional; short Title Case (1-3 words) wrapped in **…**; no blank line before the first bullet; add only if they truly help.
- Bullets: use - ; merge related points; keep to one line when possible; 4-6 per list ordered by importance; keep phrasing consistent.
- Monospace: backticks for commands/paths/env vars/code ids and inline examples; use for literal keyword bullets; never combine with **.
- Code samples or multi-line snippets should be wrapped in fenced code blocks; include an info string as often as possible.
- Structure: group related bullets; order sections general → specific → supporting; for subsections, start with a bolded keyword bullet, then items; match complexity to the task.
- Tone: collaborative, concise, factual; present tense, active voice; self-contained; no "above/below"; parallel wording.
- Don'ts: no nested bullets/hierarchies; no ANSI codes; don't cram unrelated keywords; keep keyword lists short—wrap/reformat if long; avoid naming formatting styles in answers.
- Adaptation: code explanations → precise, structured with code refs; simple tasks → lead with outcome; big changes → logical walkthrough + rationale + next actions; casual one-offs → plain sentences, no headers/bullets.
- File References: When referencing files in your response, make sure to include the relevant start line and always follow the below rules:
  * Use inline code to make file paths clickable.
  * Each reference should have a stand alone path. Even if it's the same file.
  * Accepted: absolute, workspace-relative, a/ or b/ diff prefixes, or bare filename/suffix.
  * Line/column (1-based, optional): :line[:column] or #Lline[Ccolumn] (column defaults to 1).
  * Do not use URIs like file://, vscode://, or https://.
  * Do not provide range of lines
  * Examples: src/app.ts, src/app.ts:42, b/server/index.js#L10, C:\\repo\\project\\main.rs:12:5
"""
    CODEx_ORIGINATOR = "codex_cli_rs"
    CODEx_VERSION_HEADER = "0.46.0"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        response_processor: Any | None = None,
        translation_service: TranslationService | None = None,
    ) -> None:
        # Use explicit keywords to avoid argument order issues
        super().__init__(
            client=client,
            config=config,
            translation_service=translation_service,
            response_processor=response_processor,
        )
        self.name = "openai-oauth"
        self._oauth_dir_override: Path | None = None
        self._auth_path: Path | None = None
        self._last_modified: float = 0.0
        self.is_functional: bool = False

        # Stale token handling pattern attributes
        # Use BaseObserver for type checking to ensure stop/join are recognized by mypy
        self._file_observer: BaseObserver | None = None
        self._credential_validation_errors: list[str] = []
        self._initialization_failed: bool = False
        self._last_validation_time: float = 0.0
        self._pending_reload_task: asyncio.Future[None] | None = None
        self._auth_credentials: dict[str, Any] | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._reload_task_lock = threading.Lock()
        self._reload_scheduling_in_progress = False

        # Health checks are unnecessary for OAuth bearer flow in tests; disable by default
        import contextlib

        with contextlib.suppress(Exception):
            self.disable_health_check()

    @staticmethod
    def _is_codex_model(model_name: str) -> bool:
        """Return True when the model routes through the Codex Responses API."""
        lowered = model_name.lower()
        return lowered.startswith(("gpt-5-codex", "codex-"))

    def _codex_user_agent(self) -> str:
        """Build a Codex CLI compatible User-Agent string."""
        system_name = platform.system() or "UnknownOS"
        system_version = platform.release() or "0"
        arch = platform.machine() or "unknown"
        python_runtime = f"python-{platform.python_version()}"
        return (
            f"{self.CODEx_ORIGINATOR}/{self.CODEx_VERSION_HEADER} "
            f"({system_name} {system_version}; {arch}; {python_runtime})"
        )

    def _codex_account_id(self) -> str | None:
        """Return the ChatGPT account_id from cached credentials when available."""
        tokens = None
        if isinstance(self._auth_credentials, dict):
            tokens = self._auth_credentials.get("tokens")
        if isinstance(tokens, dict):
            account_id = tokens.get("account_id")
            if isinstance(account_id, str) and account_id.strip():
                return account_id
        return None

    @staticmethod
    def _message_to_text(message: Any) -> str:
        """Best-effort conversion of a ChatMessage-like object to plain text."""
        # Prefer explicit attributes
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                        continue
                if hasattr(part, "model_dump") and callable(part.model_dump):
                    dumped = part.model_dump()
                    if isinstance(dumped, dict):
                        text = dumped.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                            continue
                parts.append(str(part))
            return "\n".join(parts)

        if content is not None:
            return str(content)

        # Fallback to message string representation
        return str(message)

    def _build_user_instructions_block(self, request_data: Any) -> str:
        """Compose the <user_instructions> block from system messages."""
        system_messages: list[str] = []
        messages = getattr(request_data, "messages", [])
        for message in messages or []:
            role = getattr(message, "role", None)
            if role is None and isinstance(message, dict):
                role = message.get("role")
            if (role or "").lower() == "system":
                system_messages.append(self._message_to_text(message))

        body = "\n\n".join(msg for msg in system_messages if msg.strip())
        return f"<user_instructions>\n\n{body}\n\n</user_instructions>"

    def _build_environment_context_block(
        self, request_data: Any, effective_model: str
    ) -> str:
        """Compose the <environment_context> block with best-effort metadata."""
        extra_body = getattr(request_data, "extra_body", {}) or {}

        cwd = extra_body.get("project_dir") or extra_body.get("cwd")
        if not cwd:
            cwd = os.getcwd()

        sandbox_mode = extra_body.get("sandbox_mode") or "unknown"
        approval_policy = extra_body.get("approval_policy") or "unknown"
        network_access = extra_body.get("network_access") or "unknown"
        shell = extra_body.get("shell") or os.environ.get("SHELL") or "bash"

        lines = [
            "<environment_context>",
            f"  <cwd>{cwd}</cwd>",
            f"  <model>{effective_model}</model>",
            f"  <sandbox_mode>{sandbox_mode}</sandbox_mode>",
            f"  <approval_policy>{approval_policy}</approval_policy>",
            f"  <network_access>{network_access}</network_access>",
            f"  <shell>{shell}</shell>",
            "</environment_context>",
        ]
        return "\n".join(lines)

    def _build_codex_tools(self) -> list[dict[str, Any]]:
        """Return the tool definitions expected by the Codex Responses API."""
        return [
            {
                "type": "function",
                "name": "shell",
                "description": "Runs a shell command and returns its output.",
                "strict": False,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The command to execute",
                        },
                        "justification": {
                            "type": "string",
                            "description": "Only set if with_escalated_permissions is true. 1-sentence explanation of why we want to run this command.",
                        },
                        "timeout_ms": {
                            "type": "number",
                            "description": "The timeout for the command in milliseconds",
                        },
                        "with_escalated_permissions": {
                            "type": "boolean",
                            "description": "Whether to request escalated permissions. Set to true if command needs to be run without sandbox restrictions",
                        },
                        "workdir": {
                            "type": "string",
                            "description": "The working directory to execute the command in",
                        },
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "apply_patch",
                "description": "Applies a unified diff to the repository.",
                "strict": False,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patch": {
                            "type": "string",
                            "description": "Unified diff content to apply",
                        }
                    },
                    "required": ["patch"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "view_image",
                "description": "Attach a local image (by filesystem path) to the conversation context for this turn.",
                "strict": False,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Local filesystem path to an image file",
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        ]

    def _build_codex_input_items(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
    ) -> list[dict[str, Any]]:
        """Transform processed messages into Codex Responses `input` array."""
        input_items: list[dict[str, Any]] = []
        input_items.append(
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": self._build_user_instructions_block(request_data),
                    }
                ],
            }
        )
        input_items.append(
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": self._build_environment_context_block(
                            request_data, effective_model
                        ),
                    }
                ],
            }
        )

        for message in processed_messages or []:
            role = getattr(message, "role", None)
            if role is None and isinstance(message, dict):
                role = message.get("role")
            role = (role or "user").lower()

            text = self._message_to_text(message)
            if not text.strip():
                continue

            content_type = "output_text" if role == "assistant" else "input_text"
            input_items.append(
                {
                    "type": "message",
                    "role": "assistant" if role == "assistant" else "user",
                    "content": [{"type": content_type, "text": text}],
                }
            )
        return input_items

    def _build_codex_payload(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
    ) -> tuple[dict[str, Any], str]:
        """Create the request payload and conversation id for Codex Responses API."""
        conversation_id = str(uuid.uuid4())
        input_items = self._build_codex_input_items(
            request_data, processed_messages, effective_model
        )

        payload: dict[str, Any] = {
            "model": effective_model,
            "instructions": self.CODex_SYSTEM_PROMPT,
            "input": input_items,
            "tools": self._build_codex_tools(),
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "reasoning": None,
            "store": False,
            "stream": True,
            "include": [],
            "prompt_cache_key": conversation_id,
        }
        return payload, conversation_id

    def _build_codex_headers(self, conversation_id: str) -> dict[str, str]:
        """Construct Codex-specific HTTP headers."""
        headers = self.get_headers() or {}
        headers["OpenAI-Beta"] = "responses=experimental"
        headers["Accept"] = "text/event-stream"
        headers["version"] = self.CODEx_VERSION_HEADER
        headers["originator"] = self.CODEx_ORIGINATOR
        headers["User-Agent"] = self._codex_user_agent()
        headers["conversation_id"] = conversation_id
        headers["session_id"] = conversation_id
        headers["Codex-Task-Type"] = "standard"

        account_id = self._codex_account_id()
        if account_id:
            headers["chatgpt-account-id"] = account_id

        return headers

    async def _call_codex_responses_api(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        domain_request: Any,
    ) -> Any:
        """Call the Codex-specific Responses API endpoint."""
        payload, conversation_id = self._build_codex_payload(
            request_data, processed_messages, effective_model
        )
        headers = self._build_codex_headers(conversation_id)
        url = "https://chatgpt.com/backend-api/codex/responses"

        session_id = getattr(domain_request, "session_id", None) or conversation_id
        if getattr(domain_request, "stream", False):
            stream_handle = await self._handle_streaming_response(
                url,
                payload,
                headers,
                session_id,
                "responses",
            )
            from src.core.domain.responses import StreamingResponseEnvelope

            return StreamingResponseEnvelope(
                content=stream_handle.iterator,
                media_type="text/event-stream",
                headers={},
                cancel_callback=stream_handle.cancel_callback,
            )

        return await self._handle_non_streaming_response(
            url,
            payload,
            headers,
            session_id,
        )

    # -----------------------------
    # Health Tracking API (stale token handling pattern)
    # -----------------------------
    def is_backend_functional(self) -> bool:
        """Return True if the backend is functional and ready to serve requests."""
        return self.is_functional and not self._initialization_failed

    def get_validation_errors(self) -> list[str]:
        """Return list of validation errors encountered during initialization or runtime."""
        return self._credential_validation_errors.copy()

    def _fail_init(self, errors: list[str]) -> None:
        """Mark initialization as failed with given errors."""
        self._initialization_failed = True
        self.is_functional = False
        self._credential_validation_errors = errors
        logger.error(f"OpenAI OAuth initialization failed: {'; '.join(errors)}")

    def _degrade(self, errors: list[str]) -> None:
        """Mark backend as degraded due to runtime validation failures."""
        self.is_functional = False
        self._credential_validation_errors = errors
        logger.warning(f"OpenAI OAuth backend degraded: {'; '.join(errors)}")

    def _recover(self) -> None:
        """Mark backend as recovered after successful validation."""
        self.is_functional = True
        self._credential_validation_errors = []
        self._last_validation_time = time.time()
        logger.info("OpenAI OAuth backend recovered")

    # -----------------------------
    # Validation methods (stale token handling pattern)
    # -----------------------------
    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that credentials file exists and is readable."""
        errors = []

        auth_path = self._discover_auth_path()
        if auth_path is None:
            errors.append("OAuth credentials file not found in any default location")
            return False, errors

        if not auth_path.exists():
            errors.append(f"OAuth credentials file does not exist: {auth_path}")
            return False, errors

        if not auth_path.is_file():
            errors.append(f"OAuth credentials path is not a file: {auth_path}")
            return False, errors

        try:
            with open(auth_path, encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"OAuth credentials file contains invalid JSON: {e}")
            return False, errors
        except PermissionError:
            errors.append(f"No permission to read OAuth credentials file: {auth_path}")
            return False, errors
        except Exception as e:
            errors.append(f"Error reading OAuth credentials file: {e}")
            return False, errors

        return True, errors

    def _validate_credentials_structure(
        self, credentials: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate OAuth credentials structure and content."""
        errors = []

        if not isinstance(credentials, dict):
            errors.append("OAuth credentials must be a JSON object")
            return False, errors

        # Check for tokens.access_token or OPENAI_API_KEY
        access_token = None
        tokens = credentials.get("tokens")
        if isinstance(tokens, dict):
            tok = tokens.get("access_token")
            if isinstance(tok, str) and tok.strip():
                access_token = tok

        api_key = credentials.get("OPENAI_API_KEY")
        if not access_token and not (isinstance(api_key, str) and api_key.strip()):
            errors.append(
                "OAuth credentials missing required 'tokens.access_token' or 'OPENAI_API_KEY' field"
            )
            return False, errors

        return True, errors

    def _validate_runtime_credentials(self) -> tuple[bool, list[str]]:
        """Validate credentials at runtime with throttling."""
        # Simple throttling: only validate once per 30 seconds
        current_time = time.time()
        if current_time - self._last_validation_time < 30:
            return True, []

        # Validate file existence and structure
        ok, errors = self._validate_credentials_file_exists()
        if not ok:
            return False, errors

        if self._auth_credentials is not None:
            ok, struct_errors = self._validate_credentials_structure(
                self._auth_credentials
            )
            if not ok:
                errors.extend(struct_errors)
                return False, errors
        else:
            errors.append("OAuth credentials not loaded in memory")
            return False, errors

        self._last_validation_time = current_time
        return True, errors

    # -----------------------------
    # File watching methods (stale token handling pattern)
    # -----------------------------
    def _start_file_watching(self) -> None:
        """Start watching the credentials file for changes."""
        if self._auth_path is None or self._file_observer is not None:
            return

        try:
            self._file_observer = Observer()
            handler = OpenAICredentialsFileHandler(self)
            watch_dir = self._auth_path.parent
            self._file_observer.schedule(handler, str(watch_dir), recursive=False)
            self._file_observer.start()
            logger.debug(
                f"Started watching OpenAI OAuth credentials directory: {watch_dir}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to start file watching for OpenAI OAuth credentials: {e}"
            )

    def _stop_file_watching(self) -> None:
        """Stop watching the credentials file for changes."""
        if self._file_observer is not None:
            try:
                self._file_observer.stop()
                self._file_observer.join(timeout=1.0)
            except Exception as e:
                logger.debug(f"Error stopping OpenAI OAuth file watcher: {e}")
            finally:
                self._file_observer = None

    def _schedule_credentials_reload(self) -> None:
        """Schedule an asynchronous reload of credentials.

        This method is called when the file system watcher detects a change to the
        auth.json file. It forces a reload of credentials bypassing the cache
        to ensure the latest token is loaded even if the file timestamp didn't change.
        """
        with self._reload_task_lock:
            if (
                self._pending_reload_task is not None
                and not self._pending_reload_task.done()
            ):
                return
            if self._reload_scheduling_in_progress:
                return
            self._reload_scheduling_in_progress = True

        async def reload_task() -> None:
            try:
                logger.debug("Reloading OpenAI OAuth credentials due to file change")
                # Use force_reload=True to bypass cache
                try:
                    loaded = await self._load_auth(force_reload=True)
                except TypeError:
                    loaded = await self._load_auth()
                if loaded:
                    if self._auth_credentials is not None:
                        ok, errors = self._validate_credentials_structure(
                            self._auth_credentials
                        )
                        if ok:
                            self._recover()
                        else:
                            self._degrade(errors)
                    else:
                        self._degrade(
                            ["Failed to load credentials despite successful file read"]
                        )
                else:
                    self._degrade(["Failed to reload credentials from file"])
            except Exception as e:
                logger.error(f"Error during OpenAI OAuth credentials reload: {e}")
                self._degrade([f"Credentials reload failed: {e}"])

        loop = self._event_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning(
                    "Cannot schedule credentials reload: no running event loop available."
                )
                with self._reload_task_lock:
                    self._reload_scheduling_in_progress = False
                return
            self._event_loop = loop

        if loop.is_closed():
            logger.warning("Cannot schedule credentials reload: event loop is closed.")
            with self._reload_task_lock:
                self._reload_scheduling_in_progress = False
            return

        def _clear(_: asyncio.Future[Any]) -> None:
            with self._reload_task_lock:
                self._pending_reload_task = None
                self._reload_scheduling_in_progress = False

        def _assign_task(task: asyncio.Future[None]) -> None:
            task.add_done_callback(_clear)
            with self._reload_task_lock:
                self._pending_reload_task = task
                self._reload_scheduling_in_progress = False

        try:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is loop:
                task = loop.create_task(reload_task())
                _assign_task(task)
                return

            def schedule_task() -> None:
                try:
                    task = loop.create_task(reload_task())
                    _assign_task(task)
                except Exception as exc:
                    logger.warning(
                        "Failed to schedule OpenAI OAuth credentials reload: %s", exc
                    )
                    with self._reload_task_lock:
                        self._reload_scheduling_in_progress = False

            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.warning(
                "Failed to schedule OpenAI OAuth credentials reload: %s", exc
            )
            with self._reload_task_lock:
                self._reload_scheduling_in_progress = False

    def _default_auth_paths(self) -> list[Path]:
        paths: list[Path] = []
        userprofile = os.getenv("USERPROFILE")
        if userprofile:
            paths.append(Path(userprofile) / ".codex" / "auth.json")
        # Cross-platform default
        paths.append(Path.home() / ".codex" / "auth.json")
        return paths

    def _discover_auth_path(self) -> Path | None:
        if self._oauth_dir_override is not None:
            return self._oauth_dir_override / "auth.json"
        for p in self._default_auth_paths():
            if p.exists():
                return p
        return None

    async def _load_auth(self, force_reload: bool = False) -> bool:
        """Load OAuth credentials from auth.json file.

        Args:
            force_reload: If True, bypass cache and force reload from file even if timestamp unchanged

        Returns:
            bool: True if credentials loaded successfully, False otherwise
        """
        auth_path = self._discover_auth_path()
        if auth_path is None:
            logger.warning("OpenAI OAuth auth.json not found in default locations")
            return False

        self._auth_path = auth_path
        try:
            # Check if file has been modified since last load (unless force_reload is True)
            if not force_reload:
                try:
                    mtime = auth_path.stat().st_mtime
                    if mtime == self._last_modified and self.api_key:
                        logger.debug(
                            "OpenAI OAuth credentials file not modified, using cached."
                        )
                        return True
                except OSError:
                    pass

            # Update last modified time
            try:
                mtime = auth_path.stat().st_mtime
                self._last_modified = mtime
            except OSError:
                pass

            with open(auth_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            token: str | None = None
            # Prefer ChatGPT OAuth access token
            tokens = data.get("tokens")
            if isinstance(tokens, dict):
                tok = tokens.get("access_token")
                if isinstance(tok, str) and tok:
                    token = tok
            # Fallback to OPENAI_API_KEY if present
            if not token:
                api_key = data.get("OPENAI_API_KEY")
                if isinstance(api_key, str) and api_key:
                    token = api_key

            if not token:
                logger.warning(
                    "OpenAI OAuth auth.json missing tokens.access_token and OPENAI_API_KEY"
                )
                return False

            # Set as API key for parent header logic
            self.api_key = token
            # Store credentials for validation
            self._auth_credentials = data
            log_msg = "Successfully loaded OpenAI OAuth credentials"
            if force_reload:
                log_msg += " (force reload)"
            logger.info(log_msg + ".")
            return True
        except json.JSONDecodeError as e:
            logger.error("Malformed auth.json for OpenAI OAuth: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "Failed to load OpenAI OAuth credentials: %s", e, exc_info=True
            )
            return False

    async def initialize(self, **kwargs: Any) -> None:  # type: ignore[override]
        """Initialize backend with enhanced validation using stale token handling pattern."""
        logger.info("Initializing OpenAI OAuth backend with enhanced validation.")

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        # Allow base URL override
        base = kwargs.get("openai_api_base_url") or kwargs.get("api_base_url")
        if isinstance(base, str) and base:
            self.api_base_url = base

        # Optional directory override for auth.json
        dir_override = kwargs.get("openai_oauth_path")
        if isinstance(dir_override, str) and dir_override:
            self._oauth_dir_override = Path(dir_override)

        # 1) File exists + readable + parseable
        ok, errors = self._validate_credentials_file_exists()
        if not ok:
            self._fail_init(errors)
            return

        # 2) Load credentials into memory
        if not await self._load_auth():
            self._fail_init(["Failed to load credentials despite validation passing"])
            return

        # 3) Structure validation
        if self._auth_credentials is not None:
            ok, errors = self._validate_credentials_structure(self._auth_credentials)
            if not ok:
                self._fail_init(errors)
                return
        else:
            self._fail_init(["OAuth credentials are None after loading"])
            return

        # 4) Start file watching and mark functional
        self._start_file_watching()
        self.is_functional = True
        self._last_validation_time = time.time()
        logger.info(f"Credentials file validation passed for {self.name}.")

        # Optionally prefetch models (non-fatal if it fails)
        import contextlib

        with contextlib.suppress(Exception):
            await self.list_models()

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ):
        # Runtime validation with throttling
        ok, errors = self._validate_runtime_credentials()
        if not ok:
            self._degrade(errors)
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "openai_oauth_credentials_invalid",
                    "message": f"OpenAI OAuth credentials validation failed: {'; '.join(errors)}",
                    "details": {
                        "backend": self.name,
                        "validation_errors": errors,
                        "suggestion": "Please check your OAuth credentials file and ensure it contains valid tokens.access_token or OPENAI_API_KEY",
                    },
                },
            )

        # Ensure we have a token loaded just before the call
        if not await self._load_auth():
            self._degrade(["Failed to load OAuth credentials"])
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "openai_oauth_credentials_unavailable",
                    "message": "No valid OpenAI OAuth credentials available",
                    "details": {
                        "backend": self.name,
                        "suggestion": "Run codex login or set openai_oauth_path to the directory containing auth.json",
                    },
                },
            )

        if self._is_codex_model(effective_model):
            try:
                result = await self._call_codex_responses_api(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=effective_model,
                    domain_request=request_data,
                )
                if not self.is_functional:
                    self._recover()
                return result
            except Exception as e:
                if (
                    isinstance(e, AuthenticationError | HTTPException)
                    and hasattr(e, "status_code")
                    and e.status_code in (401, 403)
                ):
                    self._degrade([f"Authentication failed: {e!s}"])
                raise

        # Delegate to parent with our token
        try:
            result = await super().chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                identity=identity,
                **kwargs,
            )
            # If we reach here, the call was successful - mark as recovered if we were degraded
            if not self.is_functional:
                self._recover()
            return result
        except Exception as e:
            # Check if it's an auth-related error and degrade accordingly
            if (
                isinstance(e, AuthenticationError | HTTPException)
                and hasattr(e, "status_code")
                and e.status_code in (401, 403)
            ):
                self._degrade([f"Authentication failed: {e!s}"])
            raise

    def __del__(self) -> None:
        """Cleanup file watcher on destruction."""
        self._stop_file_watching()


backend_registry.register_backend("openai-oauth", OpenAIOAuthConnector)
