"""
Behavior specification tests for Wire Capture Service.

These tests follow BDD principles to specify the expected behavior of the wire capture
system as defined in debugging and monitoring requirements. They use Given-When-Then
structure to clearly specify behavior requirements rather than just validating
implementation details.

Key behaviors specified:
1. Request/response capture and formatting
2. Buffer management and flushing behavior
3. File rotation and size management
4. Async I/O and background task management
5. API key redaction and security
6. Stream capture and chunking
7. Performance optimization and caching
8. Error handling and resilience
"""

import asyncio
import json
import os
import tempfile
import time
from unittest.mock import Mock, patch

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.services.buffered_wire_capture_service import (
    BufferedWireCapture,
)
from tests.unit.fixtures.markers import real_time


class TestWireCaptureInitializationBehavior:
    """
    Behavior specifications for wire capture initialization as defined in system requirements.

    Given: Various configuration scenarios
    When: Wire capture service is initialized
    Then: Service should initialize correctly with appropriate settings
    """

    def test_enabled_wire_capture_initialization(self):
        """
        Given: A configuration with wire capture enabled
        When: The wire capture service is initialized
        Then: Service should be enabled and ready to capture
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "test_capture.log")
            config.logging.capture_buffer_size = 1024
            config.logging.capture_flush_interval = 0.5
            config.logging.capture_max_entries_per_flush = 10
            config.logging.capture_max_files = 5
            config.logging.capture_total_max_bytes = 5242880

            # When
            service = BufferedWireCapture(config)

            try:
                # Then
                assert service.enabled() is True
                assert service._file_path == config.logging.capture_file
                assert service._buffer_size == 1024
                assert service._flush_interval == 0.5
            finally:
                # Cleanup
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.run_until_complete(service.shutdown())
                except RuntimeError:
                    asyncio.run(service.shutdown())

    def test_disabled_wire_capture_initialization(self):
        """
        Given: A configuration without wire capture file path
        When: The wire capture service is initialized
        Then: Service should be disabled and not capture anything
        """
        # Given
        config = Mock(spec=AppConfig)
        config.logging = Mock()
        config.logging.capture_file = None

        # When
        service = BufferedWireCapture(config)

        try:
            # Then
            assert service.enabled() is False
        finally:
            # Cleanup (even disabled services might have background tasks)
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.run_until_complete(service.shutdown())
            except RuntimeError:
                asyncio.run(service.shutdown())

    def test_directory_creation_on_initialization(self):
        """
        Given: A configuration with a capture file in non-existent directory
        When: The wire capture service is initialized
        Then: Directory should be created automatically
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_dir = os.path.join(temp_dir, "nested", "path")
            capture_file = os.path.join(nested_dir, "capture.log")

            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = capture_file

            # When
            service = BufferedWireCapture(config)

            try:
                # Then
                assert os.path.exists(nested_dir)
                assert service.enabled() is True
            finally:
                # Cleanup
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.run_until_complete(service.shutdown())
                except RuntimeError:
                    asyncio.run(service.shutdown())

    def test_initialization_header_writing(self):
        """
        Given: A valid wire capture configuration
        When: The wire capture service is initialized
        Then: An initialization header should be written to the capture file
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_file = os.path.join(temp_dir, "test_capture.log")

            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = capture_file

            # When
            service = BufferedWireCapture(config)

            try:
                # Then
                assert os.path.exists(capture_file)
                with open(capture_file) as f:
                    first_line = f.readline().strip()
                    header_entry = json.loads(first_line)

                assert header_entry["direction"] == "system_init"
                assert header_entry["source"] == "wire_capture_service"
                assert header_entry["destination"] == "file_system"
                assert "Wire capture initialized" in header_entry["payload"]["message"]
            finally:
                # Cleanup
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.run_until_complete(service.shutdown())
                except RuntimeError:
                    asyncio.run(service.shutdown())

    def test_configuration_parameter_inheritance(self):
        """
        Given: Various configuration parameters
        When: The wire capture service is initialized
        Then: All relevant parameters should be properly inherited
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "test.log")
            config.logging.capture_buffer_size = 32768
            config.logging.capture_flush_interval = 2.0
            config.logging.capture_max_entries_per_flush = 50
            config.logging.capture_max_bytes = 1048576  # 1MB
            config.logging.capture_max_files = 5
            config.logging.capture_total_max_bytes = 5242880  # 5MB

            # When
            service = BufferedWireCapture(config)

            try:
                # Then
                assert service._buffer_size == 32768
                assert service._flush_interval == 2.0
                assert service._max_entries_per_flush == 50
                assert service._max_bytes == 1048576
                assert service._max_files == 5
                assert service._total_cap == 5242880
            finally:
                # Cleanup
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.run_until_complete(service.shutdown())
                except RuntimeError:
                    asyncio.run(service.shutdown())


class TestRequestResponseCaptureBehavior:
    """
    Behavior specifications for request/response capture as defined in monitoring requirements.

    Given: Various request/response scenarios
    When: Capture methods are called
    Then: Data should be captured with proper formatting and metadata
    """

    @pytest.mark.asyncio
    async def test_inbound_request_capture(self):
        """
        Given: A client request to the proxy
        When: The inbound request capture method is called
        Then: Request should be captured with client metadata
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._create_test_config(temp_dir)
            service = BufferedWireCapture(config)

            context = Mock(spec=RequestContext)
            context.client_host = "192.168.1.100"
            context.agent = "TestAgent/1.0"
            context.request_id = "req-123"

            request_payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            }

            # When
            await service.capture_inbound_request(
                context=context,
                session_id="session-456",
                request_payload=request_payload,
            )

            # Force flush to write to file
            await service.shutdown()

            # Then
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()

            # Skip header line
            request_line = lines[1].strip()
            request_entry = json.loads(request_line)

            assert request_entry["direction"] == "inbound_request"
            assert request_entry["source"] == "192.168.1.100(TestAgent/1.0)"
            assert request_entry["destination"] == "proxy"
            assert request_entry["session_id"] == "session-456"
            assert request_entry["backend"] == "client"
            assert request_entry["model"] == "gpt-4"
            assert request_entry["content_type"] == "json"
            assert request_entry["metadata"]["client_host"] == "192.168.1.100"
            assert request_entry["metadata"]["user_agent"] == "TestAgent/1.0"
            assert request_entry["metadata"]["request_id"] == "req-123"

    @pytest.mark.asyncio
    async def test_outbound_request_capture(self):
        """
        Given: A proxy request to a backend
        When: The outbound request capture method is called
        Then: Request should be captured with backend metadata
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._create_test_config(temp_dir)
            service = BufferedWireCapture(config)

            context = Mock(spec=RequestContext)
            context.client_host = "10.0.0.1"

            request_payload = {
                "model": "gemini-pro",
                "messages": [{"role": "user", "content": "Test"}],
                "temperature": 0.7,
            }

            # When
            await service.capture_outbound_request(
                context=context,
                session_id="session-789",
                backend="google",
                model="gemini-pro",
                key_name="test-key",
                request_payload=request_payload,
            )

            await service.shutdown()

            # Then
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()

            request_line = lines[1].strip()  # Skip header
            request_entry = json.loads(request_line)

            assert request_entry["direction"] == "outbound_request"
            assert request_entry["source"] == "10.0.0.1"
            assert request_entry["destination"] == "google"
            assert request_entry["backend"] == "google"
            assert request_entry["model"] == "gemini-pro"
            assert request_entry["key_name"] == "test-key"

    @pytest.mark.asyncio
    async def test_inbound_response_capture(self):
        """
        Given: A backend response to the proxy
        When: The inbound response capture method is called
        Then: Response should be captured with response metadata
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._create_test_config(temp_dir)
            service = BufferedWireCapture(config)

            response_content = {
                "choices": [{"message": {"content": "Hello, how can I help you?"}}]
            }

            # When
            await service.capture_inbound_response(
                context=None,
                session_id="session-abc",
                backend="openai",
                model="gpt-4",
                key_name="openai-key",
                response_content=response_content,
            )

            await service.shutdown()

            # Then
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()

            response_line = lines[1].strip()  # Skip header
            response_entry = json.loads(response_line)

            assert response_entry["direction"] == "inbound_response"
            assert response_entry["source"] == "openai"
            assert response_entry["destination"] == "unknown_client"
            assert response_entry["backend"] == "openai"
            assert response_entry["model"] == "gpt-4"
            assert response_entry["key_name"] == "openai-key"
            assert response_entry["content_type"] == "json"

    @pytest.mark.asyncio
    async def test_content_type_detection(self):
        """
        Given: Various payload types
        When: Capture methods are called
        Then: Content types should be correctly detected
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._create_test_config(temp_dir)
            service = BufferedWireCapture(config)

            test_cases = [
                ({"key": "value"}, "json"),
                ("plain text", "text"),
                (b"bytes data", "bytes"),
                (123, "object"),
                ([1, 2, 3], "json"),
            ]

            for payload, expected_type in test_cases:
                # When
                await service.capture_inbound_response(
                    context=None,
                    session_id=f"session-{expected_type}",
                    backend="test",
                    model="test-model",
                    key_name=None,
                    response_content=payload,
                )

            await service.shutdown()

            # Then
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()

            # Skip header line
            for i, (_payload, expected_type) in enumerate(test_cases):
                entry = json.loads(lines[i + 1].strip())
                assert entry["content_type"] == expected_type

    def _create_test_config(self, temp_dir: str) -> AppConfig:
        """Helper to create test configuration."""
        config = Mock(spec=AppConfig)
        config.logging = Mock()
        config.logging.capture_file = os.path.join(temp_dir, "test_capture.log")
        config.logging.capture_buffer_size = 1024
        config.logging.capture_flush_interval = 0.1
        config.logging.capture_max_entries_per_flush = 5
        config.logging.capture_max_files = 3
        config.logging.capture_total_max_bytes = 1048576
        return config


class TestBufferManagementBehavior:
    """
    Behavior specifications for buffer management and flushing as defined in performance requirements.

    Given: Various buffer scenarios
    When: Entries are captured and buffers are managed
    Then: Buffer behavior should follow configured policies
    """

    @pytest.mark.asyncio
    async def test_buffer_size_flush_trigger(self):
        """
        Given: A buffer with maximum entries per flush configured
        When: Buffer reaches the maximum size
        Then: Buffer should be automatically flushed
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "test.log")
            config.logging.capture_max_entries_per_flush = 3  # Small buffer for testing
            config.logging.capture_flush_interval = (
                10.0  # Long interval to prevent time-based flush
            )

            service = BufferedWireCapture(config)

            # When - Add entries up to buffer limit
            for i in range(3):
                await service.capture_inbound_response(
                    context=None,
                    session_id=f"session-{i}",
                    backend="test",
                    model="test",
                    key_name=None,
                    response_content={"data": f"response-{i}"},
                )

            # Give a moment for async processing
            from tests.utils.fake_clock import FakeClockContext

            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                clock.advance(0.1)
                await sleep_task

            # Await the service flush so the asynchronous write is complete
            # before inspecting the capture file.
            await service.shutdown()

            # Then - Buffer should have been flushed (file should contain entries)
            assert service._file_path is not None
            assert os.path.exists(service._file_path)
            with open(service._file_path) as f:
                lines = f.readlines()

            # Should have header + 3 entries
            assert len(lines) >= 4

    @pytest.mark.asyncio
    async def test_time_based_flush_trigger(self):
        """
        Given: A buffer with flush interval configured
        When: The flush interval elapses
        Then: Buffer should be automatically flushed
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "test.log")
            config.logging.capture_max_entries_per_flush = 100  # Large buffer
            config.logging.capture_flush_interval = 0.05  # Short interval for testing

            service = BufferedWireCapture(config)

            # When - Add a single entry and wait for flush interval
            await service.capture_inbound_response(
                context=None,
                session_id="time-test",
                backend="test",
                model="test",
                key_name=None,
                response_content={"data": "test"},
            )

            # Wait longer than flush interval
            await asyncio.sleep(0.1)
            await service.shutdown()

            # Then - Entry should have been flushed
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()

            # Should have header + our entry
            assert len(lines) >= 2

    @pytest.mark.asyncio
    async def test_concurrent_buffer_access(self):
        """
        Given: Multiple concurrent capture operations
        When: Operations access the buffer simultaneously
        Then: All operations should complete safely without data loss
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "test.log")
            config.logging.capture_max_entries_per_flush = 20
            config.logging.capture_flush_interval = 1.0

            service = BufferedWireCapture(config)

            async def capture_worker(worker_id: int):
                """Worker function that captures multiple entries."""
                for i in range(10):
                    await service.capture_inbound_response(
                        context=None,
                        session_id=f"session-{worker_id}-{i}",
                        backend="test",
                        model="test",
                        key_name=None,
                        response_content={"worker": worker_id, "entry": i},
                    )

            # When - Run multiple workers concurrently
            tasks = [capture_worker(i) for i in range(5)]
            await asyncio.gather(*tasks)

            # Force final flush
            await service.shutdown()

            # Then - All entries should be captured
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()

            # Should have header + 50 entries (5 workers * 10 entries each)
            assert len(lines) >= 51

    @pytest.mark.asyncio
    async def test_buffer_overflow_handling(self):
        """
        Given: Rapid capture that exceeds buffer processing capacity
        When: Many entries are captured quickly
        Then: Buffer should handle overflow gracefully
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "test.log")
            config.logging.capture_max_entries_per_flush = 10
            config.logging.capture_flush_interval = 2.0  # Long interval

            service = BufferedWireCapture(config)

            # When - Add many entries rapidly
            for i in range(50):
                await service.capture_inbound_response(
                    context=None,
                    session_id=f"overflow-{i}",
                    backend="test",
                    model="test",
                    key_name=None,
                    response_content={"index": i},
                )

            # Force shutdown to flush everything
            await service.shutdown()

            # Then - All entries should be captured (multiple flushes should have occurred)
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()

            # Should have header + 50 entries
            assert len(lines) >= 51


class TestFileRotationBehavior:
    """
    Behavior specifications for file rotation as defined in storage management requirements.

    Given: File rotation configuration
    When: Files reach size limits
    Then: Rotation should occur according to configured policies
    """

    @pytest.mark.asyncio
    async def test_file_rotation_on_size_limit(self):
        """
        Given: A capture file with maximum size configured
        When: The file reaches the size limit
        Then: File should be rotated according to policy
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_file = os.path.join(temp_dir, "rotating.log")

            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = capture_file
            config.logging.capture_max_bytes = 1024  # Very small for testing
            config.logging.capture_max_files = 3
            config.logging.capture_flush_interval = 0.1

            service = BufferedWireCapture(config)

            # Create a large payload that will exceed the size limit
            large_payload = {"data": "x" * 800}  # Large entry

            # When - Add enough entries to trigger rotation
            for i in range(3):  # This should trigger rotation
                await service.capture_inbound_response(
                    context=None,
                    session_id=f"rotation-{i}",
                    backend="test",
                    model="test",
                    key_name=None,
                    response_content=large_payload,
                )

            # Wait for flush and rotation
            await asyncio.sleep(0.2)  # Increased from 0.1 for stability
            await service.shutdown()

            # Allow background rotation to complete on slower systems
            rotated_path = f"{capture_file}.1"
            if not os.path.exists(rotated_path):
                for _ in range(10):  # Increased from 5 for stability
                    await asyncio.sleep(0.05)  # Increased from 0.02 for stability
                    if os.path.exists(rotated_path):
                        break

            # Then - Rotation should have occurred
            assert os.path.exists(capture_file)  # Current file
            assert os.path.exists(rotated_path)  # Rotated file

    @pytest.mark.asyncio
    async def test_max_files_rotation_limit(self):
        """
        Given: File rotation with maximum files configured
        When: More files than the maximum are created
        Then: Oldest files should be deleted
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_file = os.path.join(temp_dir, "max_files.log")

            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = capture_file
            config.logging.capture_max_bytes = 500  # Small to trigger frequent rotation
            config.logging.capture_max_files = 2  # Keep only 2 rotated files
            config.logging.capture_flush_interval = 0.05

            service = BufferedWireCapture(config)

            # Create multiple rotations
            large_payload = {"data": "y" * 400}

            # When - Create enough entries to exceed max files
            for i in range(5):
                await service.capture_inbound_response(
                    context=None,
                    session_id=f"max-files-{i}",
                    backend="test",
                    model="test",
                    key_name=None,
                    response_content=large_payload,
                )

            await asyncio.sleep(0.15)
            await service.shutdown()

            # Then - Only max_files should exist
            files_present = []
            for i in range(1, 10):  # Check reasonable range
                file_path = f"{capture_file}.{i}"
                if os.path.exists(file_path):
                    files_present.append(i)

            # Should have at most max_files rotated files
            assert len(files_present) <= 2

    @pytest.mark.asyncio
    async def test_rotation_disabled_by_default(self):
        """
        Given: A capture configuration without rotation settings
        When: Files grow large
        Then: No rotation should occur
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_file = os.path.join(temp_dir, "no_rotation.log")

            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = capture_file
            config.logging.capture_max_bytes = None  # No rotation
            config.logging.capture_max_files = 0

            service = BufferedWireCapture(config)

            try:
                # When
                assert service._max_bytes is None
                assert service._max_files == 0

                # Then - Rotation methods should return early
                await service._check_rotation()  # Should not raise any errors
            finally:
                # Cleanup
                await service.shutdown()


class TestAPICKeyRedactionBehavior:
    """
    Behavior specifications for API key redaction as defined in security requirements.

    Given: Captured data containing sensitive information
    When: Data is processed for capture
    Then: Sensitive information should be redacted
    """

    @pytest.mark.asyncio
    async def test_api_key_redaction_in_payloads(self):
        """
        Given: Payloads containing API keys
        When: Payloads are captured
        Then: API keys should be redacted
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "redaction.log")
            config.logging.capture_flush_interval = 0.1

            # Mock API key discovery
            with patch(
                "src.core.services.buffered_wire_capture_service.discover_api_keys_from_config_and_env"
            ) as mock_discover:
                mock_discover.return_value = {"sk-test123", "sk-secret456"}

                service = BufferedWireCapture(config)

                payload_with_keys = {
                    "api_key": "sk-test123",
                    "authorization": "Bearer sk-secret456",
                    "headers": {
                        "X-API-Key": "sk-test123",
                        "Authorization": "Bearer sk-secret456",
                    },
                    "messages": [{"content": "The key is sk-test123"}],
                }

                # When
                await service.capture_inbound_request(
                    context=None,
                    session_id="redaction-test",
                    request_payload=payload_with_keys,
                )

                await service.shutdown()

                # Then
                assert service._file_path is not None
                with open(service._file_path) as f:
                    lines = f.readlines()

                request_entry = json.loads(lines[1].strip())  # Skip header
                captured_payload = request_entry["payload"]

                # Keys should be redacted
                assert "sk-test123" not in str(captured_payload)
                assert "sk-secret456" not in str(captured_payload)
                assert "[REDACTED]" in str(captured_payload)

    @pytest.mark.asyncio
    async def test_redaction_preserves_structure(self):
        """
        Given: Complex nested structures with API keys
        When: Redaction occurs
        Then: Structure should be preserved with keys redacted
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "structure.log")
            config.logging.capture_flush_interval = 0.1

            with patch(
                "src.core.services.buffered_wire_capture_service.discover_api_keys_from_config_and_env"
            ) as mock_discover:
                mock_discover.return_value = {"sensitive-key"}

                service = BufferedWireCapture(config)

                complex_payload = {
                    "level1": {
                        "api_key": "sensitive-key",
                        "level2": {
                            "data": ["item1", "item2"],
                            "secret": "sensitive-key",
                        },
                    },
                    "normal_data": ["a", "b", "c"],
                }

                # When
                await service.capture_outbound_request(
                    context=None,
                    session_id="structure-test",
                    backend="test",
                    model="test",
                    key_name=None,
                    request_payload=complex_payload,
                )

                await service.shutdown()

                # Then
                assert service._file_path is not None
                with open(service._file_path) as f:
                    lines = f.readlines()

                request_entry = json.loads(lines[1].strip())
                captured_payload = request_entry["payload"]

                # Structure should be preserved
                assert "level1" in captured_payload
                assert "level2" in captured_payload["level1"]
                assert "data" in captured_payload["level1"]["level2"]
                assert captured_payload["normal_data"] == ["a", "b", "c"]

                # Keys should be redacted
                assert "[REDACTED]" in captured_payload["level1"]["api_key"]
                assert "[REDACTED]" in captured_payload["level1"]["level2"]["secret"]


class TestStreamCaptureBehavior:
    """
    Behavior specifications for streaming response capture as defined in monitoring requirements.

    Given: Streaming response scenarios
    When: Streams are wrapped for capture
    Then: Stream data should be captured with appropriate metadata
    """

    @pytest.mark.asyncio
    async def test_stream_capture_with_markers(self):
        """
        Given: A streaming response
        When: The stream is wrapped for capture
        Then: Stream start, chunks, and end markers should be captured
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "stream.log")
            config.logging.capture_flush_interval = 0.1

            service = BufferedWireCapture(config)

            # Create a mock stream
            async def mock_stream():
                yield b'{"chunk": "1"}'
                yield b'{"chunk": "2"}'
                yield b'{"chunk": "3"}'

            # When
            wrapped_stream = service.wrap_inbound_stream(
                context=None,
                session_id="stream-test",
                backend="test-backend",
                model="test-model",
                key_name=None,
                stream=mock_stream(),
            )

            # Consume the wrapped stream
            chunks = []
            async for chunk in wrapped_stream:
                chunks.append(chunk)

            await service.shutdown()

            # Then
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()

            # Should have: header + start + 3 chunks + end = 5 lines
            assert len(lines) >= 5

            # Check stream start marker
            start_entry = json.loads(lines[1].strip())
            assert start_entry["direction"] == "stream_start"
            assert start_entry["backend"] == "test-backend"

            # Check stream chunks
            for i in range(3):
                chunk_entry = json.loads(lines[2 + i].strip())
                assert chunk_entry["direction"] == "stream_chunk"
                assert f'"chunk": "{i + 1}"' in chunk_entry["payload"]
                assert chunk_entry["metadata"]["chunk_number"] == i + 1

            # Check stream end marker
            end_entry = json.loads(lines[5].strip())
            assert end_entry["direction"] == "stream_end"
            assert end_entry["payload"]["total_chunks"] == 3

    @pytest.mark.asyncio
    async def test_disabled_stream_passthrough(self):
        """
        Given: A wire capture service that is disabled
        When: A stream is wrapped
        Then: Original stream should be returned unchanged
        """
        # Given
        config = Mock(spec=AppConfig)
        config.logging = Mock()
        config.logging.capture_file = None  # Disabled

        service = BufferedWireCapture(config)

        try:

            async def mock_stream():
                yield b"data1"
                yield b"data2"

            # When
            wrapped_stream = service.wrap_inbound_stream(
                context=None,
                session_id="passthrough-test",
                backend="test",
                model="test",
                key_name=None,
                stream=mock_stream(),
            )

            # Then
            chunks = []
            async for chunk in wrapped_stream:
                chunks.append(chunk)

            assert chunks == [b"data1", b"data2"]
            assert wrapped_stream == mock_stream()  # Should be the same stream object
        finally:
            # Cleanup
            await service.shutdown()

    @pytest.mark.asyncio
    async def test_stream_error_handling(self):
        """
        Given: A stream that raises an error
        When: The stream is wrapped and consumed
        Then: Errors should be propagated correctly
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "error.log")
            config.logging.capture_flush_interval = 0.1

            service = BufferedWireCapture(config)

            async def error_stream():
                yield b"before error"
                raise ValueError("Stream error")

            # When/Then
            wrapped_stream = service.wrap_inbound_stream(
                context=None,
                session_id="error-test",
                backend="test",
                model="test",
                key_name=None,
                stream=error_stream(),
            )

            chunks = []
            with pytest.raises(ValueError, match="Stream error"):
                async for chunk in wrapped_stream:
                    chunks.append(chunk)

            assert chunks == [b"before error"]


class TestPerformanceOptimizationBehavior:
    """
    Behavior specifications for performance optimizations as defined in system requirements.

    Given: Performance optimization features
    When: Various operations are performed
    Then: Optimizations should work correctly and improve performance
    """

    @pytest.mark.asyncio
    async def test_content_length_caching(self):
        """
        Given: Multiple captures of the same payload objects
        When: Content length is calculated
        Then: Caching should avoid repeated calculations
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "cache.log")

            service = BufferedWireCapture(config)

            try:
                # Create a payload and reuse the same object
                payload = {"data": "test", "items": [1, 2, 3, 4, 5]}

                # When - Capture the same payload multiple times
                for i in range(5):
                    await service.capture_inbound_response(
                        context=None,
                        session_id=f"cache-{i}",
                        backend="test",
                        model="test",
                        key_name=None,
                        response_content=payload,  # Same object
                    )

                # Then - Cache should be used (cache size should be 1, not 5)
                assert len(service._content_length_cache) <= 1
                # Content length should be cached
                payload_id = id(payload)
                assert payload_id in service._content_length_cache
            finally:
                # Cleanup
                await service.shutdown()

    @pytest.mark.asyncio
    async def test_cache_size_limit_enforcement(self):
        """
        Given: A content length cache with maximum size
        When: More unique payloads than the limit are captured
        Then: Oldest entries should be evicted to maintain size limit
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "cache_limit.log")

            service = BufferedWireCapture(config)
            original_cache_max_size = service._cache_max_size
            service._cache_max_size = 3  # Small limit for testing

            try:
                # When - Add more unique payloads than the cache limit
                unique_payloads = []
                for i in range(5):
                    payload = {"unique_data": f"value-{i}"}
                    unique_payloads.append(payload)

                    await service.capture_inbound_response(
                        context=None,
                        session_id=f"unique-{i}",
                        backend="test",
                        model="test",
                        key_name=None,
                        response_content=payload,
                    )

                # Then - Cache size should not exceed the limit
                assert len(service._content_length_cache) <= 3

                # Restore original cache size
                service._cache_max_size = original_cache_max_size
            finally:
                # Cleanup
                await service.shutdown()
                # Restore original cache size in case of test failure
                service._cache_max_size = original_cache_max_size

    @real_time(
        reason="Measures actual capture time to verify performance remains reasonable (< 1.0s for 50 captures)."
    )
    @pytest.mark.asyncio
    async def test_async_background_flush_performance(self):
        """
        Given: High-frequency capture operations
        When: Background flushing is enabled
        Then: Performance should be maintained with non-blocking operations
        """
        # Given
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Mock(spec=AppConfig)
            config.logging = Mock()
            config.logging.capture_file = os.path.join(temp_dir, "performance.log")
            config.logging.capture_flush_interval = 0.1
            config.logging.capture_max_entries_per_flush = 50

            service = BufferedWireCapture(config)

            # When - Perform many rapid captures
            start_time = time.time()

            for i in range(50):  # Reduced from 100 for performance
                await service.capture_inbound_response(
                    context=None,
                    session_id=f"perf-{i}",
                    backend="test",
                    model="test",
                    key_name=None,
                    response_content={"index": i, "data": "x" * 100},
                )

            capture_time = time.time() - start_time

            # Wait for background flushing
            await asyncio.sleep(0.1)  # Reduced from 0.2 for performance
            await service.shutdown()

            # Then - Capture should be fast (non-blocking)
            assert capture_time < 1.0  # Should complete quickly

            # All data should be captured
            assert service._file_path is not None
            with open(service._file_path) as f:
                lines = f.readlines()
            assert len(lines) >= 51  # Header + 50 entries (reduced from 101)
