"""Integration test to verify model validation returns proper HTTP status codes."""
import pytest
from httpx import AsyncClient
from src.core.app.main import create_app


@pytest.mark.asyncio
async def test_gemini_connector_rejects_unsupported_model_with_400():
    """Test that gemini-oauth-antigravity rejects unsupported models (e.g. GPT-4) with HTTP 400."""
    app = create_app()
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Try to use GPT-4 model with Gemini backend
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini-oauth-antigravity:gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        
        # Should return 400 Bad Request
        assert response.status_code == 400
        
        data = response.json()
        assert "error" in data
        assert "invalid_model_for_backend" in str(data)
        assert "not supported by the Antigravity sandbox" in data["error"]["message"]
