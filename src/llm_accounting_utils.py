"""
LLM Accounting integration utilities for tracking usage and audit logging across all backends.

This module implements two separate tracking systems:
1. Usage tracking - for metrics, rate limiting, and cost monitoring
2. Audit logging - for compliance and security audit trails with full prompt/response logging
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Optional, TypedDict, Union

import tiktoken
from fastapi.responses import StreamingResponse
from llm_accounting import LLMAccounting  # type: ignore

logger = logging.getLogger(__name__)

# Global LLM accounting instance
_llm_accounting: Optional[LLMAccounting] = None

# Token encoding cache
_token_encoders: dict[str, tiktoken.Encoding] = {}


class RateLimitInfo(TypedDict, total=False):
    requests_remaining: Optional[str]
    requests_reset: Optional[str]
    tokens_remaining: Optional[str]
    tokens_reset: Optional[str]
    quota_remaining: Optional[str]
    quota_reset: Optional[str]


class ProviderInfo(TypedDict, total=False):
    provider: Optional[str]
    model: Optional[str]
    request_id: Optional[str]
    note: Optional[str]


class BillingInfo(TypedDict, total=False):
    backend: str
    cost: float
    upstream_cost: Optional[float]
    provider_info: ProviderInfo
    rate_limit_info: RateLimitInfo
    usage: dict[str, int]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    reasoning_tokens: Optional[int]
    cached_tokens: Optional[int]


def is_accounting_disabled() -> bool:
    """Check if LLM accounting is disabled via environment variable."""
    return os.getenv("DISABLE_ACCOUNTING", "false").lower() == "true"


def get_llm_accounting() -> LLMAccounting:
    """Get or create the global LLM accounting instance."""
    global _llm_accounting
    if _llm_accounting is None:
        _llm_accounting = LLMAccounting()
        logger.info(
            "Initialized LLM accounting system with usage tracking and audit logging"
        )
    return _llm_accounting


def get_system_username() -> str:
    """Get the current system username."""
    try:
        return os.getlogin()
    except Exception:
        # Fallback methods for different environments
        try:
            return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
        except Exception:
            return "unknown"


def get_token_encoder(model: str = "gpt-3.5-turbo") -> tiktoken.Encoding:
    """
    Get a token encoder for counting tokens.

    Args:
        model: Model name to get appropriate encoder for

    Returns:
        tiktoken.Encoding instance
    """
    global _token_encoders

    # Map model names to appropriate encoders
    if "gemini" in model.lower():
        # Use cl100k_base for Gemini models (similar to GPT-4)
        encoder_name = "cl100k_base"
    elif "gpt-4" in model.lower() or "gpt-3.5" in model.lower():
        encoder_name = "cl100k_base"
    else:
        # Default to cl100k_base for unknown models
        encoder_name = "cl100k_base"

    if encoder_name not in _token_encoders:
        try:
            _token_encoders[encoder_name] = tiktoken.get_encoding(encoder_name)
        except Exception as e:
            logger.warning(
                f"Failed to get encoding {encoder_name}, using cl100k_base: {e}"
            )
            _token_encoders[encoder_name] = tiktoken.get_encoding("cl100k_base")

    return _token_encoders[encoder_name]


def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """
    Count tokens in text using tiktoken.

    Args:
        text: Text to count tokens for
        model: Model name to get appropriate encoder

    Returns:
        Number of tokens
    """
    try:
        encoder = get_token_encoder(model)
        return len(encoder.encode(text))
    except Exception as e:
        logger.error(f"Failed to count tokens: {e}")
        # Fallback: rough estimate (4 chars per token)
        return len(text) // 4


def extract_prompt_from_messages(messages: list[Union[dict[str, Any], Any]]) -> str:
    """
    Extract the full prompt text from OpenAI-style messages.

    Args:
        messages: List of message dictionaries or Pydantic ChatMessage objects

    Returns:
        Combined prompt text
    """
    prompt_parts = []
    for message in messages:
        # Handle both dict and Pydantic object formats
        if hasattr(message, "role") and hasattr(message, "content"):
            # Pydantic ChatMessage object
            role = message.role
            content = message.content
        elif isinstance(message, dict):
            # Dictionary format
            role = message.get("role", "user")
            content = message.get("content", "")
        else:
            # Handle unknown message types gracefully
            role = "unknown"
            content = ""

        if isinstance(content, str):
            prompt_parts.append(f"{role}: {content}")
        elif isinstance(content, list):
            # Handle multi-part content (text + images)
            text_parts = []
            for part in content:
                if hasattr(part, "text"):
                    # Pydantic object with text attribute
                    text_parts.append(part.text)
                elif isinstance(part, dict) and part.get("type") == "text":
                    # Dictionary format
                    text_parts.append(part.get("text", ""))
            if text_parts:
                prompt_parts.append(f"{role}: {' '.join(text_parts)}")

    return "\n".join(prompt_parts)


def extract_response_text(response: Union[dict[str, Any], StreamingResponse]) -> str:
    """
    Extract response text from backend response.

    Args:
        response: Backend response

    Returns:
        Response text content
    """
    if isinstance(response, dict):
        choices = response.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            return str(message.get("content", ""))

    # For streaming responses, we can't extract the content easily
    return "<streaming_response>"


def extract_billing_info_from_headers(
    headers: dict[str, str], backend: str
) -> BillingInfo:
    """
    Extract billing information from response headers based on backend.

    Args:
        headers: Response headers dictionary
        backend: Backend name (openrouter, gemini)

    Returns:
        Dictionary with billing information
    """
    billing_info: BillingInfo = {
        "backend": backend,
        "cost": 0.0,
        "provider_info": {},
        "rate_limit_info": {},
    }

    if backend == "openrouter":
        _apply_openrouter_header_info(headers, billing_info)
    elif backend == "gemini":
        _apply_gemini_header_info(headers, billing_info)
    elif backend == "anthropic":
        _apply_anthropic_header_info(billing_info)

    return billing_info


def _apply_openrouter_header_info(
    headers: dict[str, str], billing_info: BillingInfo
) -> None:
    if "x-ratelimit-requests-remaining" in headers:
        billing_info["rate_limit_info"]["requests_remaining"] = headers.get(
            "x-ratelimit-requests-remaining"
        )
    if "x-ratelimit-requests-reset" in headers:
        billing_info["rate_limit_info"]["requests_reset"] = headers.get(
            "x-ratelimit-requests-reset"
        )
    if "x-ratelimit-tokens-remaining" in headers:
        billing_info["rate_limit_info"]["tokens_remaining"] = headers.get(
            "x-ratelimit-tokens-remaining"
        )
    if "x-ratelimit-tokens-reset" in headers:
        billing_info["rate_limit_info"]["tokens_reset"] = headers.get(
            "x-ratelimit-tokens-reset"
        )
    if "x-or-provider" in headers:
        billing_info["provider_info"]["provider"] = headers.get("x-or-provider")
    if "x-or-model" in headers:
        billing_info["provider_info"]["model"] = headers.get("x-or-model")


def _apply_gemini_header_info(
    headers: dict[str, str], billing_info: BillingInfo
) -> None:
    if "x-goog-quota-remaining" in headers:
        billing_info["rate_limit_info"]["quota_remaining"] = headers.get(
            "x-goog-quota-remaining"
        )
    if "x-goog-quota-reset" in headers:
        billing_info["rate_limit_info"]["quota_reset"] = headers.get(
            "x-goog-quota-reset"
        )
    if "x-goog-request-id" in headers:
        billing_info["provider_info"]["request_id"] = headers.get("x-goog-request-id")


def _apply_anthropic_header_info(billing_info: BillingInfo) -> None:
    billing_info["provider_info"][
        "note"
    ] = "Anthropic backend - usage info in response only"
    billing_info["usage"] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def extract_billing_info_from_response(
    response: Union[dict[str, Any], StreamingResponse], backend: str
) -> BillingInfo:
    """
    Extract billing information from response body based on backend.

    Args:
        response: Backend response
        backend: Backend name

    Returns:
        Dictionary with billing and usage information
    """
    billing_info: BillingInfo = {
        "backend": backend,
        "provider_info": {},
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "cost": 0.0,
        # legacy flat keys kept for backwards compat
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
        "cached_tokens": None,
    }

    if isinstance(response, dict):
        if backend == "openrouter":
            _apply_openrouter_usage_from_response(response, billing_info)
        elif backend == "gemini":
            _apply_gemini_usage_from_response(response, billing_info)
        elif backend == "anthropic":
            _apply_anthropic_usage_from_dict(response, billing_info)

    elif backend == "anthropic" and hasattr(response, "usage"):
        _apply_anthropic_usage_from_streaming(response, billing_info)

    elif isinstance(response, StreamingResponse) and backend == "anthropic":
        # For streaming responses, usage info may not be readily available
        # Anthropic streaming responses don't include usage; default zeros
        billing_info["usage"]["prompt_tokens"] = 0
        billing_info["usage"]["completion_tokens"] = 0
        billing_info["usage"]["total_tokens"] = 0
        billing_info["prompt_tokens"] = 0
        billing_info["completion_tokens"] = 0
        billing_info["total_tokens"] = 0

    return billing_info


def _apply_openrouter_usage_from_response(
    response: dict[str, Any], billing_info: BillingInfo
) -> None:
    usage = response.get("usage", {})
    if not usage:
        return
    billing_info["prompt_tokens"] = usage.get("prompt_tokens")
    billing_info["completion_tokens"] = usage.get("completion_tokens")
    billing_info["total_tokens"] = usage.get("total_tokens")
    billing_info["cost"] = usage.get("cost", 0.0)

    completion_details = usage.get("completion_tokens_details", {})
    if completion_details:
        billing_info["reasoning_tokens"] = completion_details.get("reasoning_tokens", 0)

    prompt_details = usage.get("prompt_tokens_details", {})
    if prompt_details:
        billing_info["cached_tokens"] = prompt_details.get("cached_tokens", 0)

    cost_details = usage.get("cost_details", {})
    if cost_details:
        billing_info["upstream_cost"] = cost_details.get("upstream_inference_cost")


def _apply_gemini_usage_from_response(
    response: dict[str, Any], billing_info: BillingInfo
) -> None:
    usage = response.get("usageMetadata", {})
    if not usage:
        return
    billing_info["prompt_tokens"] = usage.get("promptTokenCount", 0)
    billing_info["completion_tokens"] = usage.get("candidatesTokenCount", 0)
    billing_info["total_tokens"] = usage.get("totalTokenCount", 0)


def _apply_anthropic_usage_from_dict(
    response: dict[str, Any], billing_info: BillingInfo
) -> None:
    from src.anthropic_converters import extract_anthropic_usage

    usage_info = extract_anthropic_usage(response)
    billing_info["usage"]["prompt_tokens"] = usage_info["input_tokens"]
    billing_info["usage"]["completion_tokens"] = usage_info["output_tokens"]
    billing_info["usage"]["total_tokens"] = usage_info["total_tokens"]
    billing_info["prompt_tokens"] = usage_info["input_tokens"]
    billing_info["completion_tokens"] = usage_info["output_tokens"]
    billing_info["total_tokens"] = usage_info["total_tokens"]
    billing_info["provider_info"]["note"] = "Anthropic backend response usage"


def _apply_anthropic_usage_from_streaming(
    response: Any, billing_info: BillingInfo
) -> None:
    from src.anthropic_converters import extract_anthropic_usage

    usage_info = extract_anthropic_usage(response)
    billing_info["usage"]["prompt_tokens"] = usage_info["input_tokens"]
    billing_info["usage"]["completion_tokens"] = usage_info["output_tokens"]
    billing_info["usage"]["total_tokens"] = usage_info["total_tokens"]
    billing_info["prompt_tokens"] = usage_info["input_tokens"]
    billing_info["completion_tokens"] = usage_info["output_tokens"]
    billing_info["total_tokens"] = usage_info["total_tokens"]
    billing_info["provider_info"]["note"] = "Anthropic backend response usage"


def track_usage_metrics(
    model: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    cost: float = 0.0,
    execution_time: float = 0.0,
    backend: Optional[str] = None,
    username: Optional[str] = None,
    project: Optional[str] = None,
    session: Optional[str] = None,
    caller_name: Optional[str] = None,
    reasoning_tokens: int = 0,
    cached_tokens: int = 0,
) -> None:
    """
    Track LLM usage metrics for rate limiting and cost monitoring.

    This is the first tracking system - focused on usage metrics.
    """
    try:
        accounting = get_llm_accounting()

        # Create a full model identifier including backend
        full_model = f"{backend}:{model}" if backend else model

        # Use system username if not provided
        if not username:
            username = get_system_username()

        accounting.track_usage(
            model=full_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            execution_time=execution_time,
            timestamp=datetime.now(),
            caller_name=caller_name or "llm-interactive-proxy",
            username=username,
            project=project,
            session=session,
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
        )

        logger.debug(
            f"Tracked usage metrics: model={full_model}, tokens={total_tokens}, "
            f"cost={cost}, time={execution_time:.2f}s, user={username}"
        )
    except Exception as e:
        logger.error(f"Failed to track usage metrics: {e}")


def log_audit_trail(
    model: str,
    prompt_text: str,
    response_text: str,
    backend: Optional[str] = None,
    username: Optional[str] = None,
    project: Optional[str] = None,
    session: Optional[str] = None,
    remote_completion_id: Optional[str] = None,
) -> None:
    """
    Log audit trail for compliance and security monitoring.

    This is the second tracking system - focused on audit logging with full content.
    """
    try:
        accounting = get_llm_accounting()
        audit_logger = accounting.audit_logger

        # Create a full model identifier including backend
        full_model = f"{backend}:{model}" if backend else model

        # Use system username if not provided
        if not username:
            username = get_system_username()

        # Log the complete interaction as an event
        audit_logger.log_event(
            app_name="llm-interactive-proxy",
            user_name=username,
            model=full_model,
            log_type="completion",
            prompt_text=prompt_text,
            response_text=response_text,
            remote_completion_id=remote_completion_id,
            project=project,
            timestamp=datetime.now(),
            session=session,
        )

        logger.debug(
            f"Logged audit trail: model={full_model}, user={username}, "
            f"prompt_len={len(prompt_text)}, response_len={len(response_text)}"
        )
    except Exception as e:
        logger.error(f"Failed to log audit trail: {e}")


@asynccontextmanager
async def track_llm_request(
    model: str,
    backend: str,
    messages: list[Union[dict[str, Any], Any]],
    username: Optional[str] = None,
    project: Optional[str] = None,
    session: Optional[str] = None,
    caller_name: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator[Any, None]:
    """
    Context manager to track both usage metrics and audit logs for LLM requests.

    Usage:
        async with track_llm_request(model, backend, messages, session=session_id) as tracker:
            response = await backend.chat_completions(...)
            tracker.set_response(response)
            tracker.set_response_headers(response_headers)  # NEW: Set headers for billing extraction
    """

    class RequestTracker:
        def __init__(self) -> None:
            self.response: Optional[Union[dict[str, Any], StreamingResponse]] = None
            self.response_headers: dict[str, str] = {}
            self.cost = 0.0
            self.remote_completion_id: Optional[str] = None

        def set_response(
            self, response: Union[dict[str, Any], StreamingResponse]
        ) -> None:
            """Set the response and extract information."""
            self.response = response

        def set_response_headers(self, headers: dict[str, str]) -> None:
            """Set the response headers for billing extraction."""
            self.response_headers = headers

        def set_cost(self, cost: float) -> None:
            """Set the cost for this request."""
            self.cost = cost

        def set_completion_id(self, completion_id: str) -> None:
            """Set the remote completion ID."""
            self.remote_completion_id = completion_id

    tracker = RequestTracker()

    if is_accounting_disabled():
        try:
            yield tracker
        finally:
            pass  # Do nothing if accounting is disabled
        return

    start_time = time.time()
    prompt_text = extract_prompt_from_messages(messages)

    # Use system username if not provided
    if not username:
        username = get_system_username()

    try:
        yield tracker
    finally:
        execution_time = time.time() - start_time

        # Extract response information
        response_text = ""
        prompt_tokens = None
        completion_tokens = None
        total_tokens = None
        reasoning_tokens = 0
        cached_tokens = 0
        cost = tracker.cost

        if tracker.response:
            response_text = extract_response_text(tracker.response)

            # Extract billing info from response body
            billing_info = extract_billing_info_from_response(tracker.response, backend)
            if billing_info["prompt_tokens"]:
                prompt_tokens = billing_info["prompt_tokens"]
            if billing_info["completion_tokens"]:
                completion_tokens = billing_info["completion_tokens"]
            if billing_info["total_tokens"]:
                total_tokens = billing_info["total_tokens"]
            if billing_info["cost"]:
                cost = billing_info["cost"]
            if billing_info["reasoning_tokens"]:
                reasoning_tokens = billing_info["reasoning_tokens"]
            if billing_info["cached_tokens"]:
                cached_tokens = billing_info["cached_tokens"]

            # Extract completion ID if available
            if not tracker.remote_completion_id and isinstance(tracker.response, dict):
                tracker.remote_completion_id = tracker.response.get("id")

        # Extract billing info from headers
        if tracker.response_headers:
            header_billing_info = extract_billing_info_from_headers(
                tracker.response_headers, backend
            )
            logger.debug(f"Extracted billing info from headers: {header_billing_info}")

        # Track usage metrics (first tracking system)
        track_usage_metrics(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            execution_time=execution_time,
            backend=backend,
            username=username,
            project=project,
            session=session,
            caller_name=caller_name,
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
        )

        # Log audit trail (second tracking system)
        log_audit_trail(
            model=model,
            prompt_text=prompt_text,
            response_text=response_text,
            backend=backend,
            username=username,
            project=project,
            session=session,
            remote_completion_id=tracker.remote_completion_id,
        )


def get_usage_stats(
    days: int = 30,
    backend: Optional[str] = None,
    project: Optional[str] = None,
    username: Optional[str] = None,
) -> dict[str, Any]:
    """
    Get usage statistics from the accounting system.
    """
    try:
        accounting = get_llm_accounting()

        # Get period stats
        stats = accounting.get_period_stats(days=days)

        # Get model rankings
        rankings = accounting.get_model_rankings(days=days)

        return {
            "period_stats": stats,
            "model_rankings": rankings,
            "days": days,
        }
    except Exception as e:
        logger.error(f"Failed to get usage stats: {e}")
        return {"error": str(e)}


def get_audit_logs(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    username: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Get audit log entries from the accounting system.
    """
    try:
        accounting = get_llm_accounting()
        audit_logger = accounting.audit_logger

        entries = audit_logger.get_entries(
            start_date=start_date,
            end_date=end_date,
            username=username,
            limit=limit,
        )

        return [
            {
                "id": entry.id,
                "app_name": entry.app_name,
                "user_name": entry.user_name,
                "model": entry.model,
                "log_type": entry.log_type,
                "prompt_text": entry.prompt_text,
                "response_text": entry.response_text,
                "remote_completion_id": entry.remote_completion_id,
                "project": entry.project,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "session": entry.session,
            }
            for entry in entries
        ]
    except Exception as e:
        logger.error(f"Failed to get audit logs: {e}")
        return []
