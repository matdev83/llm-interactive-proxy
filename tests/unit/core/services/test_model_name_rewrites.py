"""Unit tests for model name rewrites feature."""

import pytest
from unittest.mock import Mock, AsyncMock
from src.core.config.app_config import AppConfig, ModelAliasRule
from src.core.services.backend_service import BackendService
from src.core.domain.chat import ChatRequest
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.services.backend_factory import BackendFactory


class TestModelNameRewrites:
    """Test cases for model name rewrite functionality."""

    @pytest.fixture
    def mock_factory(self):
        """Mock backend factory."""
        return Mock(spec=BackendFactory)

    @pytest.fixture
    def mock_rate_limiter(self):
        """Mock rate limiter."""
        return Mock(spec=IRateLimiter)

    @pytest.fixture
    def mock_session_service(self):
        """Mock session service."""
        return Mock(spec=ISessionService)

    @pytest.fixture
    def mock_app_state(self):
        """Mock application state."""
        return Mock(spec=IApplicationState)

    @pytest.fixture
    def base_config(self):
        """Base configuration without model aliases."""
        return AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[]
        )

    @pytest.fixture
    def config_with_aliases(self):
        """Configuration with model alias rules."""
        return AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="^claude-3-sonnet-20240229$",
                    replacement="gemini-cli-oauth-personal:gemini-1.5-flash"
                ),
                ModelAliasRule(
                    pattern="^gpt-(.*)",
                    replacement="openrouter:openai/gpt-\\1"
                ),
                ModelAliasRule(
                    pattern="^(.*)$",
                    replacement="gemini-cli-oauth-personal:gemini-1.5-pro"
                )
            ]
        )

    @pytest.fixture
    def backend_service(self, mock_factory, mock_rate_limiter, base_config, 
                       mock_session_service, mock_app_state):
        """Backend service with base configuration."""
        return BackendService(
            factory=mock_factory,
            rate_limiter=mock_rate_limiter,
            config=base_config,
            session_service=mock_session_service,
            app_state=mock_app_state
        )

    @pytest.fixture
    def backend_service_with_aliases(self, mock_factory, mock_rate_limiter, 
                                   config_with_aliases, mock_session_service, 
                                   mock_app_state):
        """Backend service with model alias configuration."""
        return BackendService(
            factory=mock_factory,
            rate_limiter=mock_rate_limiter,
            config=config_with_aliases,
            session_service=mock_session_service,
            app_state=mock_app_state
        )

    def test_apply_model_aliases_no_rules(self, backend_service):
        """Test that model name is unchanged when no alias rules are configured."""
        # AC7: Given a request with a model name that does not match any pattern 
        # in model_aliases, the model name MUST remain unchanged.
        original_model = "gpt-4"
        result = backend_service._apply_model_aliases(original_model)
        assert result == original_model

    def test_apply_model_aliases_static_replacement(self, backend_service_with_aliases):
        """Test static model name replacement."""
        # AC4: Given a request with a model name that exactly matches a pattern 
        # for a static replacement, the model name MUST be rewritten to the 
        # corresponding replacement value.
        original_model = "claude-3-sonnet-20240229"
        expected_model = "gemini-cli-oauth-personal:gemini-1.5-flash"
        
        result = backend_service_with_aliases._apply_model_aliases(original_model)
        assert result == expected_model

    def test_apply_model_aliases_regex_with_capture_groups(self, backend_service_with_aliases):
        """Test regex replacement with capture groups."""
        # AC5: Given a request with a model name that matches a regex pattern 
        # with capture groups, the model name MUST be rewritten using the 
        # replacement string with the captured values correctly substituted.
        original_model = "gpt-4-turbo"
        expected_model = "openrouter:openai/gpt-4-turbo"
        
        result = backend_service_with_aliases._apply_model_aliases(original_model)
        assert result == expected_model

    def test_apply_model_aliases_first_match_wins(self):
        """Test that only the first matching rule is applied."""
        # AC6: Given multiple rules in model_aliases, if a model name matches 
        # more than one pattern, only the first matching rule in the list MUST be applied.
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="gpt-.*",
                    replacement="first-match:gpt-model"
                ),
                ModelAliasRule(
                    pattern="gpt-4",
                    replacement="second-match:gpt-4"
                ),
                ModelAliasRule(
                    pattern="^(.*)$",
                    replacement="catch-all:model"
                )
            ]
        )
        
        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState)
        )
        
        original_model = "gpt-4"
        expected_model = "first-match:gpt-model"
        
        result = backend_service._apply_model_aliases(original_model)
        assert result == expected_model

    def test_apply_model_aliases_no_match(self, backend_service_with_aliases):
        """Test that model name is unchanged when no rules match."""
        # Create a config with specific patterns that won't match our test model
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="^claude-.*",
                    replacement="gemini:claude-replacement"
                ),
                ModelAliasRule(
                    pattern="^gpt-.*",
                    replacement="openrouter:gpt-replacement"
                )
            ]
        )
        
        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState)
        )
        
        original_model = "llama-2-70b"
        result = backend_service._apply_model_aliases(original_model)
        assert result == original_model

    def test_apply_model_aliases_invalid_regex(self, caplog):
        """Test handling of invalid regex patterns."""
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="[invalid-regex",  # Missing closing bracket
                    replacement="should-not-be-used"
                ),
                ModelAliasRule(
                    pattern="gpt-.*",
                    replacement="openrouter:gpt-model"
                )
            ]
        )
        
        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState)
        )
        
        original_model = "gpt-4"
        expected_model = "openrouter:gpt-model"
        
        result = backend_service._apply_model_aliases(original_model)
        assert result == expected_model
        
        # Check that warning was logged for invalid regex
        assert "Invalid regex pattern" in caplog.text

    @pytest.mark.asyncio
    async def test_resolve_backend_and_model_with_aliases(self, backend_service_with_aliases):
        """Test that model aliases are applied during backend resolution."""
        # Mock session service to return None (no session)
        backend_service_with_aliases._session_service.get_session = AsyncMock(return_value=None)
        
        request = ChatRequest(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": "Hello"}]
        )
        
        backend_type, effective_model = await backend_service_with_aliases._resolve_backend_and_model(request)
        
        # The model should be rewritten by the alias rule
        assert effective_model == "openai/gpt-4-turbo"  # After parsing backend:model format
        assert backend_type == "openrouter"

    @pytest.mark.asyncio
    async def test_resolve_backend_and_model_static_route_precedence(self):
        """Test that static_route takes precedence over model aliases."""
        # AC8: If the --static-route CLI parameter is set, it MUST take precedence 
        # over any model_aliases rules. The model alias logic should not be executed.
        config = AppConfig(
            backends={
                "default_backend": "openai",
                "static_route": "forced-backend:forced-model"
            },
            model_aliases=[
                ModelAliasRule(
                    pattern=".*",
                    replacement="should-not-be-used:model"
                )
            ]
        )
        
        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState)
        )
        
        # Mock session service
        backend_service._session_service.get_session = AsyncMock(return_value=None)
        
        request = ChatRequest(
            model="any-model",
            messages=[{"role": "user", "content": "Hello"}]
        )
        
        backend_type, effective_model = await backend_service._resolve_backend_and_model(request)
        
        # Static route should override alias rules
        assert backend_type == "forced-backend"
        assert effective_model == "forced-model"

    def test_config_validation_valid_rules(self):
        """Test that valid model alias rules can be configured."""
        # AC1: The proxy MUST start without errors when a valid model_aliases 
        # list is present in config.yaml.
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="^gpt-4$",
                    replacement="openrouter:openai/gpt-4"
                ),
                ModelAliasRule(
                    pattern="claude-(.*)",
                    replacement="anthropic:claude-\\1"
                )
            ]
        )
        
        # Should not raise any exceptions
        assert len(config.model_aliases) == 2
        assert config.model_aliases[0].pattern == "^gpt-4$"
        assert config.model_aliases[0].replacement == "openrouter:openai/gpt-4"

    def test_config_validation_empty_rules(self):
        """Test that configuration works when model_aliases is absent or empty."""
        # AC3: The proxy MUST start and operate normally if the model_aliases 
        # key is absent from the configuration.
        config = AppConfig(
            backends={"default_backend": "openai"}
            # model_aliases not specified - should default to empty list
        )
        
        assert config.model_aliases == []

    def test_complex_regex_patterns(self, backend_service_with_aliases):
        """Test complex regex patterns with multiple capture groups."""
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="^(gpt|claude)-(\\d+)-(\\w+)$",
                    replacement="unified:\\1-\\2-\\3-model"
                )
            ]
        )
        
        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState)
        )
        
        # Test GPT model
        result = backend_service._apply_model_aliases("gpt-4-turbo")
        assert result == "unified:gpt-4-turbo-model"
        
        # Test Claude model
        result = backend_service._apply_model_aliases("claude-3-sonnet")
        assert result == "unified:claude-3-sonnet-model"
        
        # Test non-matching model
        result = backend_service._apply_model_aliases("llama-2-70b")
        assert result == "llama-2-70b"