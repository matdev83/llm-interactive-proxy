"""Usage recording service for detailed usage tracking.

This module provides the UsageRecordingService class which records detailed
usage metrics at all four measurement points (verbatim ingress, mutated egress
to backend, verbatim backend response, mutated egress to client).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.core.domain.openrouter_usage import OpenRouterUsage
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.interfaces.usage_recording_interface import IUsageRecordingService
from src.core.interfaces.usage_store_interface import IUsageStore

logger = logging.getLogger(__name__)


class UsageRecordingService(IUsageRecordingService):
    """Service for recording detailed usage metrics.

    This service records usage at all four measurement points to provide
    full observability of traffic before and after proxy mutations.

    Attributes:
        _store: In-memory storage for usage records
        _turn_counters: Dictionary tracking turn numbers per session
    """

    def __init__(self, store: IUsageStore):
        """Initialize the usage recording service.

        Args:
            store: Usage store for recording usage records
        """
        self._store = store
        self._turn_counters: dict[str, int] = {}

    async def record_request(
        self,
        session_id: str,
        backend_type: str,
        model: str,
        frontend_type: str,
        leg: TrafficLeg,
        prompt_tokens: int,
        user_agent: str | None = None,
        proxy_user: str | None = None,
        app_title: str | None = None,
    ) -> str:
        """Record an incoming request and create a usage record.

        This method creates a new UsageRecord with request data and returns
        a record ID that can be used to complete the record with response data.

        Args:
            session_id: Session identifier for grouping related requests
            backend_type: Backend type (e.g., 'openai', 'anthropic', 'gemini')
            model: Model name effectively used
            frontend_type: Frontend type (e.g., 'openai', 'anthropic')
            leg: Traffic leg (CTP, PTB, BTP, PTC)
            prompt_tokens: Number of prompt tokens
            user_agent: User agent string (optional)
            proxy_user: Proxy user identifier (optional)
            app_title: Application title (optional)

        Returns:
            Record ID that can be used to complete the record with response data

        Raises:
            ValueError: If required parameters are invalid
        """
        # Validate required parameters
        if not session_id:
            raise ValueError("session_id is required")
        if not backend_type:
            raise ValueError("backend_type is required")
        if not model:
            raise ValueError("model is required")
        if not frontend_type:
            raise ValueError("frontend_type is required")
        if prompt_tokens < 0:
            raise ValueError("prompt_tokens must be non-negative")

        # Get or increment turn number for this session
        if session_id not in self._turn_counters:
            self._turn_counters[session_id] = 0
        self._turn_counters[session_id] += 1
        turn_number = self._turn_counters[session_id]

        # Generate unique record ID
        record_id = str(uuid.uuid4())

        # Create usage record
        # Determine which token field to populate based on leg
        verbatim_prompt = 0
        mutated_prompt = 0
        verbatim_completion = 0
        mutated_completion = 0

        if leg == TrafficLeg.CLIENT_TO_PROXY:
            # Verbatim ingress from client
            verbatim_prompt = prompt_tokens
        elif leg == TrafficLeg.PROXY_TO_BACKEND:
            # Mutated egress to backend
            mutated_prompt = prompt_tokens
        elif leg == TrafficLeg.BACKEND_TO_PROXY:
            # Verbatim ingress from backend (completion tokens)
            verbatim_completion = prompt_tokens  # Will be updated in record_response
        elif leg == TrafficLeg.PROXY_TO_CLIENT:
            # Mutated egress to client (completion tokens)
            mutated_completion = prompt_tokens  # Will be updated in record_response

        record = UsageRecord(
            id=record_id,
            timestamp=datetime.now(timezone.utc),
            session_id=session_id,
            turn_number=turn_number,
            backend_type=backend_type,
            model=model,
            frontend_type=frontend_type,
            leg=leg,
            verbatim_prompt_tokens=verbatim_prompt,
            mutated_prompt_tokens=mutated_prompt,
            verbatim_completion_tokens=verbatim_completion,
            mutated_completion_tokens=mutated_completion,
            total_tokens=prompt_tokens,  # Will be updated in record_response
            user_agent=user_agent,
            app_title=app_title,
            proxy_user=proxy_user,
        )

        # Store the record
        self._store.add_record(record)

        logger.debug(
            f"Recorded request {record_id} for session {session_id}, "
            f"turn {turn_number}, leg {leg.value}"
        )

        return record_id

    async def record_response(
        self,
        record_id: str,
        completion_tokens: int,
        http_status_code: int,
        tool_call_count: int = 0,
        tool_names: list[str] | None = None,
        ttft_ms: float | None = None,
        proxy_processing_ms: float = 0.0,
        total_duration_ms: float = 0.0,
        backend_reported_usage: dict[str, Any] | None = None,
    ) -> None:
        """Complete a usage record with response data.

        This method updates an existing UsageRecord with response metrics,
        including timing, tool calls, and backend-reported usage.

        Args:
            record_id: ID of the record to update (from record_request)
            completion_tokens: Number of completion tokens
            http_status_code: HTTP status code from response
            tool_call_count: Number of tool calls in response (default: 0)
            tool_names: Names of tools called (optional)
            ttft_ms: Time to first token in milliseconds (optional)
            proxy_processing_ms: Proxy processing time in milliseconds (default: 0.0)
            total_duration_ms: Total request duration in milliseconds (default: 0.0)
            backend_reported_usage: Backend-reported usage metadata (optional)

        Raises:
            ValueError: If record_id is not found or parameters are invalid
        """
        # Validate parameters
        if completion_tokens < 0:
            raise ValueError("completion_tokens must be non-negative")
        if tool_call_count < 0:
            raise ValueError("tool_call_count must be non-negative")
        if ttft_ms is not None and ttft_ms < 0:
            raise ValueError("ttft_ms must be non-negative")
        if proxy_processing_ms < 0:
            raise ValueError("proxy_processing_ms must be non-negative")
        if total_duration_ms < 0:
            raise ValueError("total_duration_ms must be non-negative")

        # Retrieve existing record
        record = self._store.get_record_by_id(record_id)
        if record is None:
            raise ValueError(f"Record with id {record_id} not found")

        # Update completion tokens based on leg
        if record.leg == TrafficLeg.BACKEND_TO_PROXY:
            # Verbatim ingress from backend
            record.verbatim_completion_tokens = completion_tokens
        elif record.leg == TrafficLeg.PROXY_TO_CLIENT:
            # Mutated egress to client
            record.mutated_completion_tokens = completion_tokens
        else:
            # For request legs (CTP, PTB), update both verbatim and mutated
            # This handles cases where we're recording both request and response
            record.verbatim_completion_tokens = completion_tokens
            record.mutated_completion_tokens = completion_tokens

        # Update total tokens
        record.total_tokens = max(
            record.verbatim_prompt_tokens, record.mutated_prompt_tokens
        ) + max(record.verbatim_completion_tokens, record.mutated_completion_tokens)

        # Update response metadata
        record.http_status_code = http_status_code
        record.tool_call_count = tool_call_count
        record.tool_names = tool_names or []

        # Update timing metrics
        record.ttft_ms = ttft_ms
        record.proxy_processing_ms = proxy_processing_ms
        record.total_duration_ms = total_duration_ms

        # Extract and store backend-reported usage
        if backend_reported_usage:
            try:
                record.backend_reported_usage = OpenRouterUsage.from_dict(
                    backend_reported_usage
                )
            except Exception as e:
                logger.warning(
                    f"Failed to parse backend-reported usage: {e}", exc_info=True
                )
                record.backend_reported_usage = None

        # Update the record in store
        self._store.update_record(record)

        logger.debug(
            f"Completed record {record_id} with {completion_tokens} completion tokens, "
            f"status {http_status_code}, {tool_call_count} tool calls"
        )

    def _extract_tool_calls(
        self, response_data: dict[str, Any]
    ) -> tuple[int, list[str]]:
        """Extract tool call information from response data.

        This is a helper method to parse tool calls from various response formats.

        Args:
            response_data: Response data dictionary

        Returns:
            Tuple of (tool_call_count, tool_names)
        """
        tool_names: list[str] = []

        # Try OpenAI format
        if "choices" in response_data:
            for choice in response_data.get("choices", []):
                message = choice.get("message", {})
                tool_calls = message.get("tool_calls", [])
                for tool_call in tool_calls:
                    function = tool_call.get("function", {})
                    name = function.get("name")
                    if name:
                        tool_names.append(name)

        # Try Anthropic format
        if "content" in response_data:
            for content_block in response_data.get("content", []):
                if content_block.get("type") == "tool_use":
                    name = content_block.get("name")
                    if name:
                        tool_names.append(name)

        return len(tool_names), tool_names
