"""
Domain models for LLM-based conversation assessment system.

This module defines the core data structures used by the assessment system,
replicating the response format and state management from gemini-cli.

Reference: dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class LLMAssessmentResponse(BaseModel):
    """Structured response from LLM assessment backend."""

    reasoning: str = Field(description="Analysis of the conversation state")
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0", ge=0.0, le=1.0
    )


class LoopType(Enum):
    """Types of loops that can be detected, matching gemini-cli patterns."""

    LLM_DETECTED_LOOP = "llm_detected_loop"
    CONSECUTIVE_IDENTICAL_TOOL_CALLS = "consecutive_identical_tool_calls"
    COGNITIVE_LOOP = "cognitive_loop"
    LACK_OF_PROGRESS = "lack_of_progress"


@dataclass
class AssessmentResult:
    """
    Result of conversation assessment, matching gemini-cli response format.

    This replicates the JSON schema expected by gemini-cli's checkForLoopWithLLM method:
    {
      "reasoning": "string",
      "confidence": "number"
    }
    """

    reasoning: str
    confidence: float
    session_id: str
    turn_count: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    loop_type: LoopType | None = None

    @property
    def is_unproductive(self) -> bool:
        """
        Determine if conversation is unproductive based on confidence.

        Replicates gemini-cli logic: confidence >= 0.9 indicates unproductive state.
        Reference: loopDetectionService.ts line ~380
        """
        return self.confidence >= 0.9

    @property
    def should_intervene(self) -> bool:
        """Alias for is_unproductive for clarity in middleware."""
        return self.is_unproductive

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging and serialization."""
        return {
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "timestamp": self.timestamp.isoformat(),
            "is_unproductive": self.is_unproductive,
            "loop_type": self.loop_type.value if self.loop_type else None,
        }

    @classmethod
    def from_llm_response(
        cls, response: dict[str, Any], session_id: str, turn_count: int
    ) -> "AssessmentResult":
        """
        Create AssessmentResult from LLM JSON response.

        Expected response format (matching gemini-cli schema):
        {
          "reasoning": "Your analysis of the conversation state",
          "confidence": 0.85
        }
        """
        confidence = float(response.get("confidence", 0.0))
        return cls(
            reasoning=response.get("reasoning", ""),
            confidence=confidence,
            session_id=session_id,
            turn_count=turn_count,
            loop_type=(
                LoopType.LLM_DETECTED_LOOP
                if confidence >= 0.9  # Keep this hardcoded for loop_type classification
                else None
            ),
        )


@dataclass
class SessionAssessmentState:
    """
    Per-session state for assessment tracking.

    This replicates the state management from gemini-cli's LoopDetectionService,
    tracking turn counts and assessment intervals per session.
    """

    session_id: str
    turn_count: int = 0
    last_check_turn: int = 0
    current_check_interval: int = 3  # DEFAULT_LLM_CHECK_INTERVAL
    disabled_for_session: bool = False
    assessment_history: list[AssessmentResult] = field(default_factory=list)
    last_tool_call_key: str | None = None
    tool_call_repetition_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def __post_init__(self):
        self._lock = threading.Lock()

    def update_timestamp(self):
        """Update the last_updated timestamp."""
        new_timestamp = time.time()
        if new_timestamp <= self.last_updated:
            # Ensure strictly increasing timestamps to satisfy timing-sensitive tests
            new_timestamp = self.last_updated + 1e-6
        self.last_updated = new_timestamp

    def add_assessment_result(self, result: AssessmentResult):
        """Add an assessment result to the history."""
        with self._lock:
            self.assessment_history.append(result)
            self.update_timestamp()

            # Keep only recent assessments to prevent memory bloat
            if len(self.assessment_history) > 10:
                self.assessment_history = self.assessment_history[-10:]

    def should_trigger_assessment(self, turn_threshold: int) -> bool:
        """
        Determine if assessment should be triggered.

        Replicates the logic from gemini-cli's turnStarted method:
        - Must be past turn threshold
        - Must be past the check interval since last assessment
        """
        if self.disabled_for_session:
            return False

        return (
            self.turn_count >= turn_threshold
            and self.turn_count - self.last_check_turn >= self.current_check_interval
        )

    def update_check_interval(
        self, confidence: float, min_interval: int, max_interval: int
    ):
        """
        Adjust check interval based on confidence.

        Replicates gemini-cli's interval adjustment formula:
        MIN + (MAX - MIN) * (1 - confidence)

        Reference: loopDetectionService.ts lines ~385-390
        """
        new_interval = round(
            min_interval + (max_interval - min_interval) * (1 - confidence)
        )
        self.current_check_interval = max(min_interval, min(max_interval, new_interval))
        self.update_timestamp()

    def mark_assessment_performed(self):
        """Mark that an assessment was performed at the current turn."""
        with self._lock:
            self.last_check_turn = self.turn_count
            # Add a placeholder assessment result to track the assessment
            placeholder_result = AssessmentResult(
                reasoning="Assessment performed",
                confidence=0.0,  # Placeholder value
                session_id=self.session_id,
                turn_count=self.turn_count,
            )
            # Directly add to history without timestamp update (repository will handle it)
            self.assessment_history.append(placeholder_result)
            # Keep only recent assessments to prevent memory bloat
            if len(self.assessment_history) > 10:
                self.assessment_history = self.assessment_history[-10:]

    def increment_turn(self) -> int:
        """Increment turn count and return new count."""
        with self._lock:
            self.turn_count += 1
            self.update_timestamp()
            return self.turn_count

    def is_expired(self, max_age_seconds: int = 3600) -> bool:
        """Check if session state is expired and should be cleaned up."""
        with self._lock:
            return time.time() - self.last_updated > max_age_seconds

    def len(self) -> int:
        """Get length of assessment_history."""
        with self._lock:
            return len(self.assessment_history)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging and debugging."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "turn_count": self.turn_count,
                "last_check_turn": self.last_check_turn,
                "current_check_interval": self.current_check_interval,
                "disabled_for_session": self.disabled_for_session,
                "assessment_count": len(self.assessment_history),
                "created_at": self.created_at,
                "last_updated": self.last_updated,
            }


@dataclass
class ToolCallPattern:
    """
    Pattern for detecting repetitive tool calls.

    This helps identify when the same tool is being called repeatedly,
    which is one of the patterns gemini-cli detects.
    """

    tool_name: str
    args_hash: str
    count: int = 1
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def increment(self):
        """Increment the count and update last seen timestamp."""
        self.count += 1
        self.last_seen = datetime.now(timezone.utc)

    @classmethod
    def from_tool_call(cls, tool_call: dict[str, Any]) -> "ToolCallPattern":
        """Create pattern from a tool call."""
        import hashlib
        import json

        tool_name = tool_call.get("name", "unknown")
        args = tool_call.get("args", {})

        # Create a hash of the arguments for comparison
        args_str = json.dumps(args, sort_keys=True)
        args_hash = hashlib.sha256(args_str.encode()).hexdigest()

        return cls(tool_name=tool_name, args_hash=args_hash)


@dataclass
class AssessmentRequest:
    """
    Request structure for performing assessment.

    This encapsulates all the information needed to perform an assessment,
    including the conversation history and session context.
    """

    session_id: str
    messages: list[Any]  # ChatMessage objects
    turn_count: int
    prompt_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "turn_count": self.turn_count,
            "prompt_id": self.prompt_id,
        }
