"""
Traffic simulation engine for replay-based regression testing.

This module provides tools for:
- Reading CBOR capture files
- Simulating client requests
- Simulating backend responses with timing replay
- Full session replay with validation
"""

from src.core.simulation.backend_simulator import (
    BackendSimulator,
    BackendSimulatorTransport,
    RequestMatch,
)
from src.core.simulation.capture_reader import CaptureReader
from src.core.simulation.client_simulator import (
    ClientSimulator,
    ContentMismatch,
    TimingDeviation,
    ValidationResult,
)
from src.core.simulation.output_utils import (
    configure_console_encoding,
    console_print,
    safe_bytes_preview,
    safe_str,
)
from src.core.simulation.simulation_runner import (
    SimulationResult,
    SimulationRunner,
    create_simulation_report,
)
from src.core.simulation.timing_controller import TimingController

__all__ = [
    "BackendSimulator",
    "BackendSimulatorTransport",
    "CaptureReader",
    "ClientSimulator",
    "ContentMismatch",
    "RequestMatch",
    "SimulationResult",
    "SimulationRunner",
    "TimingController",
    "TimingDeviation",
    "ValidationResult",
    "configure_console_encoding",
    "console_print",
    "create_simulation_report",
    "safe_bytes_preview",
    "safe_str",
]
