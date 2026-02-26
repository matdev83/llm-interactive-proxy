"""Replacement state models for random model replacement feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ReplacementState:
    """Tracks replacement state for a session.

    This class manages the state of model replacement for a single session,
    including whether replacement is active, how many turns remain, and
    the original and replacement backend:model pairs.
    """

    active: bool = False
    turns_remaining: int = 0
    cool_down_active: bool = False
    first_turn_complete: bool = False  # Tracks if first turn has been processed
    original_backend: str = ""

    original_model: str = ""
    replacement_backend: str = ""
    replacement_model: str = ""

    def activate(
        self,
        turn_count: int,
        original_backend: str,
        original_model: str,
        replacement_backend: str,
        replacement_model: str,
    ) -> None:
        """Activate replacement mode."""
        self.active = True
        self.turns_remaining = turn_count
        self.cool_down_active = False  # Ensure cool-down is cleared when activating
        self.original_backend = original_backend
        self.original_model = original_model
        self.replacement_backend = replacement_backend
        self.replacement_model = replacement_model

    def decrement_turn(self) -> None:
        """Decrement turn counter and deactivate if expired."""
        if self.active and self.turns_remaining > 0:
            self.turns_remaining -= 1
            if self.turns_remaining == 0:
                self.deactivate(trigger_cool_down=True)

    def deactivate(self, trigger_cool_down: bool = False) -> None:
        """Deactivate replacement mode."""
        self.active = False
        self.turns_remaining = 0
        if trigger_cool_down:
            self.cool_down_active = True

    def consume_cool_down(self) -> bool:
        """Check and consume the cool-down turn if active.

        Returns:
            True if cool-down was active and has been consumed, False otherwise
        """
        if self.cool_down_active:
            self.cool_down_active = False
            return True
        return False

    def mark_first_turn_complete(self) -> None:
        """Mark that the first turn has been completed."""
        self.first_turn_complete = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for persistence."""
        return {
            "active": self.active,
            "turns_remaining": self.turns_remaining,
            "cool_down_active": self.cool_down_active,
            "first_turn_complete": self.first_turn_complete,
            "original_backend": self.original_backend,
            "original_model": self.original_model,
            "replacement_backend": self.replacement_backend,
            "replacement_model": self.replacement_model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplacementState:
        """Deserialize state from persistence."""
        return cls(
            active=data.get("active", False),
            turns_remaining=data.get("turns_remaining", 0),
            cool_down_active=data.get("cool_down_active", False),
            first_turn_complete=data.get("first_turn_complete", False),
            original_backend=data.get("original_backend", ""),
            original_model=data.get("original_model", ""),
            replacement_backend=data.get("replacement_backend", ""),
            replacement_model=data.get("replacement_model", ""),
        )
