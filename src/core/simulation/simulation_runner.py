"""
Simulation runner for full session replay and validation.

Orchestrates client and backend simulators for complete regression testing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.simulation.capture_reader import CaptureReader
from src.core.simulation.client_simulator import (
    ClientSimulator,
    ContentMismatch,
    TimingDeviation,
    ValidationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Complete result of a simulation run."""

    success: bool
    capture_file: str
    session_id: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    content_mismatches: list[ContentMismatch] = field(default_factory=list)
    timing_deviations: list[TimingDeviation] = field(default_factory=list)
    duration_seconds: float = 0.0
    validation_results: list[ValidationResult] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Get a human-readable summary."""
        status = "PASSED" if self.success else "FAILED"
        lines = [
            f"Simulation {status}",
            f"  Capture: {self.capture_file}",
            f"  Session: {self.session_id}",
            f"  Requests: {self.successful_requests}/{self.total_requests} successful",
            f"  Duration: {self.duration_seconds:.2f}s",
        ]
        if self.content_mismatches:
            lines.append(f"  Content mismatches: {len(self.content_mismatches)}")
        if self.timing_deviations:
            lines.append(f"  Timing deviations: {len(self.timing_deviations)}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "capture_file": self.capture_file,
            "session_id": self.session_id,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "content_mismatches": [
                {
                    "sequence": m.sequence,
                    "expected_bytes": m.expected_bytes,
                    "actual_bytes": m.actual_bytes,
                    "difference_type": m.difference_type,
                }
                for m in self.content_mismatches
            ],
            "timing_deviations": [
                {
                    "sequence": d.sequence,
                    "expected_delay": d.expected_delay,
                    "actual_delay": d.actual_delay,
                    "deviation_ms": d.deviation_ms,
                }
                for d in self.timing_deviations
            ],
            "duration_seconds": self.duration_seconds,
        }


class SimulationRunner:
    """Orchestrates full session replay with validation.

    This runner:
    - Loads capture files using CaptureReader
    - Replays requests using ClientSimulator
    - Validates responses against captured expectations
    - Aggregates results for reporting
    """

    def __init__(
        self,
        proxy_base_url: str = "http://localhost:8000",
        timing_tolerance_ms: float = 100.0,
        speed_multiplier: float = 1.0,
    ) -> None:
        """Initialize the simulation runner.

        Args:
            proxy_base_url: Base URL of the proxy to test
            timing_tolerance_ms: Maximum acceptable timing deviation in milliseconds
            speed_multiplier: Speed multiplier for replay (1.0 = realtime)
        """
        self._proxy_base_url = proxy_base_url
        self._timing_tolerance_ms = timing_tolerance_ms
        self._speed_multiplier = speed_multiplier
        self._reader = CaptureReader()

    async def run(self, capture_path: Path | str) -> SimulationResult:
        """Run a complete simulation from a capture file.

        Args:
            capture_path: Path to the CBOR capture file

        Returns:
            SimulationResult with all validation details
        """
        import time

        start_time = time.time()
        capture_path = Path(capture_path)

        # Load capture
        try:
            session = self._reader.load(capture_path)
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Failed to load capture file: {e}")
            return SimulationResult(
                success=False,
                capture_file=str(capture_path),
                session_id="",
                total_requests=0,
                successful_requests=0,
                failed_requests=1,
                content_mismatches=[
                    ContentMismatch(
                        sequence=0,
                        expected_bytes=0,
                        actual_bytes=0,
                        expected_preview="",
                        actual_preview=f"Load error: {e}",
                        difference_type="error",
                    )
                ],
            )

        # Run simulation
        all_mismatches: list[ContentMismatch] = []
        all_deviations: list[TimingDeviation] = []
        all_results: list[ValidationResult] = []
        successful = 0
        failed = 0

        simulator = ClientSimulator(
            session=session,
            proxy_base_url=self._proxy_base_url,
            timing_tolerance_ms=self._timing_tolerance_ms,
        )

        try:
            async with simulator:
                results = await simulator.replay_session()

                for result in results:
                    all_results.append(result)
                    if result.success:
                        successful += 1
                    else:
                        failed += 1
                    all_mismatches.extend(result.content_mismatches)
                    all_deviations.extend(result.timing_deviations)
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Simulation failed: {e}")
            failed += 1
            all_mismatches.append(
                ContentMismatch(
                    sequence=0,
                    expected_bytes=0,
                    actual_bytes=0,
                    expected_preview="",
                    actual_preview=f"Simulation error: {e}",
                    difference_type="error",
                )
            )

        duration = time.time() - start_time

        return SimulationResult(
            success=(failed == 0 and len(all_mismatches) == 0),
            capture_file=str(capture_path),
            session_id=session.header.session_id,
            total_requests=successful + failed,
            successful_requests=successful,
            failed_requests=failed,
            content_mismatches=all_mismatches,
            timing_deviations=all_deviations,
            duration_seconds=duration,
            validation_results=all_results,
        )

    async def run_multiple(
        self, capture_paths: list[Path | str]
    ) -> list[SimulationResult]:
        """Run simulations for multiple capture files.

        Args:
            capture_paths: List of paths to CBOR capture files

        Returns:
            List of SimulationResults
        """
        results = []
        for path in capture_paths:
            result = await self.run(path)
            results.append(result)
            if logger.isEnabledFor(logging.INFO):
                logger.info(result.summary)
        return results

    def run_sync(self, capture_path: Path | str) -> SimulationResult:
        """Synchronous wrapper for run().

        Args:
            capture_path: Path to the CBOR capture file

        Returns:
            SimulationResult
        """
        return asyncio.run(self.run(capture_path))


def create_simulation_report(results: list[SimulationResult]) -> str:
    """Create a detailed report from simulation results.

    Args:
        results: List of simulation results

    Returns:
        Formatted report string
    """
    lines = ["=" * 60, "SIMULATION REPORT", "=" * 60, ""]

    total_success = sum(1 for r in results if r.success)
    total_failed = len(results) - total_success

    lines.extend(
        [
            f"Total simulations: {len(results)}",
            f"Successful: {total_success}",
            f"Failed: {total_failed}",
            "",
            "-" * 60,
            "",
        ]
    )

    for result in results:
        lines.extend([result.summary, ""])

        if result.content_mismatches:
            lines.append("  Content Mismatches:")
            for m in result.content_mismatches[:5]:  # Show first 5
                lines.append(
                    f"    - Seq {m.sequence}: {m.difference_type} "
                    f"(expected {m.expected_bytes}B, got {m.actual_bytes}B)"
                )
            if len(result.content_mismatches) > 5:
                lines.append(f"    ... and {len(result.content_mismatches) - 5} more")
            lines.append("")

        if result.timing_deviations:
            lines.append("  Timing Deviations:")
            for d in result.timing_deviations[:5]:  # Show first 5
                lines.append(
                    f"    - Seq {d.sequence}: {d.deviation_ms:.1f}ms deviation "
                    f"(expected {d.expected_delay:.3f}s, got {d.actual_delay:.3f}s)"
                )
            if len(result.timing_deviations) > 5:
                lines.append(f"    ... and {len(result.timing_deviations) - 5} more")
            lines.append("")

        lines.append("-" * 60)
        lines.append("")

    lines.extend(["=" * 60, f"OVERALL: {'PASSED' if total_failed == 0 else 'FAILED'}"])

    return "\n".join(lines)
