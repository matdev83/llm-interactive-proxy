"""Metrics tracking for model replacement service.

This module provides comprehensive metrics tracking for the random model
replacement feature, including activation rates, turn count distributions,
and opt-out rates.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Any

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Maximum number of timestamps to keep in memory to prevent unbounded growth
# These limits ensure we can still calculate rates for reasonable time windows
# (e.g., 10,000 activations at 1/sec = ~2.7 hours of history)
_MAX_ACTIVATION_TIMESTAMPS = 10000
_MAX_OPT_OUT_TIMESTAMPS = 1000


@dataclass
class ReplacementMetrics:
    """Metrics container for model replacement service.

    Tracks:
    - Activation rate: Number of activations per time period
    - Turn count distribution: Distribution of turn counts across activations
    - Opt-out rate: Number of opt-outs per time period
    """

    # Activation tracking (Requirement 3.2)
    total_activations: int = 0
    activations_by_session: MutableMapping[str, int] = field(
        default_factory=lambda: TTLCache(maxsize=10000, ttl=3600)
    )
    activation_timestamps: list[float] = field(default_factory=list)

    # Turn count distribution tracking (Requirement 4.1)
    total_turns_completed: int = 0
    turns_by_session: MutableMapping[str, int] = field(
        default_factory=lambda: TTLCache(maxsize=10000, ttl=3600)
    )

    # Opt-out tracking (Requirements 9.1, 9.2)
    total_opt_outs: int = 0
    opt_outs_by_session: MutableMapping[str, int] = field(
        default_factory=lambda: TTLCache(maxsize=10000, ttl=3600)
    )
    opt_out_timestamps: list[float] = field(default_factory=list)
    header_opt_outs: int = 0
    session_opt_outs: int = 0

    # Probability check tracking
    total_probability_checks: int = 0
    probability_checks_by_session: MutableMapping[str, int] = field(
        default_factory=lambda: TTLCache(maxsize=10000, ttl=3600)
    )

    # Metadata
    start_time: float = field(default_factory=time.time)

    # Internal histograms (replacing unbounded lists)
    _turn_count_histogram: dict[int, int] = field(
        default_factory=lambda: defaultdict(int)
    )

    def record_activation(self, session_id: str, turn_count: int) -> None:
        """Record a replacement activation.

        Args:
            session_id: The session identifier
            turn_count: The number of turns for this activation
        """
        self.total_activations += 1
        self.activations_by_session[session_id] = (
            self.activations_by_session.get(session_id, 0) + 1
        )
        self.activation_timestamps.append(time.time())

        # Enforce size limit to prevent unbounded memory growth
        # Keep only the most recent timestamps (they are appended in order)
        if len(self.activation_timestamps) > _MAX_ACTIVATION_TIMESTAMPS:
            # Remove oldest entries, keeping only the most recent ones
            excess = len(self.activation_timestamps) - _MAX_ACTIVATION_TIMESTAMPS
            self.activation_timestamps = self.activation_timestamps[excess:]
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Pruned {excess} old activation timestamps to enforce size limit "
                    f"({_MAX_ACTIVATION_TIMESTAMPS})"
                )

        # Track in histogram instead of unbounded list
        self._turn_count_histogram[turn_count] += 1
        # Maintain compatibility for turn_counts property if needed, but we remove the field
        # self.turn_counts.append(turn_count) # Removed

        logger.debug(
            f"Metrics: Recorded activation for session {session_id}, "
            f"turn_count={turn_count}, total_activations={self.total_activations}"
        )

    def record_turn_completion(self, session_id: str) -> None:
        """Record a turn completion.

        Args:
            session_id: The session identifier
        """
        self.total_turns_completed += 1
        self.turns_by_session[session_id] = self.turns_by_session.get(session_id, 0) + 1

        logger.debug(
            f"Metrics: Recorded turn completion for session {session_id}, "
            f"total_turns={self.total_turns_completed}"
        )

    def record_opt_out(self, session_id: str, opt_out_type: str) -> None:
        """Record an opt-out event.

        Args:
            session_id: The session identifier
            opt_out_type: Type of opt-out ('header' or 'session')
        """
        self.total_opt_outs += 1
        self.opt_outs_by_session[session_id] = (
            self.opt_outs_by_session.get(session_id, 0) + 1
        )
        self.opt_out_timestamps.append(time.time())

        # Enforce size limit to prevent unbounded memory growth
        # Keep only the most recent timestamps (they are appended in order)
        if len(self.opt_out_timestamps) > _MAX_OPT_OUT_TIMESTAMPS:
            # Remove oldest entries, keeping only the most recent ones
            excess = len(self.opt_out_timestamps) - _MAX_OPT_OUT_TIMESTAMPS
            self.opt_out_timestamps = self.opt_out_timestamps[excess:]
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Pruned {excess} old opt-out timestamps to enforce size limit "
                    f"({_MAX_OPT_OUT_TIMESTAMPS})"
                )

        if opt_out_type == "header":
            self.header_opt_outs += 1
        elif opt_out_type == "session":
            self.session_opt_outs += 1

        logger.debug(
            f"Metrics: Recorded {opt_out_type} opt-out for session {session_id}, "
            f"total_opt_outs={self.total_opt_outs}"
        )

    def record_probability_check(self, session_id: str) -> None:
        """Record a probability check.

        Args:
            session_id: The session identifier
        """
        self.total_probability_checks += 1
        self.probability_checks_by_session[session_id] = (
            self.probability_checks_by_session.get(session_id, 0) + 1
        )

    def get_activation_rate(self, time_window_seconds: float | None = None) -> float:
        """Calculate activation rate per time period.

        Args:
            time_window_seconds: Time window in seconds (None for all time)

        Returns:
            Activations per second in the time window
        """
        if time_window_seconds is None:
            elapsed = max(time.time() - self.start_time, 1e-9)
            return self.total_activations / elapsed

        # Count activations within time window
        cutoff_time = time.time() - time_window_seconds
        recent_activations = sum(
            1 for ts in self.activation_timestamps if ts >= cutoff_time
        )

        if time_window_seconds == 0:
            return 0.0
        return recent_activations / time_window_seconds

    def get_activation_rate_by_session(self, session_id: str) -> float:
        """Calculate activation rate for a specific session.

        Args:
            session_id: The session identifier

        Returns:
            Activations per probability check for the session
        """
        checks = self.probability_checks_by_session.get(session_id, 0)
        if checks == 0:
            return 0.0

        activations = self.activations_by_session.get(session_id, 0)
        return activations / checks

    def get_turn_count_distribution(self) -> dict[int, int]:
        """Get distribution of turn counts.

        Returns:
            Dictionary mapping turn count to frequency
        """
        return dict(self._turn_count_histogram)

    def get_average_turn_count(self) -> float:
        """Calculate average turn count per activation.

        Returns:
            Average turn count (0.0 if no activations)
        """
        total_counts = sum(self._turn_count_histogram.values())
        if total_counts == 0:
            return 0.0

        weighted_sum = sum(
            count * freq for count, freq in self._turn_count_histogram.items()
        )
        return weighted_sum / total_counts

    def get_opt_out_rate(self, time_window_seconds: float | None = None) -> float:
        """Calculate opt-out rate per time period.

        Args:
            time_window_seconds: Time window in seconds (None for all time)

        Returns:
            Opt-outs per second in the time window
        """
        if time_window_seconds is None:
            elapsed = max(time.time() - self.start_time, 1e-9)
            return self.total_opt_outs / elapsed

        # Count opt-outs within time window
        cutoff_time = time.time() - time_window_seconds
        recent_opt_outs = sum(1 for ts in self.opt_out_timestamps if ts >= cutoff_time)

        if time_window_seconds == 0:
            return 0.0
        return recent_opt_outs / time_window_seconds

    def get_opt_out_rate_by_session(self, session_id: str) -> float:
        """Calculate opt-out rate for a specific session.

        Args:
            session_id: The session identifier

        Returns:
            Opt-outs per probability check for the session
        """
        checks = self.probability_checks_by_session.get(session_id, 0)
        if checks == 0:
            return 0.0

        opt_outs = self.opt_outs_by_session.get(session_id, 0)
        return opt_outs / checks

    def cleanup_session(self, session_id: str) -> None:
        """Remove metrics for a specific session to prevent memory leaks.

        Args:
            session_id: The session identifier to cleanup
        """
        self.activations_by_session.pop(session_id, None)
        self.turns_by_session.pop(session_id, None)
        self.opt_outs_by_session.pop(session_id, None)
        self.probability_checks_by_session.pop(session_id, None)

    def prune_history(self, max_age_seconds: float = 3600.0) -> None:
        """Prune historical timestamps to prevent unbounded growth.

        Args:
            max_age_seconds: Keep timestamps newer than this age
        """
        cutoff_time = time.time() - max_age_seconds

        # Prune activation timestamps
        if self.activation_timestamps and self.activation_timestamps[0] < cutoff_time:
            # Find index where timestamps become recent enough
            # Timestamps are appended, so they are sorted
            keep_idx = 0
            for i, ts in enumerate(self.activation_timestamps):
                if ts >= cutoff_time:
                    keep_idx = i
                    break
            else:
                # All are old
                keep_idx = len(self.activation_timestamps)

            if keep_idx > 0:
                self.activation_timestamps = self.activation_timestamps[keep_idx:]

        # Prune opt-out timestamps
        if self.opt_out_timestamps and self.opt_out_timestamps[0] < cutoff_time:
            keep_idx = 0
            for i, ts in enumerate(self.opt_out_timestamps):
                if ts >= cutoff_time:
                    keep_idx = i
                    break
            else:
                keep_idx = len(self.opt_out_timestamps)

            if keep_idx > 0:
                self.opt_out_timestamps = self.opt_out_timestamps[keep_idx:]

    def get_summary(self) -> dict[str, Any]:
        """Get a comprehensive metrics summary.

        Returns:
            Dictionary containing all metrics
        """
        elapsed = time.time() - self.start_time

        return {
            "elapsed_seconds": elapsed,
            "activation_metrics": {
                "total_activations": self.total_activations,
                "activation_rate_per_second": self.get_activation_rate(),
                "activations_last_60s": self.get_activation_rate(60.0) * 60,
                "unique_sessions_activated": len(dict(self.activations_by_session)),
            },
            "turn_count_metrics": {
                "total_turns_completed": self.total_turns_completed,
                "average_turn_count": self.get_average_turn_count(),
                "turn_count_distribution": self.get_turn_count_distribution(),
                "unique_sessions_with_turns": len(dict(self.turns_by_session)),
            },
            "opt_out_metrics": {
                "total_opt_outs": self.total_opt_outs,
                "header_opt_outs": self.header_opt_outs,
                "session_opt_outs": self.session_opt_outs,
                "opt_out_rate_per_second": self.get_opt_out_rate(),
                "opt_outs_last_60s": self.get_opt_out_rate(60.0) * 60,
                "unique_sessions_opted_out": len(dict(self.opt_outs_by_session)),
            },
            "probability_check_metrics": {
                "total_probability_checks": self.total_probability_checks,
                "unique_sessions_checked": len(
                    dict(self.probability_checks_by_session)
                ),
            },
        }

    def log_summary(self) -> None:
        """Log a comprehensive metrics summary."""
        summary = self.get_summary()

        logger.info(
            f"REPLACEMENT_METRICS_SUMMARY: "
            f"elapsed={summary['elapsed_seconds']:.1f}s | "
            f"activations={summary['activation_metrics']['total_activations']} "
            f"(rate={summary['activation_metrics']['activation_rate_per_second']:.4f}/s, "
            f"last_60s={summary['activation_metrics']['activations_last_60s']:.1f}) | "
            f"turns={summary['turn_count_metrics']['total_turns_completed']} "
            f"(avg={summary['turn_count_metrics']['average_turn_count']:.2f}) | "
            f"opt_outs={summary['opt_out_metrics']['total_opt_outs']} "
            f"(header={summary['opt_out_metrics']['header_opt_outs']}, "
            f"session={summary['opt_out_metrics']['session_opt_outs']}, "
            f"rate={summary['opt_out_metrics']['opt_out_rate_per_second']:.4f}/s)"
        )

        # Log turn count distribution if there are activations
        if self._turn_count_histogram:
            distribution = summary["turn_count_metrics"]["turn_count_distribution"]
            dist_str = ", ".join(
                f"{k}turns={v}x" for k, v in sorted(distribution.items())
            )
            logger.info(f"REPLACEMENT_TURN_DISTRIBUTION: {dist_str}")

    def reset(self) -> None:
        """Reset all metrics to initial state."""
        self.total_activations = 0
        self.activations_by_session.clear()
        self.activation_timestamps.clear()

        self._turn_count_histogram.clear()
        self.total_turns_completed = 0
        self.turns_by_session.clear()

        self.total_opt_outs = 0
        self.opt_outs_by_session.clear()
        self.opt_out_timestamps.clear()
        self.header_opt_outs = 0
        self.session_opt_outs = 0

        self.total_probability_checks = 0
        self.probability_checks_by_session.clear()

        self.start_time = time.time()

        logger.info("Replacement metrics reset")
