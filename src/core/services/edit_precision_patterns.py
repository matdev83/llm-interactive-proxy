from __future__ import annotations

import os
from functools import lru_cache

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
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
]

DEFAULT_RESPONSE_PATTERNS: list[str] = [
    r"<diff_error>|diff_error",
    r"SEARCH\s+block.*does\s+not\s+match",
    r"No\s+sufficiently\s+similar\s+match\s+found",
    r"hunk\s+failed\s+to\s+apply",
]


def _load_yaml(path: str) -> dict | None:
    if not yaml:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


@lru_cache(maxsize=1)
def _load_patterns() -> tuple[list[str], list[str]]:
    path = os.environ.get(
        "EDIT_PRECISION_PATTERNS_PATH",
        os.path.join("conf", "edit_precision_patterns.yaml"),
    )
    data = _load_yaml(path)
    if not data:
        return DEFAULT_REQUEST_PATTERNS, DEFAULT_RESPONSE_PATTERNS
    req = data.get("request_patterns")
    resp = data.get("response_patterns")
    req_list = (
        req
        if isinstance(req, list) and all(isinstance(x, str) for x in req)
        else DEFAULT_REQUEST_PATTERNS
    )
    resp_list = (
        resp
        if isinstance(resp, list) and all(isinstance(x, str) for x in resp)
        else DEFAULT_RESPONSE_PATTERNS
    )
    return list(req_list), list(resp_list)


def get_request_patterns() -> list[str]:
    req, _ = _load_patterns()
    return list(req)


def get_response_patterns() -> list[str]:
    _, resp = _load_patterns()
    return list(resp)
