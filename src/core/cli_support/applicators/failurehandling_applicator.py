"""Failure Handling Applicator - Extracts and applies failure handling CLI arguments.

This applicator handles:
- disable_failure_handling
- max_silent_wait, total_timeout_budget
- keepalive_interval, max_failover_hops, min_retry_wait

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


class FailureHandlingApplicator:
    """Applies failure handling CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply failure handling CLI arguments to configuration overrides."""
        failure_overrides: dict[str, Any] = {}

        if getattr(args, "disable_failure_handling", False):
            failure_overrides["enabled"] = False
            os.environ["DISABLE_FAILURE_HANDLING"] = "1"
            resolution.record(
                "failure_handling.enabled",
                False,
                ParameterSource.CLI,
                origin="--disable-failure-handling",
            )

        if getattr(args, "max_silent_wait", None) is not None:
            failure_overrides["max_silent_wait"] = args.max_silent_wait
            os.environ["FAILURE_HANDLING_MAX_SILENT_WAIT"] = str(args.max_silent_wait)
            resolution.record(
                "failure_handling.max_silent_wait",
                args.max_silent_wait,
                ParameterSource.CLI,
                origin="--max-silent-wait",
            )

        if getattr(args, "total_timeout_budget", None) is not None:
            failure_overrides["total_timeout_budget"] = args.total_timeout_budget
            os.environ["FAILURE_HANDLING_TOTAL_TIMEOUT_BUDGET"] = str(
                args.total_timeout_budget
            )
            resolution.record(
                "failure_handling.total_timeout_budget",
                args.total_timeout_budget,
                ParameterSource.CLI,
                origin="--total-timeout-budget",
            )

        if getattr(args, "keepalive_interval", None) is not None:
            failure_overrides["keepalive_interval"] = args.keepalive_interval
            os.environ["FAILURE_HANDLING_KEEPALIVE_INTERVAL"] = str(
                args.keepalive_interval
            )
            resolution.record(
                "failure_handling.keepalive_interval",
                args.keepalive_interval,
                ParameterSource.CLI,
                origin="--keepalive-interval",
            )

        if getattr(args, "max_failover_hops", None) is not None:
            failure_overrides["max_failover_hops"] = args.max_failover_hops
            os.environ["FAILURE_HANDLING_MAX_FAILOVER_HOPS"] = str(
                args.max_failover_hops
            )
            resolution.record(
                "failure_handling.max_failover_hops",
                args.max_failover_hops,
                ParameterSource.CLI,
                origin="--max-failover-hops",
            )

        if getattr(args, "min_retry_wait", None) is not None:
            failure_overrides["min_retry_wait"] = args.min_retry_wait
            os.environ["FAILURE_HANDLING_MIN_RETRY_WAIT"] = str(args.min_retry_wait)
            resolution.record(
                "failure_handling.min_retry_wait",
                args.min_retry_wait,
                ParameterSource.CLI,
                origin="--min-retry-wait",
            )

        if failure_overrides:
            overrides["failure_handling"] = failure_overrides
