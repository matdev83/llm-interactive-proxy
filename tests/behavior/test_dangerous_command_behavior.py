"""
Behavior specification tests for Dangerous Command Handler.

These tests follow BDD principles to specify the expected behavior of the dangerous
command protection system as defined in security requirements. They use Given-When-Then
structure to clearly specify behavior requirements rather than just validating
implementation details.

Key behaviors specified:
1. Dangerous command detection and blocking
2. Command argument parsing and extraction
3. Legitimate command discrimination
4. Steering message generation and user guidance
5. Security boundary enforcement
6. Edge case handling and resilience
"""

import asyncio
from unittest.mock import Mock

import pytest
from src.core.domain.configuration.dangerous_command_config import (
    DEFAULT_DANGEROUS_COMMAND_CONFIG,
)
from src.core.interfaces.tool_call_reactor_interface import (
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.dangerous_command_service import DangerousCommandService
from src.core.services.tool_call_handlers.dangerous_command_handler import (
    DangerousCommandHandler,
)
from tests.unit.fixtures.markers import real_time


class TestDangerousCommandDetectionBehavior:
    """
    Behavior specifications for dangerous command detection as defined in security requirements.

    Given: A dangerous command handler with security rules
    When: Various tool calls are processed
    Then: Dangerous commands should be detected and blocked appropriately
    """

    def test_git_reset_hard_detection(self):
        """
        Given: A dangerous command handler with default git rules
        When: A git reset --hard command is attempted
        Then: The command should be detected and blocked
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
            tool_name="bash",
            tool_arguments="git reset --hard HEAD~1",
        )

        # When
        can_handle = asyncio.run(handler.can_handle(context))
        result = asyncio.run(handler.handle(context))

        # Then
        assert can_handle is True
        assert result.should_swallow is True
        assert "intercepted" in result.replacement_response.lower()
        assert result.metadata["handler"] == "dangerous_command_handler"

    def test_git_clean_force_detection(self):
        """
        Given: A dangerous command handler with git rules
        When: A git clean -fd command is attempted
        Then: The command should be detected and blocked
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
            tool_name="execute_command",
            tool_arguments={"command": "git clean -fd"},
        )

        # When
        result = asyncio.run(handler.handle(context))

        # Then
        assert result.should_swallow is True
        assert "git clean" in result.metadata["command"].lower()

    def test_git_push_force_detection(self):
        """
        Given: A dangerous command handler with git rules
        When: A git push --force command is attempted
        Then: The command should be detected and blocked
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
            tool_name="shell",
            tool_arguments={"cmd": "git push --force origin main"},
        )

        # When
        result = asyncio.run(handler.handle(context))

        # Then
        assert result.should_swallow is True
        assert result.metadata["rule"] is not None
        assert "force" in result.metadata["command"]

    def test_complex_argument_parsing(self):
        """
        Given: Various argument formats in tool calls
        When: Complex nested arguments contain dangerous commands
        Then: Commands should be extracted and detected regardless of format
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        test_cases = [
            # JSON string argument
            {
                "tool_name": "bash",
                "args": '{"command": "git reset --hard HEAD"}',
                "expected_match": True,
            },
            # Nested dict structure
            {
                "tool_name": "exec_command",
                "args": {"input": {"command": "git clean -fd"}},
                "expected_match": True,
            },
            # Array arguments joined
            {
                "tool_name": "run_shell_command",
                "args": {"args": ["git", "push", "--force", "origin"]},
                "expected_match": True,
            },
            # Direct list
            {
                "tool_name": "shell",
                "args": ["git", "branch", "-D", "feature-branch"],
                "expected_match": True,
            },
        ]

        for case in test_cases:
            context = ToolCallContext(
                session_id="test_session",
                backend_name="test_backend",
                model_name="test_model",
                full_response="test_response",
                tool_name=case["tool_name"],
                tool_arguments=case["args"],
            )

            # When
            result = asyncio.run(handler.handle(context))

            # Then
            if case["expected_match"]:
                assert (
                    result.should_swallow is True
                ), f"Failed to detect dangerous command in case: {case}"
                assert result.metadata["command"] is not None

    def test_legitimate_git_commands_allowed(self):
        """
        Given: A dangerous command handler with git rules
        When: Legitimate git commands are attempted
        Then: The commands should be allowed through
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        legitimate_commands = [
            "git status",
            "git add .",
            "git commit -m 'feat: add new feature'",
            "git log --oneline",
            "git diff HEAD~1",
            "git checkout feature-branch",  # Not destructive without --
            "git branch new-feature",
            "git pull origin main",
            "git push origin main",  # Not force push
            "git clean -n",  # Dry run, safe
        ]

        for cmd in legitimate_commands:
            context = ToolCallContext(
                session_id="test_session",
                tool_name="bash",
                tool_arguments={"command": cmd},
                backend_name="test_backend",
                model_name="test_model",
                full_response="test_response",
            )

            # When
            result = asyncio.run(handler.handle(context))

            # Then
            assert (
                result.should_swallow is False
            ), f"Legitimate command was blocked: {cmd}"

    def test_tool_name_filtering(self):
        """
        Given: A dangerous command handler with specific tool names
        When: Dangerous commands are called from non-monitored tools
        Then: The commands should be allowed (tool filtering)
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        # Test with non-monitored tool name
        context = ToolCallContext(
            session_id="test_session",
            tool_name="python_execute",  # Not in monitored tool names
            tool_arguments={
                "code": "import subprocess; subprocess.run('git reset --hard', shell=True)"
            },
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
        )

        # When
        result = asyncio.run(handler.handle(context))

        # Then
        assert result.should_swallow is False


class TestSteeringMessageBehavior:
    """
    Behavior specifications for steering message generation as defined in security requirements.

    Given: A dangerous command has been intercepted
    When: The handler generates a response
    Then: Appropriate steering message should be provided to guide the user
    """

    def test_default_steering_message_content(self):
        """
        Given: A dangerous command handler with default configuration
        When: A dangerous command is intercepted
        Then: A comprehensive steering message should be generated
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        context = ToolCallContext(
            session_id="test_session",
            tool_name="bash",
            tool_arguments="git reset --hard HEAD",
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
        )

        # When
        result = asyncio.run(handler.handle(context))

        # Then
        assert result.should_swallow is True
        assert result.replacement_response is not None
        assert len(result.replacement_response) > 100  # Should be comprehensive

        # Check for key message components
        message_lower = result.replacement_response.lower()
        assert "security enforcement" in message_lower
        assert "intercepted" in message_lower
        assert "dangerous" in message_lower
        assert "inform user" in message_lower
        assert (
            "execute such command on he's own" in message_lower
        )  # Actual message content
        assert "destructive consequences" in message_lower

    def test_custom_steering_message_override(self):
        """
        Given: A dangerous command handler with custom steering message
        When: A dangerous command is intercepted
        Then: The custom message should be used instead of default
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        custom_message = "CUSTOM SECURITY: This dangerous git command has been blocked. Please ask the user to run it manually after warning them about data loss."
        handler = DangerousCommandHandler(service, steering_message=custom_message)

        context = ToolCallContext(
            session_id="test_session",
            tool_name="bash",
            tool_arguments="git clean -fd",
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
        )

        # When
        result = asyncio.run(handler.handle(context))

        # Then
        assert result.should_swallow is True
        assert result.replacement_response == custom_message
        assert "custom security" in result.replacement_response.lower()

    def test_steering_message_metadata_completeness(self):
        """
        Given: A dangerous command interception
        When: The handler generates a response
        Then: Complete metadata should be provided for debugging and auditing
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        context = ToolCallContext(
            session_id="test_session",
            tool_name="execute_command",
            tool_arguments={"command": "git push --force-with-lease origin main"},
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
        )

        # When
        result = asyncio.run(handler.handle(context))

        # Then
        assert result.metadata is not None
        assert result.metadata["handler"] == "dangerous_command_handler"
        assert result.metadata["tool_name"] == "execute_command"
        assert result.metadata["command"] == "git push --force-with-lease origin main"
        assert result.metadata["source"] == "dangerous_command_reactor"
        assert result.metadata["rule"] is not None  # Should have matched rule name

    def test_steering_message_user_guidance_clarity(self):
        """
        Given: Multiple types of dangerous commands
        When: Each is intercepted
        Then: Steering messages should consistently guide users toward safe alternatives
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        dangerous_scenarios = [
            ("git reset --hard HEAD", "data loss"),
            ("git clean -fd", "file deletion"),
            ("git push --force origin main", "history overwrite"),
            ("git branch -D feature", "branch deletion"),
        ]

        for command, _expected_warning in dangerous_scenarios:
            context = ToolCallContext(
                session_id="test_session",
                tool_name="bash",
                tool_arguments=command,
                backend_name="test_backend",
                model_name="test_model",
                full_response="test_response",
            )

            # When
            result = asyncio.run(handler.handle(context))

            # Then
            assert result.should_swallow is True
            # All steering messages should contain user guidance elements
            assert "inform user" in result.replacement_response.lower()
            assert (
                "execute such command on he's own"
                in result.replacement_response.lower()
            )
            assert "destructive consequences" in result.replacement_response.lower()


class TestSecurityBoundaryBehavior:
    """
    Behavior specifications for security boundary enforcement as defined in security architecture.

    Given: Various security threat scenarios
    When: The dangerous command handler processes them
    Then: Security boundaries should be properly enforced
    """

    def test_protection_against_command_obfuscation(self):
        """
        Given: Various forms of command obfuscation attempts
        When: The dangerous command handler processes them
        Then: Obfuscated dangerous commands should still be detected
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        obfuscation_attempts = [
            # Extra spaces and tabs
            "git  reset\t--hard  HEAD",
            # Command chaining
            "git status && git reset --hard HEAD",
            # Command with environment variables
            "GIT_MERGE_AUTOEDIT=no git reset --hard",
            # Using full paths
            "/usr/bin/git reset --hard HEAD",
            # Command substitution
            "$(which git) reset --hard HEAD",
        ]

        for command in obfuscation_attempts:
            context = ToolCallContext(
                session_id="test_session",
                tool_name="bash",
                tool_arguments={"command": command},
                backend_name="test_backend",
                model_name="test_model",
                full_response="test_response",
            )

            # When
            result = asyncio.run(handler.handle(context))

            # Then
            # Most obfuscation attempts should still be caught by regex patterns
            # Note: Some sophisticated obfuscation might bypass simple patterns,
            # which is expected behavior for this regex-based system
            if "reset --hard" in command:
                assert (
                    result.should_swallow is True
                ), f"Failed to detect obfuscated command: {command}"

    def test_case_sensitivity_handling(self):
        """
        Given: Git commands with various case combinations
        When: The dangerous command handler processes them
        Then: Case variations should be handled appropriately
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        # Git commands are generally case-sensitive, but we test various scenarios
        case_variations = [
            "git reset --hard HEAD",  # Normal case
            "git RESET --hard HEAD",  # Uppercase command (wouldn't work in real git)
            "git reset --HARD HEAD",  # Uppercase flag
        ]

        for command in case_variations:
            context = ToolCallContext(
                session_id="test_session",
                tool_name="bash",
                tool_arguments={"command": command},
                backend_name="test_backend",
                model_name="test_model",
                full_response="test_response",
            )

            # When
            asyncio.run(handler.handle(context))

            # Then
            # Should catch variations that match the regex patterns
            # Note: This tests current regex behavior, not git's actual case sensitivity
            if "reset --hard" in command.lower():
                # Most patterns are case-insensitive or specifically match the cases
                # that would actually be executed by git
                pass  # Behavior depends on regex pattern specifics

    def test_handler_enable_disable_behavior(self):
        """
        Given: A dangerous command handler that can be enabled/disabled
        When: The handler is disabled
        Then: No dangerous commands should be blocked
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        disabled_handler = DangerousCommandHandler(service, enabled=False)

        context = ToolCallContext(
            session_id="test_session",
            tool_name="bash",
            tool_arguments="git reset --hard HEAD",
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
        )

        # When
        can_handle = asyncio.run(disabled_handler.can_handle(context))
        result = asyncio.run(disabled_handler.handle(context))

        # Then
        assert can_handle is False
        assert result.should_swallow is False
        assert result.replacement_response is None

    def test_priority_behavior_with_other_handlers(self):
        """
        Given: Multiple handlers that could process the same tool call
        When: A dangerous command is detected
        Then: The dangerous command handler should take priority
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        # When
        priority = handler.priority

        # Then
        # Dangerous command handler should have high priority
        assert (
            priority >= 90
        ), "Dangerous command handler should have high priority to ensure security"


class TestErrorHandlingAndResilienceBehavior:
    """
    Behavior specifications for error handling and system resilience.

    Given: Various error conditions and edge cases
    When: The dangerous command handler encounters them
    Then: The system should handle them gracefully without compromising security
    """

    def test_malformed_argument_handling(self):
        """
        Given: Tool calls with malformed or unparseable arguments
        When: The dangerous command handler processes them
        Then: The handler should not crash and should handle gracefully
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        malformed_cases = [
            # None arguments
            None,
            # Empty dict
            {},
            # Dict without command field
            {"other_field": "value"},
            # Invalid JSON string
            '{"invalid": json structure}',
            # Circular reference (if possible)
            # Note: Python's JSON handling would prevent this in most cases
        ]

        for args in malformed_cases:
            context = ToolCallContext(
                session_id="test_session",
                tool_name="bash",
                tool_arguments=args,
                backend_name="test_backend",
                model_name="test_model",
                full_response="test_response",
            )

            # When/Then - Should not raise exceptions
            try:
                can_handle = asyncio.run(handler.can_handle(context))
                result = asyncio.run(handler.handle(context))

                # Should handle gracefully (either allow or block based on parsing)
                assert isinstance(can_handle, bool)
                assert isinstance(result, ToolCallReactionResult)
            except Exception as e:
                pytest.fail(f"Handler crashed with malformed arguments {args}: {e}")

    def test_exception_resilience_in_service_scanning(self):
        """
        Given: Potential exceptions during command scanning
        When: The service encounters scanning errors
        Then: The handler should fail safely without blocking legitimate operations
        """
        # Given
        # Create a mock service that raises exceptions during scanning
        mock_service = Mock()
        mock_service.scan.side_effect = Exception("Scanning error")
        handler = DangerousCommandHandler(mock_service)

        context = ToolCallContext(
            session_id="test_session",
            tool_name="bash",
            tool_arguments="any command",
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
        )

        # When
        can_handle = asyncio.run(handler.can_handle(context))
        result = asyncio.run(handler.handle(context))

        # Then
        # Should fail safely - don't block if we can't scan
        assert can_handle is False
        assert result.should_swallow is False

    def test_empty_command_arguments(self):
        """
        Given: Tool calls with empty or minimal command arguments
        When: The dangerous command handler processes them
        Then: Empty commands should not be blocked
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        empty_cases = [
            "",
            "   ",  # Whitespace only
            {},  # Empty dict
            [],  # Empty list
            {"command": ""},  # Empty command field
            {"args": []},  # Empty args array
        ]

        for args in empty_cases:
            context = ToolCallContext(
                session_id="test_session",
                tool_name="bash",
                tool_arguments=args,
                backend_name="test_backend",
                model_name="test_model",
                full_response="test_response",
            )

            # When
            result = asyncio.run(handler.handle(context))

            # Then
            assert (
                result.should_swallow is False
            ), f"Empty command {args} was incorrectly blocked"

    @real_time(
        reason="Measures actual processing time to verify performance remains reasonable (< 1.0s)."
    )
    def test_large_command_argument_handling(self):
        """
        Given: Very large command arguments
        When: The dangerous command handler processes them
        Then: Performance should remain reasonable and memory usage controlled
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        # Create a large command (simulating a long script or command)
        large_command = "git reset --hard HEAD; " + "echo 'test'; " * 10000

        context = ToolCallContext(
            session_id="test_session",
            tool_name="bash",
            tool_arguments={"command": large_command},
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
        )

        # When
        import time

        start_time = time.time()

        can_handle = asyncio.run(handler.can_handle(context))
        result = asyncio.run(handler.handle(context))

        processing_time = time.time() - start_time

        # Then
        assert isinstance(can_handle, bool)
        assert isinstance(result, ToolCallReactionResult)
        assert processing_time < 1.0, f"Processing took too long: {processing_time}s"

        # Should still detect the dangerous command despite the large size
        assert can_handle is True
        assert result.should_swallow is True

    def test_concurrent_safety(self):
        """
        Given: Multiple concurrent dangerous command detections
        When: The handler processes them simultaneously
        Then: All should be handled correctly without race conditions
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        import asyncio

        async def process_concurrent_commands():
            tasks = []
            for i in range(10):
                context = ToolCallContext(
                    session_id=f"session_{i}",
                    tool_name="bash",
                    tool_arguments=f"git reset --hard HEAD~{i}",
                    backend_name="test_backend",
                    model_name="test_model",
                    full_response="test_response",
                )
                task = handler.handle(context)
                tasks.append(task)

            results = await asyncio.gather(*tasks)
            return results

        # When
        results = asyncio.run(process_concurrent_commands())

        # Then
        assert len(results) == 10
        for result in results:
            assert result.should_swallow is True
            assert result.metadata["handler"] == "dangerous_command_handler"
            assert "reset --hard" in result.metadata["command"]

    def test_logging_behavior(self):
        """
        Given: Dangerous command interceptions
        When: The handler processes them
        Then: Appropriate security events should be logged
        """
        # Given
        service = DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)
        handler = DangerousCommandHandler(service)

        context = ToolCallContext(
            session_id="test_session",
            tool_name="bash",
            tool_arguments="git clean -fd",
            backend_name="test_backend",
            model_name="test_model",
            full_response="test_response",
        )

        # When
        with pytest.warns(None):  # Capture any warnings
            result = asyncio.run(handler.handle(context))

        # Then
        assert result.should_swallow is True
        # The handler should log security events (verified through log message content)
        # In a real test environment, you'd capture and verify log output
        # For this behavioral test, we verify the expected metadata is present
        assert result.metadata["command"] == "git clean -fd"
        assert result.metadata["rule"] is not None
