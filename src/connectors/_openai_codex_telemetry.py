"""Telemetry and monitoring for OpenAI Codex compatibility layer.

Memory note:
This module previously stored *all* duration samples in in-memory lists
(`detection_durations`, `translation_durations`, and `durations_by_tool`). In a
long-running proxy this grows without bound and becomes a memory leak.

We cap the number of stored samples per series to a small rolling window.
Counters (totals, per-tool counts, etc.) remain unbounded integers by design.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from src.core.app.constants.logging_constants import TRACE_LEVEL

logger = logging.getLogger(__name__)

# Maximum number of duration samples retained per series (rolling window).
# This keeps memory bounded while still providing useful averages.
DEFAULT_DURATION_SAMPLE_LIMIT = 1024

# Maximum number of unique tools to track individually
# This prevents memory leaks from clients generating random tool names
DEFAULT_TOOL_TRACKING_LIMIT = 100
_OTHER_TOOL_KEY = "__other_tools_overflow__"


class MetricType(Enum):
    """Types of metrics tracked by compatibility layer."""

    DETECTION_TOTAL = "compatibility_layer_detection_total"
    DETECTION_DURATION = "compatibility_layer_detection_duration_seconds"
    CACHE_HIT_TOTAL = "compatibility_layer_cache_hit_total"
    TRANSLATION_TOTAL = "compatibility_layer_translation_total"
    TRANSLATION_DURATION = "compatibility_layer_translation_duration_seconds"
    TOOL_EXECUTION_TOTAL = "compatibility_layer_tool_execution_total"
    ERROR_TOTAL = "compatibility_layer_error_total"
    UNSUPPORTED_TOOL_TOTAL = "compatibility_layer_unsupported_tool_total"


from pydantic import BaseModel


class DetectionMetricsSummary(BaseModel):
    total: int
    by_method: dict[str, int]
    cache: dict[str, int | float]
    average_duration_ms: float


class ToolTranslationSummary(BaseModel):
    count: int
    average_duration_ms: float


class TranslationMetricsSummary(BaseModel):
    total: int
    successful: int
    failed: int
    success_rate: float
    average_duration_ms: float
    by_tool: dict[str, ToolTranslationSummary]


class ErrorMetricsSummary(BaseModel):
    total: int
    by_code: dict[str, int]
    by_tool: dict[str, int]


class TelemetrySummary(BaseModel):
    detection: DetectionMetricsSummary
    translation: TranslationMetricsSummary
    errors: ErrorMetricsSummary


@dataclass
class DetectionMetrics:
    """Metrics for client detection operations."""

    total_detections: int = 0
    metadata_detections: int = 0
    header_detections: int = 0
    heuristic_detections: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_duration_ms: float = 0.0

    # Rolling window of recent detection durations (bounded).
    detection_durations: deque[float] = field(
        default_factory=lambda: deque(maxlen=DEFAULT_DURATION_SAMPLE_LIMIT)
    )

    def record_detection(
        self, method: str, duration_ms: float, is_cached: bool = False
    ) -> None:
        """Record a detection event.

        Args:
            method: Detection method used (metadata, header, heuristic, cached)
            duration_ms: Time taken for detection in milliseconds
            is_cached: Whether this was a cache hit
        """
        self.total_detections += 1
        self.total_duration_ms += duration_ms
        self.detection_durations.append(duration_ms)

        if is_cached:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

            if method == "metadata":
                self.metadata_detections += 1
            elif method == "header":
                self.header_detections += 1
            elif method == "heuristic":
                self.heuristic_detections += 1

    def get_average_duration(self) -> float:
        """Get average detection duration in milliseconds."""
        if not self.detection_durations:
            return 0.0
        return sum(self.detection_durations) / len(self.detection_durations)


@dataclass
class TranslationMetrics:
    """Metrics for tool translation operations."""

    total_translations: int = 0
    successful_translations: int = 0
    failed_translations: int = 0
    total_duration_ms: float = 0.0

    # Rolling window of recent translation durations (bounded).
    translation_durations: deque[float] = field(
        default_factory=lambda: deque(maxlen=DEFAULT_DURATION_SAMPLE_LIMIT)
    )

    translations_by_tool: dict[str, int] = field(default_factory=dict)

    # Rolling window of durations per tool (bounded per tool).
    durations_by_tool: dict[str, deque[float]] = field(default_factory=dict)

    def record_translation(
        self, tool_name: str, duration_ms: float, success: bool = True
    ) -> None:
        """Record a translation event.

        Args:
            tool_name: Name of tool being translated
            duration_ms: Time taken for translation in milliseconds
            success: Whether translation was successful
        """
        self.total_translations += 1
        self.total_duration_ms += duration_ms
        self.translation_durations.append(duration_ms)

        if success:
            self.successful_translations += 1
        else:
            self.failed_translations += 1

        # Track per-tool counters
        effective_tool_name = tool_name
        if (
            len(self.translations_by_tool) >= DEFAULT_TOOL_TRACKING_LIMIT
            and tool_name not in self.translations_by_tool
        ):
            effective_tool_name = _OTHER_TOOL_KEY

        self.translations_by_tool[effective_tool_name] = (
            self.translations_by_tool.get(effective_tool_name, 0) + 1
        )

        durations = self.durations_by_tool.get(effective_tool_name)
        if durations is None:
            durations = deque(maxlen=DEFAULT_DURATION_SAMPLE_LIMIT)
            self.durations_by_tool[effective_tool_name] = durations
        durations.append(duration_ms)

    def get_average_duration(self, tool_name: str | None = None) -> float:
        """Get average translation duration in milliseconds.

        Args:
            tool_name: Optional tool name to get average for specific tool

        Returns:
            Average duration in milliseconds
        """
        if tool_name:
            durations = self.durations_by_tool.get(tool_name)
            if not durations:
                return 0.0
            return sum(durations) / len(durations)

        if not self.translation_durations:
            return 0.0
        return sum(self.translation_durations) / len(self.translation_durations)


@dataclass
class ErrorMetrics:
    """Metrics for error tracking."""

    total_errors: int = 0
    errors_by_code: dict[str, int] = field(default_factory=dict)
    errors_by_tool: dict[str, int] = field(default_factory=dict)

    def record_error(self, error_code: str, tool_name: str | None = None) -> None:
        """Record an error event.

        Args:
            error_code: Error code from CompatibilityErrorCode
            tool_name: Optional tool name where error occurred
        """
        self.total_errors += 1

        # Track by error code
        self.errors_by_code[error_code] = self.errors_by_code.get(error_code, 0) + 1

        # Track by tool if provided
        if tool_name:
            effective_tool_name = tool_name
            if (
                len(self.errors_by_tool) >= DEFAULT_TOOL_TRACKING_LIMIT
                and tool_name not in self.errors_by_tool
            ):
                effective_tool_name = _OTHER_TOOL_KEY

            self.errors_by_tool[effective_tool_name] = (
                self.errors_by_tool.get(effective_tool_name, 0) + 1
            )


class CompatibilityTelemetry:
    """Central telemetry collector for compatibility layer."""

    def __init__(self):
        """Initialize telemetry collector."""
        self.detection_metrics = DetectionMetrics()
        self.translation_metrics = TranslationMetrics()
        self.error_metrics = ErrorMetrics()
        self._enabled = True
        self._lock = threading.Lock()

    def enable(self) -> None:
        """Enable telemetry collection."""
        with self._lock:
            self._enabled = True
        if logger.isEnabledFor(logging.INFO):
            logger.info("Compatibility layer telemetry enabled")

    def disable(self) -> None:
        """Disable telemetry collection."""
        with self._lock:
            self._enabled = False
        if logger.isEnabledFor(logging.INFO):
            logger.info("Compatibility layer telemetry disabled")

    def is_enabled(self) -> bool:
        """Check if telemetry is enabled."""
        with self._lock:
            return bool(self._enabled)

    def log_detection_event(
        self,
        session_id: str,
        is_kilocode: bool,
        detection_method: str,
        confidence: float,
        duration_ms: float,
        agent_string: str | None = None,
    ) -> None:
        """Log a structured detection event.

        Args:
            session_id: Session identifier
            is_kilocode: Whether KiloCode was detected
            detection_method: Method used for detection
            confidence: Detection confidence (0.0 to 1.0)
            duration_ms: Detection duration in milliseconds
            agent_string: Optional agent string
        """
        if not self._enabled:
            return

        is_cached = detection_method == "cached"

        # Thread-safe: Record metrics under lock to prevent concurrent mutations
        with self._lock:
            self.detection_metrics.record_detection(
                detection_method, duration_ms, is_cached
            )

        # Structured logging at TRACE (verbose; avoid building extra dict when disabled)
        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "Codex-Kilo compatibility layer detection",
                extra={
                    "event_type": "detection",
                    "session_id": session_id,
                    "is_kilocode": is_kilocode,
                    "detection_method": detection_method,
                    "confidence": confidence,
                    "duration_ms": duration_ms,
                    "agent_string": agent_string,
                    "cached": is_cached,
                },
            )

    def log_translation_event(
        self,
        session_id: str,
        tool_name: str,
        original_xml: str | None,
        translated_tool: str | None,
        execution_mode: str,
        duration_ms: float,
        success: bool = True,
    ) -> None:
        """Log a structured translation event.

        Args:
            session_id: Session identifier
            tool_name: Original tool name from XML
            original_xml: Original XML text (truncated for logging)
            translated_tool: Translated tool name
            execution_mode: Execution mode (codex, proxy, mcp)
            duration_ms: Translation duration in milliseconds
            success: Whether translation was successful
        """
        if not self._enabled:
            return

        # Thread-safe: Record metrics under lock to prevent concurrent mutations
        with self._lock:
            self.translation_metrics.record_translation(tool_name, duration_ms, success)

        # Structured logging at TRACE (truncate XML only when TRACE is enabled)
        if logger.isEnabledFor(TRACE_LEVEL):
            xml_preview = None
            if original_xml:
                xml_preview = (
                    original_xml[:200] + "..."
                    if len(original_xml) > 200
                    else original_xml
                )
            logger.log(
                TRACE_LEVEL,
                "Codex-Kilo tool translation",
                extra={
                    "event_type": "translation",
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "original_xml_preview": xml_preview,
                    "translated_tool": translated_tool,
                    "execution_mode": execution_mode,
                    "duration_ms": duration_ms,
                    "success": success,
                },
            )

    def log_error_event(
        self,
        session_id: str,
        error_code: str,
        tool_name: str | None,
        error_message: str,
        original_xml: str | None = None,
        stack_trace: str | None = None,
    ) -> None:
        """Log a structured error event.

        Args:
            session_id: Session identifier
            error_code: Error code from CompatibilityErrorCode
            tool_name: Tool name where error occurred
            error_message: Error message
            original_xml: Original XML that caused error (truncated)
            stack_trace: Optional stack trace
        """
        if not self._enabled:
            return

        # Thread-safe: Record metrics under lock to prevent concurrent mutations
        with self._lock:
            self.error_metrics.record_error(error_code, tool_name)

        # Truncate XML for logging
        xml_preview = None
        if original_xml:
            xml_preview = (
                original_xml[:200] + "..." if len(original_xml) > 200 else original_xml
            )

        # Structured logging
        logger.error(
            "Codex-Kilo compatibility layer error",
            extra={
                "event_type": "error",
                "session_id": session_id,
                "error_code": error_code,
                "tool_name": tool_name,
                "error_message": error_message,
                "original_xml_preview": xml_preview,
                "stack_trace": stack_trace,
            },
        )

    def get_metrics_summary(self) -> TelemetrySummary:
        """Get a summary of all collected metrics.

        Returns:
            TelemetrySummary model containing metrics summary.
        """
        # Thread-safe: Acquire lock to ensure consistent snapshot
        with self._lock:
            return TelemetrySummary(
                detection=DetectionMetricsSummary(
                    total=self.detection_metrics.total_detections,
                    by_method={
                        "metadata": self.detection_metrics.metadata_detections,
                        "header": self.detection_metrics.header_detections,
                        "heuristic": self.detection_metrics.heuristic_detections,
                    },
                    cache={
                        "hits": self.detection_metrics.cache_hits,
                        "misses": self.detection_metrics.cache_misses,
                        "hit_rate": (
                            self.detection_metrics.cache_hits
                            / self.detection_metrics.total_detections
                            if self.detection_metrics.total_detections > 0
                            else 0.0
                        ),
                    },
                    average_duration_ms=self.detection_metrics.get_average_duration(),
                ),
                translation=TranslationMetricsSummary(
                    total=self.translation_metrics.total_translations,
                    successful=self.translation_metrics.successful_translations,
                    failed=self.translation_metrics.failed_translations,
                    success_rate=(
                        self.translation_metrics.successful_translations
                        / self.translation_metrics.total_translations
                        if self.translation_metrics.total_translations > 0
                        else 0.0
                    ),
                    average_duration_ms=self.translation_metrics.get_average_duration(),
                    by_tool={
                        tool: ToolTranslationSummary(
                            count=count,
                            average_duration_ms=self.translation_metrics.get_average_duration(
                                tool
                            ),
                        )
                        for tool, count in self.translation_metrics.translations_by_tool.items()
                    },
                ),
                errors=ErrorMetricsSummary(
                    total=self.error_metrics.total_errors,
                    by_code=self.error_metrics.errors_by_code,
                    by_tool=self.error_metrics.errors_by_tool,
                ),
            )

    def reset_metrics(self) -> None:
        """Reset all collected metrics."""
        with self._lock:
            self.detection_metrics = DetectionMetrics()
            self.translation_metrics = TranslationMetrics()
            self.error_metrics = ErrorMetrics()
        if logger.isEnabledFor(logging.INFO):
            logger.info("Compatibility layer metrics reset")


# Global telemetry instance
_telemetry_instance: CompatibilityTelemetry | None = None
_telemetry_lock = threading.Lock()


def get_telemetry() -> CompatibilityTelemetry:
    """Get the global telemetry instance.

    Returns:
        Global CompatibilityTelemetry instance
    """
    global _telemetry_instance
    if _telemetry_instance is None:
        with _telemetry_lock:
            if _telemetry_instance is None:
                _telemetry_instance = CompatibilityTelemetry()
    return _telemetry_instance


def reset_telemetry() -> None:
    """Reset the global telemetry instance (mainly for testing)."""
    global _telemetry_instance
    with _telemetry_lock:
        _telemetry_instance = None
