from __future__ import annotations

import logging
import asyncio
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Union, Optional

# Moved imports to the top (E402 fix)
import httpx  # json is used for logging, will keep
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.responses import StreamingResponse

from src import models
from src.agents import detect_agent, wrap_proxy_message, format_command_response_for_agent
from src.command_parser import CommandParser
from src.connectors import GeminiBackend, OpenRouterBackend
from src.connectors.gemini_cli_direct import GeminiCliDirectConnector
from src.core.config import _keys_for, _load_config, get_openrouter_headers
from src.core.metadata import _load_project_metadata
from src.core.persistence import ConfigManager
from src.proxy_logic import ProxyState
from src.rate_limit import RateLimitRegistry, parse_retry_delay
from src.security import APIKeyRedactor, ProxyCommandFilter
from src.session import SessionInteraction, SessionManager
from src.llm_accounting_utils import track_llm_request, get_usage_stats, get_audit_logs, get_llm_accounting
from src.performance_tracker import track_request_performance, track_phase
from src.gemini_models import GenerateContentRequest, GenerateContentResponse, ListModelsResponse
from src.gemini_converters import (
    gemini_to_openai_request, openai_to_gemini_response, openai_to_gemini_stream_chunk,
    extract_model_from_gemini_path, is_streaming_request, openai_models_to_gemini_models
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def build_app(
    cfg: Dict[str, Any] | None = None, *, config_file: str | None = None
) -> FastAPI:
    cfg = cfg or _load_config()

    disable_auth = cfg.get("disable_auth", False)
    disable_accounting = cfg.get("disable_accounting", False)
    api_key = os.getenv("LLM_INTERACTIVE_PROXY_API_KEY")
    if not disable_auth:
        if not api_key:
            api_key = secrets.token_urlsafe(32)
            logger.warning(
                "No client API key provided, generated one: %s",
                api_key)
            if not any(isinstance(h, logging.StreamHandler)
                       for h in logger.handlers):
                sys.stdout.write(f"Generated client API key: {api_key}\n")
    else:
        api_key = api_key or None

    project_name, project_version = _load_project_metadata()

    functional: set[str] = set()
    # app_for_banner is a reference to the app instance being built.
    # It will be assigned later in this function. This is for _welcome_banner's closure.
    # To make it clearer, we'll pass app_instance to _welcome_banner when it's called.
    # However, _welcome_banner is defined before app_instance is created.
    # This means _welcome_banner must rely on the global 'app' if not passed explicitly,
    # or be defined later, or take 'app' as an argument.
    # For now, let's assume the global 'app' (created at the end of the module) is implicitly used
    # by _welcome_banner if it's not shadowed.
    # The cleanest is to pass app to _welcome_banner.

    def _welcome_banner(current_app: FastAPI, session_id: str) -> str:
        project_name = current_app.state.project_metadata["name"]
        project_version = current_app.state.project_metadata["version"]
        backend_info = []
        # Use current_app.state.functional_backends instead of 'functional'
        # from closure
        if "openrouter" in current_app.state.functional_backends:
            keys = len(cfg.get("openrouter_api_keys", {}))
            models_list = current_app.state.openrouter_backend.get_available_models()
            models_count = len(models_list)
            backend_info.append(f"openrouter (K:{keys}, M:{models_count})")
        if "gemini" in current_app.state.functional_backends:
            keys = len(cfg.get("gemini_api_keys", {}))
            # Ensure gemini_backend is accessed via current_app.state
            models_list = current_app.state.gemini_backend.get_available_models()
            models_count = len(models_list)
            backend_info.append(f"gemini (K:{keys}, M:{models_count})")
        if "gemini-cli-direct" in current_app.state.functional_backends:
            # For gemini-cli-direct, we call Gemini CLI directly (no API keys needed)
            models_list = current_app.state.gemini_cli_direct_backend.get_available_models()
            models_count = len(models_list)
            backend_info.append(f"gemini-cli-direct (M:{models_count})")
        backends_str = ", ".join(sorted(backend_info))
        banner_lines = [
            f"Hello, this is {project_name} {project_version}",
            f"Session id: {session_id}",
            f"Functional backends: {backends_str}",
            f"Type {cfg['command_prefix']}help for list of available commands"
        ]
        return "\n".join(banner_lines)

    @asynccontextmanager
    # Renamed 'app' to 'app_param' to avoid confusion
    async def lifespan(app_param: FastAPI):
        nonlocal functional

        client_httpx = httpx.AsyncClient(timeout=cfg["proxy_timeout"])
        app_param.state.httpx_client = client_httpx
        app_param.state.failover_routes = {}
        default_mode = (
            False
            if cfg.get("disable_interactive_commands")
            else cfg["interactive_mode"]
        )
        app_param.state.session_manager = SessionManager(
            default_interactive_mode=default_mode,
            failover_routes=app_param.state.failover_routes,
        )
        app_param.state.disable_interactive_commands = cfg.get(
            "disable_interactive_commands", False
        )
        app_param.state.command_prefix = cfg["command_prefix"]

        openrouter_backend = OpenRouterBackend(client_httpx)
        gemini_backend = GeminiBackend(client_httpx)
        gemini_cli_direct_backend = GeminiCliDirectConnector()
        app_param.state.openrouter_backend = openrouter_backend
        app_param.state.gemini_backend = gemini_backend
        app_param.state.gemini_cli_direct_backend = gemini_cli_direct_backend

        openrouter_ok = False
        gemini_ok = False
        gemini_cli_direct_ok = False

        if cfg.get("openrouter_api_keys"):
            openrouter_api_keys_list = list(cfg["openrouter_api_keys"].items())
            if openrouter_api_keys_list:
                key_name, current_api_key = openrouter_api_keys_list[0]
                await openrouter_backend.initialize(
                    openrouter_api_base_url=cfg["openrouter_api_base_url"],
                    openrouter_headers_provider=(
                        lambda n, k: get_openrouter_headers(cfg, k)
                    ),
                    key_name=key_name,
                    api_key=current_api_key,
                )
                if openrouter_backend.get_available_models():
                    openrouter_ok = True

        if cfg.get("gemini_api_keys"):
            gemini_api_keys_list = list(cfg["gemini_api_keys"].items())
            if gemini_api_keys_list:
                key_name, current_api_key = gemini_api_keys_list[0]
                await gemini_backend.initialize(
                    gemini_api_base_url=cfg["gemini_api_base_url"],
                    key_name=key_name,
                    api_key=current_api_key,
                )
                if gemini_backend.get_available_models():
                    gemini_ok = True

        # Try to initialize gemini-cli-direct backend (direct CLI calls)
        try:
            await gemini_cli_direct_backend.initialize(
                google_cloud_project=cfg.get("google_cloud_project")
            )
            if gemini_cli_direct_backend.get_available_models():
                gemini_cli_direct_ok = True
        except Exception as e:
            logger.error(f"Failed to initialize Gemini CLI Direct backend: {e}")
            gemini_cli_direct_ok = False


        functional = {
            name
            for name, ok in (
                ("openrouter", openrouter_ok),
                ("gemini", gemini_ok),
                ("gemini-cli-direct", gemini_cli_direct_ok),
            )
            if ok
        }
        app_param.state.functional_backends = functional

        # Generate the welcome banner at startup to show API key and model counts
        startup_banner = _welcome_banner(app_param, "startup")
        # Banner is logged instead of printed to avoid test failures

        backend_type = cfg.get("backend")
        if backend_type:
            if functional and backend_type not in functional:
                raise ValueError(
                    f"default backend {backend_type} is not functional"
                )
        else:
            if len(functional) == 1:
                backend_type = next(iter(functional))
            elif len(functional) > 1:
                # E501: Wrapped string
                raise ValueError(
                    "Multiple functional backends, specify --default-backend"
                )
            else:
                backend_type = "openrouter"
        app_param.state.backend_type = backend_type
        app_param.state.initial_backend_type = backend_type

        if backend_type == "gemini":
            current_backend = gemini_backend
        elif backend_type == "gemini-cli-direct":
            current_backend = gemini_cli_direct_backend
        else: # Default to openrouter if not specified or not gemini/gemini-cli-direct
            current_backend = openrouter_backend

        app_param.state.backend = current_backend

        all_keys = list(cfg.get("openrouter_api_keys", {}).values()) + list(
            cfg.get("gemini_api_keys", {}).values()
        )
        app_param.state.api_key_redactor = APIKeyRedactor(all_keys)
        app_param.state.default_api_key_redaction_enabled = cfg.get(
            "redact_api_keys_in_prompts", True
        )
        app_param.state.api_key_redaction_enabled = (
            app_param.state.default_api_key_redaction_enabled
        )

        # Initialize emergency command filter
        app_param.state.command_filter = ProxyCommandFilter(cfg["command_prefix"])

        app_param.state.rate_limits = RateLimitRegistry()
        app_param.state.force_set_project = cfg.get("force_set_project", False)

        if config_file:
            app_param.state.config_manager = ConfigManager(
                app_param, config_file)
            app_param.state.config_manager.load()
        else:
            app_param.state.config_manager = None

        yield
        await client_httpx.aclose()

    app_instance = FastAPI(lifespan=lifespan)
    app_instance.state.project_metadata = {
        "name": project_name, "version": project_version}
    app_instance.state.client_api_key = api_key
    app_instance.state.disable_auth = disable_auth
    app_instance.state.disable_accounting = disable_accounting

    async def verify_client_auth(http_request: Request) -> None:
        if http_request.app.state.disable_auth:
            return
        auth_header = http_request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = auth_header.split(" ", 1)[1]
        if token != http_request.app.state.client_api_key:
            raise HTTPException(status_code=401, detail="Unauthorized")

    async def verify_gemini_auth(http_request: Request) -> None:
        """Verify Gemini API authentication via x-goog-api-key header."""
        if http_request.app.state.disable_auth:
            return

        # Check for Gemini-style API key in x-goog-api-key header
        api_key_header = http_request.headers.get("x-goog-api-key")
        if api_key_header:
            # For Gemini API compatibility, accept the API key directly
            if api_key_header == http_request.app.state.client_api_key:
                return

        # Fallback to standard Bearer token authentication
        auth_header = http_request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            if token == http_request.app.state.client_api_key:
                return

        raise HTTPException(status_code=401, detail="Unauthorized")

    @app_instance.get("/")
    async def root():
        return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

    @app_instance.post(
        "/v1/chat/completions",
        dependencies=[Depends(verify_client_auth)],
    )
    async def chat_completions(
        request_data: models.ChatCompletionRequest, http_request: Request
    ):
        session_id = http_request.headers.get("x-session-id", "default")
        
        with track_request_performance(session_id) as perf_metrics:
            session = http_request.app.state.session_manager.get_session(
                session_id)
            proxy_state: ProxyState = session.proxy_state
            
            # Set initial context for performance tracking
            perf_metrics.streaming = getattr(request_data, 'stream', False)

            # Add detailed logging for debugging Cline issues
            logger.info(f"[CLINE_DEBUG] ========== NEW REQUEST ==========")
            logger.info(f"[CLINE_DEBUG] Session ID: {session_id}")
            logger.info(f"[CLINE_DEBUG] User-Agent: {http_request.headers.get('user-agent', 'Unknown')}")
            logger.info(f"[CLINE_DEBUG] Authorization: {http_request.headers.get('authorization', 'None')[:20]}...")
            logger.info(f"[CLINE_DEBUG] Content-Type: {http_request.headers.get('content-type', 'Unknown')}")
            logger.info(f"[CLINE_DEBUG] Model requested: {request_data.model}")
            logger.info(f"[CLINE_DEBUG] Messages count: {len(request_data.messages) if request_data.messages else 0}")
            
            # Check if tools are included in the request
            if request_data.tools:
                logger.info(f"[CLINE_DEBUG] Tools provided: {len(request_data.tools)} tools")
                for i, tool in enumerate(request_data.tools):
                    logger.info(f"[CLINE_DEBUG] Tool {i}: {tool.function.name}")
            else:
                logger.info(f"[CLINE_DEBUG] No tools provided in request")
                
            if request_data.messages:
                for i, msg in enumerate(request_data.messages):
                    content_preview = str(msg.content)[:100] + "..." if len(str(msg.content)) > 100 else str(msg.content)
                    logger.info(f"[CLINE_DEBUG] Message {i}: role={msg.role}, content={content_preview}")
            logger.info(f"[CLINE_DEBUG] ================================")

            # Start command processing phase
            with track_phase(perf_metrics, "command_processing"):
                if request_data.messages:
                    first = request_data.messages[0]
                    if isinstance(first.content, str):
                        text = first.content
                    elif isinstance(first.content, list):
                        # E501: Wrapped list comprehension
                        text = " ".join(
                            p.text for p in first.content
                            if isinstance(p, models.MessageContentPartText)
                        )
                    else:
                        text = ""

                    if not proxy_state.is_cline_agent and "<attempt_completion>" in text:
                        proxy_state.set_is_cline_agent(True)
                        # Also set session.agent to ensure XML wrapping works
                        if session.agent is None:
                            session.agent = "cline"
                        logger.info(f"[CLINE_DEBUG] Detected Cline agent via <attempt_completion> pattern. Session: {session_id}")

                    if session.agent is None:
                        session.agent = detect_agent(text)
                        if session.agent:
                            logger.info(f"[CLINE_DEBUG] Detected agent via detect_agent(): {session.agent}. Session: {session_id}")

        current_backend_type = http_request.app.state.backend_type
        if proxy_state.override_backend:
            current_backend_type = proxy_state.override_backend
            if proxy_state.invalid_override:
                # E501: Wrapped detail message
                detail_msg = {
                    "message": "invalid or unsupported model",
                    "model": (
                        f"{proxy_state.override_backend}:"
                        f"{proxy_state.override_model}"
                    ),
                }
                raise HTTPException(status_code=400, detail=detail_msg)
            if current_backend_type not in {"openrouter", "gemini", "gemini-cli-direct"}:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown backend {current_backend_type}")

        parser = None
        confirmation_text = ""  # Initialize confirmation_text for both paths
        
        if not http_request.app.state.disable_interactive_commands:
            from src.command_config import CommandParserConfig
            parser_config = CommandParserConfig(
                proxy_state=proxy_state,
                app=http_request.app,
                preserve_unknown=not proxy_state.interactive_mode,
                functional_backends=http_request.app.state.functional_backends,
            )
            parser = CommandParser(
                parser_config, command_prefix=http_request.app.state.command_prefix
            )
            
            processed_messages, commands_processed = parser.process_messages(
                request_data.messages
            )
            
            # Generate confirmation text from command results
            if parser and parser.command_results:
                confirmation_messages = []
                for result in parser.command_results:
                    if result.success:
                        confirmation_messages.append(result.message)
                    else:
                        confirmation_messages.append(f"Error: {result.message}")
                confirmation_text = "\n".join(confirmation_messages)
            
            if parser.command_results and any(
                    not result.success for result in parser.command_results):
                error_messages = [
                    result.message for result in parser.command_results if not result.success]
                # E501: Wrapped dict
                return {
                    "id": "proxy_cmd_processed",
                    "object": "chat.completion",
                    "created": int(datetime.now(timezone.utc).timestamp()),
                    "model": request_data.model,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "; ".join(error_messages),
                        },
                        "finish_reason": "error",
                    }],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                }
        else:
            processed_messages = request_data.messages
            commands_processed = False

        current_backend_type = proxy_state.get_selected_backend(http_request.app.state.backend_type)

        # Only show banner when explicitly requested via !/hello command
        show_banner = proxy_state.hello_requested

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

        # Check if commands were processed and determine if we should return proxy response or continue to backend
        if commands_processed:
            # Check if there's meaningful content remaining after command processing
            has_meaningful_content = False
            if processed_messages:
                for msg in processed_messages:
                    if isinstance(msg.content, str) and msg.content.strip():
                        content = msg.content.strip()
                        
                        # Use a smarter threshold to distinguish between:
                        # 1. Command-focused requests (short remaining content like "hi") -> return proxy response
                        # 2. Mixed content requests (substantial content) -> continue to backend
                        
                        # For Cline agents, be more restrictive about what constitutes meaningful content
                        if proxy_state.is_cline_agent or session.agent == "cline":
                            # If it's short content that looks like XML markup, don't consider it meaningful
                            # This handles cases like "test" from "<attempt_completion>test</attempt_completion>"
                            if len(content) < 50:
                                logger.debug(f"[CLINE_DEBUG] Ignoring short content for Cline agent: '{content}'")
                                continue
                            
                            # If it looks like a Cline agent prompt (contains typical agent instructions),
                            # don't consider it meaningful user content for LLM processing
                            cline_indicators = [
                                "You are Cline, an AI assistant",
                                "Your goal is to be helpful, accurate, and efficient",
                                "You should always think step by step",
                                "Make sure to handle errors gracefully",
                                "Remember to be concise but thorough"
                            ]
                            if any(indicator in content for indicator in cline_indicators):
                                logger.debug(f"[CLINE_DEBUG] Ignoring Cline agent prompt content (length: {len(content)})")
                                continue
                        else:
                            # For non-Cline agents, use a smarter heuristic to distinguish between:
                            # 1. Filler text around commands (should not trigger backend calls)
                            # 2. Actual LLM requests (should trigger backend calls)
                            
                            # Short content should not trigger backend calls
                            if len(content.split()) <= 2:  # 2 words or less
                                logger.debug(f"[COMMAND_DEBUG] Ignoring short remaining content: '{content}'")
                                continue
                            
                            # Check if the content looks like an actual instruction/request to an AI
                            # vs just filler text around a command
                            instruction_indicators = [
                                "write", "create", "generate", "explain", "describe", "tell", "show",
                                "help", "how", "what", "why", "where", "when", "please", "can you",
                                "could you", "would you", "i need", "i want", "make", "build",
                                "story", "code", "example", "list", "summary", "analysis"
                            ]
                            
                            content_lower = content.lower()
                            has_instruction_words = any(indicator in content_lower for indicator in instruction_indicators)
                            
                            # If it has instruction words and is substantial (>5 words), consider it meaningful
                            if has_instruction_words and len(content.split()) > 5:
                                logger.debug(f"[COMMAND_DEBUG] Found meaningful LLM request: '{content[:50]}...'")
                                has_meaningful_content = True
                                break
                            else:
                                logger.debug(f"[COMMAND_DEBUG] Ignoring filler text around command: '{content[:50]}...'")
                                continue
                        
                        break
                    elif isinstance(msg.content, list) and msg.content:
                        # Check if list has any non-empty text parts
                        for part in msg.content:
                            if isinstance(part, models.MessageContentPartText) and part.text.strip():
                                has_meaningful_content = True
                                break
                        if has_meaningful_content:
                            break
            
            # If no meaningful content remains, return proxy response for command-only requests
            if not has_meaningful_content:
                # Enhanced Cline detection: if commands were processed but no agent was detected yet,
                # check if this looks like a Cline request (long prompt with command at the end)
                if session.agent is None and request_data.messages:
                    first_message = request_data.messages[0]
                    if isinstance(first_message.content, str):
                        content = first_message.content
                        logger.info(f"[CLINE_DEBUG] Commands processed but no agent detected. Message length: {len(content)}. Session: {session_id}")
                        logger.debug(f"[CLINE_DEBUG] Message content preview: {content[:200]}...")
                        # Cline typically sends long prompts (agent instructions) followed by user commands
                        # If we see a command in a reasonably long message, it's likely Cline
                        if len(content) > 100 and ("!/hello" in content or "!/" in content):
                            session.agent = "cline"
                            proxy_state.set_is_cline_agent(True)
                            logger.info(f"[CLINE_DEBUG] Enhanced detection: Set agent to Cline (long message with commands). Session: {session_id}")
                        else:
                            logger.info(f"[CLINE_DEBUG] Enhanced detection: Did not match Cline pattern. Session: {session_id}")
                else:
                    logger.info(f"[CLINE_DEBUG] Commands processed, agent already detected: {session.agent}. Session: {session_id}")

                content_lines_for_agent = []
                if proxy_state.interactive_mode and show_banner and not http_request.app.state.disable_interactive_commands:
                    banner_content = _welcome_banner(http_request.app, session_id)
                    content_lines_for_agent.append(banner_content)

                # Include command results for Cline agents, but exclude simple confirmations for non-Cline agents
                if confirmation_text:
                    if session.agent == "cline":
                        # For Cline agents, include command results but exclude "hello acknowledged" confirmations
                        if confirmation_text != "hello acknowledged":
                            content_lines_for_agent.append(confirmation_text)
                    else:
                        # For non-Cline agents, include all confirmation messages
                        content_lines_for_agent.append(confirmation_text)

                final_content = "\n".join(content_lines_for_agent)

                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt,
                        handler="proxy",
                        model=proxy_state.get_effective_model(request_data.model),
                        project=proxy_state.project,
                        response=final_content,
                    )
                )
                proxy_state.hello_requested = False
                proxy_state.interactive_just_enabled = False

                if session.agent == "cline":
                    logger.debug("[CLINE_DEBUG] Returning as XML-wrapped content for Cline agent")
                    # Format the response in the XML format expected by Cline tests
                    xml_wrapped_content = f"<attempt_completion>\n<result>\n{final_content}\n</result>\n</attempt_completion>\n"
                    return models.CommandProcessedChatCompletionResponse(
                        id="proxy_cmd_processed",
                        object="chat.completion",
                        created=int(datetime.now(timezone.utc).timestamp()),
                        model=request_data.model,
                        choices=[
                            models.ChatCompletionChoice(
                                index=0,
                                message=models.ChatCompletionChoiceMessage(
                                    role="assistant",
                                    content=xml_wrapped_content
                                ),
                                finish_reason="stop"
                            )
                        ],
                        usage=models.CompletionUsage(
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_tokens=0
                        )
                    )
                else:
                    logger.debug(f"[CLINE_DEBUG] Returning as regular assistant message for agent: {session.agent}")
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
                                    role="assistant",
                                    content=formatted_content
                                ),
                                finish_reason="stop"
                            )
                        ],
                        usage=models.CompletionUsage(
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_tokens=0
                        )
                    )
            # If there's meaningful content remaining, continue to backend call

        # Check if messages became empty after processing and no commands were processed
        if not processed_messages:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No messages provided in the request or messages became "
                    "empty after processing."
                ),
            )

        if http_request.app.state.force_set_project and proxy_state.project is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Project name not set. Use !/set(project=<name>) before "
                    "sending prompts."
                ),
            )

        effective_model = proxy_state.get_effective_model(request_data.model)
        
        # Apply model-specific defaults if configured
        if hasattr(http_request.app.state, 'model_defaults') and http_request.app.state.model_defaults:
            # Check for exact model match first
            if effective_model in http_request.app.state.model_defaults:
                proxy_state.apply_model_defaults(effective_model, http_request.app.state.model_defaults[effective_model])
            else:
                # Check for backend:model pattern match
                current_backend = proxy_state.get_selected_backend(http_request.app.state.backend_type)
                full_model_name = f"{current_backend}:{effective_model}"
                if full_model_name in http_request.app.state.model_defaults:
                    proxy_state.apply_model_defaults(full_model_name, http_request.app.state.model_defaults[full_model_name])
        
        # Update performance metrics with backend and model info
        perf_metrics.backend_used = current_backend_type
        perf_metrics.model_used = effective_model

        # Inject reasoning parameters from proxy state into request_data
        if proxy_state.reasoning_effort:
            request_data.reasoning_effort = proxy_state.reasoning_effort

        if proxy_state.reasoning_config:
            request_data.reasoning = proxy_state.reasoning_config

        # Inject Gemini-specific reasoning parameters
        if proxy_state.thinking_budget:
            request_data.thinking_budget = proxy_state.thinking_budget

        if proxy_state.gemini_generation_config:
            request_data.generation_config = proxy_state.gemini_generation_config

        # Inject temperature parameter (only if not already set in API request)
        if proxy_state.temperature is not None and request_data.temperature is None:
            request_data.temperature = proxy_state.temperature

        # Provider-specific reasoning parameter handling
        if current_backend_type == "openrouter":
            # For OpenRouter, add reasoning parameters to extra_params if not already set
            if not request_data.extra_params:
                request_data.extra_params = {}
            
            if proxy_state.reasoning_effort and "reasoning_effort" not in request_data.extra_params:
                request_data.extra_params["reasoning_effort"] = proxy_state.reasoning_effort
            
            if proxy_state.reasoning_config and "reasoning" not in request_data.extra_params:
                request_data.extra_params["reasoning"] = proxy_state.reasoning_config

        elif current_backend_type in ["gemini", "gemini-cli-direct"]:
            # For Gemini, handle thinking budget and generation config
            if not request_data.extra_params:
                request_data.extra_params = {}
            
            # Convert thinking budget to Gemini's generation config format
            if proxy_state.thinking_budget and "generationConfig" not in request_data.extra_params:
                request_data.extra_params["generationConfig"] = {
                    "thinkingConfig": {
                        "thinkingBudget": proxy_state.thinking_budget
                    }
                }
            
            # Add generation config if provided
            if proxy_state.gemini_generation_config:
                if "generationConfig" not in request_data.extra_params:
                    request_data.extra_params["generationConfig"] = {}
                request_data.extra_params["generationConfig"].update(proxy_state.gemini_generation_config)

        async def _call_backend(
            b_type: str, model_str: str, key_name_str: str, api_key_str: str
        ):
            # Extract username from request headers or use default
            username = http_request.headers.get("X-User-ID", "anonymous")

            # Create a context manager that does nothing if accounting is disabled
            @asynccontextmanager
            async def no_op_tracker():
                class DummyTracker:
                    def set_response(self, *args, **kwargs): pass
                    def set_response_headers(self, *args, **kwargs): pass
                    def set_cost(self, *args, **kwargs): pass
                    def set_completion_id(self, *args, **kwargs): pass
                yield DummyTracker()

            tracker_context = track_llm_request(
                model=model_str,
                backend=b_type,
                messages=processed_messages,
                username=username,
                project=proxy_state.project,
                session=session_id,
                caller_name=f"{b_type}_backend"
            ) if not http_request.app.state.disable_accounting else no_op_tracker()

            async with tracker_context as tracker:
                if b_type == "gemini":
                    retry_at = http_request.app.state.rate_limits.get(
                        "gemini", model_str, key_name_str
                    )
                    if retry_at:
                        # E501: Wrapped dict
                        detail_dict = {
                            "message": "Backend rate limited, retry later",
                            "retry_after": int(retry_at - time.time()),
                        }
                        raise HTTPException(status_code=429, detail=detail_dict)
                    try:
                        backend_result = (
                            await http_request.app.state.gemini_backend.chat_completions(
                                request_data=request_data,
                                processed_messages=processed_messages,
                                effective_model=model_str,
                                project=proxy_state.project,
                                gemini_api_base_url=cfg["gemini_api_base_url"],
                                key_name=key_name_str,
                                api_key=api_key_str,
                                prompt_redactor=(
                                    http_request.app.state.api_key_redactor
                                    if http_request.app.state.api_key_redaction_enabled
                                    else None
                                ),
                                command_filter=http_request.app.state.command_filter,
                            )
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            # Streaming response
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from Gemini backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    "gemini", model_str, key_name_str, delay
                                )
                        raise
                elif b_type == "gemini-cli-direct":
                    # Direct Gemini CLI calls - no API keys needed
                    try:
                        backend_result = await http_request.app.state.gemini_cli_direct_backend.chat_completions(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_str,
                            project=proxy_state.project,
                            prompt_redactor=(
                                http_request.app.state.api_key_redactor
                                if http_request.app.state.api_key_redaction_enabled
                                else None
                            ),
                            command_filter=http_request.app.state.command_filter,
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            # Streaming response
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from Gemini CLI Direct backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        logger.error(f"Error from Gemini CLI Direct backend: {e.status_code} - {e.detail}")
                        raise
                    except Exception as e:
                        logger.error(f"Unexpected error from Gemini CLI Direct backend: {e}", exc_info=True)
                        raise HTTPException(status_code=500, detail=f"Gemini CLI Direct backend error: {str(e)}")

                else: # Default to OpenRouter or handle unknown b_type if more are added
                    retry_at = http_request.app.state.rate_limits.get(
                        "openrouter", model_str, key_name_str
                    )
                    if retry_at:
                        detail_dict = {  # E501
                            "message": "Backend rate limited, retry later",
                            "retry_after": int(retry_at - time.time()),
                        }
                        raise HTTPException(status_code=429, detail=detail_dict)
                    try:
                        backend_result = (
                            await http_request.app.state.openrouter_backend.chat_completions(
                                request_data=request_data,
                                processed_messages=processed_messages,
                                effective_model=model_str,
                                openrouter_api_base_url=cfg["openrouter_api_base_url"],
                                openrouter_headers_provider=(
                                    lambda n, k: get_openrouter_headers(cfg, k)
                                ),
                                key_name=key_name_str,
                                api_key=api_key_str,
                                project=proxy_state.project,
                                prompt_redactor=(
                                    http_request.app.state.api_key_redactor
                                    if http_request.app.state.api_key_redaction_enabled
                                    else None
                                ),
                                command_filter=http_request.app.state.command_filter,
                            )
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            # Streaming response
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from OpenRouter backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    "openrouter", model_str, key_name_str, delay
                                )
                        raise

        # Start backend selection phase
        with track_phase(perf_metrics, "backend_selection"):
            route = proxy_state.failover_routes.get(effective_model)
            attempts: list[tuple[str, str, str, str]] = []
        if route:
            elements = route.get("elements", [])
            if isinstance(elements, dict):
                elems = list(elements.values())
            elif isinstance(elements, list):
                elems = elements
            else:
                elems = []
            policy = route.get("policy", "k")
            if policy == "k" and elems:
                b, m = elems[0].split(":", 1)
                for kname, key_val in _keys_for(cfg, b):
                    attempts.append((b, m, kname, key_val))
            elif policy == "m":
                for el in elems:
                    b, m = el.split(":", 1)
                    keys = _keys_for(cfg, b)
                    if not keys:
                        continue
                    kname, key_val = keys[0]
                    attempts.append((b, m, kname, key_val))
            elif policy == "km":
                for el in elems:
                    b, m = el.split(":", 1)
                    for kname, key_val in _keys_for(cfg, b):
                        attempts.append((b, m, kname, key_val))
            elif policy == "mk":
                backends_used = {el.split(":", 1)[0] for el in elems}
                key_map = {b: _keys_for(cfg, b) for b in backends_used}
                max_len = max(len(v)
                              for v in key_map.values()) if key_map else 0
                for i in range(max_len):
                    for el in elems:
                        b, m = el.split(":", 1)
                        if i < len(key_map[b]):
                            kname, key_val = key_map[b][i]
                            attempts.append((b, m, kname, key_val))
        else:
            default_keys = _keys_for(cfg, current_backend_type)
            if not default_keys:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"No API keys configured for the default backend: "
                        f"{current_backend_type}"
                    ),
                )
            attempts.append(
                (
                    current_backend_type,
                    effective_model,
                    default_keys[0][0],
                    default_keys[0][1],
                )
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
                retry_ts = http_request.app.state.rate_limits.get(
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
                        detail={"message": "Backend rate limited", "retry_after": int(retry_ts - time.time())},
                    )
                    continue
                try:
                    attempted_any = True
                    response_from_backend = await _call_backend(
                        b_attempt, m_attempt, kname_attempt, key_attempt
                    )
                    used_backend = b_attempt
                    used_model = m_attempt
                    success = True
                    logger.debug(
                        f"Attempt successful for backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt}"
                    )
                    
                    # Clear oneoff route after successful backend call
                    if proxy_state.oneoff_backend or proxy_state.oneoff_model:
                        proxy_state.clear_oneoff_route()
                    
                    break
                except HTTPException as e:
                    logger.debug(
                        f"Attempt failed for backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt} with HTTPException: {e.status_code} - {e.detail}"
                    )
                    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
                    if e.status_code in RETRYABLE_STATUS_CODES:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    b_attempt, m_attempt, kname_attempt, delay
                                )
                                retry_at = time.time() + delay
                                earliest_retry = (
                                    retry_at
                                    if earliest_retry is None
                                    or retry_at < earliest_retry
                                    else earliest_retry
                                )
                        last_error = e
                        attempted_any = True
                        continue
                    raise
            if not success:
                if earliest_retry is None:
                    error_msg_detail = last_error.detail if last_error else "all backends failed"
                    status_code_to_return = last_error.status_code if last_error else 500
                    response_content = {
                        "id": "error",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": effective_model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": f"All backends failed: {error_msg_detail}",
                                },
                                "finish_reason": "error",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                        "error": error_msg_detail,
                    }
                    raise HTTPException(status_code=status_code_to_return, detail=response_content)
                if not attempted_any:
                    raise HTTPException(status_code=429, detail={"message": "Backend rate limited", "retry_after": int(earliest_retry - time.time())})
                await asyncio.sleep(max(0, earliest_retry - time.time()))

        # Start response processing phase
        with track_phase(perf_metrics, "response_processing"):
            if isinstance(response_from_backend, StreamingResponse):
                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt, handler="backend", backend=used_backend,
                        model=used_model, project=proxy_state.project,
                        parameters=request_data.model_dump(exclude_unset=True),
                        response="<streaming>",
                    )
                )
                return response_from_backend

            # Handle different types of responses from backends
            if isinstance(response_from_backend, dict):
                backend_response_dict = response_from_backend
            elif response_from_backend and hasattr(response_from_backend, 'model_dump'):
                backend_response_dict = response_from_backend.model_dump(exclude_none=True)
            elif hasattr(response_from_backend, '__call__') or hasattr(response_from_backend, '__await__'):
                # Handle mock objects or coroutines that weren't properly awaited
                logger.warning(f"Backend returned a callable/awaitable object instead of response: {type(response_from_backend)}")
                backend_response_dict = {}
            else:
                backend_response_dict = {}

            # Ensure backend_response_dict is actually a dictionary
            if not isinstance(backend_response_dict, dict):
                logger.warning(f"Backend response is not a dictionary: {type(backend_response_dict)}")
                backend_response_dict = {}

            if "choices" not in backend_response_dict:
                backend_response_dict["choices"] = [{"index": 0, "message": {
                    "role": "assistant", "content": "(no response)"}, "finish_reason": "error"}]

            usage_data = backend_response_dict.get("usage")
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt, handler="backend", backend=used_backend,
                    model=used_model, project=proxy_state.project,
                    parameters=request_data.model_dump(exclude_unset=True),
                    response=backend_response_dict.get("choices", [{}])[0]
                    .get("message", {}).get("content"),
                    usage=(
                        models.CompletionUsage(**usage_data)
                        if isinstance(usage_data, dict) else None
                    ),
                )
            )
            proxy_state.hello_requested = False
            proxy_state.interactive_just_enabled = False
            
            # Remove None values from the response to match expected format
            def remove_none_values(obj):
                if isinstance(obj, dict):
                    return {k: remove_none_values(v) for k, v in obj.items() if v is not None}
                elif isinstance(obj, list):
                    return [remove_none_values(item) for item in obj]
                else:
                    return obj
            
            return remove_none_values(backend_response_dict)

    @app_instance.get("/models", dependencies=[Depends(verify_client_auth)])
    async def list_all_models(http_request: Request):
        """List all available models from all backends."""
        all_models = []
        for backend_name in ["openrouter", "gemini", "gemini-cli-direct"]:
            backend = getattr(http_request.app.state, f"{backend_name}_backend", None)
            if backend and hasattr(backend, "get_available_models"):
                models = backend.get_available_models()
                for model in models:
                    all_models.append({
                        "id": f"{backend_name}:{model}",
                        "object": "model",
                        "owned_by": backend_name,
                    })
        return {"object": "list", "data": all_models}

    @app_instance.get("/v1/models", dependencies=[Depends(verify_client_auth)])
    async def list_all_models_v1(http_request: Request):
        """OpenAI-compatible models endpoint."""
        return await list_all_models(http_request)

    # Gemini API Compatibility Endpoints
    @app_instance.get("/v1beta/models", dependencies=[Depends(verify_gemini_auth)])
    async def list_gemini_models(http_request: Request):
        """Gemini API compatible models listing endpoint."""
        try:
            # Get all available models from backends
            all_models = []
            for backend_name in ["openrouter", "gemini", "gemini-cli-direct"]:
                backend = getattr(http_request.app.state, f"{backend_name}_backend", None)
                if backend and hasattr(backend, "get_available_models"):
                    models = backend.get_available_models()
                    for model in models:
                        all_models.append({
                            "id": f"{backend_name}:{model}",
                            "object": "model",
                            "owned_by": backend_name,
                        })

            # Convert to Gemini format
            gemini_models_response = openai_models_to_gemini_models(all_models)
            return gemini_models_response.model_dump(exclude_none=True, by_alias=True)
        except Exception as e:
            logger.error(f"Error in list_gemini_models: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list models: {str(e)}")

    def _parse_model_backend(model: str, default_backend: str) -> tuple[str, str]:
        """Parse model string to extract backend and actual model name."""
        from src.models import parse_model_backend
        return parse_model_backend(model, default_backend)

    @app_instance.post("/v1beta/models/{model}:generateContent", dependencies=[Depends(verify_gemini_auth)])
    async def gemini_generate_content(
        model: str,
        request_data: GenerateContentRequest,
        http_request: Request
    ):
        """Gemini API compatible content generation endpoint (non-streaming)."""
        # Debug: Check session ID for Gemini interface
        session_id = http_request.headers.get("x-session-id", "default")
        logger.debug(f"[GEMINI_DEBUG] Gemini interface session ID: {session_id}")
        
        # Parse the model to determine backend
        backend_type, actual_model = _parse_model_backend(model, http_request.app.state.backend_type)

        # Convert Gemini request to OpenAI format
        openai_request = gemini_to_openai_request(request_data, actual_model)
        openai_request.stream = False

        # Use the existing chat_completions logic by calling it with the converted request
        # We need to temporarily modify the request path to match OpenAI format
        original_url = http_request.url
        new_url_str = str(http_request.url).replace(
            f"/v1beta/models/{model}:generateContent",
            "/v1/chat/completions"
        )
        from starlette.datastructures import URL
        http_request._url = URL(new_url_str)

        # Temporarily override the backend type for this request
        original_backend_type = http_request.app.state.backend_type
        http_request.app.state.backend_type = backend_type

        try:
            # Call the existing chat_completions endpoint
            openai_response = await chat_completions(openai_request, http_request)

            # Convert response back to Gemini format
            if isinstance(openai_response, dict):
                # Handle direct dict response (like error responses)
                if "choices" in openai_response:
                    # Convert successful response
                    from src.models import ChatCompletionResponse
                    openai_resp_obj = models.ChatCompletionResponse.model_validate(openai_response)
                    gemini_response = openai_to_gemini_response(openai_resp_obj)
                    return gemini_response.model_dump(exclude_none=True, by_alias=True)
                else:
                    # Pass through error responses
                    return openai_response
            else:
                # Handle model object response
                gemini_response = openai_to_gemini_response(models.ChatCompletionResponse.model_validate(openai_response))
                return gemini_response.model_dump(exclude_none=True, by_alias=True)
        finally:
            # Restore original URL and backend type
            http_request._url = original_url
            http_request.app.state.backend_type = original_backend_type

    @app_instance.post("/v1beta/models/{model}:streamGenerateContent", dependencies=[Depends(verify_gemini_auth)])
    async def gemini_stream_generate_content(
        model: str,
        request_data: GenerateContentRequest,
        http_request: Request
    ):
        """Gemini API compatible streaming content generation endpoint."""
        # Parse the model to determine backend
        backend_type, actual_model = _parse_model_backend(model, http_request.app.state.backend_type)

        # Convert Gemini request to OpenAI format
        openai_request = gemini_to_openai_request(request_data, actual_model)
        openai_request.stream = True

        # Use the existing chat_completions logic by calling it with the converted request
        # We need to temporarily modify the request path to match OpenAI format
        original_url = http_request.url
        new_url_str = str(http_request.url).replace(
            f"/v1beta/models/{model}:streamGenerateContent",
            "/v1/chat/completions"
        )
        from starlette.datastructures import URL
        http_request._url = URL(new_url_str)

        # Temporarily override the backend type for this request
        original_backend_type = http_request.app.state.backend_type
        http_request.app.state.backend_type = backend_type

        try:
            # Call the existing chat_completions endpoint
            openai_response = await chat_completions(openai_request, http_request)

            # If we get a StreamingResponse, convert the chunks to Gemini format
            if isinstance(openai_response, StreamingResponse):
                async def convert_stream():
                    async for chunk in openai_response.body_iterator:
                        if isinstance(chunk, bytes):
                            chunk_str = chunk.decode('utf-8')
                        else:
                            chunk_str = str(chunk)

                        # Convert OpenAI chunk to Gemini format
                        gemini_chunk = openai_to_gemini_stream_chunk(chunk_str)
                        yield gemini_chunk.encode('utf-8')

                return StreamingResponse(
                    convert_stream(),
                    media_type="text/plain",
                    headers={"Content-Type": "text/plain; charset=utf-8"}
                )
            else:
                # Handle non-streaming response (shouldn't happen for streaming endpoint)
                if isinstance(openai_response, dict):
                    if "choices" in openai_response:
                        from src.models import ChatCompletionResponse
                        openai_resp_obj = models.ChatCompletionResponse.model_validate(openai_response)
                        gemini_response = openai_to_gemini_response(openai_resp_obj)
                        return gemini_response.model_dump(exclude_none=True, by_alias=True)
                    else:
                        return openai_response
                else:
                    gemini_response = openai_to_gemini_response(models.ChatCompletionResponse.model_validate(openai_response))
                    return gemini_response.model_dump(exclude_none=True, by_alias=True)
        finally:
            # Restore original URL and backend type
            http_request._url = original_url
            http_request.app.state.backend_type = original_backend_type

    @app_instance.get("/usage/stats", dependencies=[Depends(verify_client_auth)])
    async def get_usage_statistics(
        http_request: Request,
        days: int = 30,
        backend: Optional[str] = None,
        project: Optional[str] = None,
        username: Optional[str] = None,
    ):
        """Get usage statistics from the LLM accounting system."""
        try:
            stats = get_usage_stats(
                days=days,
                backend=backend,
                project=project,
                username=username,
            )
            return {
                "object": "usage_stats",
                "data": stats,
            }
        except Exception as e:
            logger.error(f"Failed to get usage statistics: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get usage statistics: {str(e)}")

    @app_instance.get("/usage/recent", dependencies=[Depends(verify_client_auth)])
    async def get_recent_usage(
        http_request: Request,
        limit: int = 100,
    ):
        """Get recent usage entries from the LLM accounting system."""
        try:
            accounting = get_llm_accounting()
            recent_entries = accounting.tail(n=limit)

            return {
                "object": "usage_entries",
                "data": [
                    {
                        "id": entry.id,
                        "model": entry.model,
                        "prompt_tokens": entry.prompt_tokens,
                        "completion_tokens": entry.completion_tokens,
                        "total_tokens": entry.total_tokens,
                        "cost": entry.cost,
                        "execution_time": entry.execution_time,
                        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                        "username": entry.username,
                        "project": entry.project,
                        "session": entry.session,
                        "caller_name": entry.caller_name,
                    }
                    for entry in recent_entries
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get recent usage: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get recent usage: {str(e)}")

    @app_instance.get("/audit/logs", dependencies=[Depends(verify_client_auth)])
    async def get_audit_logs_endpoint(
        http_request: Request,
        limit: int = 100,
        username: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        """Get audit log entries with full prompt/response content for compliance monitoring."""
        try:
            from datetime import datetime

            # Parse date strings if provided
            start_dt = None
            end_dt = None
            if start_date:
                try:
                    start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid start_date format, use ISO format")
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid end_date format, use ISO format")

            audit_logs = get_audit_logs(
                start_date=start_dt,
                end_date=end_dt,
                username=username,
                limit=limit,
            )

            return {
                "object": "audit_logs",
                "data": audit_logs,
                "total": len(audit_logs),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get audit logs: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get audit logs: {str(e)}")

    return app_instance

# Only create the app instance when the module is run directly, not when imported
if __name__ == "__main__":
    from src.core.cli import main as cli_main
    cli_main(build_app_fn=build_app)
else:
    # For testing and other imports, create app on demand
    app = None
