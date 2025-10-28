"""Unit tests for OpenAI Codex SessionDetector."""

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from src.connectors._openai_codex_session_detector import (
    SessionDetector,
)


class TestSessionDetectorMetadataDetection:
    """Test metadata-based detection."""

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_metadata_exact_match(self):
        """Test detection with exact 'kilocode' in metadata."""
        detector = SessionDetector()
        metadata = {"agent": "kilocode"}
        request_data = MagicMock()

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "metadata"
        assert result.confidence == 1.0
        assert result.agent_string == "kilocode"

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_metadata_with_hyphen(self):
        """Test detection with 'kilo-code' variant."""
        detector = SessionDetector()
        metadata = {"agent": "kilo-code"}
        request_data = MagicMock()

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "metadata"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_metadata_with_underscore(self):
        """Test detection with 'kilo_code' variant."""
        detector = SessionDetector()
        metadata = {"agent": "kilo_code"}
        request_data = MagicMock()

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "metadata"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_metadata_with_version(self):
        """Test detection with version suffix like 'kilocode/1.0.0'."""
        detector = SessionDetector()
        metadata = {"agent": "kilocode/1.0.0"}
        request_data = MagicMock()

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "metadata"
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_metadata_case_insensitive(self):
        """Test detection is case-insensitive."""
        detector = SessionDetector()
        metadata = {"agent": "KiloCode"}
        request_data = MagicMock()

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "metadata"

    @pytest.mark.asyncio
    async def test_non_kilocode_agent_not_detected(self):
        """Test that non-KiloCode agents are not detected."""
        detector = SessionDetector()
        metadata = {"agent": "cline"}
        request_data = MagicMock()

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is False
        assert result.detection_method == "none"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_missing_metadata_falls_through(self):
        """Test that missing metadata doesn't cause errors."""
        detector = SessionDetector()
        request_data = MagicMock()

        result = await detector.detect(
            request_data=request_data,
            metadata=None,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is False


class TestSessionDetectorHeaderDetection:
    """Test header-based detection."""

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_user_agent_header(self):
        """Test detection from User-Agent header."""
        detector = SessionDetector()
        request_data = MagicMock()
        request_data.headers = {"User-Agent": "kilocode/1.0.0"}
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "header"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_lowercase_user_agent(self):
        """Test detection with lowercase 'user-agent' header."""
        detector = SessionDetector()
        request_data = MagicMock()
        request_data.headers = {"user-agent": "KiloCode-Client/2.0"}
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "header"

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_extra_body_headers(self):
        """Test detection from headers in extra_body."""
        detector = SessionDetector()
        request_data = MagicMock()
        request_data.headers = {}
        request_data.extra_body = {"headers": {"User-Agent": "kilocode-cli"}}
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "header"

    @pytest.mark.asyncio
    async def test_non_kilocode_user_agent_not_detected(self):
        """Test that non-KiloCode User-Agent is not detected."""
        detector = SessionDetector()
        request_data = MagicMock()
        request_data.headers = {"User-Agent": "Mozilla/5.0"}
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is False


class TestSessionDetectorHeuristicDetection:
    """Test heuristic-based detection using XML tags."""

    @pytest.mark.asyncio
    async def test_detect_kilocode_from_xml_tags(self):
        """Test detection from KiloCode XML tags in messages."""
        detector = SessionDetector()
        request_data = MagicMock()
        request_data.headers = {}
        request_data.messages = [
            {"role": "user", "content": "Please <read_file>test.py</read_file>"},
            {"role": "assistant", "content": "Sure"},
            {"role": "user", "content": "Now <execute_command>ls</execute_command>"},
        ]
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "heuristic"
        assert result.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_heuristic_detection_with_threshold(self):
        """Test that heuristic detection requires minimum tag count."""
        detector = SessionDetector(heuristic_threshold=3)
        request_data = MagicMock()
        request_data.headers = {}
        request_data.messages = [
            {"role": "user", "content": "Please <read_file>test.py</read_file>"},
            {"role": "assistant", "content": "Sure"},
        ]
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        # Only 1 tag, threshold is 3, should not detect
        assert result.is_kilocode is False

    @pytest.mark.asyncio
    async def test_heuristic_detection_multiple_tags(self):
        """Test heuristic detection with multiple different tags."""
        detector = SessionDetector(heuristic_threshold=2)
        request_data = MagicMock()
        request_data.headers = {}
        request_data.messages = [
            {
                "role": "user",
                "content": "<read_file>a.py</read_file> and <list_files>.</list_files>",
            },
        ]
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "heuristic"

    @pytest.mark.asyncio
    async def test_heuristic_detection_case_insensitive(self):
        """Test that XML tag detection is case-insensitive."""
        detector = SessionDetector(heuristic_threshold=2)
        request_data = MagicMock()
        request_data.headers = {}
        request_data.messages = [
            {
                "role": "user",
                "content": "<READ_FILE>a.py</READ_FILE> and <EXECUTE_COMMAND>ls</EXECUTE_COMMAND>",
            },
        ]
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "heuristic"

    @pytest.mark.asyncio
    async def test_no_xml_tags_not_detected(self):
        """Test that messages without XML tags are not detected."""
        detector = SessionDetector()
        request_data = MagicMock()
        request_data.headers = {}
        request_data.messages = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well!"},
        ]
        metadata = {}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is False


class TestSessionDetectorCaching:
    """Test caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self):
        """Test that cached results are reused."""
        detector = SessionDetector(cache_ttl_seconds=60)
        metadata = {"agent": "kilocode"}
        request_data = MagicMock()

        # First call - should detect and cache
        result1 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result1.is_kilocode is True
        assert result1.detection_method == "metadata"

        # Second call - should return cached result
        result2 = await detector.detect(
            request_data=request_data,
            metadata={"agent": "different"},  # Different metadata
            session_id="test_session",
            backend="openai-codex",
        )

        assert result2.is_kilocode is True
        assert result2.detection_method == "cached"
        assert result2.timestamp == result1.timestamp

    @pytest.mark.asyncio
    async def test_cache_miss_after_ttl_expiry(self):
        """Test that cache expires after TTL."""
        detector = SessionDetector(cache_ttl_seconds=0)  # Immediate expiry
        metadata = {"agent": "kilocode"}
        request_data = MagicMock()

        # First call
        result1 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result1.detection_method == "metadata"

        # Wait a bit to ensure TTL expires
        await asyncio.sleep(0.01)

        # Second call - cache should be expired
        result2 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result2.detection_method == "metadata"  # Re-detected, not cached
        assert result2.timestamp > result1.timestamp

    @pytest.mark.asyncio
    async def test_cache_invalidation(self):
        """Test manual cache invalidation."""
        detector = SessionDetector(cache_ttl_seconds=3600)
        metadata = {"agent": "kilocode"}
        request_data = MagicMock()

        # First call - cache result
        result1 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result1.detection_method == "metadata"

        # Invalidate cache
        await detector.invalidate_cache("test_session", "openai-codex")

        # Small delay to ensure timestamp difference
        await asyncio.sleep(0.001)

        # Second call - should re-detect
        result2 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result2.detection_method == "metadata"
        assert result2.timestamp >= result1.timestamp

    @pytest.mark.asyncio
    async def test_cache_per_session_and_backend(self):
        """Test that cache is keyed by session and backend."""
        detector = SessionDetector(cache_ttl_seconds=60)
        metadata = {"agent": "kilocode"}
        request_data = MagicMock()

        # Detect for session1 with backend1
        result1 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="session1",
            backend="openai-codex",
        )

        # Detect for session2 with same backend - should not use cache
        result2 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="session2",
            backend="openai-codex",
        )

        # Detect for session1 with different backend - should not use cache
        result3 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="session1",
            backend="openai",
        )

        assert result1.detection_method == "metadata"
        assert result2.detection_method == "metadata"
        assert result3.detection_method == "metadata"

        # Detect for session1 with backend1 again - should use cache
        result4 = await detector.detect(
            request_data=request_data,
            metadata={"agent": "different"},
            session_id="session1",
            backend="openai-codex",
        )

        assert result4.detection_method == "cached"


class TestSessionDetectorDetectionPriority:
    """Test detection method priority."""

    @pytest.mark.asyncio
    async def test_metadata_takes_priority_over_headers(self):
        """Test that metadata detection takes priority."""
        detector = SessionDetector()
        metadata = {"agent": "kilocode"}
        request_data = MagicMock()
        request_data.headers = {"User-Agent": "cline"}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "metadata"

    @pytest.mark.asyncio
    async def test_headers_take_priority_over_heuristics(self):
        """Test that header detection takes priority over heuristics."""
        detector = SessionDetector()
        metadata = {}
        request_data = MagicMock()
        request_data.headers = {"User-Agent": "kilocode"}
        request_data.messages = [
            {"role": "user", "content": "<read_file>test.py</read_file>"},
            {"role": "user", "content": "<execute_command>ls</execute_command>"},
        ]

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "header"


class TestSessionDetectorPerformance:
    """Test detection performance."""

    @pytest.mark.asyncio
    async def test_detection_completes_quickly(self):
        """Test that detection completes within 5ms target."""
        detector = SessionDetector()
        metadata = {"agent": "kilocode"}
        request_data = MagicMock()

        start_time = time.time()
        await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )
        elapsed_ms = (time.time() - start_time) * 1000

        # Should complete well under 5ms
        assert elapsed_ms < 5.0

    @pytest.mark.asyncio
    async def test_cached_detection_is_faster(self):
        """Test that cached detection is faster than initial detection."""
        detector = SessionDetector()
        metadata = {"agent": "kilocode"}
        request_data = MagicMock()

        # First detection
        start_time = time.time()
        await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )
        first_elapsed = time.time() - start_time

        # Cached detection
        start_time = time.time()
        await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )
        cached_elapsed = time.time() - start_time

        # Cached should be faster (or at least not slower)
        assert cached_elapsed <= first_elapsed * 1.5  # Allow some variance
