from __future__ import annotations

import logging

from src.core.domain.base import ValueObject

logger = logging.getLogger(__name__)


class ProjectConfiguration(ValueObject):
    """Configuration for project-related settings.

    This class handles project name and directory settings.
    """

    project: str | None = None
    project_dir: str | None = None

    def with_project(self, project_name: str | None) -> ProjectConfiguration:
        """Create a new config with updated project name."""
        return self.model_copy(update={"project": project_name})

    def with_project_dir(self, project_dir: str | None) -> ProjectConfiguration:
        """Create a new config with updated project directory."""
        return self.model_copy(update={"project_dir": project_dir})
