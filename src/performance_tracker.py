"""
Performance tracking system for measuring execution times across the full request handling cycle.
"""
import time
import logging
from typing import Dict, Optional, Any
from contextlib import contextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Container for performance metrics during a request."""
    request_start: float = field(default_factory=time.time)
    command_processing_time: Optional[float] = None
    backend_selection_time: Optional[float] = None
    backend_call_time: Optional[float] = None
    response_processing_time: Optional[float] = None
    total_time: Optional[float] = None
    
    # Additional context
    backend_used: Optional[str] = None
    model_used: Optional[str] = None
    session_id: Optional[str] = None
    commands_processed: bool = False
    streaming: bool = False
    
    def __post_init__(self):
        """Initialize timing markers."""
        self._markers: Dict[str, float] = {}
        self._current_phase: Optional[str] = None
    
    def start_phase(self, phase_name: str) -> None:
        """Start timing a specific phase."""
        if self._current_phase:
            # End the previous phase
            self.end_phase()
        
        self._current_phase = phase_name
        self._markers[f"{phase_name}_start"] = time.time()
    
    def end_phase(self) -> None:
        """End timing the current phase."""
        if not self._current_phase:
            return
        
        end_time = time.time()
        start_time = self._markers.get(f"{self._current_phase}_start")
        if start_time:
            duration = end_time - start_time
            
            # Store the duration based on phase name
            if self._current_phase == "command_processing":
                self.command_processing_time = duration
            elif self._current_phase == "backend_selection":
                self.backend_selection_time = duration
            elif self._current_phase == "backend_call":
                self.backend_call_time = duration
            elif self._current_phase == "response_processing":
                self.response_processing_time = duration
        
        self._current_phase = None
    
    def finalize(self) -> None:
        """Finalize metrics and calculate total time."""
        if self._current_phase:
            self.end_phase()
        
        self.total_time = time.time() - self.request_start
    
    def log_summary(self) -> None:
        """Log a comprehensive performance summary."""
        if not self.total_time:
            self.finalize()
        
        # Build performance summary
        summary_parts = [
            f"PERF_SUMMARY session={self.session_id or 'unknown'}",
            f"total={self.total_time:.3f}s",
            f"backend={self.backend_used or 'unknown'}",
            f"model={self.model_used or 'unknown'}",
            f"streaming={self.streaming}",
            f"commands={self.commands_processed}"
        ]
        
        # Add timing breakdown
        timing_parts = []
        if self.command_processing_time is not None:
            timing_parts.append(f"cmd_proc={self.command_processing_time:.3f}s")
        if self.backend_selection_time is not None:
            timing_parts.append(f"backend_sel={self.backend_selection_time:.3f}s")
        if self.backend_call_time is not None:
            timing_parts.append(f"backend_call={self.backend_call_time:.3f}s")
        if self.response_processing_time is not None:
            timing_parts.append(f"resp_proc={self.response_processing_time:.3f}s")
        
        if timing_parts:
            summary_parts.append(f"breakdown=[{', '.join(timing_parts)}]")
        
        # Calculate overhead (time not accounted for in specific phases)
        accounted_time = sum(filter(None, [
            self.command_processing_time,
            self.backend_selection_time, 
            self.backend_call_time,
            self.response_processing_time
        ]))
        
        if accounted_time and self.total_time:
            overhead = self.total_time - accounted_time
            summary_parts.append(f"overhead={overhead:.3f}s")
        
        logger.info(" | ".join(summary_parts))


@contextmanager
def track_request_performance(session_id: Optional[str] = None):
    """Context manager for tracking performance across a full request."""
    metrics = PerformanceMetrics()
    metrics.session_id = session_id
    
    try:
        yield metrics
    finally:
        metrics.log_summary()


@contextmanager
def track_phase(metrics: PerformanceMetrics, phase_name: str):
    """Context manager for tracking a specific phase within a request."""
    metrics.start_phase(phase_name)
    try:
        yield
    finally:
        metrics.end_phase()