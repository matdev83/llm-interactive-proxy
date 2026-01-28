from __future__ import annotations

from types import SimpleNamespace

from src.connectors.gemini_base import thought_signature_manager as tsm
from src.connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall


def test_thought_signature_is_refreshed_on_observation_and_survives_cleanup(
    monkeypatch,
) -> None:
    """Regression: long-running sessions must not lose signatures mid-session.

    The manager performs TTL cleanup on each new store. If a signature is used/seen
    shortly before the cleanup, it must be "touched" so it doesn't get purged.
    """

    now = 0.0

    def fake_time() -> float:
        return now

    monkeypatch.setattr(tsm.time, "time", fake_time)

    manager = ThoughtSignatureManager(ttl_seconds=10)

    # Store an initial signature at t=0
    manager.store_signatures_from_tool_calls(
        [
            {
                "id": "call_1",
                "extra_content": {"google": {"thought_signature": "sig_1"}},
            }
        ],
        session_id="s1",
    )

    # At t=9, observe the same signature in a request.
    # This should refresh the timestamp so it survives cleanup at t=15.
    now = 9.0
    canonical_request = SimpleNamespace(
        messages=[
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(name="test", arguments="{}"),
                        extra_content={"google": {"thought_signature": "sig_1"}},
                    )
                ],
            )
        ]
    )
    manager.inject_signatures(canonical_request, session_id="s1")

    # At t=15, storing a new signature triggers TTL cleanup.
    # Without touching, call_1 would be considered expired and removed.
    now = 15.0
    manager.store_signatures_from_tool_calls(
        [
            {
                "id": "call_2",
                "extra_content": {"google": {"thought_signature": "sig_2"}},
            }
        ],
        session_id="s1",
    )

    assert "s1:call_1" in manager.cache
