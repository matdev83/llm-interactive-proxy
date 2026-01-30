"""
Kiro OAuth Auto connector.

Implements Builder-ID device-code OAuth (via an external login script) and uses the
stored credentials to call the Kiro inference streaming endpoints.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

import httpx
from fastapi import HTTPException

from src.connectors.base import LLMBackend, add_vendor_prefix
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.kiro_oauth_auto.account_selector import AccountSelectorService
from src.connectors.kiro_oauth_auto.constants import (
    AMAZONQ_AMZ_TARGET,
    AMAZONQ_GENERATE_URL,
    CODEWHISPERER_AMZ_TARGET,
    CODEWHISPERER_GENERATE_URL,
    CODEWHISPERER_LIST_MODELS_URL,
    KIRO_AMZ_USER_AGENT,
    KIRO_CLI_AMZ_USER_AGENT,
    KIRO_CLI_USER_AGENT,
    KIRO_USER_AGENT,
)
from src.connectors.kiro_oauth_auto.errors import NoValidAccountsError
from src.connectors.kiro_oauth_auto.event_stream import AwsEventStreamDecoder
from src.connectors.kiro_oauth_auto.models import KiroOAuthAutoConfig, StoredAccount
from src.connectors.kiro_oauth_auto.token_refresh import TokenRefreshService
from src.connectors.kiro_oauth_auto.token_storage import TokenStorageService
from src.core.common.exceptions import BackendError, ServiceUnavailableError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.ports.streaming_integration import integrate_streaming_pipeline
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService
from src.core.utils.token_count import count_tokens, extract_prompt_text

logger = logging.getLogger(__name__)


class KiroOAuthAutoConnector(LLMBackend):
    """Kiro OAuth auto connector (device-code accounts stored on disk)."""

    backend_type: str = "kiro-oauth-auto"
    VENDOR_PREFIX: str | None = "amazon"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str = "kiro-oauth-auto",
    ) -> None:
        super().__init__(config)
        self.client = client
        self.translation_service = translation_service
        self.name = name

        self._storage = TokenStorageService()
        self._refresh = TokenRefreshService(
            storage=self._storage, http_client=self.client
        )
        self._selector = AccountSelectorService(
            storage=self._storage, refresh_service=self._refresh
        )

        self._config = KiroOAuthAutoConfig()
        self._available_models: list[str] = []

    def get_provider_name(self) -> str:
        return "kiro"

    async def initialize(self, **kwargs: Any) -> None:
        backend_config = self.config.backends.get(self.backend_type)
        extras = backend_config.extra if backend_config else {}
        try:
            self._config = KiroOAuthAutoConfig(**extras)
        except Exception as exc:
            logger.warning(
                "Invalid kiro-oauth-auto config, using defaults: %s", exc, exc_info=True
            )
            self._config = KiroOAuthAutoConfig()

        refresh_buffer_ms = int(self._config.refresh_buffer_seconds * 1000)
        allowed_ids = None
        if self._config.accounts != "all":
            allowed_ids = set(self._config.accounts)

        self._storage = TokenStorageService(storage_path=self._config.storage_path)
        self._refresh = TokenRefreshService(
            storage=self._storage, http_client=self.client
        )
        self._selector = AccountSelectorService(
            storage=self._storage,
            refresh_service=self._refresh,
            refresh_buffer_ms=refresh_buffer_ms,
            allowed_account_ids=allowed_ids,
            selection_strategy=self._config.selection_strategy,
        )
        await self._selector.reload_accounts()

        try:
            _ = await self._selector.get_next_account()
        except NoValidAccountsError:
            logger.warning("Kiro OAuth auto backend initialized with NO valid accounts")
            self._available_models = []
            return

        # Best-effort model fetch
        with contextlib.suppress(Exception):
            self._available_models = await self._fetch_available_models()

    def get_available_models(self) -> list[str]:
        # Implementation Note: Claude Opus 4.5 is functional but often hidden from the
        # backend's ListAvailableModels response. We ensure it's always available
        # in the returned list.
        base_models = {
            "claude-sonnet-4.5",
            "claude-haiku-4.5",
            "claude-opus-4.5",
            "auto",
        }
        
        fetched_models = set(self._available_models)
        
        # Merge fetched models with our core known-good models
        all_models = sorted(base_models.union(fetched_models))
        
        # Explicitly remove models known to be unsupported/legacy if they show up
        legacy_models = {"claude-sonnet-4"}
        all_models = [m for m in all_models if m not in legacy_models]

        if self.VENDOR_PREFIX is None:
            return all_models
        return [add_vendor_prefix(m, self.VENDOR_PREFIX) for m in all_models]

    async def chat_completions(  # type: ignore[override]
        self,
        request: ConnectorChatCompletionsRequest | Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        if request is None and "request_data" in kwargs:
            request = kwargs.pop("request_data")
        if isinstance(request, ConnectorChatCompletionsRequest):
            return await self._chat_completions_canonical(request)

        # Legacy: coerce into canonical request shape as best-effort
        request_data = request
        processed_messages = args[0] if args else kwargs.get("processed_messages", [])
        effective_model = (
            args[1] if len(args) > 1 else kwargs.get("effective_model", "")
        )
        domain_request = cast(CanonicalChatRequest, request_data)
        canonical = ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=kwargs.get("identity"),
            cancellation_token=kwargs.get("cancellation_token"),
            cancellation_coordinator=kwargs.get("cancellation_coordinator"),
            context=None,
            options=kwargs,
        )
        return await self._chat_completions_canonical(canonical)

    async def _chat_completions_canonical(
        self, request: ConnectorChatCompletionsRequest
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        domain_request = request.request

        # Ensure we have a valid token selected
        try:
            await self._selector.get_next_account()
        except NoValidAccountsError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        # Effective model may include backend prefix and vendor prefix
        effective_model = request.effective_model
        if ":" in effective_model:
            effective_model = effective_model.split(":", 1)[-1]

        if self.VENDOR_PREFIX is not None:
            # Aggressive strip: handles both "amazon/" and "amazon:" if it somehow got there
            for sep in ("/", ":"):
                v_prefix = f"{self.VENDOR_PREFIX}{sep}"
                if effective_model.startswith(v_prefix):
                    effective_model = effective_model[len(v_prefix) :]

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Kiro completions: backend=%s, requested=%s, stripped=%s",
                self.backend_type,
                request.effective_model,
                effective_model,
            )

        if domain_request.stream:
            prompt_tokens = 0
            try:
                prompt_text = extract_prompt_text(list(request.processed_messages))
                prompt_tokens = count_tokens(prompt_text, model=effective_model)
            except Exception:
                logger.debug("Failed to estimate prompt tokens", exc_info=True)

            envelope = await integrate_streaming_pipeline(
                raw_stream=self.stream_completion(
                    request, effective_model=effective_model
                ),
                provider=self.get_provider_name(),
                stream_id=domain_request.session_id,
                enable_loop_detection=True,
                enable_tool_call_repair=True,
                enable_think_tags=True,
                prompt_tokens=prompt_tokens,
                model_name=effective_model,
                vtc_enabled=getattr(domain_request, "vtc_enabled", False) or False,
            )
            await self._selector.mark_current_account_used()
            return envelope

        # Non-streaming: accumulate stream into a single response
        content_text = ""
        tool_calls: list[dict[str, Any]] = []
        finish_reason: str | None = None
        stream_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())

        async for chunk in self.stream_completion(
            request,
            effective_model=effective_model,
            stream_id=stream_id,
            created=created,
        ):
            if chunk.is_done:
                finish_reason = cast(str | None, chunk.metadata.get("finish_reason"))
                break
            if isinstance(chunk.content, str) and chunk.content:
                content_text += chunk.content
            tc = chunk.metadata.get("tool_calls")
            if isinstance(tc, list) and tc:
                for item in tc:
                    if isinstance(item, dict):
                        tool_calls.append(item)

        response: dict[str, Any] = {
            "id": stream_id,
            "object": "chat.completion",
            "created": created,
            "model": effective_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content_text if content_text else None,
                    },
                    "finish_reason": finish_reason
                    or ("tool_calls" if tool_calls else "stop"),
                }
            ],
        }
        if tool_calls:
            response["choices"][0]["message"]["tool_calls"] = tool_calls  # type: ignore[index]

        await self._selector.mark_current_account_used()
        return ResponseEnvelope(
            content=response, status_code=200, media_type="application/json"
        )

    async def stream_completion(
        self,
        request: ConnectorChatCompletionsRequest,
        *,
        effective_model: str | None = None,
        stream_id: str | None = None,
        created: int | None = None,
    ) -> AsyncGenerator[StreamingContent, None]:
        """StreamProducer implementation: yields StreamingContent objects via Kiro normalizer."""
        account = self._selector.get_current_account()
        if not account:
            raise ServiceUnavailableError(message="No Kiro account selected")

        canonical = request.request
        effective_model = effective_model or canonical.model
        stream_id = stream_id or f"chatcmpl-{uuid.uuid4().hex}"
        created = created or int(time.time())

        payload = self._build_payload(request, effective_model=effective_model)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Kiro payload: modelId=%s, conversationId=%s",
                payload.get("conversationState", {})
                .get("currentMessage", {})
                .get("userInputMessage", {})
                .get("modelId"),
                payload.get("conversationState", {}).get("conversationId"),
            )
        preferred = self._config.preferred_endpoint or "codewhisperer"

        urls: list[tuple[str, str]] = []
        if preferred == "codewhisperer":
            urls.append((CODEWHISPERER_GENERATE_URL, CODEWHISPERER_AMZ_TARGET))
            urls.append((AMAZONQ_GENERATE_URL, AMAZONQ_AMZ_TARGET))
        else:
            urls.append((AMAZONQ_GENERATE_URL, AMAZONQ_AMZ_TARGET))
            urls.append((CODEWHISPERER_GENERATE_URL, CODEWHISPERER_AMZ_TARGET))

        last_exc: Exception | None = None
        for url, target in urls:
            try:
                async for chunk in self._stream_from_endpoint(
                    account=account,
                    url=url,
                    amz_target=target,
                    payload=payload,
                    stream_id=stream_id,
                    model=effective_model,
                    created=created,
                ):
                    yield chunk
                return
            except BackendError as exc:
                last_exc = exc
                # Fallback on quota or invalid model (might be supported on the other endpoint)
                if exc.status_code in (400, 429) or exc.code == "quota_exceeded":
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                continue

        raise ServiceUnavailableError(message=f"Kiro streaming failed: {last_exc}")

    async def _stream_from_endpoint(
        self,
        *,
        account: StoredAccount,
        url: str,
        amz_target: str,
        payload: dict[str, Any],
        stream_id: str,
        model: str,
        created: int,
    ) -> AsyncIterator[StreamingContent]:
        headers = self._build_headers(account=account, amz_target=amz_target)

        decoder = AwsEventStreamDecoder()
        saw_tool_call = False
        role_emitted = False

        current_tool_use_id: str | None = None
        current_tool_name: str | None = None
        current_tool_input_buffer = ""
        processed_tool_ids: set[str] = set()

        try:
            async with self.client.stream(
                "POST",
                url,
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(120.0, connect=30.0),
            ) as resp:
                if resp.status_code == 429:
                    raise BackendError(
                        "quota_exceeded", status_code=429, code="quota_exceeded"
                    )
                if resp.status_code in (401, 403):
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:2000]
                    raise BackendError(
                        f"Auth error {resp.status_code}: {body}",
                        status_code=resp.status_code,
                        code="auth_error",
                    )
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:2000]
                    raise BackendError(
                        f"API error {resp.status_code}: {body}",
                        status_code=resp.status_code,
                    )

                async for data in resp.aiter_bytes():
                    for msg in decoder.feed(data):
                        event = msg.json()
                        event_type = msg.event_type

                        if (
                            event_type == "assistantResponseEvent"
                            or "assistantResponseEvent" in event
                        ):
                            assistant_obj: Any | None = event.get(
                                "assistantResponseEvent"
                            )
                            if assistant_obj is None:
                                assistant_obj = event
                            if not isinstance(assistant_obj, dict):
                                continue
                            content = assistant_obj.get("content")
                            if isinstance(content, str) and content:
                                meta = {
                                    "provider": self.get_provider_name(),
                                    "id": stream_id,
                                    "model": model,
                                    "created": created,
                                }
                                if not role_emitted:
                                    meta["role"] = "assistant"
                                    role_emitted = True
                                yield StreamingContent(
                                    content=content, metadata=meta, stream_id=stream_id
                                )
                            continue

                        if (
                            event_type == "reasoningContentEvent"
                            or "reasoningContentEvent" in event
                        ):
                            reasoning_obj: Any | None = event.get(
                                "reasoningContentEvent"
                            )
                            if reasoning_obj is None:
                                reasoning_obj = event
                            if not isinstance(reasoning_obj, dict):
                                continue
                            reasoning = reasoning_obj.get("text")
                            if isinstance(reasoning, str) and reasoning:
                                yield StreamingContent(
                                    content="",
                                    metadata={
                                        "provider": self.get_provider_name(),
                                        "id": stream_id,
                                        "model": model,
                                        "created": created,
                                        "reasoning_content": reasoning,
                                    },
                                    stream_id=stream_id,
                                )
                            continue

                        if event_type == "toolUseEvent" or "toolUseEvent" in event:
                            tool_obj: Any | None = event.get("toolUseEvent")
                            if tool_obj is None:
                                tool_obj = event
                            if not isinstance(tool_obj, dict):
                                continue
                            tool_use_id = tool_obj.get("toolUseId")
                            tool_name = tool_obj.get("name")
                            is_stop = tool_obj.get("stop") is True

                            input_fragment = ""
                            input_obj: dict[str, Any] | None = None
                            raw_input = tool_obj.get("input")
                            if isinstance(raw_input, str):
                                input_fragment = raw_input
                            elif isinstance(raw_input, dict):
                                input_obj = raw_input

                            if isinstance(tool_use_id, str) and isinstance(
                                tool_name, str
                            ):
                                if (
                                    current_tool_use_id
                                    and current_tool_use_id != tool_use_id
                                ):
                                    # Flush previous as best-effort
                                    if current_tool_use_id not in processed_tool_ids:
                                        for item in _yield_tool_call(
                                            stream_id=stream_id,
                                            model=model,
                                            created=created,
                                            provider=self.get_provider_name(),
                                            tool_use_id=current_tool_use_id,
                                            tool_name=current_tool_name or "unknown",
                                            input_buffer=current_tool_input_buffer,
                                        ):
                                            yield item
                                        processed_tool_ids.add(current_tool_use_id)
                                    current_tool_use_id = None
                                    current_tool_name = None
                                    current_tool_input_buffer = ""

                                if tool_use_id in processed_tool_ids:
                                    continue

                                if current_tool_use_id is None:
                                    current_tool_use_id = tool_use_id
                                    current_tool_name = tool_name
                                    current_tool_input_buffer = ""

                            if current_tool_use_id and input_fragment:
                                current_tool_input_buffer += input_fragment
                            if current_tool_use_id and input_obj is not None:
                                current_tool_input_buffer = json.dumps(input_obj)

                            if is_stop and current_tool_use_id:
                                for item in _yield_tool_call(
                                    stream_id=stream_id,
                                    model=model,
                                    created=created,
                                    provider=self.get_provider_name(),
                                    tool_use_id=current_tool_use_id,
                                    tool_name=current_tool_name or "unknown",
                                    input_buffer=current_tool_input_buffer,
                                ):
                                    yield item
                                saw_tool_call = True
                                processed_tool_ids.add(current_tool_use_id)
                                current_tool_use_id = None
                                current_tool_name = None
                                current_tool_input_buffer = ""
                            continue

                        continue
        except GeneratorExit:
            # Client disconnected; do not attempt to emit terminal chunks.
            return

        # Flush any pending tool call
        if current_tool_use_id and current_tool_use_id not in processed_tool_ids:
            for item in _yield_tool_call(
                stream_id=stream_id,
                model=model,
                created=created,
                provider=self.get_provider_name(),
                tool_use_id=current_tool_use_id,
                tool_name=current_tool_name or "unknown",
                input_buffer=current_tool_input_buffer,
            ):
                yield item
            saw_tool_call = True

        yield StreamingContent(
            content="",
            metadata={
                "provider": self.get_provider_name(),
                "id": stream_id,
                "model": model,
                "created": created,
                "finish_reason": "tool_calls" if saw_tool_call else "stop",
            },
            is_done=True,
            stream_id=stream_id,
        )

    def _build_headers(
        self, *, account: StoredAccount, amz_target: str
    ) -> dict[str, str]:
        is_cli = self._config.origin == "CLI"
        user_agent = KIRO_CLI_USER_AGENT if is_cli else KIRO_USER_AGENT
        amz_user_agent = KIRO_CLI_AMZ_USER_AGENT if is_cli else KIRO_AMZ_USER_AGENT
        agent_mode = "vibe" if is_cli else "spec"

        return {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "X-Amz-Target": amz_target,
            "User-Agent": user_agent,
            "X-Amz-User-Agent": amz_user_agent,
            "x-amzn-kiro-agent-mode": agent_mode,
            "x-amzn-codewhisperer-optout": "true",
            "Amz-Sdk-Request": "attempt=1; max=3",
            "Amz-Sdk-Invocation-Id": str(uuid.uuid4()),
            "Authorization": f"Bearer {account.access_token}",
        }

    def _build_payload(
        self, request: ConnectorChatCompletionsRequest, *, effective_model: str
    ) -> dict[str, Any]:
        canonical = request.request
        # Tools
        tools: list[dict[str, Any]] = []
        if canonical.tools:
            for tool in canonical.tools:
                fn = tool.get("function")
                if not isinstance(fn, dict):
                    continue
                name = fn.get("name")
                if not isinstance(name, str) or not name:
                    continue
                description = (
                    fn.get("description")
                    if isinstance(fn.get("description"), str)
                    else ""
                )
                params = (
                    fn.get("parameters")
                    if isinstance(fn.get("parameters"), dict)
                    else {}
                )
                tools.append(
                    {
                        "toolSpecification": {
                            "name": name,
                            "description": description,
                            "inputSchema": {"json": params},
                        }
                    }
                )

        # IMPORTANT: Do not send structured toolResults to Kiro/AWS.
        # In real-world KiloCode sessions, the follow-up request after a tool call
        # includes role=tool messages, and sending them as userInputMessageContext.toolResults
        # triggers AWS 400 "Improperly formed request".
        #
        # Instead, embed tool outputs into the flattened text prompt.
        # Flatten prompt content (include tool messages).
        # request.processed_messages often contains ChatMessage objects with multimodal
        # content parts (Pydantic models). Use extract_prompt_text() to reliably flatten
        # them, then inject tool call markers so the backend can validate toolResults.
        prompt_parts: list[str] = []
        for m in request.processed_messages:
            if isinstance(m, dict):
                role = m.get("role")
                tool_calls = m.get("tool_calls")
                tool_call_id = m.get("tool_call_id")
            else:
                role = getattr(m, "role", None)
                tool_calls = getattr(m, "tool_calls", None)
                tool_call_id = getattr(m, "tool_call_id", None)

            text = extract_prompt_text([m])
            if (
                text
                and role == "tool"
                and isinstance(tool_call_id, str)
                and tool_call_id
                and text.startswith("tool:")
            ):
                text = text.replace(
                    "tool:",
                    f"tool (tool_call_id={tool_call_id}):",
                    1,
                )
            if text:
                prompt_parts.append(text)

            if tool_calls and isinstance(tool_calls, list):
                for tc in tool_calls:
                    tc_dict: dict[str, Any] | None
                    if isinstance(tc, dict):
                        tc_dict = tc
                    elif hasattr(tc, "model_dump"):
                        try:
                            tc_dict = tc.model_dump()  # type: ignore[no-any-return]
                        except Exception:
                            tc_dict = None
                    else:
                        tc_dict = None

                    if not tc_dict:
                        continue

                    fn = tc_dict.get("function")
                    if isinstance(fn, dict):
                        fn_name = fn.get("name")
                        fn_args = fn.get("arguments")
                    else:
                        fn_name = getattr(fn, "name", None)
                        fn_args = getattr(fn, "arguments", None)

                    if not isinstance(fn_name, str) or not fn_name:
                        continue

                    prompt_parts.append(f"assistant (tool_call): {fn_name}({fn_args})")

        prompt_text = "\n".join(prompt_parts)
        if canonical.system_prompt:
            prompt_text = f"system: {canonical.system_prompt}\n{prompt_text}"

        current_message: dict[str, Any] = {
            "content": prompt_text,
            "modelId": effective_model or "auto",
        }
        # Only send origin if it's not the default AI_EDITOR, or if explicitly requested.
        # Observation: AI_EDITOR origin might restrict available models (like Opus).
        if self._config.origin != "AI_EDITOR":
            current_message["origin"] = self._config.origin

        if tools:
            current_message["userInputMessageContext"] = {}
            if tools:
                current_message["userInputMessageContext"]["tools"] = tools

        inference_config: dict[str, Any] = {}
        max_tokens = canonical.max_completion_tokens or canonical.max_tokens
        if isinstance(max_tokens, int) and max_tokens > 0:
            inference_config["maxTokens"] = max_tokens
        if isinstance(canonical.temperature, int | float):
            inference_config["temperature"] = float(canonical.temperature)
        if isinstance(canonical.top_p, int | float):
            inference_config["topP"] = float(canonical.top_p)
        inference_config["reasoningEffort"] = canonical.reasoning_effort or "high"

        conversation_id = str(
            uuid.uuid5(uuid.NAMESPACE_OID, canonical.session_id or uuid.uuid4().hex)
        )
        payload: dict[str, Any] = {
            "conversationState": {
                "chatTriggerType": "MANUAL",
                "conversationId": conversation_id,
                "currentMessage": {"userInputMessage": current_message},
            }
        }
        if inference_config:
            payload["inferenceConfig"] = inference_config
        return payload

    async def _fetch_available_models(self) -> list[str]:
        account = self._selector.get_current_account()
        if not account:
            return []
        headers = {
            "Authorization": f"Bearer {account.access_token}",
            "Accept": "application/json",
            "User-Agent": KIRO_USER_AGENT,
            "x-amz-user-agent": KIRO_AMZ_USER_AGENT,
            "x-amzn-codewhisperer-optout": "true",
        }
        res = await self.client.get(
            CODEWHISPERER_LIST_MODELS_URL, headers=headers, timeout=30.0
        )
        if res.status_code != 200:
            return []
        data = res.json()
        models = data.get("models")
        if not isinstance(models, list):
            return []
        result: list[str] = []
        for m in models:
            if isinstance(m, dict) and isinstance(m.get("modelId"), str):
                result.append(m["modelId"])
        return result


def _yield_tool_call(
    *,
    stream_id: str,
    model: str,
    created: int,
    provider: str,
    tool_use_id: str,
    tool_name: str,
    input_buffer: str,
) -> list[StreamingContent]:

    args_obj: dict[str, Any] = {}
    try:
        if input_buffer:
            parsed = json.loads(input_buffer)
            if isinstance(parsed, dict):
                args_obj = parsed
            else:
                args_obj = {"_": parsed}
    except Exception:
        args_obj = {
            "_error": "failed_to_parse_tool_input",
            "_partialInput": input_buffer[:500],
        }

    tool_call = {
        "id": tool_use_id,
        "type": "function",
        "function": {"name": tool_name, "arguments": json.dumps(args_obj)},
    }

    return [
        StreamingContent(
            content="",
            metadata={
                "provider": provider,
                "id": stream_id,
                "model": model,
                "created": created,
                "tool_calls": [tool_call],
            },
            stream_id=stream_id,
        )
    ]


backend_registry.register_backend("kiro-oauth-auto", KiroOAuthAutoConnector)
