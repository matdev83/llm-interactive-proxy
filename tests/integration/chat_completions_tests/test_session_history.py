import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from src.main import app
import src.models as models
from src.session import SessionManager

@pytest.fixture
def client():
    with TestClient(app) as c:
        c.app.state.session_manager = SessionManager()  # type: ignore
        yield c

def test_session_records_proxy_and_backend_interactions(client: TestClient):
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = {
            'choices': [{'message': {'content': 'backend reply'}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3}
        }
        payload1 = {
            'model': 'model-a',
            'messages': [{'role': 'user', 'content': '!/set(model=override)'}]
        }
        client.post('/v1/chat/completions', json=payload1, headers={'X-Session-ID': 'abc'})

        payload2 = {
            'model': 'model-a',
            'messages': [{'role': 'user', 'content': 'hello'}]
        }
        client.post('/v1/chat/completions', json=payload2, headers={'X-Session-ID': 'abc'})

    session = client.app.state.session_manager.get_session('abc')  # type: ignore
    assert len(session.history) == 2
    assert session.history[0].handler == 'proxy'
    assert session.history[0].prompt == '!/set(model=override)'
    assert session.history[1].handler == 'backend'
    assert session.history[1].backend == 'openrouter'
    assert session.history[1].model == 'override'
    assert session.history[1].response == 'backend reply'
    assert session.history[1].usage.total_tokens == 3

def test_session_records_streaming_placeholder(client: TestClient):
    async def gen():
        yield b'data: hi\n\n'
    stream_resp = StreamingResponse(gen(), media_type='text/event-stream')
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = stream_resp
        payload = {
            'model': 'model-a',
            'messages': [{'role': 'user', 'content': 'hello'}],
            'stream': True
        }
        client.post('/v1/chat/completions', json=payload, headers={'X-Session-ID': 's2'})

    session = client.app.state.session_manager.get_session('s2')  # type: ignore
    assert session.history[0].response == '<streaming>'
