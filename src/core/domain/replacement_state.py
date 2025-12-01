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
        """Activate replacement mode.

        Args:
            turn_count: Number of turns to keep replacement active
            original_backend: The original backend name
            original_model: The original model name
            replacement_backend: The replacement backend name
            replacement_model: The replacement model name
        """
        self.active = True
        self.turns_remaining = turn_count
        self.original_backend = original_backend
        self.original_model = original_model
        self.replacement_backend = replacement_backend
        self.replacement_model = replacement_model

    def decrement_turn(self) -> None:
        """Decrement turn counter and deactivate if expired.

        If replacement is active and turns_remaining > 0, decrements the counter.
        When the counter reaches 0, automatically deactivates replacement.
        """
        if self.active and self.turns_remaining > 0:
            self.turns_remaining -= 1
            if self.turns_remaining == 0:
                self.deactivate()

    def deactivate(self) -> None:
        """Deactivate replacement mode.

        Resets the active flag and turns_remaining counter to their default values.
        """
        self.active = False
        self.turns_remaining = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for persistence.

        Returns:
            Dictionary representation of the replacement state
        """
        return {
            "active": self.active,
            "turns_remaining": self.turns_remaining,
            "original_backend": self.original_backend,
            "original_model": self.original_model,
            "replacement_backend": self.replacement_backend,
            "replacement_model": self.replacement_model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplacementState:
        """Deserialize state from persistence.

        Args:
            data: Dictionary containing replacement state data

        Returns:
            ReplacementState instance created from the dictionary
        """
        return cls(
            active=data.get("active", False),
            turns_remaining=data.get("turns_remaining", 0),
            original_backend=data.get("original_backend", ""),
            original_model=data.get("original_model", ""),
            replacement_backend=data.get("replacement_backend", ""),
            replacement_model=data.get("replacement_model", ""),
        )
