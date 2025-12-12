"""
Usage tracking service implementation.

This service provides the implementation for the IUsageTrackingService interface,
using UsageRecordRepository for persistence and SessionMetricsRepository for
session-level aggregation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.core.database.repositories.usage_repository import (
    SessionMetricsRepository,
    UsageRecordRepository,
)
from src.core.domain.aggregated_stats import AggregatedStats
from src.core.domain.openrouter_usage import OpenRouterUsage
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService

logger = logging.getLogger(__name__)


class UsageTrackingService(IUsageTrackingService):
    """Service for tracking LLM usage across the application.

    This service implements the detailed usage tracking specification, recording
    metrics at four key points (legs) of the traffic flow:
    1. Client to Proxy (CTP) - Verbatim request
    2. Proxy to Backend (PTB) - Mutated request
    3. Backend to Proxy (BTP) - Verbatim response
    4. Proxy to Client (PTC) - Mutated response
    """

    def __init__(
        self,
        usage_repository: UsageRecordRepository,
        session_repository: SessionMetricsRepository,
    ) -> None:
        """Initialize the usage tracking service.

        Args:
            usage_repository: Repository for storing usage records
            session_repository: Repository for storing session metrics
        """
        self._usage_repo = usage_repository
        self._session_repo = session_repository

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
        turn_number: int = 1,
    ) -> str:
        """Record an incoming request (or leg start), returns record_id.

        This method is called when a traffic leg starts (e.g. request received,
        request sent to backend). It records the initial metrics like prompt tokens.
        """
        record_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)

        # Determine which prompt_tokens field to populate based on leg
        verbatim_prompt = 0
        mutated_prompt = 0

        if leg in (TrafficLeg.CLIENT_TO_PROXY, TrafficLeg.BACKEND_TO_PROXY):
            # Ingress points (from client or from backend) - typically "verbatim" relative to proxy processing
            # Note: BTP is a response, but record_request might be used to init the record if we treat it as a new event
            # However, usually BTP is recorded via record_response of the PTB record, OR as a new record if we track distinct legs.
            # The spec implies 4 separate measurements. If we store them as separate records, each has its own ID.
            # If we store them as fields in one record, we need to correlate.
            # The Requirement 1 says: "Usage_Tracking_System SHALL record verbatim_inbound_tokens... mutated_outbound_tokens..."
            # The Design says: UsageRecord has fields for both verbatim and mutated.
            # But the interaction diagram shows:
            # Frontend->UsageService: record_request(CTP) -> Create UsageRecord
            # UsageService->UsageService: record_request(PTB) -> Update UsageRecord? Or Create new?
            #
            # Design doc: "UsageRecord... The core data structure for tracking individual request/response cycles"
            # It seems one UsageRecord represents one Turn (CTP -> PTB -> BTP -> PTC).
            # But `leg` is a field in `UsageRecord`.
            #
            # Let's look at `UsageRecord` definition in `src/core/domain/usage_record.py`
            # and `src/core/database/models/usage.py`.
            # `leg` is a field. This suggests separate records for each leg.
            #
            # IF `leg` is a field, then each "leg" creates a new `UsageRecord`.
            # So:
            # 1. CTP: Record created.
            # 2. PTB: Record created.
            # 3. BTP: Record created.
            # 4. PTC: Record created.
            #
            # This seems redundant if we want to compare verbatim vs mutated in one view.
            # BUT, the design doc says:
            # "UsageRecord... leg: TrafficLeg # CTP, PTC, PTB, BTP"
            # AND "verbatim_prompt_tokens", "mutated_prompt_tokens" fields exist.
            #
            # If we have one record per leg, then for CTP:
            # verbatim_prompt_tokens = X, mutated = 0 (or X?).
            #
            # Let's re-read Requirement 7: "support filtering by traffic leg".
            # This confirms separate records per leg.
            #
            # So, for CTP:
            # - verbatim_prompt_tokens = input tokens
            # - mutated_prompt_tokens = 0 (or same as verbatim?)
            #
            # Actually, `verbatim` usually means "before proxy mutations". `mutated` means "after".
            # CTP is "before". PTB is "after".
            # If we have separate records, CTP record tracks what came in. PTB tracks what went out.
            #
            # So:
            # CTP Record: leg=CTP, verbatim_prompt=X, mutated_prompt=0
            # PTB Record: leg=PTB, verbatim_prompt=0, mutated_prompt=Y
            #
            # This allows full tracing.

            verbatim_prompt = prompt_tokens
        else:
            # Egress points (to backend or to client)
            # PTB: Proxy to Backend. This is "mutated" prompt.
            # PTC: Proxy to Client. This is response flow, but if record_request is called for it...
            # actually record_request is usually for PROMPTS. record_response is for COMPLETIONS.
            #
            # CTP (Request): Verbatim Prompt.
            # PTB (Request): Mutated Prompt.
            # BTP (Response): Verbatim Completion.
            # PTC (Response): Mutated Completion.

            mutated_prompt = prompt_tokens

        record = UsageRecord(
            id=record_id,
            timestamp=timestamp,
            session_id=session_id,
            turn_number=turn_number,
            backend_type=backend_type,
            model=model,
            frontend_type=frontend_type,
            leg=leg,
            verbatim_prompt_tokens=verbatim_prompt,
            verbatim_completion_tokens=0,
            mutated_prompt_tokens=mutated_prompt,
            mutated_completion_tokens=0,
            total_tokens=verbatim_prompt + mutated_prompt,
            backend_reported_usage=None,
            http_status_code=None,
            tool_call_count=0,
            tool_names=[],
            ttft_ms=None,
            proxy_processing_ms=0.0,
            total_duration_ms=0.0,
            user_agent=user_agent,
            app_title=None,
            proxy_user=proxy_user,
        )

        try:
            # Add single record (using batch_insert for list of 1)
            await self._usage_repo.batch_insert([record])
        except Exception as e:
            logger.error(f"Failed to record request usage: {e}", exc_info=True)
            # We don't raise here to avoid blocking the main flow, but we log error

        return record_id

    async def record_response(
        self,
        record_id: str,
        completion_tokens: int,
        http_status_code: int | None = None,
        tool_call_count: int = 0,
        tool_names: list[str] | None = None,
        ttft_ms: float | None = None,
        stream_tps: float | None = None,
        backend_wait_ms: float | None = None,
        proxy_processing_ms: float = 0,
        total_duration_ms: float = 0,
        backend_reported_prompt_tokens: int | None = None,
        backend_reported_completion_tokens: int | None = None,
        backend_reported_cost: float | None = None,
        backend_reported_usage: dict[str, Any] | None = None,
    ) -> None:
        """Complete a usage record with response data."""

        try:
            # Get existing record domain object
            record = await self._usage_repo.get_by_id_domain(record_id)
            if not record:
                logger.warning(f"Usage record not found for update: {record_id}")
                return

            # Determine fields to update
            # If leg is BTP (Backend to Proxy), we have Verbatim Completion.
            # If leg is PTC (Proxy to Client), we have Mutated Completion.
            # If leg is CTP or PTB, we usually don't have completion tokens unless it's an error or short-circuit?
            # Actually CTP/PTB are request legs, but they might be associated with the response of that leg?
            #
            # Wait, the interaction diagram:
            # Frontend->UsageService: record_request(CTP) -> Create
            # ...
            # Frontend-->>Client: Response
            # UsageService->UsageService: record_response(PTC) -> Update UsageRecord
            #
            # The diagram implies record_response updates the SAME record?
            # "UsageService->Storage: Update UsageRecord"
            #
            # If I returned `record_id` from `record_request`, the caller uses it to call `record_response`.
            # So `record_response` updates the record created by `record_request`.
            #
            # So:
            # CTP Request -> record_request(CTP) -> ID1.
            # Response to Client (corresponding to CTP) -> record_response(ID1, completion_tokens=...)
            #
            # But earlier I reasoned that CTP is "Verbatim Prompt".
            # The response to CTP is "Mutated Completion" (sent to client).
            #
            # Let's check the TrafficLeg Enum again.
            # CTP = Client To Proxy. (Request)
            # PTC = Proxy To Client. (Response)
            #
            # If we reuse the record ID from CTP for the response, then we are mixing CTP and PTC in one record?
            # "UsageRecord... leg: TrafficLeg". UsageRecord has ONE leg field.
            #
            # If I call record_request(CTP), the record has leg=CTP.
            # If I call record_response(ID_of_CTP), I am adding completion tokens to a CTP record.
            # Does CTP record represent the "Client-side Turn"? Yes.
            #
            # So:
            # - CTP Record: Represents the Client <-> Proxy interaction.
            #   - verbatim_prompt (what client sent)
            #   - mutated_completion (what client received)
            #
            # - PTB Record: Represents the Proxy <-> Backend interaction.
            #   - mutated_prompt (what backend received)
            #   - verbatim_completion (what backend returned)
            #
            # This makes sense and aligns with "Four Measurement Points" diagram if we group them into 2 records per turn (Client-side and Backend-side).
            #
            # Or maybe 4 records?
            # The diagram says:
            # Frontend->UsageService: record_request(CTP) ... UsageService->Storage: Create UsageRecord
            # Frontend->Backend: Forward Request ... UsageService->UsageService: record_request(PTB)
            #
            # This implies multiple calls to record_request.
            #
            # So:
            # 1. record_request(CTP) -> ID1.
            # 2. record_request(PTB) -> ID2.
            # 3. record_response(ID2) -> Update ID2 (BTP data).
            # 4. record_response(ID1) -> Update ID1 (PTC data).
            #
            # This implies ID2 has leg=PTB. And ID1 has leg=CTP.
            #
            # If ID2 (PTB) gets response data (BTP), then ID2 represents the Backend interaction.
            # verbatim_completion should be set on ID2.
            #
            # If ID1 (CTP) gets response data (PTC), then ID1 represents the Client interaction.
            # mutated_completion should be set on ID1.

            # Update logic:
            if record.leg == TrafficLeg.CLIENT_TO_PROXY:
                # This is the Client-side record.
                # Response is PTC (Mutated Completion).
                record.mutated_completion_tokens = completion_tokens
                # It might technically have verbatim_completion if we wanted to copy it, but strict separation suggests keeping it as "what client received".
            elif record.leg == TrafficLeg.PROXY_TO_BACKEND:
                # This is the Backend-side record.
                # Response is BTP (Verbatim Completion).
                record.verbatim_completion_tokens = completion_tokens
            elif record.leg == TrafficLeg.BACKEND_TO_PROXY:
                # Should not happen as request start? BTP is a response flow.
                # Unless we treat BTP as a separate push? Unlikely for request/response model.
                record.verbatim_completion_tokens = completion_tokens
            elif record.leg == TrafficLeg.PROXY_TO_CLIENT:
                # Should not happen as request start?
                record.mutated_completion_tokens = completion_tokens

            # Update totals
            record.total_tokens = (
                record.verbatim_prompt_tokens
                + record.mutated_prompt_tokens
                + record.verbatim_completion_tokens
                + record.mutated_completion_tokens
            )

            # Update other fields
            if http_status_code is not None:
                record.http_status_code = http_status_code

            record.tool_call_count = tool_call_count
            if tool_names:
                record.tool_names = tool_names

            if ttft_ms is not None:
                record.ttft_ms = ttft_ms

            if stream_tps is not None:
                record.stream_tps = stream_tps

            if backend_wait_ms is not None:
                record.backend_wait_ms = backend_wait_ms

            record.proxy_processing_ms = proxy_processing_ms
            record.total_duration_ms = total_duration_ms

            # Parse backend reported usage
            if backend_reported_usage:
                record.backend_reported_usage = OpenRouterUsage.from_dict(
                    backend_reported_usage
                )
            elif (
                backend_reported_prompt_tokens is not None
                or backend_reported_completion_tokens is not None
            ):
                # Fallback to creating from individual fields if dict not provided
                record.backend_reported_usage = OpenRouterUsage.from_basic_usage(
                    prompt_tokens=backend_reported_prompt_tokens or 0,
                    completion_tokens=backend_reported_completion_tokens or 0,
                    total_tokens=None,
                )
                if backend_reported_cost is not None:
                    record.backend_reported_usage.cost = backend_reported_cost

            # Persist update
            await self._usage_repo.batch_update([record])

        except Exception as e:
            logger.error(f"Failed to record response usage: {e}", exc_info=True)

    async def get_usage_stats(
        self,
        filters: StatisticsFilter,
    ) -> AggregatedStats:
        """Get aggregated statistics with optional filters."""
        try:
            # Use repository aggregation
            # The repository method returns a dict, we need to convert to AggregatedStats
            stats_dict = await self._usage_repo.get_aggregated_stats(filters)
            status_codes = await self._usage_repo.get_status_code_breakdown(filters)

            # Flatten status codes for AggregatedStats which expects dict[int, int]
            # Repository returns dict[str, dict[int, int]] (backend:model -> {code: count})
            # We need to aggregate across all backend/models for the top-level stats
            flat_status_codes: dict[int, int] = {}
            for model_codes in status_codes.values():
                for code, count in model_codes.items():
                    flat_status_codes[code] = flat_status_codes.get(code, 0) + count

            # Calculate derived metrics
            # Avoid division by zero
            tokens_per_session = 0.0
            if stats_dict.get("unique_sessions", 0) > 0:
                tokens_per_session = stats_dict.get("total_tokens", 0) / stats_dict.get(
                    "unique_sessions"
                )

            # For TPS, we need a time window. If not provided in filters (via date range),
            # we might use first/last timestamp from stats.
            time_window = 0.0
            first_ts = stats_dict.get("first_timestamp")
            last_ts = stats_dict.get("last_timestamp")
            if first_ts and last_ts:
                time_window = (last_ts - first_ts).total_seconds()

            completion_tps = 0.0
            total_tps = 0.0
            if time_window > 0:
                completion_tps = (
                    stats_dict.get("total_completion_tokens", 0) / time_window
                )
                total_tps = stats_dict.get("total_tokens", 0) / time_window

            # Map dict to AggregatedStats
            # Note: AggregatedStats expects TimingStats objects for timing
            from src.core.domain.timing_stats import TimingStats

            def make_timing(prefix: str) -> TimingStats | None:
                if (
                    stats_dict.get(f"{prefix}_ttft") is None
                    and stats_dict.get(f"avg_{prefix}") is None
                ):
                    # Check based on keys present in repo output: min_ttft, max_ttft, avg_ttft
                    # For duration: min_duration, ...
                    pass

                # Check keys from repo get_aggregated_stats
                # min_ttft, max_ttft, avg_ttft
                # min_proxy_processing, ...
                # min_duration, ...

                # Using prefix to match repo keys
                # prefix = "ttft" or "proxy_processing" or "duration"

                count = stats_dict.get("response_count", 0)  # Approximation
                if count == 0:
                    return None

                return TimingStats(
                    count=count,
                    min_ms=stats_dict.get(f"min_{prefix}", 0.0) or 0.0,
                    max_ms=stats_dict.get(f"max_{prefix}", 0.0) or 0.0,
                    avg_ms=stats_dict.get(f"avg_{prefix}", 0.0) or 0.0,
                    p50_ms=0.0,  # Not calculated by repo yet
                    p95_ms=0.0,
                    p99_ms=0.0,
                )

            return AggregatedStats(
                request_count=stats_dict.get("request_count", 0),
                response_count=stats_dict.get("response_count", 0),
                unique_sessions=stats_dict.get("unique_sessions", 0),
                total_turns=stats_dict.get("total_turns", 0),
                total_prompt_tokens=stats_dict.get("total_prompt_tokens", 0),
                total_completion_tokens=stats_dict.get("total_completion_tokens", 0),
                total_tokens=stats_dict.get("total_tokens", 0),
                tokens_per_session=tokens_per_session,
                completion_tokens_per_second=completion_tps,
                total_tokens_per_second=total_tps,
                total_tool_calls=stats_dict.get("total_tool_calls", 0),
                ttft_stats=make_timing("ttft"),
                proxy_processing_stats=make_timing("proxy_processing"),
                duration_stats=make_timing("duration"),
                status_code_counts=flat_status_codes,
                filters=filters.__dict__ if hasattr(filters, "__dict__") else {},
                time_window_seconds=time_window,
            )

        except Exception as e:
            logger.error(f"Failed to get usage stats: {e}", exc_info=True)
            return AggregatedStats()

    async def get_recent_usage(
        self,
        filters: StatisticsFilter | None = None,
        limit: int = 100,
    ) -> list[UsageRecord]:
        """Get recent usage records."""
        try:
            return await self._usage_repo.query_with_filter(filters, limit=limit)
        except Exception as e:
            logger.error(f"Failed to get recent usage: {e}", exc_info=True)
            return []
