"""Repro: Responses-style input item {role: user, name: bash} without content.

Before the fix, normalize_responses_input_to_messages omitted `content`, and the
Codex connector raised ValidationError when building ProcessedMessage.

Run from repo root:
  .\\.venv\\Scripts\\python.exe dev/scripts/repro_responses_bash_user_missing_content.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.connectors._openai_codex_connector import OpenAICodexConnector
from src.connectors.openai_codex.contracts import ProcessedMessage
from src.core.domain.chat import ChatMessage
from src.core.domain.translation import Translation


def main() -> None:
    payload = [{"role": "user", "name": "bash"}]
    normalized = Translation.normalize_responses_input_to_messages(payload)
    print("normalized:", normalized)
    assert normalized[0].get("content") == ""

    inst = OpenAICodexConnector.__new__(OpenAICodexConnector)
    object.__setattr__(inst, "_file_observer_ref", None)
    out = OpenAICodexConnector._normalize_processed_messages(inst, normalized)
    assert isinstance(out[0], ProcessedMessage)
    assert out[0].content == ""

    cm = ChatMessage(role="user", name="bash", content=None)
    out2 = OpenAICodexConnector._normalize_processed_messages(
        inst, [cm.model_dump(exclude_none=True)]
    )
    assert out2[0].content == ""
    print("OK: ProcessedMessage normalization accepts bash-style user rows.")


if __name__ == "__main__":
    main()
