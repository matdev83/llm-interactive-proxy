"""
Integration tests for multiple oneoff commands.

Tests that oneoff commands can be used multiple times in sequence,
each time properly overriding the backend/model for exactly one request
and then reverting to the default backend.
"""

from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock


class TestMultipleOneoffCommands:
    """Test multiple oneoff commands in sequence."""

    def test_multiple_oneoff_commands_sequence(self, client: TestClient):
        """
        Test that multiple oneoff commands work correctly in sequence:
        1. Normal prompt → default backend (OpenRouter)
        2. Oneoff command → sets route to cypher-alpha
        3. Prompt → uses oneoff route, clears route
        4. Normal prompt → default backend again (OpenRouter)
        5. Second oneoff command → sets new route to mistral
        6. Prompt → uses second oneoff route, clears route
        7. Normal prompt → default backend again (OpenRouter)
        """
        # Mock responses for different models
        default_openrouter_response = {
            "id": "default-openrouter-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gemini-2.0-flash-exp",  # OpenRouter backend returns the requested model name
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Default OpenRouter response"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        }
        
        cypher_response = {
            "id": "cypher-test-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "openrouter/cypher-alpha:free",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Cypher response"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40}
        }
        
        mistral_response = {
            "id": "mistral-test-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "mistralai/mistral-7b-instruct:free",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Mistral response"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 12, "completion_tokens": 18, "total_tokens": 30}
        }

        with patch.object(client.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(side_effect=[
                              (default_openrouter_response, {}),  # Step 1: Normal request
                              (cypher_response, {}),              # Step 3: First oneoff use
                              (default_openrouter_response, {}),  # Step 4: Normal request after oneoff
                              (mistral_response, {}),             # Step 6: Second oneoff use
                              (default_openrouter_response, {})   # Step 7: Normal request after second oneoff
                          ])):

            # Step 1: Normal prompt (should use default backend - OpenRouter)
            response1 = client.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "What is 1+1?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response1.status_code == 200
            response1_json = response1.json()
            assert response1_json["model"] == "gemini-2.0-flash-exp"
            assert "Default OpenRouter response" in response1_json["choices"][0]["message"]["content"]

            # Step 2: Set first oneoff route
            response2 = client.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "!/oneoff(openrouter/cypher-alpha:free)"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response2.status_code == 200
            response2_json = response2.json()
            # Command-only requests are handled by the proxy, not sent to backend
            assert "One-off route set to openrouter/cypher-alpha:free" in response2_json["choices"][0]["message"]["content"]

            # Step 3: Prompt that should use oneoff route (cypher-alpha)
            response3 = client.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response3.status_code == 200
            response3_json = response3.json()
            assert response3_json["model"] == "openrouter/cypher-alpha:free"
            assert "Cypher response" in response3_json["choices"][0]["message"]["content"]

            # Step 4: Normal prompt (should use default backend again - OpenRouter)
            response4 = client.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "What is 3+3?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response4.status_code == 200
            response4_json = response4.json()
            assert response4_json["model"] == "gemini-2.0-flash-exp"
            assert "Default OpenRouter response" in response4_json["choices"][0]["message"]["content"]

            # Step 5: Set second oneoff route
            response5 = client.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "!/oneoff(openrouter/mistralai/mistral-7b-instruct:free)"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response5.status_code == 200
            response5_json = response5.json()
            assert "One-off route set to openrouter/mistralai/mistral-7b-instruct:free" in response5_json["choices"][0]["message"]["content"]

            # Step 6: Prompt that should use second oneoff route (mistral)
            response6 = client.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "What is 4+4?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response6.status_code == 200
            response6_json = response6.json()
            assert response6_json["model"] == "mistralai/mistral-7b-instruct:free"
            assert "Mistral response" in response6_json["choices"][0]["message"]["content"]

            # Step 7: Final normal prompt (should use default backend again - OpenRouter)
            response7 = client.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "What is 5+5?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response7.status_code == 200
            response7_json = response7.json()
            assert response7_json["model"] == "gemini-2.0-flash-exp"
            assert "Default OpenRouter response" in response7_json["choices"][0]["message"]["content"]

    def test_oneoff_commands_different_sessions(self, client: TestClient):
        """
        Test that oneoff commands are session-specific and don't interfere
        with each other across different sessions.
        """
        default_openrouter_response = {
            "id": "default-openrouter-response",
            "object": "chat.completion", 
            "created": 1234567890,
            "model": "gemini-2.0-flash-exp",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Default OpenRouter response"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        }
        
        cypher_response = {
            "id": "cypher-test-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "openrouter/cypher-alpha:free", 
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Cypher response"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40}
        }

        with patch.object(client.app.state.openrouter_backend, 'chat_completions',
                          new=AsyncMock(side_effect=[
                              (default_openrouter_response, {}),  # Session 2: Normal request
                              (cypher_response, {}),              # Session 1: Oneoff use
                              (default_openrouter_response, {})   # Session 1: After oneoff
                          ])):

            # Session 1: Set oneoff route
            response1 = client.post("/v1/chat/completions", 
                                    headers={"x-session-id": "session1"},
                                    json={
                "messages": [{"role": "user", "content": "!/oneoff(openrouter/cypher-alpha:free)"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response1.status_code == 200

            # Session 2: Normal prompt (should use default backend, not affected by session1's oneoff)
            response2 = client.post("/v1/chat/completions",
                                    headers={"x-session-id": "session2"}, 
                                    json={
                "messages": [{"role": "user", "content": "What is 1+1?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response2.status_code == 200
            response2_json = response2.json()
            assert response2_json["model"] == "gemini-2.0-flash-exp"
            assert "Default OpenRouter response" in response2_json["choices"][0]["message"]["content"]

            # Session 1: Use oneoff route
            response3 = client.post("/v1/chat/completions",
                                    headers={"x-session-id": "session1"},
                                    json={
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response3.status_code == 200
            response3_json = response3.json()
            assert response3_json["model"] == "openrouter/cypher-alpha:free"
            assert "Cypher response" in response3_json["choices"][0]["message"]["content"]

            # Session 1: After oneoff use, should revert to default
            response4 = client.post("/v1/chat/completions",
                                    headers={"x-session-id": "session1"},
                                    json={
                "messages": [{"role": "user", "content": "What is 3+3?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response4.status_code == 200
            response4_json = response4.json()
            assert response4_json["model"] == "gemini-2.0-flash-exp"
            assert "Default OpenRouter response" in response4_json["choices"][0]["message"]["content"]

    def test_oneoff_command_with_prompt_in_same_message(self, client: TestClient):
        """
        Test that oneoff command + prompt in the same message works correctly.
        The command is processed (setting the oneoff route) and the remaining text
        is sent to the LLM using the oneoff route.
        """
        # Mock the backend to prevent real API calls
        with patch.object(client.app.state.openrouter_backend, 'chat_completions',
                          new=AsyncMock(return_value=({
                              "id": "test-response",
                              "object": "chat.completion",
                              "created": 1234567890,
                              "model": "cypher-alpha:free",
                              "choices": [{
                                  "index": 0,
                                  "message": {"role": "assistant", "content": "Mocked response"},
                                  "finish_reason": "stop"
                              }],
                              "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
                          }, {}))):
            
            # Oneoff command + prompt in same message
            response = client.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "!/oneoff(openrouter/cypher-alpha:free)\nWhat is the meaning of life?"}],
                "model": "gemini-2.0-flash-exp"
            })
            assert response.status_code == 200
            response_json = response.json()
            
            # The command is processed and the remaining text is sent to the LLM
            # So we should get the mocked response, not the command confirmation
            assert "Mocked response" in response_json["choices"][0]["message"]["content"]
            
            # The model shows the effective model (which is the oneoff model)
            assert response_json["model"] == "cypher-alpha:free" 