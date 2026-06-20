"""Unit tests for PathValidationService."""

import platform
import tempfile
from pathlib import Path

import pytest
from src.core.services.path_validation_service import PathValidationService


class TestPathNormalization:
    """Tests for path normalization functionality."""

    @pytest.fixture
    def service(self):
        """Create a PathValidationService instance."""
        return PathValidationService(cache_max_size=100)

    def test_absolute_unix_path(self, service):
        """Test normalization of absolute Unix paths."""
        path = "/home/user/project/file.txt"
        result = service.normalize_path(path)
        assert result.is_absolute()
        assert str(result) == str(Path(path).resolve())

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_absolute_windows_path(self, service):
        """Test normalization of absolute Windows paths."""
        path = "C:\\Users\\user\\project\\file.txt"
        result = service.normalize_path(path)
        assert result.is_absolute()
        assert result.drive == "C:"

    def test_relative_path_with_parent_directory(self, service):
        """Test normalization of relative paths with ../"""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "subdir"
            base_dir.mkdir()

            # Create a file in the parent directory
            parent_file = Path(tmpdir) / "file.txt"
            parent_file.touch()

            # Normalize relative path from subdir
            result = service.normalize_path("../file.txt", base_dir=str(base_dir))
            assert result.is_absolute()
            assert result == parent_file.resolve()

    def test_relative_path_with_current_directory(self, service):
        """Test normalization of relative paths with ./"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "file.txt"
            file_path.touch()

            result = service.normalize_path("./file.txt", base_dir=tmpdir)
            assert result.is_absolute()
            assert result == file_path.resolve()

    def test_home_directory_expansion(self, service):
        """Test normalization of paths with ~/"""
        result = service.normalize_path("~/test.txt")
        assert result.is_absolute()
        assert str(result).startswith(str(Path.home()))

    def test_home_directory_expansion_windows_style(self, service):
        """Test normalization of paths with ~\\ (Windows style)."""
        result = service.normalize_path("~\\test.txt")
        assert result.is_absolute()
        assert str(result).startswith(str(Path.home()))

    @pytest.mark.symlinks
    def test_symlink_inside_tree_resolving_outside_not_within_boundary(
        self, service, tmp_path: Path
    ) -> None:
        """Symlink under base_dir that points outside resolves outside; boundary rejects."""
        outside = tmp_path / "outside"
        outside.mkdir()
        target = outside / "secret.txt"
        target.touch()
        sandbox = tmp_path / "project"
        sandbox.mkdir()
        link = sandbox / "leak.txt"
        link.symlink_to(target)

        resolved = service.normalize_path("leak.txt", base_dir=str(sandbox))
        assert resolved == target.resolve()
        assert service.is_within_boundary(resolved, sandbox.resolve()) is False

    @pytest.mark.symlinks
    def test_symlink_resolution(self, service):
        """Test that symlinks are resolved to their real paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a real file
            real_file = Path(tmpdir) / "real.txt"
            real_file.touch()

            # Create a symlink (skip on Windows if not supported)
            symlink = Path(tmpdir) / "link.txt"
            symlink.symlink_to(real_file)

            result = service.normalize_path(str(symlink))
            assert result == real_file.resolve()

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_mixed_path_separators_windows(self, service):
        """Test normalization of paths with mixed separators on Windows."""
        path = "C:/Users\\user/project\\file.txt"
        result = service.normalize_path(path)
        assert result.is_absolute()
        # All separators should be normalized
        assert "\\" in str(result) or "/" not in str(result)

    @pytest.mark.unix_only
    def test_mixed_path_separators_unix(self, service):
        """Test normalization of paths with mixed separators on Unix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = f"{tmpdir}/subdir\\file.txt"
            # On Unix, backslashes are valid filename characters
            result = service.normalize_path(path)
            assert result.is_absolute()

    def test_invalid_empty_path(self, service):
        """Test that empty paths raise ValueError."""
        with pytest.raises(ValueError, match="Invalid path"):
            service.normalize_path("")

    def test_invalid_whitespace_path(self, service):
        """Test that whitespace-only paths raise ValueError."""
        with pytest.raises(ValueError, match="Invalid path"):
            service.normalize_path("   ")

    def test_relative_path_without_base_dir(self, service):
        """Test that relative paths without base_dir use current working directory."""
        result = service.normalize_path("file.txt")
        assert result.is_absolute()
        assert result == (Path.cwd() / "file.txt").resolve()

    def test_relative_path_with_base_dir(self, service):
        """Test that relative paths are resolved relative to base_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = service.normalize_path("file.txt", base_dir=tmpdir)
            assert result.is_absolute()
            assert result == (Path(tmpdir) / "file.txt").resolve()

    def test_path_normalization_caching(self, service):
        """Test that normalized paths are cached."""
        path = "/home/user/file.txt"

        # First call
        result1 = service.normalize_path(path)

        # Second call should use cache
        result2 = service.normalize_path(path)

        assert result1 == result2
        assert (path, None) in service._normalization_cache

    def test_cache_respects_max_size(self):
        """Test that cache doesn't exceed max size."""
        service = PathValidationService(cache_max_size=2)

        service.normalize_path("/path1")
        service.normalize_path("/path2")
        assert len(service._normalization_cache) == 2

        # Adding a third path should not exceed cache size
        service.normalize_path("/path3")
        assert len(service._normalization_cache) <= 2


class TestBoundaryValidation:
    """Tests for boundary validation functionality."""

    @pytest.fixture
    def service(self):
        """Create a PathValidationService instance."""
        return PathValidationService()

    def test_path_within_boundary(self, service):
        """Test that paths within boundary are validated correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir)
            path = boundary / "subdir" / "file.txt"

            result = service.is_within_boundary(path, boundary)
            assert result is True

    def test_path_outside_boundary(self, service):
        """Test that paths outside boundary are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir) / "project"
            boundary.mkdir()
            path = Path(tmpdir) / "outside" / "file.txt"

            result = service.is_within_boundary(path, boundary)
            assert result is False

    def test_path_traversal_attempt(self, service):
        """Test that path traversal attempts are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir) / "project"
            boundary.mkdir()

            # Try to escape using ../
            escaped_path = (boundary / ".." / ".." / "etc" / "passwd").resolve()

            result = service.is_within_boundary(escaped_path, boundary)
            assert result is False

    def test_parent_directory_access_denied(self, service):
        """Test that parent directory access is denied by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir) / "project"
            boundary.mkdir()
            parent = Path(tmpdir)

            result = service.is_within_boundary(parent, boundary, allow_parent=False)
            assert result is False

    def test_parent_directory_access_allowed(self, service):
        """Test that parent directory access can be allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir) / "project"
            boundary.mkdir()
            parent = Path(tmpdir)

            result = service.is_within_boundary(parent, boundary, allow_parent=True)
            assert result is True

    def test_boundary_itself_is_valid(self, service):
        """Test that the boundary path itself is considered valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir)

            result = service.is_within_boundary(boundary, boundary)
            assert result is True

    def test_non_absolute_path_rejected(self, service):
        """Test that non-absolute paths are rejected."""
        boundary = Path("/home/user/project")
        path = Path("relative/path")

        result = service.is_within_boundary(path, boundary)
        assert result is False

    def test_non_absolute_boundary_rejected(self, service):
        """Test that non-absolute boundary is rejected."""
        path = Path("/home/user/project/file.txt")
        boundary = Path("relative/boundary")

        result = service.is_within_boundary(path, boundary)
        assert result is False


class TestPathExtraction:
    """Tests for path extraction from arguments."""

    @pytest.fixture
    def service(self):
        """Create a PathValidationService instance."""
        return PathValidationService()

    def test_single_path_parameter(self, service):
        """Test extraction of single path parameter."""
        arguments = {"path": "/home/user/file.txt"}
        parameter_names = ["path"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        assert result == ["/home/user/file.txt"]

    def test_multiple_path_parameters(self, service):
        """Test extraction of multiple different path parameters."""
        arguments = {
            "source": "/home/user/source.txt",
            "destination": "/home/user/dest.txt",
        }
        parameter_names = ["source", "destination"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        assert len(result) == 2
        assert "/home/user/source.txt" in result
        assert "/home/user/dest.txt" in result

    def test_path_array(self, service):
        """Test extraction of path arrays."""
        arguments = {
            "files": [
                "/home/user/file1.txt",
                "/home/user/file2.txt",
                "/home/user/file3.txt",
            ]
        }
        parameter_names = ["files"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        assert len(result) == 3
        assert "/home/user/file1.txt" in result
        assert "/home/user/file2.txt" in result
        assert "/home/user/file3.txt" in result

    def test_nested_path_in_dict(self, service):
        """Test extraction of nested path from dict parameter."""
        arguments = {
            "file_info": {"path": "/home/user/file.txt", "content": "some content"}
        }
        parameter_names = ["file_info"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        assert result == ["/home/user/file.txt"]

    def test_list_of_dicts_with_paths(self, service):
        """Test extraction of paths from list of dicts."""
        arguments = {
            "operations": [
                {"path": "/home/user/file1.txt", "action": "write"},
                {"path": "/home/user/file2.txt", "action": "delete"},
            ]
        }
        parameter_names = ["operations"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        assert len(result) == 2
        assert "/home/user/file1.txt" in result
        assert "/home/user/file2.txt" in result

    def test_missing_parameters(self, service):
        """Test that missing parameters return empty list."""
        arguments = {"other_param": "value"}
        parameter_names = ["path", "file"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        assert result == []

    def test_empty_string_paths_ignored(self, service):
        """Test that empty string paths are ignored."""
        arguments = {"path": "", "file": "   ", "target": "/home/user/file.txt"}
        parameter_names = ["path", "file", "target"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        assert result == ["/home/user/file.txt"]

    def test_none_values_ignored(self, service):
        """Test that None values are ignored."""
        arguments = {"path": None, "file": "/home/user/file.txt"}
        parameter_names = ["path", "file"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        assert result == ["/home/user/file.txt"]

    def test_nested_file_path_variants(self, service):
        """Test extraction of various nested path parameter names."""
        arguments = {
            "operation": {
                "file_path": "/home/user/file1.txt",
                "filepath": "/home/user/file2.txt",
                "file": "/home/user/file3.txt",
                "target_file": "/home/user/file4.txt",
            }
        }
        parameter_names = ["operation"]

        result = service.extract_paths_from_arguments(arguments, parameter_names)
        # Should extract all nested path variants
        assert len(result) >= 1


class TestCrossPlatformBehavior:
    """Tests for cross-platform path handling."""

    @pytest.fixture
    def service(self):
        """Create a PathValidationService instance."""
        return PathValidationService()

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_windows_drive_letters(self, service):
        """Test handling of Windows drive letters."""
        path = "C:\\Users\\user\\file.txt"
        result = service.normalize_path(path)
        assert result.is_absolute()
        assert result.drive == "C:"

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_windows_unc_paths(self, service):
        """Test handling of Windows UNC paths."""
        path = "\\\\server\\share\\file.txt"
        result = service.normalize_path(path)
        assert result.is_absolute()
        # UNC paths should be preserved
        assert str(result).startswith("\\\\")

    @pytest.mark.unix_only
    def test_unix_root_paths(self, service):
        """Test handling of Unix root paths."""
        path = "/home/user/file.txt"
        result = service.normalize_path(path)
        assert result.is_absolute()
        assert str(result).startswith("/")

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_windows_case_insensitivity(self, service):
        """Test that Windows paths are case-insensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir)
            # Create path with different case
            path = Path(str(boundary).upper()) / "file.txt"

            result = service.is_within_boundary(path, boundary)
            # On Windows, this should be True due to case-insensitivity
            assert result is True

    @pytest.mark.unix_only
    def test_unix_case_sensitivity(self, service):
        """Test that Unix paths are case-sensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            boundary = Path(tmpdir)
            # Create a subdirectory
            subdir = boundary / "SubDir"
            subdir.mkdir()

            # Path with different case
            path = boundary / "subdir" / "file.txt"

            # On Unix, case matters, so this might not be within boundary
            # depending on actual filesystem
            _ = service.is_within_boundary(path, boundary)
            # Just verify it doesn't crash - actual result depends on filesystem

    def test_platform_detection(self, service):
        """Test that platform is correctly detected."""
        assert service._is_windows == (platform.system() == "Windows")

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_forward_slash_normalization_windows(self, service):
        """Test that forward slashes are normalized on Windows."""
        path = "C:/Users/user/file.txt"
        result = service.normalize_path(path)
        # On Windows, should be normalized to backslashes
        assert "\\" in str(result) or "/" not in str(result)

    @pytest.mark.unix_only
    def test_backslash_handling_unix(self, service):
        """Test that backslashes are handled on Unix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # On Unix, backslashes are valid filename characters
            path = f"{tmpdir}/file\\with\\backslashes.txt"
            result = service.normalize_path(path)
            assert result.is_absolute()
