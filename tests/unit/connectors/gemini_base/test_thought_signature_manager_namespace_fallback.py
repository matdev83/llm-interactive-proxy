from types import SimpleNamespace

from src.connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall


def test_namespaced_fallback_recovers_signatures() -> None:
    manager = ThoughtSignatureManager(ttl_seconds=60)

    manager.store_signatures_from_tool_calls(
        [
            {
                "id": "call_1",
                "extra_content": {"google": {"thought_signature": "sig_1"}},
            }
        ],
        session_id="s1|account-a",
    )

    msg = ChatMessage(
        role="assistant",
        tool_calls=[
            ToolCall(id="call_1", function=FunctionCall(name="x", arguments="{}"))
        ],
    )
    request = SimpleNamespace(messages=[msg])

    manager.inject_signatures(request, session_id="s1|account-b")

    injected = msg.tool_calls[0].extra_content  # type: ignore[index]
    assert isinstance(injected, dict)
    assert injected.get("google", {}).get("thought_signature") == "sig_1"
    assert manager.get_cached_signature("s1|account-b", "call_1") == "sig_1"


def test_namespaced_fallback_recovers_signatures_across_sessions() -> None:
    manager = ThoughtSignatureManager(ttl_seconds=60)

    manager.store_signatures_from_tool_calls(
        [
            {
                "id": "call_2",
                "extra_content": {"google": {"thought_signature": "sig_2"}},
            }
        ],
        session_id="sess-a|account-a",
    )

    msg = ChatMessage(
        role="assistant",
        tool_calls=[
            ToolCall(id="call_2", function=FunctionCall(name="x", arguments="{}"))
        ],
    )
    request = SimpleNamespace(messages=[msg])

    manager.inject_signatures(request, session_id="sess-b|account-b")

    injected = msg.tool_calls[0].extra_content  # type: ignore[index]
    assert isinstance(injected, dict)
    assert injected.get("google", {}).get("thought_signature") == "sig_2"
