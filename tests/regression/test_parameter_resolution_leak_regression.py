"""Regression test for ParameterResolution memory leak fix.

This test verifies that ParameterResolution._history is properly bounded
and that repeated calls to record() replace previous entries instead of
accumulating them.
"""

import pytest

from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestParameterResolutionLeakRegression:
    """Regression tests for ParameterResolution memory leak fix."""

    @pytest.fixture
    def resolution(self):
        """Create ParameterResolution instance."""
        return ParameterResolution()

    def test_repeated_record_calls_replace_previous_entries(
        self, resolution: ParameterResolution
    ) -> None:
        """Test that repeated record() calls replace previous entries."""
        parameter_name = "test.parameter.temperature"

        # Record the same parameter multiple times
        num_calls = 1000
        for i in range(num_calls):
            resolution.record(
                name=parameter_name,
                value=0.5 + (i * 0.001),
                source=ParameterSource.CONFIG_FILE,
                origin=f"config_file_{i}.yaml",
            )

        # Should only have one entry (latest replaces previous)
        entries = resolution._history.get(parameter_name)
        assert entries is not None, "Parameter should be in history"
        # Since record() replaces entries, _history[name] should be a single record
        # not a list
        assert isinstance(entries, object), "History entry should be a single record"

        # Verify only one entry exists for this parameter
        history_size = len(resolution._history)
        assert history_size == 1, (
            f"Expected 1 entry in history, got {history_size}. "
            "Repeated record() calls should replace previous entries."
        )

    def test_history_bounded_by_max_size(self, resolution: ParameterResolution) -> None:
        """Test that _history is bounded by _MAX_HISTORY_SIZE."""
        from src.core.config.parameter_resolution import ParameterResolution

        max_size = ParameterResolution._MAX_HISTORY_SIZE

        # Record many unique parameters (more than max size)
        num_parameters = max_size + 1000
        for i in range(num_parameters):
            parameter_name = f"test.parameter.{i}"
            resolution.record(
                name=parameter_name,
                value=i,
                source=ParameterSource.CONFIG_FILE,
                origin=f"config_{i}.yaml",
            )

        # History should not exceed max size
        history_size = len(resolution._history)
        assert history_size <= max_size, (
            f"History size ({history_size}) exceeded max size ({max_size}). "
            "Oldest entries should be evicted."
        )

    def test_build_report_uses_latest_entry(self, resolution: ParameterResolution) -> None:
        """Test that build_report() uses the latest entry."""
        parameter_name = "test.parameter.temperature"

        # Record multiple values
        values = [0.5, 0.6, 0.7, 0.8]
        for i, value in enumerate(values):
            resolution.record(
                name=parameter_name,
                value=value,
                source=ParameterSource.CONFIG_FILE,
                origin=f"config_{i}.yaml",
            )

        # Build report
        dummy_config = {"test": {"parameter": {"temperature": values[-1]}}}
        report = resolution.build_report(dummy_config)

        # Find the parameter in report
        param_entry = None
        for param in report:
            if param.name == parameter_name:
                param_entry = param
                break

        assert param_entry is not None, "Parameter should be in report"
        assert param_entry.value == values[-1], (
            f"Expected latest value ({values[-1]}), got {param_entry.value}. "
            "build_report() should use the latest entry."
        )

    def test_history_evicts_oldest_when_full(self, resolution: ParameterResolution) -> None:
        """Test that oldest entries are evicted when history is full."""
        from src.core.config.parameter_resolution import ParameterResolution

        max_size = ParameterResolution._MAX_HISTORY_SIZE

        # Fill history to max size
        for i in range(max_size):
            parameter_name = f"old.parameter.{i}"
            resolution.record(
                name=parameter_name,
                value=i,
                source=ParameterSource.CONFIG_FILE,
            )

        # Verify history is at max size
        assert len(resolution._history) == max_size

        # Add more parameters - should evict oldest
        oldest_param = "old.parameter.0"
        assert oldest_param in resolution._history, "Oldest parameter should be in history"

        # Add new parameter beyond max size
        resolution.record(
            name="new.parameter.beyond.max",
            value=9999,
            source=ParameterSource.CONFIG_FILE,
        )

        # Oldest parameter should be evicted
        assert oldest_param not in resolution._history, (
            "Oldest parameter should be evicted when history exceeds max size."
        )
        assert len(resolution._history) <= max_size, (
            f"History size ({len(resolution._history)}) should not exceed max size ({max_size})"
        )

    def test_same_parameter_multiple_sources(self, resolution: ParameterResolution) -> None:
        """Test that recording same parameter from different sources replaces entry."""
        parameter_name = "test.parameter.temperature"

        # Record from different sources
        resolution.record(
            name=parameter_name,
            value=0.5,
            source=ParameterSource.CONFIG_FILE,
            origin="config1.yaml",
        )
        resolution.record(
            name=parameter_name,
            value=0.6,
            source=ParameterSource.ENVIRONMENT,
            origin="env_var",
        )
        resolution.record(
            name=parameter_name,
            value=0.7,
            source=ParameterSource.CONFIG_FILE,
            origin="config2.yaml",
        )

        # Should only have one entry (latest replaces previous)
        history_size = len(resolution._history)
        assert history_size == 1, (
            f"Expected 1 entry in history, got {history_size}. "
            "Recording same parameter from different sources should replace entry."
        )

        # Latest entry should be from CONFIG_FILE with value 0.7
        record = resolution._history.get(parameter_name)
        assert record is not None
        assert record.value == 0.7, "Latest value should be 0.7"
        assert record.source == ParameterSource.CONFIG_FILE, "Latest source should be CONFIG_FILE"
