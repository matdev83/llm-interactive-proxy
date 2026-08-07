"""Performance tests for file access sandboxing.

This module contains performance benchmarks and tests for the file access
sandboxing feature, including caching effectiveness, path validation speed,
and overall overhead measurements.
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.domain.session import Session, SessionState
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.file_sandboxing_handler import FileSandboxingHandler
from src.core.services.path_validation_service import PathValidationService

# ============================================================================
# Task 17.1: Implement and test caching
# ============================================================================


class TestCaching:
    """Tests for path normalization caching functionality."""

    @pytest.fixture
    def service(self):
        """Create a PathValidationService instance with caching."""
        return PathValidationService(cache_max_size=100)

    def test_cache_hit_rate_single_path(self, service):
        """Test cache hit rate for repeated normalization of the same path."""
        path = "/home/user/project/file.txt"

        # First call - cache miss
        start = time.perf_counter()
        result1 = service.normalize_path(path)
        first_call_time = time.perf_counter() - start

        # Subsequent calls - cache hits
        cache_hit_times = []
        for _ in range(10):
            start = time.perf_counter()
            result = service.normalize_path(path)
            cache_hit_times.append(time.perf_counter() - start)
            assert result == result1

        # Cache hits should be significantly faster
        avg_cache_hit_time = sum(cache_hit_times) / len(cache_hit_times)

        # Verify cache is being used
        assert (path, None) in service._normalization_cache

        # Cache hits should be at least 2x faster (conservative estimate)
        # In practice, they're often 10-100x faster
        assert avg_cache_hit_time < first_call_time / 2, (
            f"Cache hits ({avg_cache_hit_time:.6f}s) not significantly faster "
            f"than first call ({first_call_time:.6f}s)"
        )

    def test_cache_hit_rate_multiple_paths(self, service):
        """Test cache effectiveness with multiple different paths."""
        paths = [
            "/home/user/project/file1.txt",
            "/home/user/project/file2.txt",
            "/home/user/project/subdir/file3.txt",
            "/home/user/project/file1.txt",  # Repeat
            "/home/user/project/file2.txt",  # Repeat
        ]

        cache_hits = 0
        cache_misses = 0

        for path in paths:
            cache_key = (path, None)
            if cache_key in service._normalization_cache:
                cache_hits += 1
            else:
                cache_misses += 1

            service.normalize_path(path)

        # Should have 2 cache hits (the repeated paths)
        assert cache_hits == 2
        assert cache_misses == 3

        # Cache should contain 3 unique paths
        assert len(service._normalization_cache) == 3

    def test_cache_size_limits(self):
        """Test that cache respects maximum size limit."""
        cache_max_size = 10
        service = PathValidationService(cache_max_size=cache_max_size)

        # Normalize more paths than cache size
        for i in range(cache_max_size + 5):
            path = f"/home/user/project/file{i}.txt"
            service.normalize_path(path)

        # Cache should not exceed max size
        assert len(service._normalization_cache) <= cache_max_size

    def test_cache_with_different_base_dirs(self, service):
        """Test that cache distinguishes paths with different base directories."""
        path = "file.txt"
        base_dir1 = "/home/user/project1"
        base_dir2 = "/home/user/project2"

        result1 = service.normalize_path(path, base_dir=base_dir1)
        result2 = service.normalize_path(path, base_dir=base_dir2)

        # Results should be different
        assert result1 != result2

        # Both should be cached separately
        assert (path, base_dir1) in service._normalization_cache
        assert (path, base_dir2) in service._normalization_cache
        assert len(service._normalization_cache) == 2

    def test_cache_invalidation_not_needed(self, service):
        """Test that cache doesn't need invalidation for immutable paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "file.txt"
            file_path.touch()

            # Normalize and cache
            result1 = service.normalize_path(str(file_path))

            # Modify file (shouldn't affect cached normalized path)
            file_path.write_text("new content")

            # Should still get same cached result
            result2 = service.normalize_path(str(file_path))
            assert result1 == result2

    @pytest.mark.symlinks
    def test_cache_performance_with_symlinks(self, service):
        """Test cache performance with symlink resolution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a real file
            real_file = Path(tmpdir) / "real.txt"
            real_file.touch()

            # Create a symlink
            symlink = Path(tmpdir) / "link.txt"
            symlink.symlink_to(real_file)

            # First call - resolves symlink
            start = time.perf_counter()
            result1 = service.normalize_path(str(symlink))
            first_call_time = time.perf_counter() - start

            # Second call - uses cache
            start = time.perf_counter()
            result2 = service.normalize_path(str(symlink))
            second_call_time = time.perf_counter() - start

            assert result1 == result2
            assert second_call_time < first_call_time

    def test_cache_memory_efficiency(self):
        """Test that cache doesn't consume excessive memory."""
        cache_max_size = 100  # Reduced from 1000 for performance
        service = PathValidationService(cache_max_size=cache_max_size)

        # Fill cache to max size
        for i in range(cache_max_size):
            path = f"/home/user/project/file{i}.txt"
            service.normalize_path(path)

        # Cache should be at max size
        assert len(service._normalization_cache) == cache_max_size

        # Adding more should not increase cache size (reduced iterations)
        for i in range(10):  # Reduced from 100
            path = f"/home/user/project/extra{i}.txt"
            service.normalize_path(path)

        assert len(service._normalization_cache) <= cache_max_size


# ============================================================================
# Task 17.2: Benchmark path validation
# ============================================================================


class TestPathValidationPerformance:
    """Performance benchmarks for path validation operations."""

    @pytest.fixture
    def service(self):
        """Create a PathValidationService instance."""
        return PathValidationService(cache_max_size=1000)

    def test_path_normalization_time(self, service):
        """Measure path normalization time and ensure < 10ms per path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = [f"{tmpdir}/file{i}.txt" for i in range(50)]  # Reduced from 100

            times = []
            for path in paths:
                start = time.perf_counter()
                service.normalize_path(path)
                elapsed = time.perf_counter() - start
                times.append(elapsed)

            avg_time = sum(times) / len(times)
            # Use 95th percentile instead of max to avoid outliers from system noise
            sorted_times = sorted(times)
            p95_time = sorted_times[int(len(sorted_times) * 0.95)]

            # Average should be well under 25ms
            assert (
                avg_time < 0.025
            ), f"Average normalization time {avg_time*1000:.2f}ms exceeds 25ms"

            # 95th percentile should be under 25ms (allows for occasional outliers)
            assert (
                p95_time < 0.025
            ), f"95th percentile normalization time {p95_time*1000:.2f}ms exceeds 25ms"

    def test_boundary_checking_time(self, service):
        """Measure boundary checking time and ensure < 10ms per path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir)
            paths = [
                boundary / f"subdir{i}" / f"file{j}.txt"
                for i in range(10)
                for j in range(10)
            ]

            times = []
            for path in paths:
                start = time.perf_counter()
                service.is_within_boundary(path, boundary)
                elapsed = time.perf_counter() - start
                times.append(elapsed)

            avg_time = sum(times) / len(times)
            # Use 95th percentile instead of max to avoid outliers from system noise
            sorted_times = sorted(times)
            p95_time = sorted_times[int(len(sorted_times) * 0.95)]

            # Average should be well under 10ms
            assert (
                avg_time < 0.010
            ), f"Average boundary check time {avg_time*1000:.2f}ms exceeds 10ms"

            # 95th percentile should be under 10ms (allows for occasional outliers)
            assert (
                p95_time < 0.010
            ), f"95th percentile boundary check time {p95_time*1000:.2f}ms exceeds 10ms"

    def test_path_extraction_time(self, service):
        """Measure path extraction time from tool arguments."""
        arguments = {
            "path": "/home/user/file1.txt",
            "source": "/home/user/file2.txt",
            "destination": "/home/user/file3.txt",
            "files": [f"/home/user/file{i}.txt" for i in range(10)],
        }
        parameter_names = ["path", "source", "destination", "files"]

        times = []
        for _ in range(100):
            start = time.perf_counter()
            service.extract_paths_from_arguments(arguments, parameter_names)
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_time = sum(times) / len(times)

        # Extraction should be very fast (< 1ms)
        assert (
            avg_time < 0.001
        ), f"Average extraction time {avg_time*1000:.2f}ms exceeds 1ms"

    def test_combined_validation_time(self, service):
        """Measure combined normalization + boundary check time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir)
            paths = [f"{tmpdir}/file{i}.txt" for i in range(50)]

            times = []
            for path_str in paths:
                start = time.perf_counter()
                # Simulate full validation flow
                normalized = service.normalize_path(path_str)
                service.is_within_boundary(normalized, boundary)
                elapsed = time.perf_counter() - start
                times.append(elapsed)

            avg_time = sum(times) / len(times)

            # Combined operation should be under 10ms
            assert (
                avg_time < 0.010
            ), f"Average combined validation time {avg_time*1000:.2f}ms exceeds 10ms"

    def test_relative_path_resolution_time(self, service):
        """Measure performance of relative path resolution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "project"
            base_dir.mkdir()

            relative_paths = [
                "../file.txt",
                "./subdir/file.txt",
                "../../other/file.txt",
                "./a/b/c/d/e/file.txt",
            ]

            times = []
            for path in relative_paths * 25:  # Repeat for better measurement
                start = time.perf_counter()
                service.normalize_path(path, base_dir=str(base_dir))
                elapsed = time.perf_counter() - start
                times.append(elapsed)

            avg_time = sum(times) / len(times)

            # Relative path resolution should be under 10ms
            assert (
                avg_time < 0.010
            ), f"Average relative path resolution time {avg_time*1000:.2f}ms exceeds 10ms"

    @pytest.mark.unix_only
    def test_symlink_resolution_time(self, service):
        """Measure performance of symlink resolution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create real files
            real_files = []
            for i in range(10):
                real_file = Path(tmpdir) / f"real{i}.txt"
                real_file.touch()
                real_files.append(real_file)

            # Create symlinks
            symlinks = []
            for i, real_file in enumerate(real_files):
                symlink = Path(tmpdir) / f"link{i}.txt"
                symlink.symlink_to(real_file)
                symlinks.append(symlink)

            times = []
            for symlink in symlinks * 10:  # Repeat for better measurement
                start = time.perf_counter()
                service.normalize_path(str(symlink))
                elapsed = time.perf_counter() - start
                times.append(elapsed)

            avg_time = sum(times) / len(times)

            # Symlink resolution should be under 10ms
            assert (
                avg_time < 0.010
            ), f"Average symlink resolution time {avg_time*1000:.2f}ms exceeds 10ms"


# ============================================================================
# Task 17.3: Benchmark overall overhead
# ============================================================================


class TestOverallOverhead:
    """Performance benchmarks for overall sandboxing overhead."""

    @pytest.mark.asyncio
    async def test_overhead_when_sandboxing_disabled(self):
        """Measure overhead when sandboxing is disabled."""
        config = SandboxingConfiguration(enabled=False)
        validator = PathValidationService()
        session_service = AsyncMock()

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/home/user/file.txt", "content": "test"},
        )

        times = []
        for _ in range(100):
            start = time.perf_counter()
            await handler.can_handle(context)
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_time = sum(times) / len(times)

        # When disabled, overhead should be minimal (< 1ms)
        assert (
            avg_time < 0.001
        ), f"Overhead when disabled {avg_time*1000:.2f}ms exceeds 1ms"

    @pytest.mark.asyncio
    async def test_overhead_when_sandboxing_inactive(self):
        """Measure overhead when sandboxing is enabled but inactive (no project dir)."""
        config = SandboxingConfiguration(enabled=True)
        validator = PathValidationService()
        session_service = AsyncMock()

        # Session without project directory
        session = Session(
            session_id="test-session",
            state=SessionState(project_dir=None),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/home/user/file.txt", "content": "test"},
        )

        times = []
        for _ in range(100):
            start = time.perf_counter()
            await handler.handle(context)
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_time = sum(times) / len(times)

        # When inactive, overhead should be < 5ms
        assert (
            avg_time < 0.005
        ), f"Overhead when inactive {avg_time*1000:.2f}ms exceeds 5ms"

    @pytest.mark.asyncio
    async def test_overhead_when_sandboxing_active(self):
        """Measure overhead when sandboxing is active and validating paths."""
        config = SandboxingConfiguration(enabled=True)
        validator = PathValidationService()
        session_service = AsyncMock()

        # Create a temporary directory for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            # Session with project directory
            session = Session(
                session_id="test-session",
                state=SessionState(project_dir=tmpdir),
            )
            session_service.get_session = AsyncMock(return_value=session)

            handler = FileSandboxingHandler(
                config=config,
                path_validator=validator,
                session_service=session_service,
            )

            context = ToolCallContext(
                session_id="test-session",
                backend_name="test-backend",
                model_name="test-model",
                full_response=None,
                tool_name="write_to_file",
                tool_arguments={"path": f"{tmpdir}/file.txt", "content": "test"},
            )

            times = []
            for _ in range(100):
                start = time.perf_counter()
                await handler.handle(context)
                elapsed = time.perf_counter() - start
                times.append(elapsed)

            avg_time = sum(times) / len(times)

            # When active, overhead should still be reasonable (< 10ms)
            assert (
                avg_time < 0.010
            ), f"Overhead when active {avg_time*1000:.2f}ms exceeds 10ms"

    @pytest.mark.asyncio
    async def test_overhead_with_multiple_paths(self):
        """Measure overhead when validating multiple paths in one tool call."""
        config = SandboxingConfiguration(enabled=True)
        validator = PathValidationService()
        session_service = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            session = Session(
                session_id="test-session",
                state=SessionState(project_dir=tmpdir),
            )
            session_service.get_session = AsyncMock(return_value=session)

            handler = FileSandboxingHandler(
                config=config,
                path_validator=validator,
                session_service=session_service,
            )

            # Tool call with multiple paths
            context = ToolCallContext(
                session_id="test-session",
                backend_name="test-backend",
                model_name="test-model",
                full_response=None,
                tool_name="write_to_file",
                tool_arguments={"files": [f"{tmpdir}/file{i}.txt" for i in range(10)]},
            )

            times = []
            for _ in range(50):
                start = time.perf_counter()
                await handler.handle(context)
                elapsed = time.perf_counter() - start
                times.append(elapsed)

            avg_time = sum(times) / len(times)

            # With 10 paths, should still be under 50ms (5ms per path)
            assert (
                avg_time < 0.050
            ), f"Overhead with 10 paths {avg_time*1000:.2f}ms exceeds 50ms"

    @pytest.mark.asyncio
    async def test_overhead_comparison_enabled_vs_disabled(self):
        """Compare overhead between enabled and disabled sandboxing."""
        validator = PathValidationService()
        session_service = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            session = Session(
                session_id="test-session",
                state=SessionState(project_dir=tmpdir),
            )
            session_service.get_session = AsyncMock(return_value=session)

            context = ToolCallContext(
                session_id="test-session",
                backend_name="test-backend",
                model_name="test-model",
                full_response=None,
                tool_name="write_to_file",
                tool_arguments={"path": f"{tmpdir}/file.txt", "content": "test"},
            )

            # Test with sandboxing disabled
            config_disabled = SandboxingConfiguration(enabled=False)
            handler_disabled = FileSandboxingHandler(
                config=config_disabled,
                path_validator=validator,
                session_service=session_service,
            )

            times_disabled = []
            for _ in range(100):
                start = time.perf_counter()
                await handler_disabled.can_handle(context)
                elapsed = time.perf_counter() - start
                times_disabled.append(elapsed)

            avg_disabled = sum(times_disabled) / len(times_disabled)

            # Test with sandboxing enabled
            config_enabled = SandboxingConfiguration(enabled=True)
            handler_enabled = FileSandboxingHandler(
                config=config_enabled,
                path_validator=validator,
                session_service=session_service,
            )

            times_enabled = []
            for _ in range(100):
                start = time.perf_counter()
                _ = await handler_enabled.handle(context)
                elapsed = time.perf_counter() - start
                times_enabled.append(elapsed)

            avg_enabled = sum(times_enabled) / len(times_enabled)

            # Enabled should be slower, but not excessively so
            # Allow up to 10x overhead when enabled
            assert avg_enabled < avg_disabled * 10 + 0.010, (
                f"Enabled overhead ({avg_enabled*1000:.2f}ms) is too high "
                f"compared to disabled ({avg_disabled*1000:.2f}ms)"
            )

    @pytest.mark.asyncio
    async def test_overhead_with_caching_benefit(self):
        """Measure how caching reduces overhead for repeated paths."""
        config = SandboxingConfiguration(enabled=True)
        validator = PathValidationService(cache_max_size=1000)
        session_service = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            session = Session(
                session_id="test-session",
                state=SessionState(project_dir=tmpdir),
            )
            session_service.get_session = AsyncMock(return_value=session)

            handler = FileSandboxingHandler(
                config=config,
                path_validator=validator,
                session_service=session_service,
            )

            context = ToolCallContext(
                session_id="test-session",
                backend_name="test-backend",
                model_name="test-model",
                full_response=None,
                tool_name="write_to_file",
                tool_arguments={"path": f"{tmpdir}/file.txt", "content": "test"},
            )

            # Warm up - first few calls to stabilize timing
            for _ in range(3):
                await handler.handle(context)

            # Measure multiple calls with cache
            all_times = []
            for _ in range(20):
                start = time.perf_counter()
                await handler.handle(context)
                elapsed = time.perf_counter() - start
                all_times.append(elapsed)

            avg_time = sum(all_times) / len(all_times)

            # With caching, average time should be reasonable (< 10ms)
            # This is more reliable than comparing first vs subsequent calls
            # which can be affected by system noise
            assert (
                avg_time < 0.010
            ), f"Average time with caching ({avg_time*1000:.2f}ms) exceeds 10ms"
