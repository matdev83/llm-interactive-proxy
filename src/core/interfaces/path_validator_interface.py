from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class IPathValidator(ABC):
    """Interface for path validation operations.

    This interface defines the contract for components that validate and
    normalize file paths for sandboxing purposes.
    """

    @abstractmethod
    def normalize_path(
        self,
        path: str,
        base_dir: str | None = None,
    ) -> Path:
        """Normalize a path to absolute form.

        Args:
            path: The path to normalize (may be relative, contain ~, .., etc.)
            base_dir: Optional base directory for resolving relative paths

        Returns:
            Normalized absolute Path object

        Raises:
            ValueError: If path is invalid or cannot be normalized
        """

    @abstractmethod
    def is_within_boundary(
        self,
        path: Path,
        boundary: Path,
        allow_parent: bool = False,
    ) -> bool:
        """Check if a path is within a boundary directory.

        Args:
            path: The normalized absolute path to check
            boundary: The boundary directory path
            allow_parent: Whether to allow parent directories of boundary

        Returns:
            True if path is within boundary, False otherwise
        """

    @abstractmethod
    def extract_paths_from_arguments(
        self,
        arguments: dict[str, Any],
        parameter_names: list[str],
    ) -> list[str]:
        """Extract file paths from tool call arguments.

        Args:
            arguments: Tool call arguments dictionary
            parameter_names: List of parameter names that may contain paths

        Returns:
            List of extracted path strings
        """
