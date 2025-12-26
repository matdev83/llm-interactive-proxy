"""Tool call tracker for detecting repetitive tool call patterns.

This module provides functionality to track tool calls, detect repetitive patterns,
and implement TTL-based pruning to prevent false positives from old tool calls.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from reprlib import repr as limited_repr
from typing import Any

from json_repair import repair_json

from src.tool_call_loop.config import (
    ToolCallLoopConfig,
    ToolCallTrackingResult,
    ToolLoopMode,
)

logger = logging.getLogger(__name__)

# Maximum JSON repair input size to prevent DoS attacks (1MB)
MAX_JSON_REPAIR_INPUT_SIZE = 1 * 1024 * 1024  # 1MB in bytes


@dataclass
class ToolCallSignature:
    """Represents a tracked tool call with timestamp and signature."""

    timestamp: datetime.datetime
    tool_name: str
    arguments_signature: str
    # Track raw arguments for logging/debugging
    raw_arguments: str

    @classmethod
    def from_tool_call(cls, tool_name: str, arguments: Any) -> ToolCallSignature:
        """Create a signature from a tool call.

        Args:
            tool_name: Name of the tool being called
            arguments: JSON string or structured payload of the tool arguments

        Returns:
            A ToolCallSignature instance with current timestamp
        """
        canonical_args = cls._canonicalize_arguments(arguments)
        raw_arguments = cls._stringify_raw_arguments(arguments)

        return cls(
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            tool_name=tool_name,
            arguments_signature=canonical_args,
            raw_arguments=raw_arguments,
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
        now = datetime.datetime.now(datetime.timezone.utc)
        age = now - self.timestamp
        return age.total_seconds() > ttl_seconds

    @staticmethod
    def _stringify_raw_arguments(arguments: Any) -> str:
        """Return a readable string representation of the original arguments."""

        if isinstance(arguments, str):
            return arguments

        try:
            return json.dumps(arguments, ensure_ascii=False, default=str)
        except (TypeError, ValueError, RecursionError):
            try:
                return limited_repr(arguments)
            except RecursionError:
                return "<unrepresentable arguments>"

    @staticmethod
    def _hash_fallback(raw_value: str) -> str:
        """Generate a deterministic fallback signature for deeply nested inputs."""

        digest = hashlib.sha256(raw_value.encode("utf-8", "replace")).hexdigest()
        return f"sha256:{digest}"

    @classmethod
    def _canonicalize_arguments(cls, arguments: Any) -> str:
        """Produce a stable string signature for tool call arguments."""
        MAX_ARG_LENGTH = 1024
        if isinstance(arguments, str):
            # DoS protection: Check input size before repair
            input_size = len(arguments.encode("utf-8"))
            if input_size > MAX_JSON_REPAIR_INPUT_SIZE:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Tool arguments too large for JSON repair (%d bytes, limit: %d bytes). "
                        "Using hash fallback to prevent DoS attack.",
                        input_size,
                        MAX_JSON_REPAIR_INPUT_SIZE,
                    )
                return cls._hash_fallback(arguments)

            try:
                repaired_arguments = repair_json(arguments)
            except (TypeError, ValueError, RecursionError):
                return arguments

            try:
                parsed_arguments = json.loads(repaired_arguments)
            except (json.JSONDecodeError, TypeError, RecursionError, ValueError):
                return arguments

            try:
                result = json.dumps(
                    parsed_arguments, sort_keys=True, ensure_ascii=False, default=str
                )
                if len(result) > MAX_ARG_LENGTH:
                    return cls._hash_fallback(result)
                return result
            except (TypeError, ValueError, RecursionError):
                return cls._hash_fallback(arguments)

        if isinstance(arguments, Mapping) or (
            isinstance(arguments, Sequence)
            and not isinstance(arguments, bytes | bytearray | str)
        ):
            try:
                result = json.dumps(
                    arguments,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )
                if len(result) > MAX_ARG_LENGTH:
                    return cls._hash_fallback(result)
                return result
            except (TypeError, ValueError, RecursionError):
                raw_value = cls._stringify_raw_arguments(arguments)
                return cls._hash_fallback(raw_value)

        try:
            result = str(arguments)
            if len(result) > MAX_ARG_LENGTH:
                return cls._hash_fallback(result)
            return result
        except RecursionError:
            return cls._hash_fallback("<unrepresentable>")


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
        # Track total occurrences of each signature (for O(1) counting)
        self.signature_counts: dict[str, int] = {}
        # Maximum number of signatures to store
        self.max_signatures = max_signatures
        self._lock = threading.Lock()

    def prune_expired(self) -> int:
        """Remove expired signatures based on TTL.

        Returns:
            Number of signatures pruned
        """
        with self._lock:
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

            pruned_signature_strs = [
                sig.get_full_signature() for sig in self.signatures
            ]
            if pruned_count > 0:
                # Rebuild signature_counts from remaining signatures
                new_signature_counts: dict[str, int] = {}
                for sig_str in pruned_signature_strs:
                    new_signature_counts[sig_str] = (
                        new_signature_counts.get(sig_str, 0) + 1
                    )
                self.signature_counts = new_signature_counts

                active_signatures = set(pruned_signature_strs)
                for sig in list(self.consecutive_repeats.keys()):
                    if sig not in active_signatures:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Resetting consecutive count for expired signature: %s",
                                sig,
                            )
                        del self.consecutive_repeats[sig]
                        self.chance_given.pop(sig, None)

                # Recompute consecutive repeat counters based on remaining signatures
                new_counts: dict[str, int] = {}
                current_sig: str | None = None
                current_run = 0
                for sig in pruned_signature_strs:
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
                    if (
                        sig not in new_counts
                        or new_counts[sig] < self.config.max_repeats
                    ):
                        self.chance_given.pop(sig, None)

            return pruned_count

    def track_tool_call(
        self, tool_name: str, arguments: str, force_block: bool = False
    ) -> ToolCallTrackingResult:
        """Track a tool call and check if it exceeds the repetition threshold.

        Args:
            tool_name: Name of the tool being called
            arguments: JSON string of the tool arguments

        Returns:
            ToolCallTrackingResult with block status and details.
        """
        # Skip tracking if disabled (unless forced)
        if not self.config.enabled and not force_block:
            return ToolCallTrackingResult(should_block=False)

        # Handle forced block (for transparent retry when same tool call is repeated)
        if force_block:
            reason = self._format_block_reason(
                tool_name, self.config.max_repeats, second_chance=True
            )
            return ToolCallTrackingResult(
                should_block=True, reason=reason, repeat_count=self.config.max_repeats
            )

        with self._lock:
            # Prune expired signatures first
            if not self.signatures:
                pass  # Nothing to prune
            else:
                original_count = len(self.signatures)
                self.signatures = [
                    sig
                    for sig in self.signatures
                    if not sig.is_expired(self.config.ttl_seconds)
                ]

                pruned_count = original_count - len(self.signatures)
                if pruned_count > 0 and logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Pruned %d expired tool call signatures", pruned_count)

                current_signatures = [
                    sig.get_full_signature() for sig in self.signatures
                ]
                if pruned_count > 0:
                    # Rebuild signature_counts from remaining signatures
                    new_signature_counts: dict[str, int] = {}
                    for sig_str in current_signatures:
                        new_signature_counts[sig_str] = (
                            new_signature_counts.get(sig_str, 0) + 1
                        )
                    self.signature_counts = new_signature_counts

                    active_signatures = set(current_signatures)
                    for sig in list(self.consecutive_repeats.keys()):
                        if sig not in active_signatures:
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "Resetting consecutive count for expired signature: %s",
                                    sig,
                                )
                            del self.consecutive_repeats[sig]
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
                        if (
                            sig not in new_counts
                            or new_counts[sig] < self.config.max_repeats
                        ):
                            self.chance_given.pop(sig, None)

            # Create signature for this call
            signature = ToolCallSignature.from_tool_call(tool_name, arguments)
            full_sig = signature.get_full_signature()

            # Count repeats within the TTL window (even if interleaved with other tools)
            # O(1) lookup using signature_counts dict instead of O(n) iteration
            total_count = (
                self.signature_counts.get(full_sig, 0) + 1
            )  # include pending call

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
                        return ToolCallTrackingResult(
                            should_block=True, reason=reason, repeat_count=repeat_count
                        )
                    elif self.config.mode == ToolLoopMode.CHANCE_THEN_BREAK:
                        # If we've already given a chance for this signature
                        if self.chance_given.get(full_sig, False):
                            reason = self._format_block_reason(
                                tool_name, repeat_count, second_chance=True
                            )
                            return ToolCallTrackingResult(
                                should_block=True,
                                reason=reason,
                                repeat_count=repeat_count,
                            )
                        else:
                            # Give one chance
                            self.chance_given[full_sig] = True
                            reason = self._format_chance_reason(tool_name, repeat_count)
                            return ToolCallTrackingResult(
                                should_block=True,
                                reason=reason,
                                repeat_count=repeat_count,
                            )
            else:
                # Not a repeat of the most recent call, reset counter for this signature
                self.consecutive_repeats[full_sig] = 1
                # Also reset chance status
                self.chance_given.pop(full_sig, None)

            # Guard against repeated calls within the TTL window even if interleaved
            if total_count >= self.config.max_repeats:
                if self.config.mode == ToolLoopMode.BREAK:
                    reason = self._format_block_reason(tool_name, total_count)
                    return ToolCallTrackingResult(
                        should_block=True, reason=reason, repeat_count=total_count
                    )
                elif self.config.mode == ToolLoopMode.CHANCE_THEN_BREAK:
                    if self.chance_given.get(full_sig, False):
                        reason = self._format_block_reason(
                            tool_name, total_count, second_chance=True
                        )
                        return ToolCallTrackingResult(
                            should_block=True, reason=reason, repeat_count=total_count
                        )
                    self.chance_given[full_sig] = True
                    reason = self._format_chance_reason(tool_name, total_count)
                    return ToolCallTrackingResult(
                        should_block=True, reason=reason, repeat_count=total_count
                    )

            # Add to history (with size limit to prevent unbounded growth)
            self.signatures.append(signature)
            # Update signature count for O(1) lookups
            self.signature_counts[full_sig] = self.signature_counts.get(full_sig, 0) + 1

            # Enforce maximum size limit by removing oldest entries if needed
            if len(self.signatures) > self.max_signatures:
                # Remove oldest entries that exceed the limit
                excess = len(self.signatures) - self.max_signatures
                if excess > 0:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Trimming %d oldest signatures to maintain size limit",
                            excess,
                        )
                    # Remove oldest entries (at the beginning of the list)
                    removed_signatures = self.signatures[:excess]
                    self.signatures = self.signatures[excess:]

                    # Decrement signature_counts for removed signatures
                    for removed_sig in removed_signatures:
                        removed_full_sig = removed_sig.get_full_signature()
                        if removed_full_sig in self.signature_counts:
                            self.signature_counts[removed_full_sig] -= 1
                            if self.signature_counts[removed_full_sig] <= 0:
                                del self.signature_counts[removed_full_sig]

                    # Clean up related dictionaries for removed signatures
                    remaining_signature_strs = set(self.signature_counts.keys())
                    for sig in list(self.consecutive_repeats.keys()):
                        if sig not in remaining_signature_strs:
                            self.consecutive_repeats.pop(sig, None)
                            self.chance_given.pop(sig, None)

        # Not blocked
        return ToolCallTrackingResult(should_block=False)

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
