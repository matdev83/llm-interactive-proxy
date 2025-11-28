"""Service for validating and normalizing file paths for sandboxing."""

from __future__ import annotations

import json
import logging
import os
import platform
from pathlib import Path
from typing import Any

from src.core.interfaces.path_validator_interface import IPathValidator


class PathValidationService(IPathValidator):
    """Service for validating and normalizing file paths.

    This service provides path normalization, boundary validation, and path
    extraction capabilities for the file access sandboxing feature. It handles
    cross-platform path formats and implements caching for performance.
    """

    def __init__(self, cache_max_size: int = 1000):
        """Initialize the path validation service.

        Args:
            cache_max_size: Maximum number of normalized paths to cache
        """
        self._logger = logging.getLogger(__name__)
        self._cache_max_size = cache_max_size
        # Cache for normalized paths: (path, base_dir) -> Path
        self._normalization_cache: dict[tuple[str, str | None], Path] = {}

        # Detect operating system for platform-specific handling
        self._is_windows = platform.system() == "Windows"
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(
                f"PathValidationService initialized (platform: {platform.system()}, "
                f"cache_max_size: {cache_max_size})"
            )

    def normalize_path(
        self,
        path: str,
        base_dir: str | None = None,
    ) -> Path:
        """Normalize a path to absolute form with caching.

        Handles:
        - Home directory expansion (~/)
        - Relative paths (../, ./)
        - Symlink resolution
        - Cross-platform path separators
        - Windows drive letters and UNC paths

        Args:
            path: The path to normalize (may be relative, contain ~, .., etc.)
            base_dir: Optional base directory for resolving relative paths

        Returns:
            Normalized absolute Path object

        Raises:
            ValueError: If path is invalid or cannot be normalized
        """
        # Check cache first
        cache_key = (path, base_dir)
        if cache_key in self._normalization_cache:
            return self._normalization_cache[cache_key]

        try:
            # Handle empty or whitespace-only paths
            if not path or not path.strip():
                raise ValueError("Path cannot be empty or whitespace-only")

            # Normalize path separators for cross-platform compatibility FIRST
            # This ensures that Windows-style home paths (~\) work correctly on Unix
            if self._is_windows:
                # On Windows, normalize forward slashes to backslashes
                path = path.replace("/", "\\")
            else:
                # On Unix-like systems, normalize backslashes to forward slashes
                path = path.replace("\\", "/")

            # Handle home directory expansion after path separator normalization
            # Now ~\ will have been converted to ~/ on Unix systems
            if path.startswith("~/"):
                path = os.path.expanduser(path)

            # Convert to Path object
            path_obj = Path(path)

            # Resolve relative paths
            if not path_obj.is_absolute():
                if base_dir:
                    path_obj = Path(base_dir) / path_obj
                else:
                    path_obj = Path.cwd() / path_obj

            # Resolve symlinks and normalize (handles .., ., and symlinks)
            # resolve() returns an absolute path with all symlinks resolved
            normalized = path_obj.resolve()

            # Cache the result if we haven't exceeded the cache size
            if len(self._normalization_cache) < self._cache_max_size:
                self._normalization_cache[cache_key] = normalized

            return normalized

        except (ValueError, OSError, RuntimeError) as e:
            self._logger.error(f"Failed to normalize path '{path}': {e}")
            raise ValueError(f"Invalid path: {path}") from e

    def is_within_boundary(
        self,
        path: Path,
        boundary: Path,
        allow_parent: bool = False,
    ) -> bool:
        """Check if a path is within a boundary directory.

        Uses Path.relative_to() for boundary checking and handles parent
        directory access based on configuration.

        Args:
            path: The normalized absolute path to check
            boundary: The boundary directory path
            allow_parent: Whether to allow parent directories of boundary

        Returns:
            True if path is within boundary, False otherwise
        """
        try:
            # Ensure both paths are absolute and normalized
            if not path.is_absolute() or not boundary.is_absolute():
                self._logger.warning(
                    f"Boundary check requires absolute paths: "
                    f"path={path} (absolute={path.is_absolute()}), "
                    f"boundary={boundary} (absolute={boundary.is_absolute()})"
                )
                return False

            # On Windows, paths are case-insensitive
            # On Unix-like systems, paths are case-sensitive
            # Path.relative_to() handles this correctly by default

            # Check if path is within boundary using relative_to
            try:
                path.relative_to(boundary)
                # If we get here, path is within boundary
                return True
            except ValueError:
                # path is not relative to boundary
                pass

            # If allow_parent, check if boundary is within path
            # This allows access to parent directories of the project root
            if allow_parent:
                try:
                    boundary.relative_to(path)
                    return True
                except ValueError:
                    pass

            return False

        except Exception as e:
            self._logger.error(
                f"Error checking boundary for path '{path}' "
                f"against '{boundary}': {e}"
            )
            return False

    def extract_paths_from_arguments(
        self,
        arguments: dict[str, Any],
        parameter_names: list[str],
    ) -> list[str]:
        """Extract file paths from tool call arguments.

        Handles:
        - Single path strings
        - Path lists/arrays
        - Nested path parameters
        - All parameter names from TOOL_INVENTORY.md

        Args:
            arguments: Tool call arguments dictionary
            parameter_names: List of parameter names that may contain paths

        Returns:
            List of extracted path strings
        """
        if arguments is None:
            return []

        if not isinstance(arguments, dict):
            if isinstance(arguments, str):
                try:
                    parsed_arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    return []
                if isinstance(parsed_arguments, dict):
                    arguments = parsed_arguments
                else:
                    return []
            else:
                return []

        paths: list[str] = []

        for param_name in parameter_names:
            value = arguments.get(param_name)

            if value is None:
                continue

            # Handle single path string
            if isinstance(value, str):
                if value.strip():  # Only add non-empty strings
                    paths.append(value)

            # Handle list of paths
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        paths.append(item)
                    # Handle list of dicts with path keys
                    elif (
                        isinstance(item, dict)
                        and "path" in item
                        and isinstance(item["path"], str)
                        and item["path"].strip()
                    ):
                        paths.append(item["path"])

            # Handle dict with path key (e.g., {"path": "...", "content": "..."})
            elif isinstance(value, dict):
                if (
                    "path" in value
                    and isinstance(value["path"], str)
                    and value["path"].strip()
                ):
                    paths.append(value["path"])
                # Also check for nested file_path, filepath, etc.
                for nested_param in ["file_path", "filepath", "file", "target_file"]:
                    if (
                        nested_param in value
                        and isinstance(value[nested_param], str)
                        and value[nested_param].strip()
                    ):
                        paths.append(value[nested_param])

        return paths
