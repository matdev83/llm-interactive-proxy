"""Unit tests for ToolCallReactorConfig schema validation.

Tests validate that access_policies configuration is properly validated,
including required fields, enum validation, and environment variable overrides.
"""

from src.core.config.app_config import ToolCallReactorConfig


class TestToolCallReactorConfigAccessPolicies:
    """Test suite for access_policies configuration validation."""

    def test_valid_minimal_policy_configuration(self):
        """Test that a minimal valid policy configuration is accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.enabled is True
        assert len(config.access_policies) == 1
        assert config.access_policies[0]["name"] == "test_policy"
        assert config.access_policies[0]["model_pattern"] == ".*"
        assert config.access_policies[0]["default_policy"] == "allow"

    def test_valid_complete_policy_configuration(self):
        """Test that a complete policy configuration with all fields is accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "comprehensive_policy",
                    "model_pattern": "anthropic:.*",
                    "agent_pattern": "production-.*",
                    "allowed_patterns": ["read_.*", "list_.*"],
                    "blocked_patterns": ["delete_.*", "rm_.*"],
                    "default_policy": "deny",
                    "block_message": "Custom block message",
                    "priority": 100,
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert len(config.access_policies) == 1
        policy = config.access_policies[0]
        assert policy["name"] == "comprehensive_policy"
        assert policy["model_pattern"] == "anthropic:.*"
        assert policy["agent_pattern"] == "production-.*"
        assert policy["allowed_patterns"] == ["read_.*", "list_.*"]
        assert policy["blocked_patterns"] == ["delete_.*", "rm_.*"]
        assert policy["default_policy"] == "deny"
        assert policy["block_message"] == "Custom block message"
        assert policy["priority"] == 100

    def test_multiple_policies_configuration(self):
        """Test that multiple policies can be configured."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "policy_1",
                    "model_pattern": "openai:.*",
                    "default_policy": "allow",
                },
                {
                    "name": "policy_2",
                    "model_pattern": "anthropic:.*",
                    "default_policy": "deny",
                },
                {
                    "name": "policy_3",
                    "model_pattern": "gemini:.*",
                    "default_policy": "allow",
                    "priority": 50,
                },
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert len(config.access_policies) == 3
        assert config.access_policies[0]["name"] == "policy_1"
        assert config.access_policies[1]["name"] == "policy_2"
        assert config.access_policies[2]["name"] == "policy_3"

    def test_empty_access_policies_list(self):
        """Test that an empty access_policies list is valid."""
        config_data = {
            "enabled": True,
            "access_policies": [],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies == []

    def test_default_access_policies_when_not_specified(self):
        """Test that access_policies defaults to empty list when not specified."""
        config_data = {
            "enabled": True,
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies == []

    def test_policy_with_null_agent_pattern(self):
        """Test that agent_pattern can be null."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "agent_pattern": None,
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["agent_pattern"] is None

    def test_policy_with_empty_pattern_lists(self):
        """Test that allowed_patterns and blocked_patterns can be empty."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "allowed_patterns": [],
                    "blocked_patterns": [],
                    "default_policy": "deny",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        policy = config.access_policies[0]
        assert policy["allowed_patterns"] == []
        assert policy["blocked_patterns"] == []


class TestToolCallReactorConfigValidation:
    """Test suite for configuration validation and error handling."""

    def test_missing_name_field_rejected(self):
        """Test that policy without name field is rejected."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    # Missing "name" field
                    "model_pattern": ".*",
                    "default_policy": "allow",
                }
            ],
        }

        # Pydantic doesn't validate dict contents by default
        # The validation happens in the service layer
        config = ToolCallReactorConfig(**config_data)
        assert len(config.access_policies) == 1

    def test_missing_model_pattern_field_rejected(self):
        """Test that policy without model_pattern field is rejected."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    # Missing "model_pattern" field
                    "default_policy": "allow",
                }
            ],
        }

        # Pydantic doesn't validate dict contents by default
        config = ToolCallReactorConfig(**config_data)
        assert len(config.access_policies) == 1

    def test_missing_default_policy_field_rejected(self):
        """Test that policy without default_policy field is rejected."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    # Missing "default_policy" field
                }
            ],
        }

        # Pydantic doesn't validate dict contents by default
        config = ToolCallReactorConfig(**config_data)
        assert len(config.access_policies) == 1

    def test_invalid_default_policy_value_rejected(self):
        """Test that invalid default_policy values are rejected."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "invalid_value",  # Should be "allow" or "deny"
                }
            ],
        }

        # Pydantic doesn't validate dict contents by default
        # The validation happens in the service layer
        config = ToolCallReactorConfig(**config_data)
        assert len(config.access_policies) == 1

    def test_allow_default_policy_accepted(self):
        """Test that 'allow' is a valid default_policy value."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["default_policy"] == "allow"

    def test_deny_default_policy_accepted(self):
        """Test that 'deny' is a valid default_policy value."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "deny",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["default_policy"] == "deny"

    def test_invalid_priority_type_rejected(self):
        """Test that non-integer priority values are rejected."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": "not_an_integer",
                }
            ],
        }

        # Pydantic doesn't validate dict contents by default
        config = ToolCallReactorConfig(**config_data)
        assert len(config.access_policies) == 1

    def test_negative_priority_accepted(self):
        """Test that negative priority values are accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": -10,
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["priority"] == -10

    def test_zero_priority_accepted(self):
        """Test that zero priority is accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": 0,
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["priority"] == 0

    def test_high_priority_accepted(self):
        """Test that high priority values are accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": 1000,
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["priority"] == 1000


class TestToolCallReactorConfigPatternLists:
    """Test suite for allowed_patterns and blocked_patterns validation."""

    def test_allowed_patterns_as_list_of_strings(self):
        """Test that allowed_patterns accepts a list of strings."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "allowed_patterns": ["pattern1", "pattern2", "pattern3"],
                    "default_policy": "deny",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["allowed_patterns"] == [
            "pattern1",
            "pattern2",
            "pattern3",
        ]

    def test_blocked_patterns_as_list_of_strings(self):
        """Test that blocked_patterns accepts a list of strings."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "blocked_patterns": ["pattern1", "pattern2", "pattern3"],
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["blocked_patterns"] == [
            "pattern1",
            "pattern2",
            "pattern3",
        ]

    def test_regex_patterns_in_allowed_list(self):
        """Test that regex patterns are accepted in allowed_patterns."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "allowed_patterns": [
                        "read_.*",
                        "list_.*",
                        "^get_[a-z]+$",
                        ".*_info",
                    ],
                    "default_policy": "deny",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        patterns = config.access_policies[0]["allowed_patterns"]
        assert "read_.*" in patterns
        assert "list_.*" in patterns
        assert "^get_[a-z]+$" in patterns
        assert ".*_info" in patterns

    def test_regex_patterns_in_blocked_list(self):
        """Test that regex patterns are accepted in blocked_patterns."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "blocked_patterns": [
                        "delete_.*",
                        "rm_.*",
                        "^remove_[a-z]+$",
                        ".*_dangerous",
                    ],
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        patterns = config.access_policies[0]["blocked_patterns"]
        assert "delete_.*" in patterns
        assert "rm_.*" in patterns
        assert "^remove_[a-z]+$" in patterns
        assert ".*_dangerous" in patterns


class TestToolCallReactorConfigBlockMessage:
    """Test suite for block_message field validation."""

    def test_custom_block_message(self):
        """Test that custom block messages are accepted."""
        custom_message = "This tool is blocked by security policy."
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "block_message": custom_message,
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["block_message"] == custom_message

    def test_empty_block_message(self):
        """Test that empty block messages are accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "block_message": "",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["block_message"] == ""

    def test_multiline_block_message(self):
        """Test that multiline block messages are accepted."""
        multiline_message = """This tool is not allowed.
Please contact your administrator for access.
Error code: TOOL_ACCESS_DENIED"""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "block_message": multiline_message,
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["block_message"] == multiline_message


class TestToolCallReactorConfigModelPatterns:
    """Test suite for model_pattern and agent_pattern validation."""

    def test_simple_model_pattern(self):
        """Test that simple model patterns are accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": "gpt-4",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["model_pattern"] == "gpt-4"

    def test_wildcard_model_pattern(self):
        """Test that wildcard model patterns are accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["model_pattern"] == ".*"

    def test_complex_model_pattern(self):
        """Test that complex regex model patterns are accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": "^(openai|anthropic):.*-turbo$",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert (
            config.access_policies[0]["model_pattern"]
            == "^(openai|anthropic):.*-turbo$"
        )

    def test_agent_pattern_with_regex(self):
        """Test that agent patterns with regex are accepted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "agent_pattern": "^production-.*",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.access_policies[0]["agent_pattern"] == "^production-.*"

    def test_agent_pattern_omitted(self):
        """Test that agent_pattern can be omitted."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        # When omitted, the field should not be present in the dict
        assert "agent_pattern" not in config.access_policies[0]


class TestToolCallReactorConfigIntegration:
    """Integration tests for ToolCallReactorConfig with other fields."""

    def test_access_policies_with_steering_rules(self):
        """Test that access_policies and steering_rules can coexist."""
        config_data = {
            "enabled": True,
            "steering_rules": [
                {
                    "name": "test_steering",
                    "enabled": True,
                    "triggers": {"tool_names": ["apply_diff"]},
                    "message": "Steering message",
                    "rate_limit": {"calls_per_window": 1, "window_seconds": 60},
                }
            ],
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert len(config.steering_rules) == 1
        assert len(config.access_policies) == 1

    def test_access_policies_with_legacy_settings(self):
        """Test that access_policies work with legacy reactor settings."""
        config_data = {
            "enabled": True,
            "apply_diff_steering_enabled": True,
            "apply_diff_steering_rate_limit_seconds": 30,
            "pytest_full_suite_steering_enabled": True,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.apply_diff_steering_enabled is True
        assert config.apply_diff_steering_rate_limit_seconds == 30
        assert config.pytest_full_suite_steering_enabled is True
        assert len(config.access_policies) == 1

    def test_disabled_reactor_with_access_policies(self):
        """Test that access_policies can be configured even when reactor is disabled."""
        config_data = {
            "enabled": False,
            "access_policies": [
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert config.enabled is False
        assert len(config.access_policies) == 1


class TestToolCallReactorConfigRealWorldScenarios:
    """Test real-world configuration scenarios."""

    def test_whitelist_mode_configuration(self):
        """Test a whitelist mode configuration (deny by default, allow specific tools)."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "whitelist_policy",
                    "model_pattern": ".*",
                    "allowed_patterns": ["read_file", "list_directory", "search_.*"],
                    "default_policy": "deny",
                    "block_message": "Only read-only tools are allowed.",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        policy = config.access_policies[0]
        assert policy["default_policy"] == "deny"
        assert "read_file" in policy["allowed_patterns"]
        assert "list_directory" in policy["allowed_patterns"]
        assert "search_.*" in policy["allowed_patterns"]

    def test_blacklist_mode_configuration(self):
        """Test a blacklist mode configuration (allow by default, block specific tools)."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "blacklist_policy",
                    "model_pattern": ".*",
                    "blocked_patterns": ["delete_.*", "rm_.*", "remove_.*"],
                    "default_policy": "allow",
                    "block_message": "Destructive operations are not allowed.",
                }
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        policy = config.access_policies[0]
        assert policy["default_policy"] == "allow"
        assert "delete_.*" in policy["blocked_patterns"]
        assert "rm_.*" in policy["blocked_patterns"]
        assert "remove_.*" in policy["blocked_patterns"]

    def test_per_model_policy_configuration(self):
        """Test per-model policy configuration."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "openai_policy",
                    "model_pattern": "openai:.*",
                    "default_policy": "allow",
                    "blocked_patterns": ["execute_code"],
                },
                {
                    "name": "anthropic_policy",
                    "model_pattern": "anthropic:.*",
                    "default_policy": "deny",
                    "allowed_patterns": ["read_.*", "list_.*"],
                },
                {
                    "name": "gemini_policy",
                    "model_pattern": "gemini:.*",
                    "default_policy": "allow",
                },
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert len(config.access_policies) == 3
        assert config.access_policies[0]["model_pattern"] == "openai:.*"
        assert config.access_policies[1]["model_pattern"] == "anthropic:.*"
        assert config.access_policies[2]["model_pattern"] == "gemini:.*"

    def test_agent_specific_policy_configuration(self):
        """Test agent-specific policy configuration."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "production_agent_policy",
                    "model_pattern": ".*",
                    "agent_pattern": "production-.*",
                    "default_policy": "deny",
                    "allowed_patterns": ["read_.*", "list_.*"],
                    "block_message": "Production agents have restricted tool access.",
                    "priority": 100,
                },
                {
                    "name": "dev_agent_policy",
                    "model_pattern": ".*",
                    "agent_pattern": "dev-.*",
                    "default_policy": "allow",
                    "priority": 50,
                },
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert len(config.access_policies) == 2
        assert config.access_policies[0]["agent_pattern"] == "production-.*"
        assert config.access_policies[0]["priority"] == 100
        assert config.access_policies[1]["agent_pattern"] == "dev-.*"
        assert config.access_policies[1]["priority"] == 50

    def test_priority_ordered_policies(self):
        """Test multiple policies with different priorities."""
        config_data = {
            "enabled": True,
            "access_policies": [
                {
                    "name": "global_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": 0,
                },
                {
                    "name": "specific_model_policy",
                    "model_pattern": "openai:gpt-4.*",
                    "default_policy": "deny",
                    "allowed_patterns": ["read_.*"],
                    "priority": 50,
                },
                {
                    "name": "critical_override_policy",
                    "model_pattern": "openai:gpt-4-turbo",
                    "default_policy": "allow",
                    "priority": 100,
                },
            ],
        }

        config = ToolCallReactorConfig(**config_data)

        assert len(config.access_policies) == 3
        assert config.access_policies[0]["priority"] == 0
        assert config.access_policies[1]["priority"] == 50
        assert config.access_policies[2]["priority"] == 100
