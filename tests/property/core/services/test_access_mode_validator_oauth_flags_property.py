"""Property tests for Multi User Mode OAuth flag blocking.

**Feature: proxy-access-modes, Property 4: Multi User Mode blocks OAuth debugging override flags**

**Validates: Requirements 7.1**

Property 4: Multi User Mode blocks OAuth debugging override flags
*For any* OAuth debugging override flag, when operating in Multi User Mode,
the system should refuse to start with a validation error.
"""

from __future__ import annotations

import argparse

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.config.app_config import AppConfig
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.config.models.auth import AuthConfig
from src.core.config.models.notification import NotificationConfig
from src.core.services.access_mode_validator import AccessModeValidator

# All OAuth debugging override flags
OAUTH_FLAGS = [
    "enable_gemini_oauth_auto_backend_debugging_override",
    "enable_gemini_oauth_free_backend_debugging_override",
    "enable_gemini_oauth_plan_backend_debugging_override",
    "enable_qwen_oauth_backend_debugging_override",
    "enable_anthropic_oauth_backend_debugging_override",
    "enable_opencode_zen_backend_debugging_override",
    "enable_kiro_oauth_auto_backend_debugging_override",
    "enable_openai_codex_backend_debugging_override",
]

# Strategy for selecting an OAuth flag
oauth_flag_strategy = st.sampled_from(OAUTH_FLAGS)


class TestMultiUserModeOAuthFlagBlockingProperty:
    """Property tests for Multi User Mode OAuth flag blocking.

    **Validates: Requirements 7.1**
    """

    @given(flag_name=oauth_flag_strategy)
    @settings(max_examples=50, deadline=None)
    def test_multi_user_mode_rejects_any_oauth_flag(self, flag_name: str) -> None:
        """**Property 4**: Multi User Mode rejects any OAuth debugging override flag.

        GIVEN any OAuth debugging override flag set to True
        WHEN operating in Multi User Mode
        THEN validation should raise ValueError
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host="127.0.0.1",
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace(**{flag_name: True})

        # Should raise ValueError for any OAuth flag
        with pytest.raises(ValueError) as exc_info:
            validator.validate(config, args)

        error_msg = str(exc_info.value)
        assert (
            "OAuth debugging override flags are not allowed in Multi User Mode"
            in error_msg
        )
        assert "OAuth connectors are blocked in production deployments" in error_msg
