"""Usage record data model for detailed usage tracking.

This module defines the UsageRecord dataclass which captures comprehensive
metrics for individual request/response cycles with full observability of
verbatim and mutated traffic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.core.domain.openrouter_usage import OpenRouterUsage
from src.core.domain.traffic_leg import TrafficLeg


@dataclass
class UsageRecord:
    """Core data structure for tracking individual request/response cycles.

    This class provides full observability of traffic before and after proxy
    mutations, capturing token counts at four measurement points:
    1. Frontend ingress (verbatim client request)
    2. Backend egress (mutated request to backend)
    3. Backend ingress (verbatim backend response)
    4. Frontend egress (mutated response to client)

    Additionally, backend-reported usage is captured separately for reconciliation.

    Attributes:
        id: Unique identifier for this usage record
        timestamp: When the record was created
        session_id: Session identifier for grouping related requests
        turn_number: Turn number within the session

        backend_type: Backend type (e.g., 'openai', 'anthropic', 'gemini')
        model: Model name effectively used
        frontend_type: Frontend type (e.g., 'openai', 'anthropic')
        leg: Traffic leg (CTP, PTB, BTP, PTC)

        verbatim_prompt_tokens: Tokens in client request BEFORE proxy modifications
        verbatim_completion_tokens: Tokens in backend response BEFORE proxy modifications
        mutated_prompt_tokens: Tokens in request TO backend AFTER proxy modifications
        mutated_completion_tokens: Tokens in response TO client AFTER proxy modifications
        total_tokens: Computed total tokens

        backend_reported_usage: Complete backend-reported usage (for reconciliation)

        http_status_code: HTTP status code from response
        tool_call_count: Number of tool calls in response
        tool_names: Names of tools called

        ttft_ms: Time to first token (milliseconds)
        proxy_processing_ms: Proxy processing time (milliseconds)
        total_duration_ms: Total request duration (milliseconds)

        user_agent: User agent string
        app_title: Application title
        proxy_user: Proxy user identifier
    """

    id: str
    timestamp: datetime
    session_id: str
    turn_number: int

    # Traffic identification
    backend_type: str
    model: str
    frontend_type: str
    leg: TrafficLeg

    # PROXY-CALCULATED TOKEN METRICS (verbatim - before mutations)
    verbatim_prompt_tokens: int = 0
    verbatim_completion_tokens: int = 0

    # PROXY-CALCULATED TOKEN METRICS (mutated - after mutations)
    mutated_prompt_tokens: int = 0
    mutated_completion_tokens: int = 0

    # Computed totals
    total_tokens: int = 0

    # BACKEND-REPORTED VALUES (separate from proxy calculations)
    backend_reported_usage: OpenRouterUsage | None = None

    # Request/response metadata
    http_status_code: int | None = None
    tool_call_count: int = 0
    tool_names: list[str] = field(default_factory=list)

    # Timing metrics
    ttft_ms: float | None = None
    proxy_processing_ms: float = 0.0
    total_duration_ms: float = 0.0

    # Context
    user_agent: str | None = None
    app_title: str | None = None
    proxy_user: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the usage record to a dictionary.

        Returns:
            Dictionary representation of the usage record
        """
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "turn_number": self.turn_number,
            "backend_type": self.backend_type,
            "model": self.model,
            "frontend_type": self.frontend_type,
            "leg": self.leg.value,
            "verbatim_prompt_tokens": self.verbatim_prompt_tokens,
            "verbatim_completion_tokens": self.verbatim_completion_tokens,
            "mutated_prompt_tokens": self.mutated_prompt_tokens,
            "mutated_completion_tokens": self.mutated_completion_tokens,
            "total_tokens": self.total_tokens,
            "backend_reported_usage": (
                self.backend_reported_usage.to_openrouter_dict()
                if self.backend_reported_usage
                else None
            ),
            "http_status_code": self.http_status_code,
            "tool_call_count": self.tool_call_count,
            "tool_names": self.tool_names,
            "ttft_ms": self.ttft_ms,
            "proxy_processing_ms": self.proxy_processing_ms,
            "total_duration_ms": self.total_duration_ms,
            "user_agent": self.user_agent,
            "app_title": self.app_title,
            "proxy_user": self.proxy_user,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageRecord:
        """Deserialize a usage record from a dictionary.

        Args:
            data: Dictionary containing usage record data

        Returns:
            UsageRecord instance

        Raises:
            ValueError: If required fields are missing or invalid
        """
        # Parse timestamp
        timestamp_str = data.get("timestamp")
        if isinstance(timestamp_str, str):
            timestamp = datetime.fromisoformat(timestamp_str)
        elif isinstance(timestamp_str, datetime):
            timestamp = timestamp_str
        else:
            raise ValueError(f"Invalid timestamp: {timestamp_str}")

        # Parse traffic leg
        leg_value = data.get("leg")
        if isinstance(leg_value, TrafficLeg):
            leg = leg_value
        elif isinstance(leg_value, str):
            leg = TrafficLeg(leg_value)
        else:
            raise ValueError(f"Invalid leg: {leg_value}")

        # Parse backend-reported usage
        backend_usage_data = data.get("backend_reported_usage")
        backend_reported_usage = None
        if backend_usage_data:
            if isinstance(backend_usage_data, OpenRouterUsage):
                backend_reported_usage = backend_usage_data
            elif isinstance(backend_usage_data, dict):
                backend_reported_usage = OpenRouterUsage.from_dict(backend_usage_data)

        return cls(
            id=data["id"],
            timestamp=timestamp,
            session_id=data["session_id"],
            turn_number=data["turn_number"],
            backend_type=data["backend_type"],
            model=data["model"],
            frontend_type=data["frontend_type"],
            leg=leg,
            verbatim_prompt_tokens=data.get("verbatim_prompt_tokens", 0),
            verbatim_completion_tokens=data.get("verbatim_completion_tokens", 0),
            mutated_prompt_tokens=data.get("mutated_prompt_tokens", 0),
            mutated_completion_tokens=data.get("mutated_completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            backend_reported_usage=backend_reported_usage,
            http_status_code=data.get("http_status_code"),
            tool_call_count=data.get("tool_call_count", 0),
            tool_names=data.get("tool_names", []),
            ttft_ms=data.get("ttft_ms"),
            proxy_processing_ms=data.get("proxy_processing_ms", 0.0),
            total_duration_ms=data.get("total_duration_ms", 0.0),
            user_agent=data.get("user_agent"),
            app_title=data.get("app_title"),
            proxy_user=data.get("proxy_user"),
        )
