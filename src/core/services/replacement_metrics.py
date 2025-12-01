"""Metrics tracking for model replacement service.

This module provides comprehensive metrics tracking for the random model
replacement feature, including activation rates, turn count distributions,
and opt-out rates.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


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
    activations_by_session: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    activation_timestamps: list[float] = field(default_factory=list)

    # Turn count distribution tracking (Requirement 4.1)
    turn_counts: list[int] = field(default_factory=list)
    total_turns_completed: int = 0
    turns_by_session: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Opt-out tracking (Requirements 9.1, 9.2)
    total_opt_outs: int = 0
    opt_outs_by_session: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    opt_out_timestamps: list[float] = field(default_factory=list)
    header_opt_outs: int = 0
    session_opt_outs: int = 0

    # Probability check tracking
    total_probability_checks: int = 0
    probability_checks_by_session: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )

    # Metadata
    start_time: float = field(default_factory=time.time)

    def record_activation(self, session_id: str, turn_count: int) -> None:
        """Record a replacement activation.

        Args:
            session_id: The session identifier
            turn_count: The number of turns for this activation
        """
        self.total_activations += 1
        self.activations_by_session[session_id] += 1
        self.activation_timestamps.append(time.time())
        self.turn_counts.append(turn_count)

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
        self.turns_by_session[session_id] += 1

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
        self.opt_outs_by_session[session_id] += 1
        self.opt_out_timestamps.append(time.time())

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
        self.probability_checks_by_session[session_id] += 1

    def get_activation_rate(self, time_window_seconds: float | None = None) -> float:
        """Calculate activation rate per time period.

        Args:
            time_window_seconds: Time window in seconds (None for all time)

        Returns:
            Activations per second in the time window
        """
        if time_window_seconds is None:
            elapsed = time.time() - self.start_time
            if elapsed == 0:
                return 0.0
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
        distribution: dict[int, int] = defaultdict(int)
        for count in self.turn_counts:
            distribution[count] += 1
        return dict(distribution)

    def get_average_turn_count(self) -> float:
        """Calculate average turn count per activation.

        Returns:
            Average turn count (0.0 if no activations)
        """
        if not self.turn_counts:
            return 0.0
        return sum(self.turn_counts) / len(self.turn_counts)

    def get_opt_out_rate(self, time_window_seconds: float | None = None) -> float:
        """Calculate opt-out rate per time period.

        Args:
            time_window_seconds: Time window in seconds (None for all time)

        Returns:
            Opt-outs per second in the time window
        """
        if time_window_seconds is None:
            elapsed = time.time() - self.start_time
            if elapsed == 0:
                return 0.0
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
                "unique_sessions_activated": len(self.activations_by_session),
            },
            "turn_count_metrics": {
                "total_turns_completed": self.total_turns_completed,
                "average_turn_count": self.get_average_turn_count(),
                "turn_count_distribution": self.get_turn_count_distribution(),
                "unique_sessions_with_turns": len(self.turns_by_session),
            },
            "opt_out_metrics": {
                "total_opt_outs": self.total_opt_outs,
                "header_opt_outs": self.header_opt_outs,
                "session_opt_outs": self.session_opt_outs,
                "opt_out_rate_per_second": self.get_opt_out_rate(),
                "opt_outs_last_60s": self.get_opt_out_rate(60.0) * 60,
                "unique_sessions_opted_out": len(self.opt_outs_by_session),
            },
            "probability_check_metrics": {
                "total_probability_checks": self.total_probability_checks,
                "unique_sessions_checked": len(self.probability_checks_by_session),
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
        if self.turn_counts:
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

        self.turn_counts.clear()
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
