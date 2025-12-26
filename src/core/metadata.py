import logging
from pathlib import Path

import tomli

logger = logging.getLogger(__name__)


def _load_project_metadata() -> tuple[str, str]:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        data = tomli.loads(pyproject.read_text())
        meta = data.get("project", {})
        return meta.get("name", "llm-interactive-proxy"), meta.get("version", "0.1.0")
    except Exception:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to load project metadata from pyproject.toml, using defaults",
                exc_info=True,
            )
        return "llm-interactive-proxy", "0.0.0"
