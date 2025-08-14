from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Protocol, cast

from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse

from src import models
from src.agents import (
    detect_agent,
    wrap_proxy_message,
)
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.constants import GEMINI_BACKENDS, BackendType

# Define CLI-specific backend types as string constants
# These were previously in BackendType but have been removed
GEMINI_CLI_DIRECT = "gemini-cli-direct"
GEMINI_CLI_BATCH = "gemini-cli-batch"
GEMINI_CLI_INTERACTIVE = "gemini-cli-interactive"


# Define protocol for tracker objects
class TrackerProtocol(Protocol):
    def set_response(self, response: Any) -> None: ...
    def set_response_headers(self, headers: dict[str, str]) -> None: ...
    def set_cost(self, cost: float) -> None: ...
    def set_completion_id(self, completion_id: str) -> None: ...


from src.core.config import _keys_for, get_openrouter_headers
from src.llm_accounting_utils import track_llm_request
from src.performance_tracker import track_phase
from src.proxy_logic import ProxyState
from src.rate_limit import parse_retry_delay
from src.request_middleware import RequestContext, get_request_middleware
from src.session import SessionInteraction

logger = logging.getLogger(__name__)


class ChatService:
    """Service layer for handling chat completion requests."""

    def __init__(self, app: Any, config: dict[str, Any]) -> None:
        self.app = app
        self.config = config

    async def process_chat_completion(
        self,
        request_data: models.ChatCompletionRequest,
        http_request: Request,
        session_id: str,
        perf_metrics: Any,
    ) -> (
        dict[str, Any]
        | models.CommandProcessedChatCompletionResponse
        | StreamingResponse
    ):
        """Process a chat completion request through the entire pipeline."""

        session = self.app.state.session_manager.get_session(session_id)
        proxy_state: ProxyState = session.proxy_state

        # Set initial context for performance tracking
        perf_metrics.streaming = getattr(request_data, "stream", False)

        # Log request details
        self._log_request_details(session_id, request_data, http_request)

        # Process commands and detect agent
        with track_phase(perf_metrics, "command_processing"):
            processed_messages, commands_processed, confirmation_text = (
                await self._process_commands(
                    request_data, proxy_state, session, http_request
                )
            )

        # Apply request middleware processing (redaction, filtering, etc.)
        with track_phase(perf_metrics, "middleware_processing"):
            request_context = RequestContext(
                session_id=session_id,
                backend_type="unknown",  # Will be updated per backend call
                model="unknown",  # Will be updated per backend call
                redaction_enabled=self.app.state.api_key_redaction_enabled,
                api_key_redactor=self.app.state.api_key_redactor,
                command_filter=self.app.state.command_filter,
            )
            processed_messages_dict = [msg.model_dump() for msg in processed_messages]
            processed_messages_dict = await get_request_middleware().process_request(
                processed_messages_dict, request_context
            )
            processed_messages = [
                models.ChatMessage.model_validate(msg)
                for msg in processed_messages_dict
            ]
        # Validate backend and model
        current_backend_type = self._validate_backend_and_model(
            proxy_state, http_request
        )

        # Handle command-only requests
        if commands_processed:
            command_response = self._handle_command_response(
                request_data,
                processed_messages,
                confirmation_text,
                proxy_state,
                session,
                session_id,
            )
            if command_response:
                return command_response

        # Validate processed messages
        if not processed_messages:
            raise HTTPException(
                status_code=400,
                detail="No messages provided in the request or messages became empty after processing.",
            )

        # Check project requirement
        if self.app.state.force_set_project and proxy_state.project is None:
            raise HTTPException(
                status_code=400,
                detail="Project name not set. Use !/set(project=<name>) before sending prompts.",
            )

        # Prepare request for backend
        effective_model = proxy_state.get_effective_model(request_data.model)
        self._apply_model_defaults(proxy_state, effective_model)
        self._inject_proxy_parameters(request_data, proxy_state, current_backend_type)

        # Update performance metrics
        perf_metrics.backend_used = current_backend_type
        perf_metrics.model_used = effective_model

        # Call backend
        response_from_backend, used_backend, used_model = (
            await self._call_backend_with_failover(
                request_data,
                processed_messages,
                effective_model,
                current_backend_type,
                proxy_state,
                perf_metrics,
            )
        )

        # Process response
        with track_phase(perf_metrics, "response_processing"):
            return self._process_backend_response(
                response_from_backend,
                request_data,
                session,
                proxy_state,
                used_backend,
                used_model,
                session_id,
            )

    def _log_request_details(
        self,
        session_id: str,
        request_data: models.ChatCompletionRequest,
        http_request: Request,
    ) -> None:
        """Log detailed request information for debugging."""
        logger.info("[CLINE_DEBUG] ========== NEW REQUEST ==========")
        logger.info(f"[CLINE_DEBUG] Session ID: {session_id}")
        logger.info(
            f"[CLINE_DEBUG] User-Agent: {http_request.headers.get('user-agent', 'Unknown')}"
        )
        logger.info(
            f"[CLINE_DEBUG] Authorization: {http_request.headers.get('authorization', 'None')[:20]}..."
        )
        logger.info(
            f"[CLINE_DEBUG] Content-Type: {http_request.headers.get('content-type', 'Unknown')}"
        )
        logger.info(f"[CLINE_DEBUG] Model requested: {request_data.model}")
        logger.info(
            f"[CLINE_DEBUG] Messages count: {len(request_data.messages) if request_data.messages else 0}"
        )

        if request_data.tools:
            logger.info(
                f"[CLINE_DEBUG] Tools provided: {len(request_data.tools)} tools"
            )
            for i, tool in enumerate(request_data.tools):
                logger.info(f"[CLINE_DEBUG] Tool {i}: {tool.function.name}")
        else:
            logger.info("[CLINE_DEBUG] No tools provided in request")

        if request_data.messages:
            for i, msg in enumerate(request_data.messages):
                content_preview = (
                    str(msg.content)[:100] + "..."
                    if len(str(msg.content)) > 100
                    else str(msg.content)
                )
                logger.info(
                    f"[CLINE_DEBUG] Message {i}: role={msg.role}, content={content_preview}"
                )

        logger.info("[CLINE_DEBUG] ================================")

    async def _process_commands(
        self,
        request_data: models.ChatCompletionRequest,
        proxy_state: ProxyState,
        session: Any,
        http_request: Request,
    ) -> tuple[list[models.ChatMessage], bool, str]:
        """Process commands in messages and detect agent."""
        # Detect agent from first message
        self._detect_agent_from_first_message(request_data, proxy_state, session)

        # Process commands if interactive commands are enabled
        if not self.app.state.disable_interactive_commands:
            processed_messages, commands_processed, confirmation_text = (
                self._run_command_parser(request_data, proxy_state)
            )
            return processed_messages, commands_processed, confirmation_text

        return request_data.messages, False, ""

    def _detect_agent_from_first_message(
        self,
        request_data: models.ChatCompletionRequest,
        proxy_state: ProxyState,
        session: Any,
    ) -> None:
        if not request_data.messages:
            return
        first = request_data.messages[0]
        if isinstance(first.content, str):
            text = first.content
        elif isinstance(first.content, list):
            text = " ".join(
                p.text
                for p in first.content
                if isinstance(p, models.MessageContentPartText)
            )
        else:
            text = ""

        if not proxy_state.is_cline_agent and "<attempt_completion>" in text:
            proxy_state.set_is_cline_agent(True)
            if session.agent is None:
                session.agent = "cline"
            logger.info(
                "[CLINE_DEBUG] Detected Cline agent via <attempt_completion> pattern."
            )

        if session.agent is None:
            session.agent = detect_agent(text)
            if session.agent:
                logger.info(
                    f"[CLINE_DEBUG] Detected agent via detect_agent(): {session.agent}"
                )

    def _run_command_parser(
        self, request_data: models.ChatCompletionRequest, proxy_state: ProxyState
    ) -> tuple[list[models.ChatMessage], bool, str]:
        parser_config = CommandParserConfig(
            proxy_state=proxy_state,
            app=self.app,
            preserve_unknown=not proxy_state.interactive_mode,
            functional_backends=self.app.state.functional_backends,
        )
        parser = CommandParser(
            parser_config, command_prefix=self.app.state.command_prefix
        )

        processed_messages, commands_processed = parser.process_messages(
            request_data.messages
        )

        confirmation_text = self._build_confirmation_text(parser)
        self._raise_if_command_errors(parser, request_data)
        return processed_messages, commands_processed, confirmation_text

    def _build_confirmation_text(self, parser: CommandParser) -> str:
        if not parser or not parser.command_results:
            return ""
        lines = [
            (r.message if r.success else f"Error: {r.message}")
            for r in parser.command_results
        ]
        return "\n".join(lines)

    def _raise_if_command_errors(
        self, parser: CommandParser, request_data: models.ChatCompletionRequest
    ) -> None:
        if not parser.command_results or all(r.success for r in parser.command_results):
            return
        error_messages = [r.message for r in parser.command_results if not r.success]
        raise HTTPException(
            status_code=400,
            detail={
                "id": "proxy_cmd_processed",
                "object": "chat.completion",
                "created": int(datetime.now(timezone.utc).timestamp()),
                "model": request_data.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "; ".join(error_messages),
                        },
                        "finish_reason": "error",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            },
        )

    def _validate_backend_and_model(
        self, proxy_state: ProxyState, http_request: Request
    ) -> str:
        """Validate backend and model configuration."""
        current_backend_type = self.app.state.backend_type

        if proxy_state.override_backend:
            current_backend_type = proxy_state.override_backend
            if proxy_state.invalid_override:
                detail_msg = {
                    "message": "invalid or unsupported model",
                    "model": f"{proxy_state.override_backend}:{proxy_state.override_model}",
                }
                raise HTTPException(status_code=400, detail=detail_msg)

            if current_backend_type not in {
                BackendType.OPENROUTER,
                BackendType.GEMINI,
                GEMINI_CLI_DIRECT,
                BackendType.ANTHROPIC,
                BackendType.QWEN_OAUTH,
            }:
                raise HTTPException(
                    status_code=400, detail=f"unknown backend {current_backend_type}"
                )

        return proxy_state.get_selected_backend(self.app.state.backend_type)

    def _handle_command_response(
        self,
        request_data: models.ChatCompletionRequest,
        processed_messages: list[models.ChatMessage],
        confirmation_text: str,
        proxy_state: ProxyState,
        session: Any,
        session_id: str,
    ) -> dict[str, Any] | models.CommandProcessedChatCompletionResponse | None:
        """Handle command-only requests that don't need backend processing."""

        # Check if there's meaningful content remaining after command processing
        has_meaningful_content = self._has_meaningful_content(
            processed_messages, proxy_state, session
        )

        if not has_meaningful_content:
            # Enhanced agent detection for command-only requests
            if session.agent is None and request_data.messages:
                first_message = request_data.messages[0]
                if isinstance(first_message.content, str):
                    content = first_message.content
                    logger.info(
                        f"[CLINE_DEBUG] Commands processed but no agent detected. Message length: {len(content)}"
                    )

                    if len(content) > 100 and ("!/hello" in content or "!/" in content):
                        session.agent = "cline"
                        proxy_state.set_is_cline_agent(True)
                        logger.info(
                            "[CLINE_DEBUG] Enhanced detection: Set agent to Cline"
                        )

            # Generate response content
            content_lines_for_agent = []
            show_banner = proxy_state.hello_requested

            if (
                proxy_state.interactive_mode
                and show_banner
                and not self.app.state.disable_interactive_commands
            ):
                banner_content = self._generate_welcome_banner(session_id)
                content_lines_for_agent.append(banner_content)

            if confirmation_text:
                content_lines_for_agent.append(confirmation_text)

            final_content = (
                "\n".join(content_lines_for_agent)
                if content_lines_for_agent
                else "Command processed successfully."
            )

            # Format response based on agent type
            if session.agent in {"cline", "roocode"}:
                logger.debug(
                    "[CLINE_DEBUG] Returning as XML-wrapped content for Cline agent"
                )
                # Format content for Cline agent
                xml_wrapped_content = (
                    f"<attempt_completion>{final_content}</attempt_completion>"
                )
                return models.CommandProcessedChatCompletionResponse(
                    id="proxy_cmd_processed",
                    object="chat.completion",
                    created=int(datetime.now(timezone.utc).timestamp()),
                    model=request_data.model,
                    choices=[
                        models.ChatCompletionChoice(
                            index=0,
                            message=models.ChatCompletionChoiceMessage(
                                role="assistant", content=xml_wrapped_content
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=models.CompletionUsage(
                        prompt_tokens=0, completion_tokens=0, total_tokens=0
                    ),
                )
            else:
                logger.debug(
                    f"[CLINE_DEBUG] Returning as regular assistant message for agent: {session.agent}"
                )
                formatted_content = wrap_proxy_message(session.agent, final_content)
                return models.CommandProcessedChatCompletionResponse(
                    id="proxy_cmd_processed",
                    object="chat.completion",
                    created=int(datetime.now(timezone.utc).timestamp()),
                    model=proxy_state.get_effective_model(request_data.model),
                    choices=[
                        models.ChatCompletionChoice(
                            index=0,
                            message=models.ChatCompletionChoiceMessage(
                                role="assistant", content=formatted_content
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=models.CompletionUsage(
                        prompt_tokens=0, completion_tokens=0, total_tokens=0
                    ),
                )

        return None

    def _has_meaningful_content(
        self,
        processed_messages: list[models.ChatMessage],
        proxy_state: ProxyState,
        session: Any,
    ) -> bool:
        """Check if processed messages contain meaningful content for backend processing."""
        has_meaningful_content = False

        if processed_messages:
            for msg in processed_messages:
                if isinstance(msg.content, str) and msg.content.strip():
                    content = msg.content.strip()

                    # For Cline agents, be more restrictive
                    if proxy_state.is_cline_agent or session.agent == "cline":
                        # Cline typically sends structured requests, so any remaining content is likely meaningful
                        if len(content.split()) > 3:  # More than 3 words
                            logger.debug(
                                f"[COMMAND_DEBUG] Cline agent: Found meaningful content: '{content[:50]}...'"
                            )
                            has_meaningful_content = True
                            break
                        else:
                            logger.debug(
                                f"[COMMAND_DEBUG] Cline agent: Ignoring short content: '{content}'"
                            )
                            continue
                    else:
                        # For non-Cline agents, use smarter heuristics
                        if len(content.split()) <= 2:  # 2 words or less
                            logger.debug(
                                f"[COMMAND_DEBUG] Ignoring short remaining content: '{content}'"
                            )
                            continue

                        # Check for instruction indicators
                        instruction_indicators = [
                            "write",
                            "create",
                            "generate",
                            "explain",
                            "describe",
                            "tell",
                            "show",
                            "help",
                            "how",
                            "what",
                            "why",
                            "where",
                            "when",
                            "please",
                            "can you",
                            "could you",
                            "would you",
                            "i need",
                            "i want",
                            "make",
                            "build",
                            "story",
                            "code",
                            "example",
                            "list",
                            "summary",
                            "analysis",
                        ]

                        content_lower = content.lower()
                        has_instruction_words = any(
                            indicator in content_lower
                            for indicator in instruction_indicators
                        )

                        if has_instruction_words and len(content.split()) > 5:
                            logger.debug(
                                f"[COMMAND_DEBUG] Found meaningful LLM request: '{content[:50]}...'"
                            )
                            has_meaningful_content = True
                            break
                        else:
                            logger.debug(
                                f"[COMMAND_DEBUG] Ignoring filler text around command: '{content[:50]}...'"
                            )
                            continue

        return has_meaningful_content

    def _generate_welcome_banner(self, session_id: str) -> str:
        """Generate welcome banner content."""
        project_name = self.app.state.project_metadata["name"]
        project_version = self.app.state.project_metadata["version"]
        backend_info = []

        if BackendType.OPENROUTER in self.app.state.functional_backends:
            keys = len(self.config.get("openrouter_api_keys", {}))
            models_list = self.app.state.openrouter_backend.get_available_models()
            models_count = len(models_list)
            backend_info.append(f"openrouter (K:{keys}, M:{models_count})")

        if BackendType.GEMINI in self.app.state.functional_backends:
            keys = len(self.config.get("gemini_api_keys", {}))
            models_list = self.app.state.gemini_backend.get_available_models()
            models_count = len(models_list)
            backend_info.append(f"gemini (K:{keys}, M:{models_count})")

        if BackendType.QWEN_OAUTH in self.app.state.functional_backends:
            # Qwen OAuth doesn't use keys in the same way, so we just show model count
            models_list = self.app.state.qwen_oauth_backend.get_available_models()
            models_count = len(models_list)
            backend_info.append(f"qwen-oauth (M:{models_count})")

        backends_str = ", ".join(sorted(backend_info))
        banner_lines = [
            f"Hello, this is {project_name} {project_version}",
            f"Session id: {session_id}",
            f"Functional backends: {backends_str}",
            f"Type {self.config['command_prefix']}help for list of available commands",
        ]
        return "\n".join(banner_lines)

    def _apply_model_defaults(
        self, proxy_state: ProxyState, effective_model: str
    ) -> None:
        """Apply model-specific defaults if configured."""
        if hasattr(self.app.state, "model_defaults") and self.app.state.model_defaults:
            if effective_model in self.app.state.model_defaults:
                proxy_state.apply_model_defaults(
                    effective_model, self.app.state.model_defaults[effective_model]
                )
            else:
                current_backend = proxy_state.get_selected_backend(
                    self.app.state.backend_type
                )
                full_model_name = f"{current_backend}:{effective_model}"
                if full_model_name in self.app.state.model_defaults:
                    proxy_state.apply_model_defaults(
                        full_model_name, self.app.state.model_defaults[full_model_name]
                    )

    def _inject_proxy_parameters(
        self,
        request_data: models.ChatCompletionRequest,
        proxy_state: ProxyState,
        current_backend_type: str,
    ) -> None:
        """Inject proxy state parameters into the request."""
        # Reasoning parameters
        if proxy_state.reasoning_effort:
            request_data.reasoning_effort = proxy_state.reasoning_effort

        if proxy_state.reasoning_config:
            request_data.reasoning = proxy_state.reasoning_config

        # Gemini-specific parameters
        if proxy_state.thinking_budget:
            request_data.thinking_budget = proxy_state.thinking_budget

        if proxy_state.gemini_generation_config:
            request_data.generation_config = proxy_state.gemini_generation_config

        # Temperature
        if proxy_state.temperature is not None and request_data.temperature is None:
            request_data.temperature = proxy_state.temperature

        # Provider-specific parameter handling
        if current_backend_type == BackendType.OPENROUTER:
            if not request_data.extra_params:
                request_data.extra_params = {}

            if (
                proxy_state.reasoning_effort
                and "reasoning_effort" not in request_data.extra_params
            ):
                request_data.extra_params["reasoning_effort"] = (
                    proxy_state.reasoning_effort
                )

            if (
                proxy_state.reasoning_config
                and "reasoning" not in request_data.extra_params
            ):
                request_data.extra_params["reasoning"] = proxy_state.reasoning_config

        elif current_backend_type in GEMINI_BACKENDS:
            if not request_data.extra_params:
                request_data.extra_params = {}

            if (
                proxy_state.thinking_budget
                and "generationConfig" not in request_data.extra_params
            ):
                request_data.extra_params["generationConfig"] = {
                    "thinkingConfig": {"thinkingBudget": proxy_state.thinking_budget}
                }

            if proxy_state.gemini_generation_config:
                if "generationConfig" not in request_data.extra_params:
                    request_data.extra_params["generationConfig"] = {}
                request_data.extra_params["generationConfig"].update(
                    proxy_state.gemini_generation_config
                )

    async def _call_backend_with_failover(
        self,
        request_data: models.ChatCompletionRequest,
        processed_messages: list[models.ChatMessage],
        effective_model: str,
        current_backend_type: str,
        proxy_state: ProxyState,
        perf_metrics: Any,
    ) -> tuple[dict[str, Any] | StreamingResponse, str, str]:
        """Call backend with failover logic."""

        # Build attempts list for failover
        attempts = self._build_failover_attempts(
            effective_model, current_backend_type, proxy_state
        )

        last_error: HTTPException | None = None
        response_from_backend = None
        used_backend = current_backend_type
        used_model = effective_model
        success = False

        while not success:
            earliest_retry: float | None = None
            attempted_any = False

            for b_attempt, m_attempt, kname_attempt, key_attempt in attempts:
                logger.debug(
                    f"Attempting backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt}"
                )

                # Check rate limits
                retry_ts = self.app.state.rate_limits.get(
                    b_attempt, m_attempt, kname_attempt
                )
                if retry_ts:
                    earliest_retry = (
                        retry_ts
                        if earliest_retry is None or retry_ts < earliest_retry
                        else earliest_retry
                    )
                    last_error = HTTPException(
                        status_code=429,
                        detail={
                            "message": "Backend rate limited",
                            "retry_after": int(retry_ts - time.time()),
                        },
                    )
                    continue

                try:
                    attempted_any = True
                    response_from_backend = await self._call_single_backend(
                        b_attempt,
                        m_attempt,
                        kname_attempt,
                        key_attempt,
                        request_data,
                        processed_messages,
                        proxy_state,
                    )
                    used_backend = b_attempt
                    used_model = m_attempt
                    success = True
                    logger.debug(
                        f"Attempt successful for backend: {b_attempt}, model: {m_attempt}"
                    )

                    # Clear oneoff route after successful backend call
                    if proxy_state.oneoff_backend or proxy_state.oneoff_model:
                        proxy_state.clear_oneoff_route()

                    break

                except HTTPException as e:
                    logger.debug(
                        f"Attempt failed for backend: {b_attempt}, model: {m_attempt}, error: {e.detail}"
                    )
                    last_error = e

                    # Handle rate limiting
                    if e.status_code == 429:
                        delay = parse_retry_delay(e.detail)
                        if delay:
                            self.app.state.rate_limits.set(
                                b_attempt, m_attempt, kname_attempt, delay
                            )

                    continue

            if not success:
                if not attempted_any and earliest_retry:
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "message": "All backends rate limited",
                            "retry_after": int(earliest_retry - time.time()),
                        },
                    )
                elif last_error:
                    raise last_error
                else:
                    raise HTTPException(
                        status_code=500, detail="All backend attempts failed"
                    )

        if response_from_backend is not None:
            return response_from_backend, used_backend, used_model
        else:
            raise HTTPException(
                status_code=500, detail="No valid response from backend"
            )

    def _build_failover_attempts(
        self, effective_model: str, current_backend_type: str, proxy_state: ProxyState
    ) -> list[tuple[str, str, str, str]]:
        """Build list of backend attempts for failover."""
        route = proxy_state.failover_routes.get(effective_model)
        if not route:
            return [self._default_attempt(current_backend_type, effective_model)]

        elements = route.get("elements", [])
        elems = self._normalize_elements(elements)
        policy = route.get("policy", "k")

        if policy == "k" and elems:
            return self._attempts_for_single_backend(elems[0])
        if policy == "m":
            return self._attempts_for_models(elems)
        if policy == "km":
            return self._attempts_for_all_keys_all_models(elems)
        if policy == "mk":
            return self._attempts_round_robin_keys(elems)
        return [self._default_attempt(current_backend_type, effective_model)]

    def _normalize_elements(self, elements: Any) -> list[str]:
        if isinstance(elements, dict):
            return list(elements.values())
        if isinstance(elements, list):
            return elements
        return []

    def _default_attempt(self, backend: str, model: str) -> tuple[str, str, str, str]:
        keys = _keys_for(self.config, backend)
        if not keys:
            raise HTTPException(
                status_code=500,
                detail=f"No API keys configured for the default backend: {backend}",
            )
        kname, key_val = keys[0]
        return (backend, model, kname, key_val)

    def _attempts_for_single_backend(
        self, element: str
    ) -> list[tuple[str, str, str, str]]:
        backend, model = element.split(":", 1)
        return [
            (backend, model, kname, key)
            for kname, key in _keys_for(self.config, backend)
        ]

    def _attempts_for_models(
        self, elements: list[str]
    ) -> list[tuple[str, str, str, str]]:
        attempts: list[tuple[str, str, str, str]] = []
        for el in elements:
            backend, model = el.split(":", 1)
            keys = _keys_for(self.config, backend)
            if keys:
                kname, key_val = keys[0]
                attempts.append((backend, model, kname, key_val))
        return attempts

    def _attempts_for_all_keys_all_models(
        self, elements: list[str]
    ) -> list[tuple[str, str, str, str]]:
        attempts: list[tuple[str, str, str, str]] = []
        for el in elements:
            backend, model = el.split(":", 1)
            for kname, key_val in _keys_for(self.config, backend):
                attempts.append((backend, model, kname, key_val))
        return attempts

    def _attempts_round_robin_keys(
        self, elements: list[str]
    ) -> list[tuple[str, str, str, str]]:
        attempts: list[tuple[str, str, str, str]] = []
        backends_used = {el.split(":", 1)[0] for el in elements}
        key_map = {b: _keys_for(self.config, b) for b in backends_used}
        max_len = max((len(v) for v in key_map.values()), default=0)
        for i in range(max_len):
            for el in elements:
                backend, model = el.split(":", 1)
                if i < len(key_map.get(backend, [])):
                    kname, key_val = key_map[backend][i]
                    attempts.append((backend, model, kname, key_val))
        return attempts

    async def _call_single_backend(
        self,
        backend_type: str,
        model: str,
        key_name: str,
        api_key: str,
        request_data: models.ChatCompletionRequest,
        processed_messages: list[models.ChatMessage],
        proxy_state: ProxyState,
    ) -> dict[str, Any] | StreamingResponse:
        """Call a single backend."""

        # Create accounting tracker
        username = "anonymous"  # This would be extracted from request headers

        @asynccontextmanager
        async def no_op_tracker() -> AsyncGenerator[TrackerProtocol, None]:
            class DummyTracker(TrackerProtocol):
                def set_response(self, *args: Any, **kwargs: Any) -> None:
                    pass

                def set_response_headers(self, *args: Any, **kwargs: Any) -> None:
                    pass

                def set_cost(self, *args: Any, **kwargs: Any) -> None:
                    pass

                def set_completion_id(self, *args: Any, **kwargs: Any) -> None:
                    pass

            yield DummyTracker()

        messages_dict = [msg.model_dump() for msg in processed_messages]
        tracker_context = (
            track_llm_request(
                model=model,
                backend=backend_type,
                messages=messages_dict,
                username=username,
                project=proxy_state.project,
                session="default",  # This would be passed in
                caller_name=f"{backend_type}_backend",
            )
            if not self.app.state.disable_accounting
            else no_op_tracker()
        )

        async with tracker_context as tracker:
            if backend_type == BackendType.GEMINI:
                return await self._call_gemini_backend(
                    request_data,
                    processed_messages,
                    model,
                    key_name,
                    api_key,
                    proxy_state,
                    tracker,
                )
            elif backend_type in [GEMINI_CLI_DIRECT, GEMINI_CLI_BATCH]:
                return await self._call_gemini_cli_direct_backend(
                    request_data, processed_messages, model, proxy_state, tracker
                )
            elif backend_type == GEMINI_CLI_INTERACTIVE:
                return await self._call_gemini_cli_interactive_backend(
                    request_data, processed_messages, model, proxy_state, tracker
                )
            else:  # OpenRouter
                return await self._call_openrouter_backend(
                    request_data,
                    processed_messages,
                    model,
                    key_name,
                    api_key,
                    proxy_state,
                    tracker,
                )

    async def _call_gemini_backend(
        self,
        request_data: models.ChatCompletionRequest,
        processed_messages: list[models.ChatMessage],
        model: str,
        key_name: str,
        api_key: str,
        proxy_state: ProxyState,
        tracker: TrackerProtocol,
    ) -> dict[str, Any] | StreamingResponse:
        """Call Gemini backend."""
        backend_result = await self.app.state.gemini_backend.chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=model,
            project=proxy_state.project,
            gemini_api_base_url=self.config["gemini_api_base_url"],
            key_name=key_name,
            api_key=api_key,
        )
        if isinstance(backend_result, tuple):
            result, response_headers = backend_result
            tracker.set_response(result)
            tracker.set_response_headers(response_headers)
        else:
            result = backend_result
            tracker.set_response(result)

        logger.debug(f"Result from Gemini backend chat_completions: {result}")
        return cast(dict[str, Any] | StreamingResponse, result)

    async def _call_gemini_cli_direct_backend(
        self,
        request_data: models.ChatCompletionRequest,
        processed_messages: list[models.ChatMessage],
        model: str,
        proxy_state: ProxyState,
        tracker: TrackerProtocol,
    ) -> dict[str, Any] | StreamingResponse:
        """Call Gemini CLI Direct backend."""
        backend_instance = (
            self.app.state.gemini_cli_batch_backend
            if hasattr(self.app.state, "gemini_cli_batch_backend")
            else self.app.state.gemini_cli_direct_backend
        )

        backend_result = await backend_instance.chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=model,
            project=proxy_state.project,
        )
        if isinstance(backend_result, tuple):
            result, response_headers = backend_result
            tracker.set_response(result)
            tracker.set_response_headers(response_headers)
        else:
            result = backend_result
            tracker.set_response(result)

        logger.debug(
            f"Result from Gemini CLI Direct backend chat_completions: {result}"
        )
        return cast(dict[str, Any] | StreamingResponse, result)

    async def _call_gemini_cli_interactive_backend(
        self,
        request_data: models.ChatCompletionRequest,
        processed_messages: list[models.ChatMessage],
        model: str,
        proxy_state: ProxyState,
        tracker: TrackerProtocol,
    ) -> dict[str, Any] | StreamingResponse:
        """Call Gemini CLI Interactive backend."""
        backend_result = (
            await self.app.state.gemini_cli_interactive_backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=model,
                project=proxy_state.project,
            )
        )
        if isinstance(backend_result, tuple):
            result, response_headers = backend_result
            tracker.set_response(result)
            tracker.set_response_headers(response_headers)
        else:
            result = backend_result
            tracker.set_response(result)

        logger.debug(
            f"Result from Gemini CLI Interactive backend chat_completions: {result}"
        )
        return cast(dict[str, Any] | StreamingResponse, result)

    async def _call_openrouter_backend(
        self,
        request_data: models.ChatCompletionRequest,
        processed_messages: list[models.ChatMessage],
        model: str,
        key_name: str,
        api_key: str,
        proxy_state: ProxyState,
        tracker: TrackerProtocol,
    ) -> dict[str, Any] | StreamingResponse:
        """Call OpenRouter backend."""
        backend_result = await self.app.state.openrouter_backend.chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=model,
            openrouter_api_base_url=self.config["openrouter_api_base_url"],
            openrouter_headers_provider=lambda n, k: get_openrouter_headers(
                self.config, k
            ),
            key_name=key_name,
            api_key=api_key,
            project=proxy_state.project,
        )
        if isinstance(backend_result, tuple):
            result, response_headers = backend_result
            tracker.set_response(result)
            tracker.set_response_headers(response_headers)
        else:
            result = backend_result
            tracker.set_response(result)

        logger.debug(f"Result from OpenRouter backend chat_completions: {result}")
        return cast(dict[str, Any] | StreamingResponse, result)

    def _process_backend_response(
        self,
        response_from_backend: dict[str, Any] | StreamingResponse,
        request_data: models.ChatCompletionRequest,
        session: Any,
        proxy_state: ProxyState,
        used_backend: str,
        used_model: str,
        session_id: str,
    ) -> dict[str, Any] | StreamingResponse:
        """Process the response from the backend."""

        # Extract raw prompt for session tracking
        raw_prompt = ""
        if request_data.messages:
            last_msg = request_data.messages[-1]
            if isinstance(last_msg.content, str):
                raw_prompt = last_msg.content
            elif isinstance(last_msg.content, list):
                raw_prompt = " ".join(
                    part.text
                    for part in last_msg.content
                    if isinstance(part, models.MessageContentPartText)
                )

        # Handle streaming response
        if isinstance(response_from_backend, StreamingResponse):
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=used_backend,
                    model=used_model,
                    project=proxy_state.project,
                    parameters=request_data.model_dump(exclude_unset=True),
                    response="<streaming>",
                )
            )
            return response_from_backend

        # Handle dict response
        if isinstance(response_from_backend, dict):
            backend_response_dict = response_from_backend
        elif response_from_backend and hasattr(response_from_backend, "model_dump"):
            backend_response_dict = response_from_backend.model_dump(exclude_none=True)
        else:
            backend_response_dict = {}

        # Ensure valid response structure
        if not isinstance(backend_response_dict, dict):
            logger.warning(
                f"Backend response is not a dictionary: {type(backend_response_dict)}"
            )
            backend_response_dict = {}

        if "choices" not in backend_response_dict:
            backend_response_dict["choices"] = [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "(no response)"},
                    "finish_reason": "error",
                }
            ]

        # Track interaction
        usage_data = backend_response_dict.get("usage")
        session.add_interaction(
            SessionInteraction(
                prompt=raw_prompt,
                handler="backend",
                backend=used_backend,
                model=used_model,
                project=proxy_state.project,
                parameters=request_data.model_dump(exclude_unset=True),
                response=backend_response_dict.get("choices", [{}])[0]
                .get("message", {})
                .get("content"),
                usage=(
                    models.CompletionUsage(**usage_data)
                    if isinstance(usage_data, dict)
                    else None
                ),
            )
        )

        # Reset proxy state flags
        proxy_state.hello_requested = False
        proxy_state.interactive_just_enabled = False

        # Clean up response
        return cast(dict[str, Any], self._remove_none_values(backend_response_dict))

    def _remove_none_values(self, obj: Any) -> Any:
        """Remove None values from response to match expected format."""
        if isinstance(obj, dict):
            return {
                k: self._remove_none_values(v) for k, v in obj.items() if v is not None
            }
        elif isinstance(obj, list):
            return [self._remove_none_values(item) for item in obj]
        else:
            return obj
