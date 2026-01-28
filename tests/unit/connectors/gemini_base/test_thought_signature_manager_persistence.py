from __future__ import annotations

from src.connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall


def test_thought_signature_persists_across_restarts(tmp_path, monkeypatch) -> None:
    persist_path = tmp_path / "thought_signatures.json"
    monkeypatch.setenv("LLM_PROXY_THOUGHT_SIGNATURE_PERSIST_PATH", str(persist_path))

    manager = ThoughtSignatureManager(ttl_seconds=86400)
    manager.store_signatures_from_tool_calls(
        [
            {
                "id": "t1",
                "extra_content": {"google": {"thought_signature": "sig-123"}},
            }
        ],
        session_id="s1",
    )

    # Simulate process restart with a new manager instance.
    manager2 = ThoughtSignatureManager(ttl_seconds=86400)
    msg = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="t1", function=FunctionCall(name="x", arguments="{}"))],
    )

    request = type("Req", (), {"messages": [msg]})()
    manager2.inject_signatures(request, session_id="s2")

    injected = msg.tool_calls[0].extra_content  # type: ignore[index]
    assert isinstance(injected, dict)
    assert injected.get("google", {}).get("thought_signature") == "sig-123"
