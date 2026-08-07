from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.core.domain.chat import ChatMessage, ChatRequest

from tests.integration.test_integration_helpers import (
    create_test_config,
    get_session_service,
    get_test_client,
)


@pytest.mark.asyncio
async def test_project_directory_resolution_ignores_drive_root():
    """
    Verify that the service does not incorrectly resolve the project root
    to a shallow path like 'c:\\' when it's mentioned in the prompt.
    """
    config = create_test_config(project_dir_resolution_mode="deterministic")
    client: TestClient = get_test_client(config)
    session_service = get_session_service(client)
    session_id = "test-session"

    request = ChatRequest(
        model="test-model",
        messages=[
            ChatMessage(
                role="user",
                content="I'm working on a project located at c:\\users\\test\\my-project, but I'm having trouble with c:\\.",
            )
        ],
    )

    # The service should be called automatically by the app
    response = client.post(
        f"/v1/chat/completions?session_id={session_id}",
        json=request.model_dump(mode="json"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200

    resolved_session_id = response.headers.get("x-session-id") or session_id
    updated_session = await session_service.get_session(resolved_session_id)
    if updated_session.state.project_dir is None:
        all_sessions = await session_service.get_all_sessions()  # type: ignore[attr-defined]
        matching = [
            s
            for s in all_sessions
            if getattr(getattr(s, "state", None), "project_dir", None)
            == "c:\\users\\test\\my-project"
        ]
        if matching:
            updated_session = matching[-1]
    assert updated_session is not None
    # The correct project path should be identified, not the drive root.
    assert updated_session.state.project_dir == "c:\\users\\test\\my-project"
