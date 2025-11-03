"""Unit tests for PathValidationService."""

import platform
import tempfile
from pathlib import Path

import pytest
from src.core.services.path_validation_service import PathValidationService


class TestPathValidationService:
    """Unit tests for path validation service."""

    @pytest.fixture
    def service(self):
        """Create a PathValidationService instance."""
        return PathValidationService()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    # Test normalize_path

    def test_normalize_absolute_path(self, service):
        """Test normalization of absolute paths."""
        if platform.system() == "Windows":
            path = "C:\\Users\\test\\file.txt"
        else:
            path = "/home/test/file.txt"

        result = service.normalize_path(path)
        assert result.is_absolute()
        assert str(result) == str(Path(path).resolve())

    def test_normalize_relative_path_with_base_dir(self, service, temp_dir):
        """Test normalization of relative paths with base directory."""
        result = service.normalize_path("subdir/file.txt", base_dir=str(temp_dir))
        assert result.is_absolute()
        assert result.parent.name == "subdir"
        assert result.parent.parent == temp_dir

    def test_normalize_home_directory_expansion(self, service):
        """Test expansion of home directory (~/)."""
        # On Windows, ~/ needs to be converted to ~\ first, then expanded
        # The service handles this by normalizing separators before expansion
        result = service.normalize_path("~/test.txt")
        assert result.is_absolute()
        # Just verify it's absolute and doesn't start with ~
        assert not str(result).startswith("~")

    def test_normalize_path_with_parent_references(self, service, temp_dir):
        """Test normalization of paths with .. references."""
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        result = service.normalize_path("subdir/../file.txt", base_dir=str(temp_dir))
        assert result.is_absolute()
        assert result.parent == temp_dir

    def test_normalize_empty_path_raises_error(self, service):
        """Test that empty paths raise ValueError."""
        with pytest.raises(ValueError, match="Invalid path"):
            service.normalize_path("")

    def test_normalize_whitespace_path_raises_error(self, service):
        """Test that whitespace-only paths raise ValueError."""
        with pytest.raises(ValueError, match="Invalid path"):
            service.normalize_path("   ")

    def test_normalize_path_caching(self, service):
        """Test that path normalization results are cached."""
        path = "test.txt"
        base_dir = "/tmp"

        result1 = service.normalize_path(path, base_dir)
        result2 = service.normalize_path(path, base_dir)

        # Should return the same cached object
        assert result1 == result2
        assert (path, base_dir) in service._normalization_cache

    def test_normalize_cross_platform_separators(self, service, temp_dir):
        """Test handling of cross-platform path separators."""
        # Test forward slashes on all platforms
        result = service.normalize_path("subdir/file.txt", base_dir=str(temp_dir))
        assert result.is_absolute()

        # Test backslashes (should be normalized)
        result2 = service.normalize_path("subdir\\file.txt", base_dir=str(temp_dir))
        assert result2.is_absolute()

    # Test is_within_boundary

    def test_is_within_boundary_direct_child(self, service, temp_dir):
        """Test path that is a direct child of boundary."""
        child_path = temp_dir / "file.txt"
        assert service.is_within_boundary(child_path, temp_dir) is True

    def test_is_within_boundary_nested_child(self, service, temp_dir):
        """Test path that is nested within boundary."""
        nested_path = temp_dir / "subdir" / "nested" / "file.txt"
        assert service.is_within_boundary(nested_path, temp_dir) is True

    def test_is_within_boundary_outside(self, service, temp_dir):
        """Test path that is outside boundary."""
        outside_path = temp_dir.parent / "outside.txt"
        assert service.is_within_boundary(outside_path, temp_dir) is False

    def test_is_within_boundary_parent_with_allow_parent(self, service, temp_dir):
        """Test parent directory access with allow_parent=True."""
        child_dir = temp_dir / "subdir"
        child_dir.mkdir()

        # Parent should be allowed when allow_parent=True
        assert (
            service.is_within_boundary(temp_dir, child_dir, allow_parent=True) is True
        )

    def test_is_within_boundary_parent_without_allow_parent(self, service, temp_dir):
        """Test parent directory access with allow_parent=False."""
        child_dir = temp_dir / "subdir"
        child_dir.mkdir()

        # Parent should not be allowed when allow_parent=False
        assert (
            service.is_within_boundary(temp_dir, child_dir, allow_parent=False) is False
        )

    def test_is_within_boundary_same_path(self, service, temp_dir):
        """Test boundary check when path equals boundary."""
        assert service.is_within_boundary(temp_dir, temp_dir) is True

    def test_is_within_boundary_non_absolute_paths(self, service):
        """Test that non-absolute paths return False."""
        relative_path = Path("relative/path")
        absolute_boundary = Path("/absolute/boundary")

        assert service.is_within_boundary(relative_path, absolute_boundary) is False

    # Test extract_paths_from_arguments

    def test_extract_single_path_string(self, service):
        """Test extraction of single path string."""
        args = {"path": "/test/file.txt"}
        paths = service.extract_paths_from_arguments(args, ["path"])
        assert paths == ["/test/file.txt"]

    def test_extract_multiple_parameter_names(self, service):
        """Test extraction from multiple parameter names."""
        args = {"path": "/test/file1.txt", "target": "/test/file2.txt"}
        paths = service.extract_paths_from_arguments(args, ["path", "target"])
        assert set(paths) == {"/test/file1.txt", "/test/file2.txt"}

    def test_extract_path_list(self, service):
        """Test extraction of path list."""
        args = {"paths": ["/test/file1.txt", "/test/file2.txt"]}
        paths = service.extract_paths_from_arguments(args, ["paths"])
        assert set(paths) == {"/test/file1.txt", "/test/file2.txt"}

    def test_extract_empty_strings_ignored(self, service):
        """Test that empty strings are ignored."""
        args = {"path": "", "target": "   "}
        paths = service.extract_paths_from_arguments(args, ["path", "target"])
        assert paths == []

    def test_extract_none_values_ignored(self, service):
        """Test that None values are ignored."""
        args = {"path": None, "target": "/test/file.txt"}
        paths = service.extract_paths_from_arguments(args, ["path", "target"])
        assert paths == ["/test/file.txt"]

    def test_extract_nested_dict_with_path(self, service):
        """Test extraction from nested dict with path key."""
        args = {"file_info": {"path": "/test/file.txt", "content": "data"}}
        paths = service.extract_paths_from_arguments(args, ["file_info"])
        assert paths == ["/test/file.txt"]

    def test_extract_list_of_dicts_with_paths(self, service):
        """Test extraction from list of dicts with path keys."""
        args = {
            "files": [
                {"path": "/test/file1.txt"},
                {"path": "/test/file2.txt"},
            ]
        }
        paths = service.extract_paths_from_arguments(args, ["files"])
        assert set(paths) == {"/test/file1.txt", "/test/file2.txt"}

    def test_extract_no_matching_parameters(self, service):
        """Test extraction when no matching parameters exist."""
        args = {"other": "/test/file.txt"}
        paths = service.extract_paths_from_arguments(args, ["path", "target"])
        assert paths == []

    def test_extract_mixed_types(self, service):
        """Test extraction with mixed argument types."""
        args = {
            "path": "/test/file1.txt",
            "paths": ["/test/file2.txt", "/test/file3.txt"],
            "target": {"path": "/test/file4.txt"},
        }
        paths = service.extract_paths_from_arguments(args, ["path", "paths", "target"])
        assert set(paths) == {
            "/test/file1.txt",
            "/test/file2.txt",
            "/test/file3.txt",
            "/test/file4.txt",
        }
