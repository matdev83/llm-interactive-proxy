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
    except (FileNotFoundError, PermissionError) as e:
        # File system errors: file missing or permission denied
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to read pyproject.toml file: %s, using defaults",
                e,
                exc_info=True,
            )
        return ProjectMetadata(name="llm-interactive-proxy", version="0.0.0")
    except (UnicodeDecodeError, tomli.TOMLDecodeError) as e:
        # Parsing errors: invalid encoding or malformed TOML
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to parse pyproject.toml: %s, using defaults",
                e,
                exc_info=True,
            )
        return ProjectMetadata(name="llm-interactive-proxy", version="0.0.0")
    except KeyError as e:
        # Missing expected keys in TOML structure
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Missing expected keys in pyproject.toml: %s, using defaults",
                e,
                exc_info=True,
            )
        return ProjectMetadata(name="llm-interactive-proxy", version="0.0.0")
    except Exception as e:
        # Catch any other unexpected exceptions
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Unexpected error loading project metadata from pyproject.toml: %s, using defaults",
                e,
                exc_info=True,
            )
        return ProjectMetadata(name="llm-interactive-proxy", version="0.0.0")
