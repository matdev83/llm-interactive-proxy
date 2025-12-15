"""
Behavior specification tests for project directory auto-detection feature.

These tests specify the expected behavior of the project directory resolution system
in realistic conversation scenarios that would be encountered in production use,
ensuring the system behaves appropriately in common edge cases and typical usage patterns.
"""

from pathlib import PureWindowsPath
from unittest.mock import AsyncMock

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session, SessionState
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


@pytest.fixture(autouse=True)
def mock_filesystem_check(monkeypatch):
    """
    Disable filesystem checks for behavior tests.

    Since these tests use hypothetical paths that likely don't exist on the test runner's
    machine (or might exist coincidentally), we mock the dot-entries check to return None
    (which means 'unknown/skip check'). This ensures the tests focus purely on path detection
    logic and not on whether the paths actually exist on disk.
    """
    monkeypatch.setattr(
        ProjectDirectoryResolutionService,
        "_dot_entries_status",
        lambda self, directory: None,
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="windows_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Windows path scenarios
        windows_prompts = [
            "Work on my project at C:\\Users\\John\\Documents\\MyApp",
            "Let's modify D:\\Projects\\Internal\\webapp\\src\\main.js",
            "Please analyze the code in E:\\Development\\Teams\\python-project\\src",
        ]

        for prompt in windows_prompts:
            request = ChatRequest(
                model="test-model", messages=[ChatMessage(role="user", content=prompt)]
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
            elif "D:\\Projects\\Internal\\webapp\\src\\main.js" in prompt:
                expected_path = "D:\\Projects\\Internal\\webapp"
            elif "E:\\Development\\Teams\\python-project\\src" in prompt:
                expected_path = "E:\\Development\\Teams\\python-project"

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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="unix_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Unix path scenarios
        unix_prompts = [
            "Help me with my project in /home/user/website",
            "Let's fix the code in /var/www/html/app",
            "Working on Python project at /home/dev/projects/ml-experiment",
        ]

        for prompt in unix_prompts:
            # Create fresh session for each test case to avoid state contamination
            session = Session(session_id="unix_test", state=SessionState())
            request = ChatRequest(
                model="test-model", messages=[ChatMessage(role="user", content=prompt)]
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="unc_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # UNC path scenarios
        unc_prompts = [
            "Open project on \\\\server01\\share\\dept\\team\\src\\project-folder",
            "Access files at \\\\\\\\file-server\\\\projects\\\\internal\\\\team\\\\group\\\\webapp",  # Extra backslashes
            "Work on code in \\\\network-share\\development\\backend\\main\\team-project",
        ]

        for prompt in unc_prompts:
            request = ChatRequest(
                model="test-model", messages=[ChatMessage(role="user", content=prompt)]
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="hybrid",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
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
            messages=[
                ChatMessage(
                    role="user", content="I want to work on my web development project"
                )
            ],
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="llm",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="llm_error_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Mock malformed XML responses
        malformed_responses = [
            ResponseEnvelope(content="<invalid>no closing tag"),
            ResponseEnvelope(content="plain text response"),
            ResponseEnvelope(
                content="<directory-resolution-response><wrong-tag>/path</wrong-tag></directory-resolution-response>"
            ),
        ]

        for malformed_response in malformed_responses:
            mock_backend.call_completion.return_value = malformed_response

            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="work on my project")],
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert (
                session.state.project_dir is None
            )  # Should not persist invalid result
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()

        # Create session with existing history
        session = Session(
            session_id="history_test",
            state=SessionState(),
            history=[ChatMessage(role="user", content="previous message")],
        )

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Work on C:\\Project\\new")],
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then
        assert session.state.project_dir is None  # Should not be set
        assert (
            session.state.project_dir_resolution_attempted is False
        )  # Should not be marked
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()

        # Session with pre-existing project directory
        session = Session(
            session_id="existing_dir_test",
            state=SessionState(project_dir="/existing/project/path"),
        )

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Work on C:\\NewProject")],
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then
        assert (
            session.state.project_dir == "/existing/project/path"
        )  # Should remain unchanged
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="complex_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Complex real-world prompts
        complex_prompts = [
            "Hey there! I'm having some issues with my React application. The project is located at C:\\Users\\Sarah\\Desktop\\react-app. Can you help me debug the component issue?",
            "I need to refactor my Python code. The repository is in /home/developer/projects/data-analysis. I'm getting a pandas error that I can't figure out.",
            "My team is working on a shared project on the network drive. The path is \\\\fileserver\\team-projects\\frontend\\src\\web-portal. We need to implement a new feature.",
        ]

        expected_paths = [
            "C:\\Users\\Sarah\\Desktop\\react-app",
            "/home/developer/projects/data-analysis",
            "\\\\fileserver\\team-projects\\frontend\\src\\web-portal",
        ]

        for prompt, expected_path in zip(complex_prompts, expected_paths, strict=False):
            request = ChatRequest(
                model="test-model", messages=[ChatMessage(role="user", content=prompt)]
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="llm",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
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
            messages=[ChatMessage(role="user", content="work on my project")],
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        mock_session.update_session.side_effect = Exception(
            "Database connection failed"
        )

        session = Session(session_id="persistence_error_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="user", content="Work on C:\\Users\\User\\TestProject")
            ],
        )

        # When/Then - Should not raise exception
        await service.maybe_resolve_project_directory(session, request)

        # State should be updated locally even if persistence fails
        assert session.state.project_dir == "C:\\Users\\User\\TestProject"
        assert session.state.project_dir_resolution_attempted is True

    @pytest.mark.asyncio
    async def test_multiple_path_extraction_priority(self):
        """
        Given: User prompt contains multiple possible paths
        When: Deterministic resolution processes the prompt
        Then: Should extract the first (most specific) path found
        """
        # Given
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="multi_path_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Prompt with multiple paths
        prompt = "I have two projects: one at C:\\ProjectA and another at /home/user/projectB. Let's work on the first one."
        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content=prompt)]
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then - Should extract the most reasonable path (Unix path wins due to depth)
        assert session.state.project_dir == "/home/user/projectB"

    @pytest.mark.asyncio
    async def test_project_directory_persistence_across_session_lifecycle(self):
        """
        Given: A new session with project directory auto-detection enabled
        When: Multiple request/response exchanges occur over the session lifecycle
        Then: Project directory should be detected once and persist throughout all subsequent requests
        """
        # Given
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session_id = "persistence_test_session"

        # Create new session (no history, no existing project_dir)
        session = Session(session_id=session_id, state=SessionState())
        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Initial request with project directory path
        initial_request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user",
                    content="Help me work on my project at C:\\Users\\Developer\\my-awesome-app\\src\\main.py",
                )
            ],
        )

        # When - First request: Should detect and set project directory
        await service.maybe_resolve_project_directory(session, initial_request)

        # Then - Verify initial detection
        assert session.state.project_dir == "C:\\Users\\Developer\\my-awesome-app"
        assert session.state.project_dir_resolution_attempted is True
        mock_session.update_session.assert_called_once_with(session)

        # Given - Add history to simulate ongoing conversation
        session.history.extend(
            [
                ChatMessage(
                    role="assistant", content="I'll help you with your project!"
                ),
                ChatMessage(
                    role="user",
                    content="Show me the dependencies in C:\\Users\\Developer\\my-awesome-app\\requirements.txt",
                ),
                ChatMessage(role="assistant", content="Here are your dependencies..."),
                ChatMessage(
                    role="user", content="Let's refactor the code in the utils folder"
                ),
            ]
        )

        # Reset mock for subsequent calls
        mock_session.reset_mock()

        # When - Second request: Should NOT attempt detection again
        second_request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user", content="Let's refactor the code in the utils folder"
                ),
                ChatMessage(
                    role="assistant", content="I'll help you refactor the utils folder"
                ),
            ],
        )
        await service.maybe_resolve_project_directory(session, second_request)

        # Then - Verify no re-detection occurred (should be skipped due to history)
        mock_session.update_session.assert_not_called()
        assert (
            session.state.project_dir == "C:\\Users\\Developer\\my-awesome-app"
        )  # Still preserved
        assert session.state.project_dir_resolution_attempted is True  # Flag still set

        # Given - Add more conversation history
        session.history.extend(
            [
                ChatMessage(
                    role="assistant", content="I've refactored the utils folder"
                ),
                ChatMessage(
                    role="user", content="Great! Now let's add tests for the new utils"
                ),
                ChatMessage(role="assistant", content="I'll help you write tests"),
                ChatMessage(
                    role="user",
                    content="Also check the configuration in C:\\Users\\Developer\\my-awesome-app\\config",
                ),
            ]
        )

        # When - Third request with same project path mentioned again: Still should skip detection
        third_request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user",
                    content="Also check the configuration in C:\\Users\\Developer\\my-awesome-app\\config",
                ),
                ChatMessage(
                    role="assistant", content="I'll examine the configuration files"
                ),
            ],
        )
        await service.maybe_resolve_project_directory(session, third_request)

        # Then - Verify project directory persists unchanged
        assert session.state.project_dir == "C:\\Users\\Developer\\my-awesome-app"
        mock_session.update_session.assert_not_called()  # No session update for skipped detection

        # When - Fourth request: Different type of request, still no detection
        fourth_request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="user", content="Run the test suite"),
                ChatMessage(role="assistant", content="I'll run the tests"),
            ],
        )
        await service.maybe_resolve_project_directory(session, fourth_request)

        # Then - Final verification: project directory still persists after multiple exchanges
        assert session.state.project_dir == "C:\\Users\\Developer\\my-awesome-app"
        assert session.state.project_dir_resolution_attempted is True
        assert len(session.history) >= 8  # Verify conversation has progressed

        # Verify the detection flag remains set but no further detection attempts were made
        mock_session.update_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_project_directory_persistence_with_explicit_session_updates(self):
        """
        Given: A session where project directory is detected and session state is explicitly updated
        When: Session state is manually updated between requests (simulating real session persistence)
        Then: Project directory should persist across state updates and subsequent requests
        """
        # Given
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session_id = "explicit_persistence_test"

        # Start with fresh session
        session = Session(session_id=session_id, state=SessionState())
        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Initial request with Unix path this time
        initial_request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user",
                    content="Work on my Python project at /home/user/projects/data-analysis",
                )
            ],
        )

        # When - Initial detection
        await service.maybe_resolve_project_directory(session, initial_request)

        # Then - Verify detection
        assert session.state.project_dir == "/home/user/projects/data-analysis"
        assert session.state.project_dir_resolution_attempted is True

        # Given - Simulate explicit session state update (like what happens in real session persistence)
        # This simulates the session being saved and reloaded with the same state
        updated_state = session.state.with_project_dir_resolution_attempted(True)
        session.state = updated_state

        # Add conversation history
        session.history.extend(
            [
                ChatMessage(
                    role="assistant",
                    content="I'll help you with your data analysis project",
                ),
                ChatMessage(role="user", content="Let's examine the datasets"),
            ]
        )

        # Reset mock to track new calls
        mock_session.reset_mock()

        # When - Subsequent request with history present
        subsequent_request = ChatRequest(
            model="test-model",
            messages=[
                *session.history,
                ChatMessage(role="user", content="What's in the src directory?"),
            ],
        )
        await service.maybe_resolve_project_directory(session, subsequent_request)

        # Then - Verify detection was skipped and project directory persisted
        mock_session.update_session.assert_not_called()  # No update needed
        assert (
            session.state.project_dir == "/home/user/projects/data-analysis"
        )  # Unchanged

        # Verify the session has evolved but project_dir remains constant
        assert len(session.history) >= 2

    @pytest.mark.asyncio
    async def test_project_directory_persistence_with_preexisting_directory(self):
        """
        Given: A session that already has a project directory set
        When: New requests come in with different project paths in the content
        Then: Should preserve the existing project directory and not attempt new detection
        """
        # Given
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()

        # Session with pre-existing project directory
        existing_project_dir = "/existing/project/path"
        session = Session(
            session_id="preexisting_test",
            state=SessionState(project_dir=existing_project_dir),
        )
        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # When - Request with different project path mentioned
        request_with_different_path = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user",
                    content="Work on the code at /different/project/path/main.py",
                )
            ],
        )
        await service.maybe_resolve_project_directory(
            session, request_with_different_path
        )

        # Then - Should preserve existing directory and not detect new one
        assert session.state.project_dir == existing_project_dir  # Unchanged
        assert session.state.project_dir_resolution_attempted is True
        mock_session.update_session.assert_called_once()  # Called to log the skip message

        # When - Another request yet another path (should be skipped due to attempted flag)
        another_request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="user", content="Check C:\\Another\\Project\\files")
            ],
        )
        await service.maybe_resolve_project_directory(session, another_request)

        # Then - Still should preserve original directory and no additional calls
        assert session.state.project_dir == existing_project_dir
        assert (
            mock_session.update_session.call_count == 1
        )  # No additional calls (skipped due to attempted flag)


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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="empty_prompt_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        empty_prompts = ["", "   ", "\n\n\t", "   \n  "]

        for empty_prompt in empty_prompts:
            request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content=empty_prompt)],
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="relative_path_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Prompts with only relative paths
        relative_prompts = [
            "Work on ./src/main.js",
            "Fix the bug in ../lib/utils.py",
            "Check the files in docs/ folder",
            "Navigate to ./components/Button.jsx",
        ]

        for prompt in relative_prompts:
            request = ChatRequest(
                model="test-model", messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert (
                session.state.project_dir is None
            )  # Should not extract relative paths

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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="malformed_path_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Prompts with malformed paths
        malformed_prompts = [
            "Check C::invalid\\path",
            "Look at /path/with/newlines\\n/in/it",
            "Access Z:drive without backslash",
            "Network path with only one backslash: \\server\\share",
        ]

        for prompt in malformed_prompts:
            request = ChatRequest(
                model="test-model", messages=[ChatMessage(role="user", content=prompt)]
            )

            # When
            await service.maybe_resolve_project_directory(session, request)

            # Then
            assert (
                session.state.project_dir is None
            )  # Should not extract malformed paths

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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="unicode_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Prompts with unicode and special characters
        unicode_prompts = [
            "Work on C:\\Users\\José\\Documents\\Mi Proyecto",
            "Access the project at /home/user/проект/код",
            "Open folder in D:\\Dev\\test-project-(copy)\\files",
            "Navigate to C:\\Users\\Project_with_spaces\\code",
        ]

        for prompt in unicode_prompts:
            request = ChatRequest(
                model="test-model", messages=[ChatMessage(role="user", content=prompt)]
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
        config = AppConfig(
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                project_dir_resolution_model="openai:gpt-4",
            )
        )
        mock_backend = AsyncMock()
        mock_session = AsyncMock()
        session = Session(session_id="long_path_test", state=SessionState())

        service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

        # Create a very long path
        long_path = "C:\\" + "\\very\\long\\directory\\name\\" * 20 + "project"
        prompt = f"Work on my project at {long_path}"

        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content=prompt)]
        )

        # When
        await service.maybe_resolve_project_directory(session, request)

        # Then
        expected_path = str(PureWindowsPath(long_path))
        assert session.state.project_dir == expected_path
        assert session.state.project_dir_resolution_attempted is True
