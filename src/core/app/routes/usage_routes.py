"""
REST API routes for detailed usage tracking and statistics.

This module provides FastAPI routes for querying usage statistics,
recent usage records, and exporting usage data with comprehensive
filtering support.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from src.core.app.routes.usage_models import (
    RecentUsageResponse,
    TimingStatsModel,
    UsageExportResponse,
    UsageStatisticsResponse,
)
from src.core.domain.aggregated_stats import AggregatedStats
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.traffic_leg import TrafficLeg
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.statistics_service_interface import IStatisticsService

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/usage", tags=["usage"])


def get_service_provider(request: Request) -> IServiceProvider:
    """Get the service provider from app state.

    Args:
        request: The FastAPI request object

    Returns:
        The service provider from app state

    Raises:
        HTTPException: If service provider is not available
    """
    service_provider = getattr(request.app.state, "service_provider", None)
    if not service_provider:
        raise HTTPException(
            status_code=503, detail="Service provider not available in app state"
        )
    return cast(IServiceProvider, service_provider)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse a datetime string in ISO format.

    Args:
        value: ISO format datetime string or None

    Returns:
        Parsed datetime or None

    Raises:
        ValueError: If the datetime string is invalid
    """
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(
            f"Invalid datetime format: {value}. Expected ISO format."
        ) from e


def parse_traffic_leg(value: str | None) -> TrafficLeg | None:
    """Parse a traffic leg string.

    Args:
        value: Traffic leg string (CTP, PTB, BTP, PTC) or None

    Returns:
        Parsed TrafficLeg or None

    Raises:
        ValueError: If the traffic leg string is invalid
    """
    if value is None:
        return None
    try:
        return TrafficLeg(value)
    except ValueError as e:
        raise ValueError(
            f"Invalid traffic leg: {value}. Expected one of: CTP, PTB, BTP, PTC"
        ) from e


@router.get("/stats")
async def get_usage_stats(
    request: Request,
    backend_type: str | None = Query(None, description="Filter by backend type"),
    model: str | None = Query(None, description="Filter by model name"),
    frontend_type: str | None = Query(None, description="Filter by frontend type"),
    leg: str | None = Query(
        None, description="Filter by traffic leg (CTP, PTB, BTP, PTC)"
    ),
    user_agent: str | None = Query(None, description="Filter by user agent"),
    proxy_user: str | None = Query(None, description="Filter by proxy user"),
    start_date: str | None = Query(
        None, description="Filter by start date (ISO format)"
    ),
    end_date: str | None = Query(None, description="Filter by end date (ISO format)"),
    day_of_week: int | None = Query(
        None, ge=0, le=6, description="Filter by day of week (0=Monday, 6=Sunday)"
    ),
    hour_of_day: int | None = Query(
        None, ge=0, le=23, description="Filter by hour of day (0-23)"
    ),
    http_status_code: int | None = Query(
        None, description="Filter by HTTP status code"
    ),
    service_provider: IServiceProvider = Depends(get_service_provider),
) -> UsageStatisticsResponse:
    """Get aggregated usage statistics with optional filters.


    This endpoint returns comprehensive statistics including:
    - Request/response counts
    - Token metrics (prompt, completion, total)
    - Session metrics (unique sessions, turns, tokens per session)
    - Throughput metrics (tokens per second)
    - Tool call metrics
    - Timing statistics (TTFT, proxy processing, total duration)
    - HTTP status code breakdown

    All filter parameters are optional and can be combined.

    Args:
        request: FastAPI request object
        backend_type: Filter by backend type (e.g., 'openai', 'anthropic', 'gemini')
        model: Filter by model name
        frontend_type: Filter by frontend type
        leg: Filter by traffic leg (CTP, PTB, BTP, PTC)
        user_agent: Filter by user agent string
        proxy_user: Filter by proxy user identifier
        start_date: Filter records on or after this date (ISO format)
        end_date: Filter records on or before this date (ISO format)
        day_of_week: Filter by day of week (0=Monday, 6=Sunday)
        hour_of_day: Filter by hour of day (0-23)
        http_status_code: Filter by HTTP status code
        service_provider: Service provider dependency

    Returns:
        Dictionary containing aggregated statistics

    Raises:
        HTTPException: 400 if filter parameters are invalid
        HTTPException: 500 if statistics service is not available
        HTTPException: 503 if service provider is not available
    """
    try:
        # Parse datetime filters
        try:
            parsed_start_date = parse_datetime(start_date)
            parsed_end_date = parse_datetime(end_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Parse traffic leg filter
        try:
            parsed_leg = parse_traffic_leg(leg)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Create filter
        filters = StatisticsFilter(
            backend_type=backend_type,
            model=model,
            frontend_type=frontend_type,
            leg=parsed_leg,
            user_agent=user_agent,
            proxy_user=proxy_user,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            day_of_week=day_of_week,
            hour_of_day=hour_of_day,
            http_status_code=http_status_code,
        )

        # Get statistics service
        stats_service = service_provider.get_service(IStatisticsService)  # type: ignore[type-abstract]
        if stats_service is None:
            raise HTTPException(
                status_code=500, detail="Statistics service not available"
            )

        # Get aggregated stats
        stats: AggregatedStats = await stats_service.get_aggregated_stats(filters)

        # Convert to response format
        return _aggregated_stats_to_response(stats)


    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting usage stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e!s}")


def _aggregated_stats_to_response(stats: AggregatedStats) -> UsageStatisticsResponse:
    """Convert AggregatedStats to a Pydantic response model.

    Args:
        stats: AggregatedStats instance

    Returns:
        UsageStatisticsResponse model
    """
    result = UsageStatisticsResponse(
        request_count=stats.request_count,
        response_count=stats.response_count,
        unique_sessions=stats.unique_sessions,
        total_turns=stats.total_turns,
        total_prompt_tokens=stats.total_prompt_tokens,
        total_completion_tokens=stats.total_completion_tokens,
        total_tokens=stats.total_tokens,
        tokens_per_session=stats.tokens_per_session,
        completion_tokens_per_second=stats.completion_tokens_per_second,
        total_tokens_per_second=stats.total_tokens_per_second,
        total_tool_calls=stats.total_tool_calls,
        status_code_counts=stats.status_code_counts,
        filters=stats.filters,
        time_window_seconds=stats.time_window_seconds,
    )

    # Add timing stats if available
    if stats.ttft_stats:
        result.ttft_stats = TimingStatsModel(
            count=stats.ttft_stats.count,
            min_ms=stats.ttft_stats.min_ms,
            max_ms=stats.ttft_stats.max_ms,
            avg_ms=stats.ttft_stats.avg_ms,
            p50_ms=stats.ttft_stats.p50_ms,
            p95_ms=stats.ttft_stats.p95_ms,
            p99_ms=stats.ttft_stats.p99_ms,
        )

    if stats.proxy_processing_stats:
        result.proxy_processing_stats = TimingStatsModel(
            count=stats.proxy_processing_stats.count,
            min_ms=stats.proxy_processing_stats.min_ms,
            max_ms=stats.proxy_processing_stats.max_ms,
            avg_ms=stats.proxy_processing_stats.avg_ms,
            p50_ms=stats.proxy_processing_stats.p50_ms,
            p95_ms=stats.proxy_processing_stats.p95_ms,
            p99_ms=stats.proxy_processing_stats.p99_ms,
        )

    if stats.duration_stats:
        result.duration_stats = TimingStatsModel(
            count=stats.duration_stats.count,
            min_ms=stats.duration_stats.min_ms,
            max_ms=stats.duration_stats.max_ms,
            avg_ms=stats.duration_stats.avg_ms,
            p50_ms=stats.duration_stats.p50_ms,
            p95_ms=stats.duration_stats.p95_ms,
            p99_ms=stats.duration_stats.p99_ms,
        )

    return result



@router.get("/recent")
async def get_recent_usage(
    request: Request,
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of records to return"
    ),
    offset: int = Query(
        0, ge=0, description="Number of records to skip (for pagination)"
    ),
    backend_type: str | None = Query(None, description="Filter by backend type"),
    model: str | None = Query(None, description="Filter by model name"),
    service_provider: IServiceProvider = Depends(get_service_provider),
) -> RecentUsageResponse:
    """Get recent usage records with pagination and filtering.


    This endpoint returns individual usage records (not aggregated) with support
    for pagination and filtering by session ID, backend type, and model.

    Args:
        request: FastAPI request object
        session_id: Filter by session ID
        limit: Maximum number of records to return (1-1000)
        offset: Number of records to skip for pagination
        backend_type: Filter by backend type
        model: Filter by model name
        service_provider: Service provider dependency

    Returns:
        Dictionary containing:
        - records: List of usage records
        - total: Total number of matching records
        - limit: Limit applied
        - offset: Offset applied

    Raises:
        HTTPException: 400 if parameters are invalid
        HTTPException: 500 if usage store is not available
        HTTPException: 503 if service provider is not available
    """
    try:
        # Get usage store
        from src.core.services.in_memory_usage_store import InMemoryUsageStore

        usage_store = service_provider.get_service(InMemoryUsageStore)
        if usage_store is None:
            raise HTTPException(status_code=500, detail="Usage store not available")

        # Create filter
        filters = StatisticsFilter(
            backend_type=backend_type,
            model=model,
        )

        # Get all matching records
        all_records = usage_store.get_records(filters)

        # Filter by session_id if provided
        if session_id:
            all_records = [r for r in all_records if r.session_id == session_id]

        # Sort by timestamp descending (most recent first)
        all_records.sort(key=lambda r: r.timestamp, reverse=True)

        # Apply pagination
        total = len(all_records)
        paginated_records = all_records[offset : offset + limit]

        # Convert to dictionaries
        records_data = [record.to_dict() for record in paginated_records]

        return RecentUsageResponse(
            records=records_data,
            total=total,
            limit=limit,
            offset=offset,
        )


    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting recent usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e!s}")


@router.get("/export")
async def export_usage_data(
    request: Request,
    start_date: str | None = Query(
        None, description="Export records on or after this date (ISO format)"
    ),
    end_date: str | None = Query(
        None, description="Export records on or before this date (ISO format)"
    ),
    backend_type: str | None = Query(None, description="Filter by backend type"),
    model: str | None = Query(None, description="Filter by model name"),
    service_provider: IServiceProvider = Depends(get_service_provider),
) -> UsageExportResponse:
    """Export usage data as JSON with date range filtering.


    This endpoint exports all usage records matching the specified filters
    in a structured JSON format suitable for backup, analysis, or import.

    Args:
        request: FastAPI request object
        start_date: Export records on or after this date (ISO format)
        end_date: Export records on or before this date (ISO format)
        backend_type: Filter by backend type
        model: Filter by model name
        service_provider: Service provider dependency

    Returns:
        Dictionary containing:
        - version: Export format version
        - exported_at: Timestamp of export
        - record_count: Number of records exported
        - filters: Filters applied
        - records: List of usage records

    Raises:
        HTTPException: 400 if date parameters are invalid
        HTTPException: 500 if usage store is not available
        HTTPException: 503 if service provider is not available
    """
    try:
        # Parse datetime filters
        try:
            parsed_start_date = parse_datetime(start_date)
            parsed_end_date = parse_datetime(end_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Get usage store
        from src.core.services.in_memory_usage_store import InMemoryUsageStore

        usage_store = service_provider.get_service(InMemoryUsageStore)
        if usage_store is None:
            raise HTTPException(status_code=500, detail="Usage store not available")

        # Create filter
        filters = StatisticsFilter(
            backend_type=backend_type,
            model=model,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        )

        # Get matching records
        records = usage_store.get_records(filters)

        # Sort by timestamp ascending (chronological order)
        records.sort(key=lambda r: r.timestamp)

        # Convert to dictionaries
        records_data = [record.to_dict() for record in records]

        # Build filter metadata
        filter_metadata: dict[str, Any] = {}
        if backend_type:
            filter_metadata["backend_type"] = backend_type
        if model:
            filter_metadata["model"] = model
        if start_date:
            filter_metadata["start_date"] = start_date
        if end_date:
            filter_metadata["end_date"] = end_date

        return UsageExportResponse(
            version=1,
            exported_at=datetime.now().isoformat(),
            record_count=len(records_data),
            filters=filter_metadata,
            records=records_data,
        )


    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting usage data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e!s}")
