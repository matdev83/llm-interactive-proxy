import logging
from dataclasses import dataclass
from pathlib import Path

import tomli

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectMetadata:
    """Project metadata from pyproject.toml."""

    name: str
    version: str


def _load_project_metadata() -> ProjectMetadata:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        data = tomli.loads(pyproject.read_text())
        meta = data.get("project", {})
        return ProjectMetadata(
            name=meta.get("name", "llm-interactive-proxy"),
            version=meta.get("version", "0.1.0"),
        )
    except Exception:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to load project metadata from pyproject.toml, using defaults",
                exc_info=True,
            )
        return ProjectMetadata(name="llm-interactive-proxy", version="0.0.0")
