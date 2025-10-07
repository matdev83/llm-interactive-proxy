"""Tool call tracker for detecting repetitive tool call patterns.

This module provides functionality to track tool calls, detect repetitive patterns,
and implement TTL-based pruning to prevent false positives from old tool calls.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass

from json_repair import repair_json

from src.core.interfaces.model_bases import InternalDTO
from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode

logger = logging.getLogger(__name__)


@dataclass
class ToolCallSignature(InternalDTO):
    """Represents a tracked tool call with timestamp and signature."""

    timestamp: datetime.datetime
    tool_name: str
    arguments_signature: str
    # Track raw arguments for logging/debugging
    raw_arguments: str

    @classmethod
    def from_tool_call(cls, tool_name: str, arguments: str) -> ToolCallSignature:
        """Create a signature from a tool call.

        Args:
            tool_name: Name of the tool being called
            arguments: JSON string of the tool arguments

        Returns:
            A ToolCallSignature instance with current timestamp
        """
        # Parse and re-dump arguments with sorted keys for stable signature
        try:
            # Attempt to repair the JSON before loading
            repaired_arguments = repair_json(arguments)
            args_dict = json.loads(repaired_arguments)
            # Stable signature for comparison (sorted keys)
            canonical_args = json.dumps(args_dict, sort_keys=True)
        except (json.JSONDecodeError, TypeError):
            # If arguments are still invalid after repair, use as-is
            canonical_args = arguments

        return cls(
            timestamp=datetime.datetime.now(),
            tool_name=tool_name,
            arguments_signature=canonical_args,
            raw_arguments=arguments,
        )

    def get_full_signature(self) -> str:
        """Get the full signature string (tool_name + arguments)."""
        return f"{self.tool_name}:{self.arguments_signature}"

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if this signature has expired based on TTL.

        Args:
            ttl_seconds: Time-to-live in seconds

        Returns:
            True if the signature has expired, False otherwise
        """
        now = datetime.datetime.now()
        age = now - self.timestamp
        return age.total_seconds() > ttl_seconds


class ToolCallTracker:
    """Tracks tool calls and detects repetitive patterns with TTL-based pruning."""

    def __init__(self, config: ToolCallLoopConfig, max_signatures: int = 100):
        """Initialize the tracker with the given configuration.

        Args:
            config: Configuration for tool call loop detection
            max_signatures: Maximum number of signatures to store (default: 100)
        """
        self.config = config
        self.signatures: list[ToolCallSignature] = []
        # Track consecutive repeats of the same signature
        self.consecutive_repeats: dict[str, int] = {}
        # Track if we're in "chance" mode for specific signatures
        self.chance_given: dict[str, bool] = {}
        # Maximum number of signatures to store
        self.max_signatures = max_signatures

    def prune_expired(self) -> int:
        """Remove expired signatures based on TTL.

        Returns:
            Number of signatures pruned
        """
        if not self.signatures:
            return 0

        original_count = len(self.signatures)
        self.signatures = [
            sig
            for sig in self.signatures
            if not sig.is_expired(self.config.ttl_seconds)
        ]

        pruned_count = original_count - len(self.signatures)
        if pruned_count > 0 and logger.isEnabledFor(logging.DEBUG):
            logger.debug("Pruned %d expired tool call signatures", pruned_count)

        current_signatures = [sig.get_full_signature() for sig in self.signatures]
        if pruned_count > 0:
            active_signatures = set(current_signatures)
            for sig in list(self.consecutive_repeats.keys()):
                if sig not in active_signatures:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Resetting consecutive count for expired signature: %s", sig
                        )
                    del self.consecutive_repeats[sig]
                    # Also clear chance status if present
                    self.chance_given.pop(sig, None)

            # Recompute consecutive repeat counters based on remaining signatures
            new_counts: dict[str, int] = {}
            current_sig: str | None = None
            current_run = 0
            for sig in current_signatures:
                if sig == current_sig:
                    current_run += 1
                else:
                    if current_sig is not None:
                        new_counts[current_sig] = current_run
                    current_sig = sig
                    current_run = 1
            if current_sig is not None:
                new_counts[current_sig] = current_run

            self.consecutive_repeats = new_counts

            # Clear chance markers for signatures whose streak reset below the threshold
            for sig in list(self.chance_given.keys()):
                if sig not in new_counts or new_counts[sig] < self.config.max_repeats:
                    self.chance_given.pop(sig, None)

        return pruned_count

    def track_tool_call(
        self, tool_name: str, arguments: str, force_block: bool = False
    ) -> tuple[bool, str | None, int | None]:
        """Track a tool call and check if it exceeds the repetition threshold.

        Args:
            tool_name: Name of the tool being called
            arguments: JSON string of the tool arguments

        Returns:
            Tuple of (should_block, reason, repeat_count):
            - should_block: True if the call should be blocked
            - reason: Reason message if blocked, None otherwise
            - repeat_count: Number of consecutive repeats if blocked, None otherwise
        """
        # Skip tracking if disabled (unless forced)
        if not self.config.enabled and not force_block:
            return False, None, None

        # Handle forced block (for transparent retry when same tool call is repeated)
        if force_block:
            reason = self._format_block_reason(
                tool_name, self.config.max_repeats, second_chance=True
            )
            return True, reason, self.config.max_repeats

        # Prune expired signatures first
        self.prune_expired()

        # Create signature for this call
        signature = ToolCallSignature.from_tool_call(tool_name, arguments)
        full_sig = signature.get_full_signature()

        # Check if this is a repeat of the most recent signature
        if self.signatures and self.signatures[-1].get_full_signature() == full_sig:
            self.consecutive_repeats[full_sig] = (
                self.consecutive_repeats.get(full_sig, 1) + 1
            )
            repeat_count = self.consecutive_repeats[full_sig]

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Repeated tool call: %s (count: %d)", tool_name, repeat_count
                )

            # Check if we need to block based on threshold and mode
            if repeat_count >= self.config.max_repeats:
                # Handle based on mode
                if self.config.mode == ToolLoopMode.BREAK:
                    reason = self._format_block_reason(tool_name, repeat_count)
                    return True, reason, repeat_count
                elif self.config.mode == ToolLoopMode.CHANCE_THEN_BREAK:
                    # If we've already given a chance for this signature
                    if self.chance_given.get(full_sig, False):
                        reason = self._format_block_reason(
                            tool_name, repeat_count, second_chance=True
                        )
                        return True, reason, repeat_count
                    else:
                        # Give one chance
                        self.chance_given[full_sig] = True
                        reason = self._format_chance_reason(tool_name, repeat_count)
                        return True, reason, repeat_count
        else:
            # Not a repeat of the most recent call, reset counter for this signature
            self.consecutive_repeats[full_sig] = 1
            # Also reset chance status
            self.chance_given.pop(full_sig, None)

        # Add to history (with size limit to prevent unbounded growth)
        self.signatures.append(signature)

        # Enforce maximum size limit by removing oldest entries if needed
        if len(self.signatures) > self.max_signatures:
            # Remove oldest entries that exceed the limit
            excess = len(self.signatures) - self.max_signatures
            if excess > 0:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Trimming %d oldest signatures to maintain size limit", excess
                    )
                # Remove oldest entries (at the beginning of the list)
                self.signatures = self.signatures[excess:]

                # Clean up related dictionaries for removed signatures
                current_signatures = {
                    sig.get_full_signature() for sig in self.signatures
                }
                for sig in list(self.consecutive_repeats.keys()):
                    if sig not in current_signatures:
                        self.consecutive_repeats.pop(sig, None)
                        self.chance_given.pop(sig, None)

        # Not blocked
        return False, None, None

    def _format_block_reason(
        self, tool_name: str, repeat_count: int, second_chance: bool = False
    ) -> str:
        """Format a reason message for blocking a tool call.

        Args:
            tool_name: Name of the tool
            repeat_count: Number of consecutive repeats
            second_chance: Whether this is after a second chance

        Returns:
            Formatted reason message
        """
        prefix = "After guidance, " if second_chance else ""
        return (
            f"{prefix}Tool call loop detected: '{tool_name}' invoked with identical "
            f"parameters {repeat_count} times within {self.config.ttl_seconds}s. "
            f"Session stopped to prevent unintended looping. "
            f"Try changing your inputs or approach."
        )

    def _format_chance_reason(self, tool_name: str, repeat_count: int) -> str:
        """Format a reason message for giving a chance to correct.

        Args:
            tool_name: Name of the tool
            repeat_count: Number of consecutive repeats

        Returns:
            Formatted guidance message
        """
        return (
            f"Tool call loop warning: '{tool_name}' has been called with identical "
            f"parameters {repeat_count} times. Please modify your approach or parameters. "
            f"If the next call uses the same parameters, the session will be stopped."
        )
