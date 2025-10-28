"""Session detection for KiloCode compatibility layer in OpenAI Codex connector."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Import telemetry
try:
    from src.connectors._openai_codex_telemetry import get_telemetry
except ImportError:
    # Fallback if telemetry module is not available
    def get_telemetry():  # type: ignore
        """Fallback telemetry getter."""
        return None


@dataclass
class DetectionResult:
    """Result of KiloCode client detection."""

    is_kilocode: bool
    detection_method: str  # "metadata", "header", "heuristic", "cached"
    confidence: float  # 0.0 to 1.0
    agent_string: str | None
    timestamp: float


class SessionDetector:
    """Detects KiloCode clients with caching for performance."""

    KILOCODE_ALIASES = {
        "kilocode",
        "kilo-code",
        "kilo_code",
        "kilocode.ai",
        "kiloc",
        "kilo",
    }

    # XML tags that are characteristic of KiloCode clients
    KILOCODE_XML_TAGS = {
        "<read_file>",
        "<list_files>",
        "<execute_command>",
        "<codebase_search>",
        "<search_files>",
        "<use_mcp_tool>",
        "<access_mcp_resource>",
        "<attempt_completion>",
        "<ask_followup_question>",
        "<search_and_replace>",
        "<write_to_file>",
        "<insert_content>",
        "<edit_file>",
    }

    def __init__(self, cache_ttl_seconds: int = 3600, heuristic_threshold: int = 2):
        """Initialize the session detector.

        Args:
            cache_ttl_seconds: Time-to-live for cached detection results
            heuristic_threshold: Minimum number of XML tags to trigger heuristic detection
        """
        self._cache: dict[str, DetectionResult] = {}
        self._cache_lock = asyncio.Lock()
        self._cache_ttl = cache_ttl_seconds
        self._heuristic_threshold = heuristic_threshold

    async def detect(
        self,
        request_data: Any,
        metadata: Mapping[str, Any] | None,
        session_id: str,
        backend: str,
    ) -> DetectionResult:
        """Detect if request is from KiloCode client.

        Args:
            request_data: The request data object
            metadata: Optional metadata dictionary
            session_id: Session identifier for caching
            backend: Backend name for cache invalidation

        Returns:
            DetectionResult with detection outcome and metadata
        """
        # Check cache first
        cache_key = self._build_cache_key(session_id, backend)
        async with self._cache_lock:
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                # Check if cache entry is still valid
                if time.time() - cached.timestamp < self._cache_ttl:
                    logger.debug(
                        "Using cached KiloCode detection result for session %s: %s",
                        session_id,
                        cached.is_kilocode,
                    )

                    # Log telemetry for cache hit
                    telemetry = get_telemetry()
                    if telemetry:
                        telemetry.log_detection_event(
                            session_id=session_id,
                            is_kilocode=cached.is_kilocode,
                            detection_method="cached",
                            confidence=cached.confidence,
                            duration_ms=0.0,  # Cache hits are essentially instant
                            agent_string=cached.agent_string,
                        )

                    return DetectionResult(
                        is_kilocode=cached.is_kilocode,
                        detection_method="cached",
                        confidence=cached.confidence,
                        agent_string=cached.agent_string,
                        timestamp=cached.timestamp,
                    )
                else:
                    # Cache expired, remove it
                    del self._cache[cache_key]

        # Perform detection
        start_time = time.time()

        # Method 1: Check metadata
        result = self._check_metadata(metadata)
        if result:
            detection_time = (time.time() - start_time) * 1000
            logger.debug(
                "KiloCode detected via metadata in %.2fms: %s",
                detection_time,
                result.agent_string,
            )
            await self._cache_result(cache_key, result)

            # Log telemetry
            telemetry = get_telemetry()
            if telemetry:
                telemetry.log_detection_event(
                    session_id=session_id,
                    is_kilocode=True,
                    detection_method=result.detection_method,
                    confidence=result.confidence,
                    duration_ms=detection_time,
                    agent_string=result.agent_string,
                )

            return result

        # Method 2: Check headers
        result = self._check_headers(request_data)
        if result:
            detection_time = (time.time() - start_time) * 1000
            logger.debug(
                "KiloCode detected via headers in %.2fms: %s",
                detection_time,
                result.agent_string,
            )
            await self._cache_result(cache_key, result)

            # Log telemetry
            telemetry = get_telemetry()
            if telemetry:
                telemetry.log_detection_event(
                    session_id=session_id,
                    is_kilocode=True,
                    detection_method=result.detection_method,
                    confidence=result.confidence,
                    duration_ms=detection_time,
                    agent_string=result.agent_string,
                )

            return result

        # Method 3: Check payload heuristics
        result = self._check_payload_heuristics(request_data)
        if result:
            detection_time = (time.time() - start_time) * 1000
            logger.debug(
                "KiloCode detected via heuristics in %.2fms (confidence: %.2f)",
                detection_time,
                result.confidence,
            )
            await self._cache_result(cache_key, result)

            # Log telemetry
            telemetry = get_telemetry()
            if telemetry:
                telemetry.log_detection_event(
                    session_id=session_id,
                    is_kilocode=True,
                    detection_method=result.detection_method,
                    confidence=result.confidence,
                    duration_ms=detection_time,
                    agent_string=result.agent_string,
                )

            return result

        # Not detected as KiloCode
        detection_time = (time.time() - start_time) * 1000
        logger.debug(
            "KiloCode not detected for session %s (%.2fms)", session_id, detection_time
        )
        result = DetectionResult(
            is_kilocode=False,
            detection_method="none",
            confidence=0.0,
            agent_string=None,
            timestamp=time.time(),
        )
        await self._cache_result(cache_key, result)

        # Log telemetry for non-detection
        telemetry = get_telemetry()
        if telemetry:
            telemetry.log_detection_event(
                session_id=session_id,
                is_kilocode=False,
                detection_method="none",
                confidence=0.0,
                duration_ms=detection_time,
                agent_string=None,
            )

        return result

    def _check_metadata(
        self, metadata: Mapping[str, Any] | None
    ) -> DetectionResult | None:
        """Check explicit agent metadata for KiloCode identification.

        Args:
            metadata: Request metadata dictionary

        Returns:
            DetectionResult if KiloCode detected, None otherwise
        """
        if not metadata or not isinstance(metadata, Mapping):
            return None

        agent = metadata.get("agent")
        if not isinstance(agent, str):
            return None

        agent_lower = agent.lower().strip()
        if not agent_lower:
            return None

        # Normalize for comparison (remove separators)
        normalized = agent_lower.replace("-", "").replace("_", "").replace(".", "")

        # Check direct matches
        if agent_lower in self.KILOCODE_ALIASES or normalized in {
            "kilocode",
            "kiloc",
            "kilo",
        }:
            return DetectionResult(
                is_kilocode=True,
                detection_method="metadata",
                confidence=1.0,
                agent_string=agent,
                timestamp=time.time(),
            )

        # Check if it starts with kilocode variants
        if normalized.startswith("kilocode"):
            return DetectionResult(
                is_kilocode=True,
                detection_method="metadata",
                confidence=0.95,
                agent_string=agent,
                timestamp=time.time(),
            )

        return None

    def _check_headers(self, request_data: Any) -> DetectionResult | None:
        """Check HTTP User-Agent header for KiloCode identification.

        Args:
            request_data: The request data object

        Returns:
            DetectionResult if KiloCode detected, None otherwise
        """
        # Try to extract User-Agent from various possible locations
        user_agent = None

        # Check if request_data has headers attribute
        if hasattr(request_data, "headers"):
            headers = request_data.headers
            if isinstance(headers, Mapping):
                user_agent = headers.get("User-Agent") or headers.get("user-agent")

        # Check extra_body for headers
        if not user_agent and hasattr(request_data, "extra_body"):
            extra_body = request_data.extra_body
            if isinstance(extra_body, Mapping):
                headers = extra_body.get("headers")
                if isinstance(headers, Mapping):
                    user_agent = headers.get("User-Agent") or headers.get("user-agent")

        if not user_agent or not isinstance(user_agent, str):
            return None

        user_agent_lower = user_agent.lower().strip()
        if not user_agent_lower:
            return None

        # Normalize for comparison
        normalized = user_agent_lower.replace("-", "").replace("_", "").replace(".", "")

        # Check for KiloCode in User-Agent
        if any(alias in user_agent_lower for alias in self.KILOCODE_ALIASES):
            return DetectionResult(
                is_kilocode=True,
                detection_method="header",
                confidence=0.9,
                agent_string=user_agent,
                timestamp=time.time(),
            )

        if "kilocode" in normalized:
            return DetectionResult(
                is_kilocode=True,
                detection_method="header",
                confidence=0.85,
                agent_string=user_agent,
                timestamp=time.time(),
            )

        return None

    def _check_payload_heuristics(self, request_data: Any) -> DetectionResult | None:
        """Check for KiloCode-specific XML tags in request payload.

        Args:
            request_data: The request data object

        Returns:
            DetectionResult if KiloCode detected, None otherwise
        """
        # Extract messages from request
        messages = None
        if hasattr(request_data, "messages"):
            messages = request_data.messages
        elif isinstance(request_data, Mapping):
            messages = request_data.get("messages")

        if not messages:
            return None

        # Count XML tag occurrences in message content
        tag_count = 0
        found_tags: set[str] = set()

        for message in messages:
            content = None
            if hasattr(message, "content"):
                content = message.content
            elif isinstance(message, Mapping):
                content = message.get("content")

            if not content:
                continue

            # Convert content to string
            content_str = str(content).lower()

            # Check for KiloCode XML tags
            for tag in self.KILOCODE_XML_TAGS:
                if tag.lower() in content_str:
                    tag_count += 1
                    found_tags.add(tag)

        # If we found enough tags, consider it KiloCode
        if tag_count >= self._heuristic_threshold:
            confidence = min(0.7 + (tag_count * 0.05), 0.95)
            logger.debug(
                "Heuristic detection found %d KiloCode XML tags: %s",
                tag_count,
                found_tags,
            )
            return DetectionResult(
                is_kilocode=True,
                detection_method="heuristic",
                confidence=confidence,
                agent_string=None,
                timestamp=time.time(),
            )

        return None

    async def invalidate_cache(self, session_id: str, backend: str) -> None:
        """Clear cached detection result for a session.

        Args:
            session_id: Session identifier
            backend: Backend name
        """
        cache_key = self._build_cache_key(session_id, backend)
        async with self._cache_lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                logger.debug(
                    "Invalidated KiloCode detection cache for session %s", session_id
                )

    async def _cache_result(self, cache_key: str, result: DetectionResult) -> None:
        """Store detection result in cache.

        Args:
            cache_key: Cache key
            result: Detection result to cache
        """
        async with self._cache_lock:
            self._cache[cache_key] = result

    @staticmethod
    def _build_cache_key(session_id: str, backend: str) -> str:
        """Build cache key from session and backend.

        Args:
            session_id: Session identifier
            backend: Backend name

        Returns:
            Cache key string
        """
        return f"{session_id}:{backend}"
