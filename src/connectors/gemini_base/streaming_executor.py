"""
Streaming executor for Gemini Code Assist API.

This module extracts the streaming execution logic from the connector,
providing a focused, testable service for handling streaming HTTP requests.
"""

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Iterable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import pydantic
import requests  # type: ignore[import-untyped]

from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.config import DEFAULT_READ_TIMEOUT
from src.connectors.gemini_base.google_auth_adapter import (
    GoogleAuthProvider,
    get_default_google_auth_provider,
)
from src.connectors.gemini_base.policies import (
    AuthRefreshPolicy,
    IAuthRefreshPolicy,
    IRetryPolicy,
)
from src.connectors.gemini_base.stream_processor import (
    build_error_chunk,
    build_rate_limit_backend_error,
    coerce_chunk_to_dict,
    normalize_chunk,
    should_skip_chunk,
)
from src.connectors.gemini_base.token_estimator import (
    TiktokenEstimator,
    get_default_token_estimator,
)
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import BackendError
from src.core.domain.gemini_metadata import create_gemini_response_metadata
from src.core.domain.streaming.contracts import (
    OpenAIError,
    OpenAIErrorChoice,
    OpenAIErrorChunk,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class ErrorMetadata(pydantic.BaseModel):
    """Metadata for error responses in streaming.

    Provides a strongly-typed contract for error metadata
    including finish reason, error details, and timing information.
    """

    finish_reason: str = "error"
    error: OpenAIError
    id: str
    model: str
    created: int

    model_config = {"extra": "forbid"}


@runtime_checkable
class IRetryDelayExtractor(Protocol):
    """Interface for extracting retry delays from errors."""

    def extract_retry_delay(self, error: BackendError) -> float | None:
        """Extract retry-after delay from a backend error."""
        ...


@runtime_checkable
class ITokenRefresher(Protocol):
    """Interface for token refresh operations.

    This protocol provides a minimal interface for token refresh during request execution.
    It enables runtime token management without coupling execution to credential coordination.

    **Data Flow**: This interface flows:
    - Produced by connector context or credential coordinator
    - Consumed by `ICodeAssistOrchestrator.run_streaming()` and `.run_non_streaming()`
    - Used during request execution for automatic token refresh on auth failures

    **Service Boundaries**: Provides a narrow interface for token refresh, isolating
    execution concerns from credential lifecycle management. Supports DI and test seams.
    """

    async def refresh_token_if_needed(self, *, force_reload: bool = False) -> bool:
        """Refresh the OAuth token if needed.

        Args:
            force_reload: If True, force reload credentials before refresh.

        Returns:
            True if refresh succeeded or was not needed, False otherwise.
        """
        ...


class SSELineProcessor:
    """Processes SSE lines from the streaming response.

    This class handles the parsing of SSE data lines, rate limit detection,
    and chunk normalization.
    """

    def __init__(
        self,
        translation_service: "TranslationService",
        effective_model: str,
        retry_delay_extractor: IRetryDelayExtractor | None = None,
        backend_type: str = "gemini",
    ) -> None:
        """Initialize the processor.

        Args:
            translation_service: Service for translating chunks to domain format.
            effective_model: The model name being used.
            retry_delay_extractor: Optional extractor for retry delays.
            backend_type: The backend type for error reporting.
        """
        self._translation_service = translation_service
        self._effective_model = effective_model
        self._retry_delay_extractor = retry_delay_extractor
        self._backend_type = backend_type

    def should_skip_chunk(self, chunk: dict[str, Any] | Any) -> bool:
        """Check if a chunk should be skipped.

        Args:
            chunk: The chunk to check.

        Returns:
            True if the chunk should be skipped.
        """
        chunk_dict = coerce_chunk_to_dict(chunk)
        if chunk_dict is None:
            return True
        normalize_chunk(chunk_dict)
        return should_skip_chunk(chunk_dict)

    def build_error_chunk(
        self, message: str, *, code: int = 500, error_type: str = "api_error"
    ) -> OpenAIErrorChunk:

        """Build a standardized error chunk.

        Args:
            message: The error message.
            code: HTTP status code.
            error_type: The error type.

        Returns:
            Error chunk dictionary.
        """
        return build_error_chunk(
            message=message,
            code=code,
            model=self._effective_model,
            error_type=error_type,
        )

    def check_rate_limit_in_payload(self, data: dict[str, Any]) -> BackendError | None:
        """Check if a payload indicates rate limiting.

        Args:
            data: The parsed SSE data.

        Returns:
            BackendError if rate limited, None otherwise.
        """
        rate_limit_error = build_rate_limit_backend_error(data, self._effective_model)
        if rate_limit_error is None:
            return None

        retry_delay = None
        if self._retry_delay_extractor:
            retry_delay = self._retry_delay_extractor.extract_retry_delay(
                rate_limit_error
            )

        details = (
            rate_limit_error.details
            if isinstance(rate_limit_error.details, dict)
            else {"raw": rate_limit_error.details}
        )
        if retry_delay is not None:
            details["retry_after"] = retry_delay

        return BackendError(
            message=rate_limit_error.message,
            code=rate_limit_error.code,
            status_code=getattr(rate_limit_error, "status_code", 429),
            details=details,
            backend_name=self._backend_type,
        )

    def translate_chunk(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Translate a raw SSE chunk to domain format.

        Args:
            data: The parsed SSE data.

        Returns:
            Translated chunk dictionary, or None if translation fails.
        """
        try:
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "[STREAMING] Received chunk from backend: choices_count=%s, has_usage=%s, has_id=%s",
                    len(data.get("choices", [])),
                    "usage" in data,
                    "id" in data,
                )

            domain_chunk = self._translation_service.to_domain_stream_chunk(
                chunk=data, source_format="code_assist"
            )

            if domain_chunk is not None and not isinstance(domain_chunk, dict):
                dump = getattr(domain_chunk, "model_dump", lambda **_: None)(
                    exclude_none=True
                )
                if isinstance(dump, dict):
                    domain_chunk = dump
                else:
                    domain_chunk = {}

            if domain_chunk is not None:
                # Ensure we use the effective model name, not what the backend returns
                domain_chunk["model"] = self._effective_model
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING] After translation: id=%s, model=%s, choices_count=%s",
                        (
                            domain_chunk.get("id", "none")[:20]
                            if domain_chunk.get("id")
                            else "none"
                        ),
                        domain_chunk.get("model", "none"),
                        len(domain_chunk.get("choices", [])),
                    )

            result: dict[str, Any] | None = (
                domain_chunk if isinstance(domain_chunk, dict) else None
            )
            return result

        except Exception as e:
            logger.error("Failed to process streaming chunk: %s", str(e))
            return None


class StreamingExecutor:
    """Executes streaming HTTP requests to the Code Assist API.

    This class handles the HTTP streaming layer, including:
    - Making the streaming request
    - Processing SSE chunks
    - Handling errors and auth retry
    - Calculating usage metrics
    """

    MAX_ERROR_JSON_SIZE = 32 * 1024  # 32KB limit for error JSON detection

    def __init__(
        self,
        translation_service: "TranslationService",
        token_estimator: TiktokenEstimator | None = None,
        google_auth_provider: GoogleAuthProvider | None = None,
        retry_delay_extractor: IRetryDelayExtractor | None = None,
        auth_refresh_policy: IAuthRefreshPolicy | None = None,
        retry_policy: IRetryPolicy | None = None,
        backend_type: str = "gemini",
        *,
        session_factory: Any | None = None,
    ) -> None:
        """Initialize the executor.

        Args:
            translation_service: Service for translating responses.
            token_estimator: Optional token estimator (defaults to tiktoken).
            google_auth_provider: Optional Google auth provider.
            retry_delay_extractor: Optional retry delay extractor.
            auth_refresh_policy: Optional auth refresh policy for 401 handling.
            retry_policy: Optional retry policy for rate-limit handling.
            backend_type: The backend type for error reporting.
            session_factory: Legacy hook retained for compatibility (unused).
        """
        self._translation_service = translation_service
        self._token_estimator = token_estimator or get_default_token_estimator()
        self._google_auth = google_auth_provider or get_default_google_auth_provider()
        self._retry_delay_extractor = retry_delay_extractor
        self._auth_refresh_policy = auth_refresh_policy or AuthRefreshPolicy()
        self._retry_policy = retry_policy
        self._backend_type = backend_type
        self._session_factory = session_factory

    async def execute(
        self,
        prepared: PreparedChatRequest,
        url: str,
        *,
        token_refresher: ITokenRefresher | None = None,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
        retry_policy: IRetryPolicy | None = None,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Execute a streaming request and yield processed responses.

        Args:
            prepared: The prepared chat request.
            url: The streaming endpoint URL.
            token_refresher: Optional token refresher for auth retry.
            thought_signature_callback: Optional callback for storing thought signatures.
            key_name: Optional key name for metadata.
            retry_policy: Optional retry policy for rate limits.

        Yields:
            ProcessedResponse objects for each chunk.
        """
        # Create the line processor
        processor = SSELineProcessor(
            translation_service=self._translation_service,
            effective_model=prepared.effective_model,
            retry_delay_extractor=self._retry_delay_extractor,
            backend_type=self._backend_type,
        )

        # Calculate prompt tokens if not already done
        prompt_tokens = prepared.prompt_tokens_estimate
        if prompt_tokens is None:
            prompt_tokens = (
                self._token_estimator.estimate_prompt_tokens(
                    prepared.code_assist_request
                )
                or 0
            )

        async for chunk in self._stream_generator(
            prepared=prepared,
            url=url,
            processor=processor,
            prompt_tokens=prompt_tokens,
            token_refresher=token_refresher,
            thought_signature_callback=thought_signature_callback,
            key_name=key_name,
            auth_refresh_policy=self._auth_refresh_policy,
            retry_policy=retry_policy or self._retry_policy,
        ):
            yield chunk

    async def _stream_generator(
        self,
        prepared: PreparedChatRequest,
        url: str,
        processor: SSELineProcessor,
        prompt_tokens: int,
        *,
        token_refresher: ITokenRefresher | None = None,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
        auth_refresh_policy: IAuthRefreshPolicy | None = None,
        retry_policy: IRetryPolicy | None = None,
        _allow_tool_retry: bool = True,
        without_tools: bool = False,
        _auth_retry_attempted: bool = False,
        _rate_limit_retry_attempted: bool = False,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Internal generator that handles the streaming loop."""
        response = None
        generated_text = ""
        error_json_buffer: str | None = None
        google_auth_exceptions = self._google_auth.get_auth_exceptions()

        try:
            # Make the HTTP request
            try:
                if without_tools:
                    prepared.code_assist_request.pop("tools", None)
                    prepared.code_assist_request.pop("toolConfig", None)

                request_body = prepared.build_request_body()

                if logger.isEnabledFor(TRACE_LEVEL):
                    tools_snapshot = request_body.get("request", {}).get("tools")
                    if tools_snapshot:
                        try:
                            logger.log(
                                TRACE_LEVEL,
                                "Code Assist sanitized tools payload: %s",
                                json.dumps(tools_snapshot)[:1000],
                            )
                        except Exception:
                            logger.log(
                                TRACE_LEVEL,
                                "Code Assist sanitized tools payload present (non-serializable)",
                            )

                response = await asyncio.to_thread(
                    prepared.auth_session.request,
                    method="POST",
                    url=url,
                    params={"alt": "sse"},
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                    timeout=int(DEFAULT_READ_TIMEOUT),
                    stream=True,
                )

            except requests.exceptions.Timeout as te:
                logger.error(f"Streaming timeout calling {url}: {te}", exc_info=True)
                error_chunk = processor.build_error_chunk(
                    "Gateway timeout reaching Code Assist streaming endpoint.",
                    code=504,
                )
                yield ProcessedResponse(
                    content=error_chunk,
                    metadata=self._build_error_metadata(error_chunk),
                )
                return

            except requests.exceptions.RequestException as rexc:
                logger.error(
                    f"Streaming connection error calling {url}: {rexc}",
                    exc_info=True,
                )
                error_chunk = processor.build_error_chunk(
                    "Connection error reaching Code Assist streaming endpoint.",
                    code=503,
                )
                yield ProcessedResponse(
                    content=error_chunk,
                    metadata=self._build_error_metadata(error_chunk),
                )
                return

            except google_auth_exceptions.GoogleAuthError as gae:
                logger.error(
                    f"Streaming auth error calling {url}: {gae}",
                    exc_info=True,
                )
                error_chunk = self._build_auth_error_chunk(prepared.effective_model)
                yield ProcessedResponse(
                    content=error_chunk,
                    metadata=self._build_error_metadata(error_chunk),
                )
                return

            # Handle non-200 responses
            if response.status_code != 200:
                async for chunk in self._handle_error_response(
                    response=response,
                    processor=processor,
                    prepared=prepared,
                    url=url,
                    prompt_tokens=prompt_tokens,
                    token_refresher=token_refresher,
                    thought_signature_callback=thought_signature_callback,
                    key_name=key_name,
                    auth_refresh_policy=auth_refresh_policy,
                    retry_policy=retry_policy,
                    _allow_tool_retry=_allow_tool_retry,
                    without_tools=without_tools,
                    _auth_retry_attempted=_auth_retry_attempted,
                    _rate_limit_retry_attempted=_rate_limit_retry_attempted,
                ):
                    yield chunk
                return

            # Process the streaming response
            line_buffer = ""
            done = False
            final_stop_chunk = None

            def _process_decoded_line(
                decoded_line: str,
            ) -> Iterable[ProcessedResponse]:
                nonlocal done, generated_text, error_json_buffer

                if not decoded_line:
                    return

                if decoded_line.startswith("data: "):
                    data_str = decoded_line[6:].strip()
                    if data_str == "[DONE]":
                        done = True
                        return

                    try:
                        data = json.loads(data_str)

                        # Check for rate limit errors
                        rate_limit_error = processor.check_rate_limit_in_payload(data)
                        if rate_limit_error:
                            with contextlib.suppress(Exception):
                                response.close()
                            raise rate_limit_error

                    except json.JSONDecodeError as e:
                        logger.warning(
                            "Received malformed JSON chunk in streaming response: %s (error: %s)",
                            data_str[:100] + "..." if len(data_str) > 100 else data_str,
                            str(e),
                        )
                        if data_str and not data_str.strip().endswith("}"):
                            logger.error(
                                "Detected incomplete JSON chunk, yielding error response"
                            )
                            error_chunk = processor.build_error_chunk(
                                "Malformed streaming chunk from Code Assist.",
                                code=502,
                            )
                            yield ProcessedResponse(
                                content=error_chunk,
                                metadata=self._build_error_metadata(error_chunk),
                            )
                            done = True
                        return

                    # Translate chunk
                    domain_chunk = processor.translate_chunk(data)
                    if domain_chunk is None:
                        error_chunk = processor.build_error_chunk(
                            "Failed to parse streaming chunk from Code Assist.",
                            code=500,
                        )
                        yield ProcessedResponse(
                            content=error_chunk,
                            metadata=self._build_error_metadata(error_chunk),
                        )
                        done = True
                        return

                    if domain_chunk and domain_chunk.get("choices"):
                        if processor.should_skip_chunk(domain_chunk):
                            return

                        choice = domain_chunk["choices"][0]
                        delta = choice.get("delta", {}) or {}
                        text_piece = delta.get("content")
                        if text_piece:
                            generated_text += text_piece
                            # Handle error JSON detection in content
                            if error_json_buffer is None:
                                stripped_piece = text_piece.lstrip()
                                if stripped_piece.startswith("{"):
                                    error_json_buffer = stripped_piece
                            elif len(error_json_buffer) < self.MAX_ERROR_JSON_SIZE:
                                error_json_buffer += text_piece
                            else:
                                # Stop buffering if too large - likely valid content, not an error
                                error_json_buffer = None

                            # Try to parse accumulated error JSON
                            if error_json_buffer:
                                candidate_json = error_json_buffer.strip()
                                try:
                                    parsed_error = json.loads(candidate_json)
                                except json.JSONDecodeError:
                                    pass
                                else:
                                    error_json_buffer = None
                                    if (
                                        isinstance(parsed_error, dict)
                                        and "error" in parsed_error
                                    ):
                                        rate_limit_error = (
                                            processor.check_rate_limit_in_payload(
                                                parsed_error
                                            )
                                        )
                                        if rate_limit_error:
                                            with contextlib.suppress(Exception):
                                                response.close()
                                            raise rate_limit_error

                                        # Handle other errors in content
                                        error_info = parsed_error.get("error") or {}
                                        error_code = error_info.get("code")
                                        error_message = error_info.get(
                                            "message",
                                            "API error received from Gemini Code Assist",
                                        )
                                        error_code_value = (
                                            error_code
                                            if isinstance(error_code, int)
                                            else 500
                                        )
                                        with contextlib.suppress(Exception):
                                            response.close()
                                        raise BackendError(
                                            message=error_message,
                                            code="api_error",
                                            status_code=error_code_value,
                                            details={"raw": parsed_error},
                                            backend_name=self._backend_type,
                                        )
                                    else:
                                        error_json_buffer = None

                    # Build metadata
                    metadata = create_gemini_response_metadata(
                        model=prepared.effective_model,
                        usage=None,
                        key_name=key_name,
                    ).model_dump()

                    raw_tool_calls = (
                        domain_chunk.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("tool_calls")
                    )
                    metadata.update(
                        {
                            "raw_tool_calls": raw_tool_calls,
                            "raw_finish_reason": domain_chunk.get("choices", [{}])[
                                0
                            ].get("finish_reason"),
                            "model": prepared.effective_model,
                        }
                    )

                    # Store thought signatures
                    if (
                        raw_tool_calls
                        and isinstance(raw_tool_calls, list)
                        and thought_signature_callback
                    ):
                        thought_signature_callback(raw_tool_calls, prepared.session_id)

                    yield ProcessedResponse(content=domain_chunk, metadata=metadata)
                    return

                # Skip non-data lines
                return

            # Process chunks
            try:
                for chunk in response.iter_content(
                    chunk_size=4096, decode_unicode=False
                ):
                    if done:
                        break

                    try:
                        chunk_str = (
                            chunk if isinstance(chunk, bytes) else str(chunk).encode()
                        ).decode("utf-8")
                    except (UnicodeDecodeError, AttributeError):
                        continue

                    line_buffer += chunk_str
                    lines = line_buffer.splitlines(keepends=True)

                    if lines and not lines[-1].endswith(("\n", "\r")):
                        line_buffer = lines.pop()
                    else:
                        line_buffer = ""

                    for line in lines:
                        decoded_line = line.rstrip("\r\n")

                        for processed_chunk in _process_decoded_line(decoded_line):
                            content = processed_chunk.content
                            is_stop_chunk = False

                            if isinstance(content, dict):
                                choices = content.get("choices", [])
                                if choices and isinstance(choices[0], dict):
                                    finish_reason = choices[0].get("finish_reason")
                                    if finish_reason is None:
                                        finish_reason = (
                                            choices[0].get("delta", {}) or {}
                                        ).get("finish_reason")
                            if finish_reason in ("stop", "stop_sequence"):
                                is_stop_chunk = True

                            # Defensive: capture stop chunks even if above branch misses
                            if not is_stop_chunk:
                                fallback_finish = (
                                    choices[0].get("delta", {}) or {}
                                ).get("finish_reason") or choices[0].get(
                                    "finish_reason"
                                )
                                if fallback_finish in ("stop", "stop_sequence"):
                                    is_stop_chunk = True

                            if is_stop_chunk:
                                if logger.isEnabledFor(TRACE_LEVEL):
                                    logger.log(
                                        TRACE_LEVEL, "[STREAMING] Buffering stop chunk"
                                    )
                                final_stop_chunk = processed_chunk
                                continue

                            yield processed_chunk
                            await asyncio.sleep(0)

                        if done:
                            break

                # Process remaining buffer
                if not done and line_buffer:
                    for processed_chunk in _process_decoded_line(
                        line_buffer.rstrip("\r\n")
                    ):
                        content = processed_chunk.content
                        is_stop_chunk = False
                        if isinstance(content, dict):
                            choices = content.get("choices", [])
                            if choices and isinstance(choices[0], dict):
                                finish_reason = choices[0].get("finish_reason")
                                if finish_reason in ("stop", "stop_sequence"):
                                    is_stop_chunk = True

                        if is_stop_chunk:
                            final_stop_chunk = processed_chunk
                            continue

                        yield processed_chunk
                        await asyncio.sleep(0)

            except GeneratorExit:
                logger.debug("Stream closed by consumer before completion")
                raise

            # Calculate usage and yield final chunk
            from src.core.ports.streaming_contracts import StopChunkWithUsage

            usage: dict[str, Any] | None = None
            usage_summary = None
            try:
                completion_tokens = self._token_estimator.estimate_tokens(
                    generated_text
                )
                usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": (prompt_tokens or 0) + completion_tokens,
                }
                from src.core.domain.usage_summary import UsageSummary

                usage_summary = UsageSummary.from_dict(usage)
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(TRACE_LEVEL, f"[STREAMING] Calculated usage: {usage}")
            except Exception as e:
                logger.warning(
                    f"Could not calculate completion tokens for streaming: {e}"
                )

            if final_stop_chunk:
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING] Yielding final stop chunk with usage",
                    )
                final_content = final_stop_chunk.content
                if isinstance(final_content, dict) and usage:
                    final_content = dict(final_content)
                    final_content["usage"] = usage
                    final_content = StopChunkWithUsage(final_content)
                yield ProcessedResponse(
                    content=final_content,
                    metadata=final_stop_chunk.metadata,
                    usage=usage_summary,
                )
            else:
                logger.debug(
                    "[STREAMING] No stop chunk buffered, yielding generic stop with usage"
                )
                final_chunk = self._translation_service.to_domain_stream_chunk(
                    chunk=None, source_format="code_assist"
                )
                if isinstance(final_chunk, dict):
                    final_chunk["model"] = prepared.effective_model
                    if usage:
                        final_chunk["usage"] = usage
                    final_chunk = StopChunkWithUsage(final_chunk)
                yield ProcessedResponse(
                    content=final_chunk,
                    usage=usage_summary,
                    metadata={"model": prepared.effective_model},
                )

        except BackendError as err:
            # Handle quota_exceeded errors by yielding error chunk with code 503
            if hasattr(err, "code") and err.code == "quota_exceeded":
                # Use standardized message for quota errors
                error_message = (
                    "Service temporarily unavailable due to rate limiting. "
                    f"Details: {err!s}"
                )
                error_chunk = processor.build_error_chunk(
                    message=error_message,
                    code=503,  # Use 503 for quota errors as expected by tests
                    error_type="quota_exceeded",
                )
                yield ProcessedResponse(
                    content=error_chunk,
                    metadata=self._build_error_metadata(error_chunk),
                )
                return

            if retry_policy:
                attempt = 1 if _rate_limit_retry_attempted else 0
                decision = retry_policy.should_retry(err, attempt, is_streaming=True)
                if (
                    decision.should_retry
                    and decision.sleep_seconds is not None
                    and not _rate_limit_retry_attempted
                ):
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Retrying streaming request after %.2fs due to rate limit (attempt=%s)",
                            decision.sleep_seconds,
                            attempt + 1,
                        )
                    await asyncio.sleep(decision.sleep_seconds)
                    async for retry_chunk in self._stream_generator(
                        prepared=prepared,
                        url=url,
                        processor=processor,
                        prompt_tokens=prompt_tokens,
                        token_refresher=token_refresher,
                        thought_signature_callback=thought_signature_callback,
                        key_name=key_name,
                        retry_policy=retry_policy,
                        _allow_tool_retry=_allow_tool_retry,
                        without_tools=without_tools,
                        _auth_retry_attempted=_auth_retry_attempted,
                        _rate_limit_retry_attempted=True,
                    ):
                        yield retry_chunk
                    return
            raise
        except Exception as e:
            logger.error(f"Error in streaming generator: {e}", exc_info=True)
            now = int(time.time())
            error_message = str(e) if str(e) else "An unexpected error occurred"

            # Check if this is a quota_exceeded BackendError
            error_code = 500
            error_type = "internal_error"
            if (
                isinstance(e, BackendError)
                and hasattr(e, "code")
                and e.code == "quota_exceeded"
            ):
                error_code = 503
                error_type = "quota_exceeded"
                # Use standardized message for quota errors
                error_message = (
                    "Service temporarily unavailable due to rate limiting. "
                    f"Details: {error_message}"
                )

            error_chunk = OpenAIErrorChunk(
                id=f"chatcmpl-error-{now}",
                object="chat.completion.chunk",
                created=now,
                model=prepared.effective_model,
                choices=[
                    OpenAIErrorChoice(index=0, delta={}, finish_reason="error")
                ],
                error=OpenAIError(
                    message=error_message,
                    type=error_type,
                    code=error_code,
                ),
            )

            yield ProcessedResponse(
                content=error_chunk,
                metadata=self._build_error_metadata(error_chunk),
            )
        finally:
            if response is not None:
                with contextlib.suppress(Exception):
                    response.close()

    async def _handle_error_response(
        self,
        response: requests.Response,
        processor: SSELineProcessor,
        prepared: PreparedChatRequest,
        url: str,
        prompt_tokens: int,
        *,
        token_refresher: ITokenRefresher | None = None,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
        auth_refresh_policy: IAuthRefreshPolicy | None = None,
        retry_policy: IRetryPolicy | None = None,
        _allow_tool_retry: bool = True,
        without_tools: bool = False,
        _auth_retry_attempted: bool = False,
        _rate_limit_retry_attempted: bool = False,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Handle non-200 HTTP response."""
        try:
            error_detail = response.json()
        except Exception:
            error_detail = response.text

        detail_payload: dict[str, Any] = (
            error_detail if isinstance(error_detail, dict) else {"raw": error_detail}
        )

        error_message = "Service temporarily unavailable."
        code = "api_error"

        if response.status_code == 429:
            retry_after_raw = response.headers.get(
                "Retry-After"
            ) or response.headers.get("retry-after")
            if retry_after_raw is not None and "retry_after" not in detail_payload:
                with contextlib.suppress(TypeError, ValueError):
                    detail_payload["retry_after"] = float(retry_after_raw)
            # Safely convert headers to dict, handling Mock objects
            try:
                headers_dict = (
                    dict(response.headers)
                    if hasattr(response.headers, "__iter__")
                    and not isinstance(response.headers, str)
                    else {}
                )
            except (TypeError, AttributeError):
                headers_dict = {}
            detail_payload.setdefault("headers", headers_dict)

        if isinstance(error_detail, dict):
            detail_error = error_detail.get("error") or {}
            status_val = str(detail_error.get("status", "")).upper()
            message_val = detail_error.get("message")
            if isinstance(message_val, str) and message_val.strip():
                error_message = message_val
            if response.status_code == 429 and status_val == "RESOURCE_EXHAUSTED":
                # Gemini often reports rate limiting as RESOURCE_EXHAUSTED.
                # Distinguish between:
                # - retryable rate limit windows (Retry-After / retry_after present) -> allow internal retry
                # - non-retryable quota exhaustion (no retry hint) -> return 503 immediately
                retry_hint = detail_payload.get("retry_after")
                code = (
                    "rate_limit_exceeded"
                    if isinstance(retry_hint, int | float) and float(retry_hint) >= 0
                    else "quota_exceeded"
                )
            elif response.status_code == 429:
                code = "rate_limit_exceeded"
            elif response.status_code == 401:
                code = "auth_error"
        elif isinstance(error_detail, str) and error_detail.strip():
            error_message = error_detail

        backend_error = BackendError(
            message=error_message,
            code=code,
            status_code=response.status_code,
            details=detail_payload,
            backend_name=self._backend_type,
        )

        auth_policy = auth_refresh_policy or self._auth_refresh_policy
        auth_attempt = 1 if _auth_retry_attempted else 0

        if response.status_code == 401 and token_refresher and auth_policy:
            decision = auth_policy.should_refresh(
                backend_error, auth_attempt, is_streaming=True
            )
            if decision.should_refresh:
                logger.info(
                    "Received 401 Unauthorized from backend, attempting token refresh and retry (attempt=%s, timeout=%.1fs)...",
                    auth_attempt + 1,
                    decision.timeout_seconds,
                )
                with contextlib.suppress(Exception):
                    response.close()

                try:
                    refreshed = await asyncio.wait_for(
                        token_refresher.refresh_token_if_needed(
                            force_reload=decision.force_reload
                        ),
                        timeout=decision.timeout_seconds,
                    )
                    if refreshed:
                        logger.info(
                            "Token refresh successful, retrying streaming request..."
                        )
                        async for retry_chunk in self._stream_generator(
                            prepared=prepared,
                            url=url,
                            processor=processor,
                            prompt_tokens=prompt_tokens,
                            token_refresher=token_refresher,
                            thought_signature_callback=thought_signature_callback,
                            key_name=key_name,
                            auth_refresh_policy=auth_policy,
                            _allow_tool_retry=_allow_tool_retry,
                            without_tools=without_tools,
                            _auth_retry_attempted=True,
                        ):
                            yield retry_chunk
                        return
                    logger.warning(
                        "Token refresh failed; will return 401 error to client"
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Token refresh timed out after %.1fs; returning 401 to client",
                        decision.timeout_seconds,
                    )
                except Exception as refresh_error:
                    logger.error(
                        "Error during token refresh attempt: %s",
                        refresh_error,
                        exc_info=True,
                    )

        # Handle quota errors (429 + RESOURCE_EXHAUSTED) by yielding error chunk with code 503
        # Quota errors should not be retried - yield error immediately before retry policy check
        if response.status_code == 429 and code == "quota_exceeded":
            with contextlib.suppress(Exception):
                response.close()

            # Use standardized message for quota errors to match test expectations and trigger failover
            std_message = (
                f"Service temporarily unavailable (quota exceeded): {error_message}"
            )

            error_chunk = processor.build_error_chunk(
                message=std_message,
                code=503,  # Use 503 for quota errors as expected by tests
                error_type=code,
            )
            yield ProcessedResponse(
                content=error_chunk,
                metadata=self._build_error_metadata(error_chunk),
            )
            return

        # Extract retry delay for rate limit errors (non-quota 429s)
        if response.status_code == 429 and self._retry_delay_extractor:
            retry_delay = self._retry_delay_extractor.extract_retry_delay(backend_error)
            if retry_delay is not None:
                detail_payload["retry_after"] = retry_delay

        if retry_policy and response.status_code == 429:
            attempt = 1 if _rate_limit_retry_attempted else 0
            retry_decision = retry_policy.should_retry(
                backend_error, attempt, is_streaming=True
            )
            sleep_seconds = retry_decision.sleep_seconds
            if (
                retry_decision.should_retry
                and sleep_seconds is not None
                and not _rate_limit_retry_attempted
            ):
                with contextlib.suppress(Exception):
                    response.close()
                logger.info(
                    "Retrying streaming request after %.2fs due to rate limit (attempt=%s)",
                    sleep_seconds,
                    attempt + 1,
                )
                # Keep the client connection alive while we wait for the retry window.
                # The BackendService-level failure strategy may not see this 429 because
                # the connector retries internally; emit OpenAI-compatible keepalive
                # chunks so agent loops don't break on short retry-after windows.
                interval_seconds = 8.0
                elapsed = 0.0
                keepalive_id = f"chatcmpl-keepalive-{uuid.uuid4().hex}"
                created = int(time.time())

                while elapsed < sleep_seconds:
                    yield ProcessedResponse(
                        content="",
                        metadata={
                            "_keepalive": True,
                            "id": keepalive_id,
                            "model": prepared.effective_model,
                            "created": created,
                            "session_id": prepared.session_id,
                            "stream_id": prepared.session_id,
                        },
                    )
                    remaining = sleep_seconds - elapsed
                    step = min(interval_seconds, remaining)
                    await asyncio.sleep(step)
                    elapsed += step
                async for retry_chunk in self._stream_generator(
                    prepared=prepared,
                    url=url,
                    processor=processor,
                    prompt_tokens=prompt_tokens,
                    token_refresher=token_refresher,
                    thought_signature_callback=thought_signature_callback,
                    key_name=key_name,
                    auth_refresh_policy=auth_refresh_policy,
                    retry_policy=retry_policy,
                    _allow_tool_retry=_allow_tool_retry,
                    without_tools=without_tools,
                    _auth_retry_attempted=_auth_retry_attempted,
                    _rate_limit_retry_attempted=True,
                ):
                    yield retry_chunk
                return

        # Handle 400 Bad Request errors (including "Prompt is too long") gracefully
        # by yielding an error chunk instead of raising, to prevent abrupt connection
        # termination. This allows the client to receive a proper error response.
        if response.status_code == 400:
            with contextlib.suppress(Exception):
                response.close()
            error_chunk = processor.build_error_chunk(
                message=error_message,
                code=400,
                error_type=code,  # e.g., "invalid_request_error"
            )
            yield ProcessedResponse(
                content=error_chunk,
                metadata=self._build_error_metadata(error_chunk),
            )
            return

        with contextlib.suppress(Exception):
            response.close()

        raise backend_error

    def _build_error_metadata(self, error_chunk: OpenAIErrorChunk | dict[str, Any]) -> ErrorMetadata:
        """Build metadata for error responses.
        
        Args:
            error_chunk: Either an OpenAIErrorChunk object or a dict with error chunk data.
        """
        # Handle both OpenAIErrorChunk objects and dicts (for test compatibility)
        if isinstance(error_chunk, dict):
            error_data = error_chunk.get("error", {})
            if isinstance(error_data, dict):
                error = OpenAIError(
                    message=error_data.get("message", ""),
                    type=error_data.get("type", "api_error"),
                    code=error_data.get("code", 500),
                )
            else:
                error = error_data
            return ErrorMetadata(
                finish_reason="error",
                error=error,
                id=error_chunk.get("id", ""),
                model=error_chunk.get("model", "unknown"),
                created=error_chunk.get("created", 0),
            )
        else:
            # OpenAIErrorChunk object
            return ErrorMetadata(
                finish_reason="error",
                error=error_chunk.error,
                id=error_chunk.id,
                model=error_chunk.model,
                created=error_chunk.created,
            )

    def _build_auth_error_chunk(self, model: str) -> OpenAIErrorChunk:
        """Build an authentication error chunk."""
        now = int(time.time())
        return OpenAIErrorChunk(
            id=f"chatcmpl-error-{now}",
            object="chat.completion.chunk",
            created=now,
            model=model,
            choices=[
                OpenAIErrorChoice(index=0, delta={}, finish_reason="error")
            ],
            error=OpenAIError(
                message="Authentication failed. Please check your credentials.",
                type="auth_error",
                code=401,
            ),
        )



__all__ = [
    "IAuthRefreshPolicy",
    "IRetryDelayExtractor",
    "ITokenRefresher",
    "SSELineProcessor",
    "StreamingExecutor",
]
