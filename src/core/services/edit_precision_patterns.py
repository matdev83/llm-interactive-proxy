from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EditPrecisionPatternsConfig(BaseModel):
    """Configuration for edit precision patterns loaded from YAML."""

    request_patterns: list[str] = Field(
        default_factory=list,
        description="Patterns for request messages that may indicate low precision",
    )
    response_patterns: list[str] = Field(
        default_factory=list,
        description="Patterns for response messages that may indicate low precision",
    )


@dataclass(frozen=True)
class EditPrecisionPatterns:
    """Edit precision patterns extracted from config or defaults."""

    request_patterns: list[str]
    response_patterns: list[str]

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    logger.debug(
        "Failed to import yaml module - edit precision patterns from YAML will not be available",
        exc_info=True,
    )
    yaml = None  # type: ignore


DEFAULT_REQUEST_PATTERNS: list[str] = [
    r"The\s+SEARCH\s+block.*does\s+not\s+match\s+anything\s+in\s+the\s+file",
    r"This\s+is\s+likely\s+because\s+the\s+SEARCH\s+block\s+content\s+doesn't\s+match\s+exactly",
    r"No\s+sufficiently\s+similar\s+match\s+found",
    r"Unable\s+to\s+apply\s+diff\s+to\s+file",
    r"Failed\s+to\s+edit,\s+could\s+not\s+find\s+the\s+string\s+to\s+replace",
    r"Failed\s+to\s+edit,\s+expected\s+\d+\s+(?:occurrence|occurrences)\s+but\s+found\s+\d+",
    r"UnifiedDiffNoMatch:\s+hunk\s+failed\s+to\s+apply",
    r"UnifiedDiffNotUnique:\s+hunk\s+failed\s+to\s+apply",
    r"old_string\s+not\s+found\s+in\s+content",
    r"old_string\s+appears\s+multiple\s+times\s+in\s+the\s+content",
    r"patch\s+contains\s+fuzzy\s+matches\s+\(fuzz\s+level:\s*\d+\)",
    r"Missing\s+value\s+for\s+required\s+parameter\s+'diff'",
    r"Special\s+marker\s+'>>>>>>>(?:[^']*)'\s+found",
    r"Unexpected\s+end\s+of\s+sequence:\s+Expected\s+'>>>>>>>\s*REPLACE'\s+was\s+not\s+found",
    r"The\s+tool\s+execution\s+failed\s+with\s+the\s+following\s+error",
]

DEFAULT_RESPONSE_PATTERNS: list[str] = [
    r"<diff_error>|diff_error",
    r"SEARCH\s+block.*does\s+not\s+match",
    r"No\s+sufficiently\s+similar\s+match\s+found",
    r"hunk\s+failed\s+to\s+apply",
]


def _load_yaml(path: str) -> EditPrecisionPatternsConfig | None:
    if not yaml:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                return EditPrecisionPatternsConfig(**data)
            return None
    except (FileNotFoundError, PermissionError, OSError, yaml.YAMLError) as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to load edit precision patterns from %s: %s",
                path,
                e,
                exc_info=True,
            )
        return None


@lru_cache(maxsize=1)
def _load_patterns() -> tuple[list[str], list[str]]:
    path = os.environ.get(
        "EDIT_PRECISION_PATTERNS_PATH",
        os.path.join("config", "edit_precision_patterns.yaml"),
    )
    config = _load_yaml(path)
    if not config:
        return DEFAULT_REQUEST_PATTERNS, DEFAULT_RESPONSE_PATTERNS
    return list(config.request_patterns), list(config.response_patterns)


def get_request_patterns() -> list[str]:
    req, _ = _load_patterns()
    return list(req)


def get_response_patterns() -> list[str]:
    _, resp = _load_patterns()
    return list(resp)
