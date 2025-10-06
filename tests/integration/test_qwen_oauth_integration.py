from __future__ import annotations

import json
from pathlib import Path

import pytest


def _qwen_oauth_available() -> bool:
    creds_path = Path.home() / ".qwen" / "oauth_creds.json"
    if not creds_path.exists():
        return False
    try:
        data = json.loads(creds_path.read_text(encoding="utf-8"))
        return bool(data.get("access_token") and data.get("refresh_token"))
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
    pytest.mark.skip(
        reason="Qwen OAuth integration tests disabled to prevent browser OAuth flows - run with --run-qwen-oauth to enable"
    ),
]
