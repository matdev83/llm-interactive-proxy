from unittest.mock import AsyncMock, patch

import pytest


class TestTemperatureCommands:
    """Test temperature set/unset commands."""

    def test_set_temperature_command_valid_float(self, client):
        """Test setting temperature with valid float value."""
        mock_backend_response = {
            "choices": [{"message": {"content": "Temperature set successfully."}}]
        }

        with patch.object(
            client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = mock_backend_response

            payload = {
                "model": "openrouter:gpt-4",
                "messages": [
                    {"role": "user", "content": "!/set(temperature=0.7)"}
                ],
            }
            response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature == 0.7

        mock_method.assert_not_called()  # Backend should not be called for command-only

        response_json = response.json()
        assert response_json["id"] == "proxy_cmd_processed"
        content = response_json["choices"][0]["message"]["content"]
        assert "temperature set to: 0.7" in content

    def test_set_temperature_command_valid_int(self, client):
        """Test setting temperature with valid integer value."""
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=1)"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature == 1.0

    def test_set_temperature_command_valid_string_number(self, client):
        """Test setting temperature with string representation of number."""
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=\"0.5\")"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature == 0.5

    def test_set_temperature_command_zero_value(self, client):
        """Test setting temperature to zero (deterministic)."""
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=0.0)"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature == 0.0

    def test_set_temperature_command_max_openai_value(self, client):
        """Test setting temperature to maximum OpenAI value (2.0)."""
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=2.0)"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature == 2.0

    def test_set_temperature_command_invalid_negative(self, client):
        """Test setting temperature with invalid negative value."""
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=-0.5)"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        response_json = response.json()
        content = response_json["choices"][0]["message"]["content"]
        assert "Temperature must be between 0.0 and 2.0" in content

        # Temperature should not be set
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature is None

    def test_set_temperature_command_invalid_too_high(self, client):
        """Test setting temperature with value too high."""
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=3.0)"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        response_json = response.json()
        content = response_json["choices"][0]["message"]["content"]
        assert "Temperature must be between 0.0 and 2.0" in content

        # Temperature should not be set
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature is None

    def test_set_temperature_command_invalid_string(self, client):
        """Test setting temperature with invalid string value."""
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=high)"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        response_json = response.json()
        content = response_json["choices"][0]["message"]["content"]
        assert "Invalid temperature value" in content

        # Temperature should not be set
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature is None

    def test_unset_temperature_command(self, client):
        """Test unsetting temperature."""
        # First set a temperature
        session = client.app.state.session_manager.get_session("default")
        session.proxy_state.set_temperature(0.8)
        assert session.proxy_state.temperature == 0.8

        # Now unset it
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/unset(temperature)"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        assert session.proxy_state.temperature is None

        response_json = response.json()
        content = response_json["choices"][0]["message"]["content"]
        assert "temperature unset" in content

    def test_temperature_persistence_across_requests(self, client):
        """Test that temperature setting persists across requests in the same session."""
        # Set temperature
        payload1 = {
            "model": "openrouter:gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=0.6)"}
            ],
        }
        response1 = client.post("/v1/chat/completions", json=payload1)
        assert response1.status_code == 200

        # Make another request without setting temperature
        mock_backend_response = {
            "choices": [{"message": {"content": "Response with temperature."}}]
        }

        with patch.object(
            client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = mock_backend_response

            payload2 = {
                "model": "openrouter:gpt-4",
                "messages": [
                    {"role": "user", "content": "Generate a creative story."}
                ],
            }
            response2 = client.post("/v1/chat/completions", json=payload2)

        assert response2.status_code == 200
        
        # Verify temperature was passed to backend
        mock_method.assert_called_once()
        call_args = mock_method.call_args
        request_data = call_args[1]["request_data"]  # keyword argument
        assert hasattr(request_data, 'temperature')
        assert request_data.temperature == 0.6

    def test_temperature_with_message_content(self, client):
        """Test temperature command combined with message content."""
        mock_backend_response = {
            "choices": [{"message": {"content": "Creative response."}}]
        }

        with patch.object(
            client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = mock_backend_response

            payload = {
                "model": "openrouter:gpt-4",
                "messages": [
                    {"role": "user", "content": "!/set(temperature=0.9) Write a creative story about robots."}
                ],
            }
            response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        
        # Temperature should be set
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature == 0.9

        # Backend should be called with the remaining message
        mock_method.assert_called_once()
        call_args = mock_method.call_args
        processed_messages = call_args[1]["processed_messages"]
        assert len(processed_messages) == 1
        # The command should be stripped, leaving only the story request
        assert "Write a creative story about robots" in processed_messages[0].content
        assert "!/set(temperature=0.9)" not in processed_messages[0].content


class TestTemperatureAPIParameters:
    """Test temperature handling via direct API parameters."""

    def test_direct_api_temperature_parameter(self, client):
        """Test temperature passed directly in API request."""
        mock_backend_response = {
            "choices": [{"message": {"content": "Response with direct temperature."}}]
        }

        with patch.object(
            client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = mock_backend_response

            payload = {
                "model": "openrouter:gpt-4",
                "temperature": 0.4,
                "messages": [
                    {"role": "user", "content": "Generate a factual explanation."}
                ],
            }
            response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        
        # Verify temperature was passed to backend
        mock_method.assert_called_once()
        call_args = mock_method.call_args
        request_data = call_args[1]["request_data"]
        assert hasattr(request_data, 'temperature')
        assert request_data.temperature == 0.4

    def test_api_temperature_overrides_session_setting(self, client):
        """Test that direct API temperature overrides session-level setting."""
        # Set session temperature
        session = client.app.state.session_manager.get_session("default")
        session.proxy_state.set_temperature(0.8)

        mock_backend_response = {
            "choices": [{"message": {"content": "Response with override temperature."}}]
        }

        with patch.object(
            client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = mock_backend_response

            payload = {
                "model": "openrouter:gpt-4",
                "temperature": 0.2,  # Should override session setting
                "messages": [
                    {"role": "user", "content": "Generate a conservative response."}
                ],
            }
            response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        
        # Verify API temperature was used, not session temperature
        mock_method.assert_called_once()
        call_args = mock_method.call_args
        request_data = call_args[1]["request_data"]
        assert request_data.temperature == 0.2  # API value, not session value (0.8)


class TestTemperatureModelDefaults:
    """Test temperature model defaults from configuration."""

    def test_temperature_model_defaults_applied(self, client):
        """Test that model defaults are applied when no session/API temperature is set."""
        # Mock model defaults in app state
        from src.models import ModelDefaults, ModelReasoningConfig
        
        model_defaults = ModelDefaults(
            reasoning=ModelReasoningConfig(temperature=0.3)
        )
        client.app.state.model_defaults = {
            "openrouter:gpt-4": model_defaults
        }

        mock_backend_response = {
            "choices": [{"message": {"content": "Response with default temperature."}}]
        }

        with patch.object(
            client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = mock_backend_response

            payload = {
                "model": "openrouter:gpt-4",
                "messages": [
                    {"role": "user", "content": "Generate a response."}
                ],
            }
            response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        
        # Verify model default temperature was applied
        session = client.app.state.session_manager.get_session("default")
        assert session.proxy_state.temperature == 0.3

        # Verify temperature was passed to backend
        mock_method.assert_called_once()
        call_args = mock_method.call_args
        request_data = call_args[1]["request_data"]
        assert request_data.temperature == 0.3

    def test_session_temperature_overrides_model_defaults(self, client):
        """Test that session temperature overrides model defaults."""
        # Mock model defaults
        from src.models import ModelDefaults, ModelReasoningConfig
        
        model_defaults = ModelDefaults(
            reasoning=ModelReasoningConfig(temperature=0.3)
        )
        client.app.state.model_defaults = {
            "openrouter:gpt-4": model_defaults
        }

        # Set session temperature (should override model default)
        session = client.app.state.session_manager.get_session("default")
        session.proxy_state.set_temperature(0.9)

        mock_backend_response = {
            "choices": [{"message": {"content": "Response with session temperature."}}]
        }

        with patch.object(
            client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = mock_backend_response

            payload = {
                "model": "openrouter:gpt-4",
                "messages": [
                    {"role": "user", "content": "Generate a response."}
                ],
            }
            response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        
        # Session temperature should remain (not overridden by model default)
        assert session.proxy_state.temperature == 0.9

        # Verify session temperature was passed to backend
        mock_method.assert_called_once()
        call_args = mock_method.call_args
        request_data = call_args[1]["request_data"]
        assert request_data.temperature == 0.9


class TestTemperatureProxyState:
    """Test temperature functionality in ProxyState directly."""

    def test_proxy_state_set_temperature_valid(self):
        """Test setting valid temperature values in ProxyState."""
        from src.proxy_logic import ProxyState
        
        proxy_state = ProxyState()
        
        # Test various valid values
        proxy_state.set_temperature(0.0)
        assert proxy_state.temperature == 0.0
        
        proxy_state.set_temperature(0.5)
        assert proxy_state.temperature == 0.5
        
        proxy_state.set_temperature(1.0)
        assert proxy_state.temperature == 1.0
        
        proxy_state.set_temperature(2.0)
        assert proxy_state.temperature == 2.0

    def test_proxy_state_set_temperature_invalid(self):
        """Test setting invalid temperature values in ProxyState."""
        from src.proxy_logic import ProxyState
        
        proxy_state = ProxyState()
        
        # Test negative value
        with pytest.raises(ValueError, match="Temperature must be between 0.0 and 2.0"):
            proxy_state.set_temperature(-0.1)
        
        # Test too high value
        with pytest.raises(ValueError, match="Temperature must be between 0.0 and 2.0"):
            proxy_state.set_temperature(2.1)

    def test_proxy_state_unset_temperature(self):
        """Test unsetting temperature in ProxyState."""
        from src.proxy_logic import ProxyState
        
        proxy_state = ProxyState()
        proxy_state.set_temperature(0.7)
        assert proxy_state.temperature == 0.7
        
        proxy_state.unset_temperature()
        assert proxy_state.temperature is None

    def test_proxy_state_reset_clears_temperature(self):
        """Test that reset() clears temperature setting."""
        from src.proxy_logic import ProxyState
        
        proxy_state = ProxyState()
        proxy_state.set_temperature(0.8)
        assert proxy_state.temperature == 0.8
        
        proxy_state.reset()
        assert proxy_state.temperature is None

    def test_proxy_state_apply_model_defaults_temperature(self):
        """Test applying model defaults with temperature."""
        from src.models import ModelDefaults, ModelReasoningConfig
        from src.proxy_logic import ProxyState
        
        proxy_state = ProxyState()
        
        # Create model defaults with temperature
        model_defaults = ModelDefaults(
            reasoning=ModelReasoningConfig(temperature=0.6)
        )
        
        # Apply defaults
        proxy_state.apply_model_defaults("test-model", model_defaults)
        
        # Temperature should be applied
        assert proxy_state.temperature == 0.6

    def test_proxy_state_apply_model_defaults_no_override(self):
        """Test that model defaults don't override existing temperature."""
        from src.models import ModelDefaults, ModelReasoningConfig
        from src.proxy_logic import ProxyState
        
        proxy_state = ProxyState()
        proxy_state.set_temperature(0.9)  # Set existing temperature
        
        # Create model defaults with different temperature
        model_defaults = ModelDefaults(
            reasoning=ModelReasoningConfig(temperature=0.3)
        )
        
        # Apply defaults
        proxy_state.apply_model_defaults("test-model", model_defaults)
        
        # Existing temperature should not be overridden
        assert proxy_state.temperature == 0.9 