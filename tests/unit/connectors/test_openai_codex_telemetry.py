"""Unit tests for OpenAI Codex compatibility layer telemetry."""

from src.connectors._openai_codex_telemetry import (
    DEFAULT_DURATION_SAMPLE_LIMIT,
    CompatibilityTelemetry,
    DetectionMetrics,
    ErrorMetrics,
    TranslationMetrics,
    get_telemetry,
    reset_telemetry,
)


class TestDetectionMetrics:
    """Test detection metrics tracking."""

    def test_record_detection_metadata(self):
        """Test recording a metadata-based detection."""
        metrics = DetectionMetrics()
        metrics.record_detection("metadata", 2.5, is_cached=False)

        assert metrics.total_detections == 1
        assert metrics.metadata_detections == 1
        assert metrics.header_detections == 0
        assert metrics.heuristic_detections == 0
        assert metrics.cache_hits == 0
        assert metrics.cache_misses == 1
        assert metrics.total_duration_ms == 2.5
        assert len(metrics.detection_durations) == 1

    def test_detection_durations_are_bounded(self):
        """Duration samples should be bounded to prevent unbounded memory growth."""
        metrics = DetectionMetrics()
        for _ in range(DEFAULT_DURATION_SAMPLE_LIMIT + 10):
            metrics.record_detection("metadata", 1.0, is_cached=False)

        assert len(metrics.detection_durations) == DEFAULT_DURATION_SAMPLE_LIMIT

    def test_record_detection_header(self):
        """Test recording a header-based detection."""
        metrics = DetectionMetrics()
        metrics.record_detection("header", 3.0, is_cached=False)

        assert metrics.total_detections == 1
        assert metrics.metadata_detections == 0
        assert metrics.header_detections == 1
        assert metrics.heuristic_detections == 0

    def test_record_detection_heuristic(self):
        """Test recording a heuristic-based detection."""
        metrics = DetectionMetrics()
        metrics.record_detection("heuristic", 4.5, is_cached=False)

        assert metrics.total_detections == 1
        assert metrics.metadata_detections == 0
        assert metrics.header_detections == 0
        assert metrics.heuristic_detections == 1

    def test_record_detection_cached(self):
        """Test recording a cached detection."""
        metrics = DetectionMetrics()
        metrics.record_detection("cached", 0.1, is_cached=True)

        assert metrics.total_detections == 1
        assert metrics.cache_hits == 1
        assert metrics.cache_misses == 0
        # Cached detections don't increment method-specific counters
        assert metrics.metadata_detections == 0
        assert metrics.header_detections == 0
        assert metrics.heuristic_detections == 0

    def test_multiple_detections(self):
        """Test recording multiple detections."""
        metrics = DetectionMetrics()
        metrics.record_detection("metadata", 2.0, is_cached=False)
        metrics.record_detection("header", 3.0, is_cached=False)
        metrics.record_detection("cached", 0.1, is_cached=True)

        assert metrics.total_detections == 3
        assert metrics.metadata_detections == 1
        assert metrics.header_detections == 1
        assert metrics.cache_hits == 1
        assert metrics.cache_misses == 2
        assert metrics.total_duration_ms == 5.1

    def test_get_average_duration(self):
        """Test calculating average detection duration."""
        metrics = DetectionMetrics()
        metrics.record_detection("metadata", 2.0, is_cached=False)
        metrics.record_detection("header", 4.0, is_cached=False)
        metrics.record_detection("heuristic", 6.0, is_cached=False)

        avg = metrics.get_average_duration()
        assert avg == 4.0  # (2 + 4 + 6) / 3

    def test_get_average_duration_empty(self):
        """Test average duration with no detections."""
        metrics = DetectionMetrics()
        avg = metrics.get_average_duration()
        assert avg == 0.0


class TestTranslationMetrics:
    """Test translation metrics tracking."""

    def test_record_translation_success(self):
        """Test recording a successful translation."""
        metrics = TranslationMetrics()
        metrics.record_translation("read_file", 1.5, success=True)

        assert metrics.total_translations == 1
        assert metrics.successful_translations == 1
        assert metrics.failed_translations == 0
        assert metrics.total_duration_ms == 1.5
        assert metrics.translations_by_tool["read_file"] == 1
        assert len(metrics.durations_by_tool["read_file"]) == 1

    def test_translation_durations_are_bounded(self):
        """Duration samples should be bounded to prevent unbounded memory growth."""
        metrics = TranslationMetrics()
        for _ in range(DEFAULT_DURATION_SAMPLE_LIMIT + 10):
            metrics.record_translation("read_file", 1.0, success=True)

        assert len(metrics.translation_durations) == DEFAULT_DURATION_SAMPLE_LIMIT
        assert (
            len(metrics.durations_by_tool["read_file"]) == DEFAULT_DURATION_SAMPLE_LIMIT
        )

    def test_record_translation_failure(self):
        """Test recording a failed translation."""
        metrics = TranslationMetrics()
        metrics.record_translation("invalid_tool", 2.0, success=False)

        assert metrics.total_translations == 1
        assert metrics.successful_translations == 0
        assert metrics.failed_translations == 1

    def test_multiple_translations_same_tool(self):
        """Test recording multiple translations for the same tool."""
        metrics = TranslationMetrics()
        metrics.record_translation("read_file", 1.0, success=True)
        metrics.record_translation("read_file", 2.0, success=True)
        metrics.record_translation("read_file", 3.0, success=True)

        assert metrics.total_translations == 3
        assert metrics.translations_by_tool["read_file"] == 3
        assert len(metrics.durations_by_tool["read_file"]) == 3

    def test_multiple_translations_different_tools(self):
        """Test recording translations for different tools."""
        metrics = TranslationMetrics()
        metrics.record_translation("read_file", 1.0, success=True)
        metrics.record_translation("list_files", 2.0, success=True)
        metrics.record_translation("execute_command", 3.0, success=True)

        assert metrics.total_translations == 3
        assert metrics.translations_by_tool["read_file"] == 1
        assert metrics.translations_by_tool["list_files"] == 1
        assert metrics.translations_by_tool["execute_command"] == 1

    def test_get_average_duration_overall(self):
        """Test calculating overall average translation duration."""
        metrics = TranslationMetrics()
        metrics.record_translation("read_file", 1.0, success=True)
        metrics.record_translation("list_files", 2.0, success=True)
        metrics.record_translation("execute_command", 3.0, success=True)

        avg = metrics.get_average_duration()
        assert avg == 2.0  # (1 + 2 + 3) / 3

    def test_get_average_duration_by_tool(self):
        """Test calculating average duration for specific tool."""
        metrics = TranslationMetrics()
        metrics.record_translation("read_file", 1.0, success=True)
        metrics.record_translation("read_file", 3.0, success=True)
        metrics.record_translation("list_files", 10.0, success=True)

        avg_read = metrics.get_average_duration("read_file")
        avg_list = metrics.get_average_duration("list_files")

        assert avg_read == 2.0  # (1 + 3) / 2
        assert avg_list == 10.0

    def test_get_average_duration_nonexistent_tool(self):
        """Test average duration for tool with no translations."""
        metrics = TranslationMetrics()
        avg = metrics.get_average_duration("nonexistent_tool")
        assert avg == 0.0


class TestErrorMetrics:
    """Test error metrics tracking."""

    def test_record_error_with_code(self):
        """Test recording an error with error code."""
        metrics = ErrorMetrics()
        metrics.record_error("COMPAT_E001", tool_name="read_file")

        assert metrics.total_errors == 1
        assert metrics.errors_by_code["COMPAT_E001"] == 1
        assert metrics.errors_by_tool["read_file"] == 1

    def test_record_error_without_tool(self):
        """Test recording an error without tool name."""
        metrics = ErrorMetrics()
        metrics.record_error("COMPAT_E002")

        assert metrics.total_errors == 1
        assert metrics.errors_by_code["COMPAT_E002"] == 1
        assert len(metrics.errors_by_tool) == 0

    def test_multiple_errors_same_code(self):
        """Test recording multiple errors with same code."""
        metrics = ErrorMetrics()
        metrics.record_error("COMPAT_E001", tool_name="read_file")
        metrics.record_error("COMPAT_E001", tool_name="list_files")
        metrics.record_error("COMPAT_E001", tool_name="read_file")

        assert metrics.total_errors == 3
        assert metrics.errors_by_code["COMPAT_E001"] == 3
        assert metrics.errors_by_tool["read_file"] == 2
        assert metrics.errors_by_tool["list_files"] == 1

    def test_multiple_errors_different_codes(self):
        """Test recording errors with different codes."""
        metrics = ErrorMetrics()
        metrics.record_error("COMPAT_E001", tool_name="read_file")
        metrics.record_error("COMPAT_E002", tool_name="list_files")
        metrics.record_error("COMPAT_E003", tool_name="execute_command")

        assert metrics.total_errors == 3
        assert metrics.errors_by_code["COMPAT_E001"] == 1
        assert metrics.errors_by_code["COMPAT_E002"] == 1
        assert metrics.errors_by_code["COMPAT_E003"] == 1


class TestCompatibilityTelemetry:
    """Test the main telemetry collector."""

    def test_initialization(self):
        """Test telemetry initialization."""
        telemetry = CompatibilityTelemetry()

        assert telemetry.is_enabled() is True
        assert telemetry.detection_metrics.total_detections == 0
        assert telemetry.translation_metrics.total_translations == 0
        assert telemetry.error_metrics.total_errors == 0

    def test_enable_disable(self):
        """Test enabling and disabling telemetry."""
        telemetry = CompatibilityTelemetry()

        assert telemetry.is_enabled() is True

        telemetry.disable()
        assert telemetry.is_enabled() is False

        telemetry.enable()
        assert telemetry.is_enabled() is True

    def test_log_detection_event(self):
        """Test logging a detection event."""
        telemetry = CompatibilityTelemetry()

        telemetry.log_detection_event(
            session_id="test_session",
            is_kilocode=True,
            detection_method="metadata",
            confidence=1.0,
            duration_ms=2.5,
            agent_string="kilocode",
        )

        assert telemetry.detection_metrics.total_detections == 1
        assert telemetry.detection_metrics.metadata_detections == 1

    def test_log_detection_event_when_disabled(self):
        """Test that detection events are not logged when disabled."""
        telemetry = CompatibilityTelemetry()
        telemetry.disable()

        telemetry.log_detection_event(
            session_id="test_session",
            is_kilocode=True,
            detection_method="metadata",
            confidence=1.0,
            duration_ms=2.5,
        )

        # Metrics should not be recorded when disabled
        assert telemetry.detection_metrics.total_detections == 0

    def test_log_translation_event(self):
        """Test logging a translation event."""
        telemetry = CompatibilityTelemetry()

        telemetry.log_translation_event(
            session_id="test_session",
            tool_name="read_file",
            original_xml="<read_file>test.py</read_file>",
            translated_tool="read_file",
            execution_mode="codex",
            duration_ms=1.5,
            success=True,
        )

        assert telemetry.translation_metrics.total_translations == 1
        assert telemetry.translation_metrics.successful_translations == 1
        assert telemetry.translation_metrics.translations_by_tool["read_file"] == 1

    def test_log_translation_event_when_disabled(self):
        """Test that translation events are not logged when disabled."""
        telemetry = CompatibilityTelemetry()
        telemetry.disable()

        telemetry.log_translation_event(
            session_id="test_session",
            tool_name="read_file",
            original_xml="<read_file>test.py</read_file>",
            translated_tool="read_file",
            execution_mode="codex",
            duration_ms=1.5,
            success=True,
        )

        assert telemetry.translation_metrics.total_translations == 0

    def test_log_error_event(self):
        """Test logging an error event."""
        telemetry = CompatibilityTelemetry()

        telemetry.log_error_event(
            session_id="test_session",
            error_code="COMPAT_E001",
            tool_name="read_file",
            error_message="Test error",
            original_xml="<read_file>test.py</read_file>",
        )

        assert telemetry.error_metrics.total_errors == 1
        assert telemetry.error_metrics.errors_by_code["COMPAT_E001"] == 1
        assert telemetry.error_metrics.errors_by_tool["read_file"] == 1

    def test_log_error_event_when_disabled(self):
        """Test that error events are not logged when disabled."""
        telemetry = CompatibilityTelemetry()
        telemetry.disable()

        telemetry.log_error_event(
            session_id="test_session",
            error_code="COMPAT_E001",
            tool_name="read_file",
            error_message="Test error",
        )

        assert telemetry.error_metrics.total_errors == 0

    def test_get_metrics_summary(self):
        """Test getting a metrics summary."""
        telemetry = CompatibilityTelemetry()

        # Log some events
        telemetry.log_detection_event(
            session_id="test",
            is_kilocode=True,
            detection_method="metadata",
            confidence=1.0,
            duration_ms=2.0,
        )
        telemetry.log_detection_event(
            session_id="test",
            is_kilocode=True,
            detection_method="cached",
            confidence=1.0,
            duration_ms=0.1,
        )
        telemetry.log_translation_event(
            session_id="test",
            tool_name="read_file",
            original_xml="<read_file>test.py</read_file>",
            translated_tool="read_file",
            execution_mode="codex",
            duration_ms=1.5,
            success=True,
        )
        telemetry.log_error_event(
            session_id="test",
            error_code="COMPAT_E001",
            tool_name="read_file",
            error_message="Test error",
        )

        summary = telemetry.get_metrics_summary()

        # Check detection metrics
        assert summary["detection"]["total"] == 2
        assert summary["detection"]["by_method"]["metadata"] == 1
        assert summary["detection"]["cache"]["hits"] == 1
        assert summary["detection"]["cache"]["misses"] == 1
        assert summary["detection"]["cache"]["hit_rate"] == 0.5

        # Check translation metrics
        assert summary["translation"]["total"] == 1
        assert summary["translation"]["successful"] == 1
        assert summary["translation"]["failed"] == 0
        assert summary["translation"]["success_rate"] == 1.0
        assert "read_file" in summary["translation"]["by_tool"]

        # Check error metrics
        assert summary["errors"]["total"] == 1
        assert summary["errors"]["by_code"]["COMPAT_E001"] == 1
        assert summary["errors"]["by_tool"]["read_file"] == 1

    def test_reset_metrics(self):
        """Test resetting all metrics."""
        telemetry = CompatibilityTelemetry()

        # Log some events
        telemetry.log_detection_event(
            session_id="test",
            is_kilocode=True,
            detection_method="metadata",
            confidence=1.0,
            duration_ms=2.0,
        )
        telemetry.log_translation_event(
            session_id="test",
            tool_name="read_file",
            original_xml="<read_file>test.py</read_file>",
            translated_tool="read_file",
            execution_mode="codex",
            duration_ms=1.5,
            success=True,
        )

        # Verify metrics were recorded
        assert telemetry.detection_metrics.total_detections == 1
        assert telemetry.translation_metrics.total_translations == 1

        # Reset metrics
        telemetry.reset_metrics()

        # Verify metrics are cleared
        assert telemetry.detection_metrics.total_detections == 0
        assert telemetry.translation_metrics.total_translations == 0
        assert telemetry.error_metrics.total_errors == 0


class TestGlobalTelemetryInstance:
    """Test the global telemetry instance."""

    def test_get_telemetry_singleton(self):
        """Test that get_telemetry returns a singleton instance."""
        # Reset first to ensure clean state
        reset_telemetry()

        telemetry1 = get_telemetry()
        telemetry2 = get_telemetry()

        assert telemetry1 is telemetry2

    def test_reset_telemetry(self):
        """Test resetting the global telemetry instance."""
        telemetry1 = get_telemetry()
        telemetry1.log_detection_event(
            session_id="test",
            is_kilocode=True,
            detection_method="metadata",
            confidence=1.0,
            duration_ms=2.0,
        )

        # Reset the global instance
        reset_telemetry()

        # Get new instance
        telemetry2 = get_telemetry()

        # Should be a new instance with clean metrics
        assert telemetry2 is not telemetry1
        assert telemetry2.detection_metrics.total_detections == 0


class TestTelemetryIntegration:
    """Test telemetry integration scenarios."""

    def test_complete_workflow_metrics(self):
        """Test metrics for a complete detection and translation workflow."""
        telemetry = CompatibilityTelemetry()

        # Simulate detection
        telemetry.log_detection_event(
            session_id="workflow_test",
            is_kilocode=True,
            detection_method="metadata",
            confidence=1.0,
            duration_ms=2.5,
            agent_string="kilocode",
        )

        # Simulate multiple translations
        telemetry.log_translation_event(
            session_id="workflow_test",
            tool_name="read_file",
            original_xml="<read_file>test.py</read_file>",
            translated_tool="read_file",
            execution_mode="codex",
            duration_ms=1.5,
            success=True,
        )
        telemetry.log_translation_event(
            session_id="workflow_test",
            tool_name="execute_command",
            original_xml="<execute_command>ls</execute_command>",
            translated_tool="shell",
            execution_mode="codex",
            duration_ms=2.0,
            success=True,
        )

        # Simulate an error
        telemetry.log_error_event(
            session_id="workflow_test",
            error_code="COMPAT_E003",
            tool_name="invalid_tool",
            error_message="Parameter validation failed",
        )

        # Get summary
        summary = telemetry.get_metrics_summary()

        assert summary["detection"]["total"] == 1
        assert summary["translation"]["total"] == 2
        assert summary["translation"]["successful"] == 2
        assert summary["errors"]["total"] == 1

    def test_cache_hit_rate_calculation(self):
        """Test cache hit rate calculation with mixed hits and misses."""
        telemetry = CompatibilityTelemetry()

        # First detection (cache miss)
        telemetry.log_detection_event(
            session_id="test",
            is_kilocode=True,
            detection_method="metadata",
            confidence=1.0,
            duration_ms=2.0,
        )

        # Cache hits
        for _ in range(3):
            telemetry.log_detection_event(
                session_id="test",
                is_kilocode=True,
                detection_method="cached",
                confidence=1.0,
                duration_ms=0.1,
            )

        summary = telemetry.get_metrics_summary()

        assert summary["detection"]["total"] == 4
        assert summary["detection"]["cache"]["hits"] == 3
        assert summary["detection"]["cache"]["misses"] == 1
        assert summary["detection"]["cache"]["hit_rate"] == 0.75

    def test_translation_success_rate_calculation(self):
        """Test translation success rate with mixed successes and failures."""
        telemetry = CompatibilityTelemetry()

        # Successful translations
        for _ in range(7):
            telemetry.log_translation_event(
                session_id="test",
                tool_name="read_file",
                original_xml="<read_file>test.py</read_file>",
                translated_tool="read_file",
                execution_mode="codex",
                duration_ms=1.5,
                success=True,
            )

        # Failed translations
        for _ in range(3):
            telemetry.log_translation_event(
                session_id="test",
                tool_name="invalid_tool",
                original_xml="<invalid_tool>test</invalid_tool>",
                translated_tool=None,
                execution_mode="codex",
                duration_ms=1.0,
                success=False,
            )

        summary = telemetry.get_metrics_summary()

        assert summary["translation"]["total"] == 10
        assert summary["translation"]["successful"] == 7
        assert summary["translation"]["failed"] == 3
        assert summary["translation"]["success_rate"] == 0.7
