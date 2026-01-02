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

    updated_session = await session_service.get_session(session_id)
    assert updated_session is not None
    # The correct project path should be identified, not the drive root.
    assert updated_session.state.project_dir == "c:\\users\\test\\my-project"
