"""
Behavior specification tests for project directory auto-detection feature.

These tests specify the expected behavior of the project directory resolution system
in realistic conversation scenarios that would be encountered in production use,
ensuring the system behaves appropriately in common edge cases and typical usage patterns.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session, SessionState
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


class TestProjectDirectoryDetectionBehavior:
    """
    Behavior specifications for project directory auto-detection in realistic scenarios.

    Given: User prompts containing project directory references in various formats
    When: Project directory resolution is triggered
    Then: Should correctly extract and persist project directories
    """

    @pytest.mark.asyncio
    async def test_windows_absolute_path_detection(self):
        """
        Given: User explicitly provides Windows absolute path
        When: Deterministic resolution is triggered
        Then: Should detect and persist the exact Windows path
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="windows_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Windows path scenarios
        windows_prompts = [
            "Work on my project at C:\\Users\\John\\Documents\\MyApp",
            "Let's modify D:\\Projects\\webapp\\src\\main.js",
            "Please analyze the code in E:\\Development\\python-project\\src"
        ]

        for prompt in windows_prompts:
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir is not None
            assert session.state.project_dir_resolution_attempted is True
            mock_session.update_session.assert_called_once_with(session)

            # Verify path was extracted correctly
            expected_path = None
            if "C:\\Users\\John\\Documents\\MyApp" in prompt:
                expected_path = "C:\\Users\\John\\Documents\\MyApp"
            elif "D:\\Projects\\webapp\\src\\main.js" in prompt:
                expected_path = "D:\\Projects\\webapp"
            elif "E:\\Development\\python-project\\src" in prompt:
                expected_path = "E:\\Development\\python-project"

            assert session.state.project_dir == expected_path

            # Reset for next iteration
            session.state = SessionState()
            mock_session.reset_mock()

    @pytest.mark.asyncio
    async def test_unix_absolute_path_detection(self):
        """
        Given: User explicitly provides Unix/Linux absolute path
        When: Deterministic resolution is triggered
        Then: Should detect and persist the exact Unix path
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="unix_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Unix path scenarios
        unix_prompts = [
            "Help me with my project in /home/user/website",
            "Let's fix the code in /var/www/html/app",
            "Working on Python project at /home/dev/projects/ml-experiment"
        ]

        for prompt in unix_prompts:
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir is not None
            assert session.state.project_dir_resolution_attempted is True

            # Verify path was extracted correctly
            expected_path = None
            if "/home/user/website" in prompt:
                expected_path = "/home/user/website"
            elif "/var/www/html/app" in prompt:
                expected_path = "/var/www/html/app"
            elif "/home/dev/projects/ml-experiment" in prompt:
                expected_path = "/home/dev/projects/ml-experiment"

            assert session.state.project_dir == expected_path

            # Reset for next iteration
            session.state = SessionState()
            mock_session.reset_mock()

    @pytest.mark.asyncio
    async def test_unc_path_detection(self):
        """
        Given: User provides UNC network path
        When: Deterministic resolution is triggered
        Then: Should detect and normalize UNC path correctly
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="unc_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # UNC path scenarios
        unc_prompts = [
            "Open project on \\\\server01\\share\\project-folder",
            "Access files at \\\\\\\\file-server\\\\projects\\\\webapp",  # Extra backslashes
            "Work on code in \\\\network-share\\development\\team-project"
        ]

        for prompt in unc_prompts:
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir is not None
            assert session.state.project_dir_resolution_attempted is True

            # Verify UNC path was normalized correctly
            assert session.state.project_dir.startswith("\\\\")

            # Reset for next iteration
            session.state = SessionState()
            mock_session.reset_mock()

    @pytest.mark.asyncio
    async def test_hybrid_mode_fallback_behavior(self):
        """
        Given: User prompt without explicit paths in hybrid mode
        When: Deterministic resolution fails and LLM resolution succeeds
        Then: Should fallback to LLM and persist detected directory
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="hybrid",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="hybrid_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Mock LLM response
        llm_response = ResponseEnvelope(
            content="<directory-resolution-response><project-absolute-directory>/home/user/my-project</project-absolute-directory></directory-resolution-response>"
        )
        mock_backend.call_completion.return_value = llm_response

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="I want to work on my web development project")]
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then
        assert session.state.project_dir == "/home/user/my-project"
        assert session.state.project_dir_resolution_attempted is True
        mock_backend.call_completion.assert_called_once()
        mock_session.update_session.assert_called_once_with(session)

    @pytest.mark.asyncio
    async def test_llm_mode_xml_parsing_errors(self):
        """
        Given: LLM returns malformed XML response
        When: XML parsing fails in LLM mode
        Then: Should handle gracefully and not persist invalid directory
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="llm",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="llm_error_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Mock malformed XML responses
        malformed_responses = [
            ResponseEnvelope(content="<invalid>no closing tag"),
            ResponseEnvelope(content="plain text response"),
            ResponseEnvelope(content="<directory-resolution-response><wrong-tag>/path</wrong-tag></directory-resolution-response>"),
        ]

        for malformed_response in malformed_responses:
            mock_backend.call_completion.return_value = malformed_response

            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="work on my project")]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir is None  # Should not persist invalid result
            assert session.state.project_dir_resolution_attempted is True

            # Reset for next iteration
            session.state = SessionState()
            mock_backend.reset_mock()

    @pytest.mark.asyncio
    async def test_only_runs_on_first_prompt(self):
        """
        Given: Session with existing history
        When: Project directory resolution is attempted on subsequent prompts
        Then: Should skip detection and not modify existing state
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()

        # Create session with existing history
        session = Session(
            session_id="history_test",
            state=SessionState(),
            history=[ChatMessage(role="user", content="previous message")]
        )

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Work on C:\\Project\\new")]
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then
        assert session.state.project_dir is None  # Should not be set
        assert session.state.project_dir_resolution_attempted is False  # Should not be marked
        mock_backend.call_completion.assert_not_called()
        mock_session.update_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_respects_existing_directory_setting(self):
        """
        Given: Session with already set project directory
        When: New prompt with different directory path arrives
        Then: Should preserve existing directory and not attempt resolution
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()

        # Session with pre-existing project directory
        session = Session(
            session_id="existing_dir_test",
            state=SessionState(project_dir="/existing/project/path")
        )

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Work on C:\\NewProject")]
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then
        assert session.state.project_dir == "/existing/project/path"  # Should remain unchanged
        mock_backend.call_completion.assert_not_called()
        mock_session.update_session.assert_called_once()  # Should log the skip message

    @pytest.mark.asyncio
    async def test_complex_real_world_prompts(self):
        """
        Given: Complex real-world prompts with mixed content and paths
        When: Deterministic resolution processes these prompts
        Then: Should correctly extract paths from noisy content
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="complex_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Complex real-world prompts
        complex_prompts = [
            "Hey there! I'm having some issues with my React application. The project is located at C:\\Users\\Sarah\\Desktop\\react-app. Can you help me debug the component issue?",
            "I need to refactor my Python code. The repository is in /home/developer/projects/data-analysis. I'm getting a pandas error that I can't figure out.",
            "My team is working on a shared project on the network drive. The path is \\\\fileserver\\team-projects\\web-portal. We need to implement a new feature.",
        ]

        expected_paths = [
            "C:\\Users\\Sarah\\Desktop\\react-app",
            "/home/developer/projects/data-analysis",
            "\\\\fileserver\\team-projects\\web-portal"
        ]

        for prompt, expected_path in zip(complex_prompts, expected_paths):
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir == expected_path

            # Reset for next iteration
            session.state = SessionState()
            mock_session.reset_mock()

    @pytest.mark.asyncio
    async def test_streaming_response_handling(self):
        """
        Given: LLM backend returns streaming response
        When: Project directory resolution attempts to process response
        Then: Should handle gracefully and not persist directory
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="llm",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="streaming_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Mock streaming response (different type than ResponseEnvelope)
        from src.core.domain.responses import StreamingResponseEnvelope
        streaming_response = StreamingResponseEnvelope()
        mock_backend.call_completion.return_value = streaming_response

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="work on my project")]
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then
        assert session.state.project_dir is None
        assert session.state.project_dir_resolution_attempted is True
        mock_backend.call_completion.assert_called_once()
        mock_session.update_session.assert_called_once_with(session)

    @pytest.mark.asyncio
    async def test_session_persistence_failure_handling(self):
        """
        Given: Session service fails to persist state
        When: Project directory resolution attempts to save results
        Then: Should handle gracefully without raising exceptions
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        mock_session.update_session.side_effect = Exception("Database connection failed")

        session = Session(session_id="persistence_error_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Work on C:\\TestProject")]
        )

        # When/Then - Should not raise exception
        await service.maybe_resolve_project_directory(session, request)

        # State should be updated locally even if persistence fails
        assert session.state.project_dir == "C:\\TestProject"
        assert session.state.project_dir_resolution_attempted is True

    @pytest.mark.asyncio
    async def test_multiple_path_extraction_priority(self):
        """
        Given: User prompt contains multiple possible paths
        When: Deterministic resolution processes the prompt
        Then: Should extract the first (most specific) path found
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="multi_path_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Prompt with multiple paths
        prompt = "I have two projects: one at C:\\ProjectA and another at /home/user/projectB. Let's work on the first one."
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content=prompt)]
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then - Should extract the first path found (C:\\ProjectA)
        assert session.state.project_dir == "C:\\ProjectA"


class TestEdgeCaseScenarios:
    """
    Behavior specifications for edge cases in project directory detection.

    Given: Unusual or edge case scenarios that may occur in production
    When: Project directory resolution processes these scenarios
    Then: Should handle appropriately without false positives or errors
    """

    @pytest.mark.asyncio
    async def test_empty_user_prompt(self):
        """
        Given: Empty or whitespace-only user prompt
        When: Project directory resolution is triggered
        Then: Should handle gracefully without attempting resolution
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="empty_prompt_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        empty_prompts = ["", "   ", "\n\n\t", "   \n  "]

        for empty_prompt in empty_prompts:
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=empty_prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir is None
            assert session.state.project_dir_resolution_attempted is True

            # Reset for next iteration
            session.state = SessionState()
            mock_session.reset_mock()

    @pytest.mark.asyncio
    async def test_relative_paths_only(self):
        """
        Given: User prompt contains only relative paths
        When: Deterministic resolution is triggered
        Then: Should not extract relative paths as project directories
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="relative_path_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Prompts with only relative paths
        relative_prompts = [
            "Work on ./src/main.js",
            "Fix the bug in ../lib/utils.py",
            "Check the files in docs/ folder",
            "Navigate to ./components/Button.jsx"
        ]

        for prompt in relative_prompts:
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir is None  # Should not extract relative paths

            # Reset for next iteration
            session.state = SessionState()
            mock_session.reset_mock()

    @pytest.mark.asyncio
    async def test_malformed_paths(self):
        """
        Given: User prompt contains malformed path-like strings
        When: Deterministic resolution is triggered
        Then: Should not extract invalid paths
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="malformed_path_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Prompts with malformed paths
        malformed_prompts = [
            "Check C::invalid\\path",
            "Look at /path/with/newlines\\n/in/it",
            "Access Z:drive without backslash",
            "Network path with only one backslash: \\server\\share"
        ]

        for prompt in malformed_prompts:
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir is None  # Should not extract malformed paths

            # Reset for next iteration
            session.state = SessionState()
            mock_session.reset_mock()

    @pytest.mark.asyncio
    async def test_unicode_and_special_characters(self):
        """
        Given: User prompt contains paths with unicode and special characters
        When: Deterministic resolution is triggered
        Then: Should correctly extract paths with special characters
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="unicode_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Prompts with unicode and special characters
        unicode_prompts = [
            "Work on C:\\Users\\José\\Documents\\Mi Proyecto",
            "Access the project at /home/user/проект/код",
            "Open folder in D:\\Dev\\test-project (copy)\\files",
            "Navigate to C:\\Project with spaces\\src"
        ]

        for prompt in unicode_prompts:
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert session.state.project_dir is not None
            assert session.state.project_dir_resolution_attempted is True

            # Reset for next iteration
            session.state = SessionState()
            mock_session.reset_mock()

    @pytest.mark.asyncio
    async def test_very_long_paths(self):
        """
        Given: User prompt contains extremely long paths
        When: Deterministic resolution is triggered
        Then: Should handle long paths correctly
        """
        # Given
        config = AppConfig(session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4"
        ))
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="long_path_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Create a very long path
        long_path = "C:\\" + "\\very\\long\\directory\\name\\" * 20 + "project"
        prompt = f"Work on my project at {long_path}"

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content=prompt)]
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then
        assert session.state.project_dir == long_path
        assert session.state.project_dir_resolution_attempted is True