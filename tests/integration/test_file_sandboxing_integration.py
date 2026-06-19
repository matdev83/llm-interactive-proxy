"""
Integration tests for file access sandboxing.

These tests verify the complete sandboxing system including:
- End-to-end sandboxing flow with real tool calls
- Project directory detection integration
- Configuration loading and precedence
- Integration with tool access control
"""

import json
import tempfile
from pathlib import Path

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.domain.responses import ProcessedResponse
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware


class TestFileSandboxingIntegration:
    """Integration tests for file access sandboxing."""

    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def create_config_with_sandboxing(
        self,
        enabled: bool = True,
        strict_mode: bool = False,
        allow_parent_access: bool = False,
    ) -> AppConfig:
        """Helper to create config with sandboxing settings."""
        sandboxing_config = SandboxingConfiguration(
            enabled=enabled,
            strict_mode=strict_mode,
            allow_parent_access=allow_parent_access,
        )

        session_config = SessionConfig(
            project_dir_resolution_mode="deterministic",
            cleanup_enabled=False,
        )

        config = AppConfig()
        config = config.model_copy(
            update={
                "sandboxing": sandboxing_config,
                "session": session_config,
            }
        )
        return config

    def create_service_provider(self, config: AppConfig):
        """Helper to create service provider with config."""
        collection = ServiceCollection()
        register_core_services(collection, config)
        provider = collection.build_service_provider()

        # Manually register sandboxing handler if enabled
        if config.sandboxing.enabled:
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.file_sandboxing_handler import FileSandboxingHandler
            from src.core.services.path_validation_service import PathValidationService
            from src.core.services.tool_call_reactor_service import (
                ToolCallReactorService,
            )

            reactor_service = provider.get_required_service(ToolCallReactorService)
            session_service = provider.get_required_service(ISessionService)
            path_validator = PathValidationService()

            handler = FileSandboxingHandler(
                config=config.sandboxing,
                path_validator=path_validator,
                session_service=session_service,
            )

            reactor_service.register_handler_sync(handler)

        return provider

    def create_llm_response_with_tool_call(
        self, tool_name: str, tool_args: dict | None = None, tool_id: str | None = None
    ) -> ProcessedResponse:
        """Helper to create a ProcessedResponse with a tool call."""
        if tool_args is None:
            tool_args = {}
        if tool_id is None:
            # Generate a unique ID based on tool name and args to avoid signature collisions
            import hashlib

            unique_str = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
            tool_id = f"call_{hashlib.md5(unique_str.encode()).hexdigest()[:8]}"

        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": tool_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_args),
                                },
                            }
                        ]
                    }
                }
            ]
        }

        return ProcessedResponse(
            content=json.dumps(tool_call_response),
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            metadata={},
        )

    # Test 16.1: End-to-end sandboxing flow with real tool calls

    @pytest.mark.asyncio
    async def test_cline_write_to_file_blocked_outside_project(self, temp_project_dir):
        """Test Cline's write_to_file tool is blocked when path is outside project."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_cline_session"
        session = await session_service.get_or_create_session(session_id)
        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create Cline-style tool call attempting to write outside project
        outside_path = str(temp_project_dir.parent / "outside.txt")
        response = self.create_llm_response_with_tool_call(
            "write_to_file",
            {"path": outside_path, "content": "malicious content"},
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": "cline",
            },
        )

        # Verify the tool call was blocked
        assert isinstance(result, ProcessedResponse)
        assert result.metadata.get("tool_call_swallowed") is True
        # Extract content from OpenAI-compatible response structure
        if isinstance(result.content, dict):
            content = result.content["choices"][0]["message"]["content"]
        else:
            content = result.content

        # Handle case where content is a dict (e.g. structured content)
        if isinstance(content, dict):
            content = json.dumps(content)

        assert "paths outside project root" in content.lower()

    @pytest.mark.asyncio
    async def test_cline_write_to_file_allowed_inside_project(self, temp_project_dir):
        """Test Cline's write_to_file tool is allowed when path is inside project."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_cline_allowed_session"
        session = await session_service.get_or_create_session(session_id)
        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create Cline-style tool call with path inside project
        inside_path = str(temp_project_dir / "src" / "file.py")
        response = self.create_llm_response_with_tool_call(
            "write_to_file",
            {"path": inside_path, "content": "valid content"},
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": "cline",
            },
        )

        # Verify the tool call was allowed
        assert isinstance(result, ProcessedResponse)
        assert result.metadata.get("tool_call_swallowed") is not True
        assert result.content == response.content

    @pytest.mark.asyncio
    async def test_kilocode_edit_file_blocked_outside_project(self, temp_project_dir):
        """Test Kilocode's edit_file tool is blocked when path is outside project."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_kilocode_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create Kilocode-style tool call with target_file outside project
        outside_path = "/etc/passwd"
        response = self.create_llm_response_with_tool_call(
            "edit_file",
            {
                "target_file": outside_path,
                "instructions": "malicious edit",
                "code_edit": "...",
            },
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": "kilocode",
            },
        )

        # Verify the tool call was blocked
        assert result.metadata.get("tool_call_swallowed") is True
        # Extract content from OpenAI-compatible response structure
        if isinstance(result.content, dict):
            content = result.content["choices"][0]["message"]["content"]
        else:
            content = result.content

        # Handle case where content is a dict (e.g. structured content)
        if isinstance(content, dict):
            content = json.dumps(content)

        assert "paths outside project root" in content.lower()

    @pytest.mark.asyncio
    async def test_kilocode_apply_diff_with_relative_path(self, temp_project_dir):
        """Test Kilocode's apply_diff tool with relative path is normalized correctly."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_kilocode_diff_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create Kilocode-style tool call with relative path inside project
        # Use insert_content instead of apply_diff to avoid config_steering_handler interference
        response = self.create_llm_response_with_tool_call(
            "insert_content",
            {"path": "./src/main.py", "line": 1, "content": "# New content"},
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": "kilocode",
            },
        )

        # Verify the tool call was allowed (relative path normalized to inside project)
        assert result.metadata.get("tool_call_swallowed") is not True

    @pytest.mark.asyncio
    async def test_str_replace_path_traversal_blocked(self, temp_project_dir):
        """Test that str_replace tool blocks path traversal attempts."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_str_replace_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create str_replace tool call with path traversal
        response = self.create_llm_response_with_tool_call(
            "str_replace",
            {
                "path": "../../etc/passwd",
                "replacements": [{"old": "root", "new": "hacked"}],
            },
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
            },
        )

        # Verify the tool call was blocked
        assert result.metadata.get("tool_call_swallowed") is True
        # Extract content from OpenAI-compatible response structure
        if isinstance(result.content, dict):
            content = result.content["choices"][0]["message"]["content"]
        else:
            content = result.content

        # Handle case where content is a dict (e.g. structured content)
        if isinstance(content, dict):
            content = json.dumps(content)

        assert "paths outside project root" in content.lower()

    @pytest.mark.asyncio
    async def test_codex_apply_patch_allowed_inside_project(self, temp_project_dir):
        """Test Codex's apply_patch tool is allowed when path is inside project."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_codex_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create Codex-style tool call
        inside_path = str(temp_project_dir / "lib" / "module.rs")
        response = self.create_llm_response_with_tool_call(
            "apply_patch",
            {"path": inside_path, "patch": "--- a/lib/module.rs\n+++ b/lib/module.rs"},
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": "codex",
            },
        )

        # Verify the tool call was allowed
        assert result.metadata.get("tool_call_swallowed") is not True

    @pytest.mark.asyncio
    async def test_multiple_agents_tool_patterns(self, temp_project_dir):
        """Test that tool patterns from multiple agents are correctly identified."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_multi_agent_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Test various tool names from different agents
        tool_names = [
            "write_to_file",  # Cline
            "write_file",  # generic write_file variant
            "edit_file",  # Kilocode
            "apply_diff",  # Kilocode
            "apply_patch",  # Codex
            "str_replace",  # str_replace variant
            "insert_content",  # Kilocode
            "search_and_replace",  # Kilocode
            "generate_image",  # Kilocode
        ]

        outside_path = str(temp_project_dir.parent / "outside.txt")

        for tool_name in tool_names:
            response = self.create_llm_response_with_tool_call(
                tool_name, {"path": outside_path}
            )

            result = await reactor_middleware.process(
                response=response,
                session_id=session_id,
                context={
                    "backend_name": "test-backend",
                    "model_name": "test-model",
                    "calling_agent": "test",
                },
            )

            # All should be blocked
            assert (
                result.metadata.get("tool_call_swallowed") is True
            ), f"Tool {tool_name} was not blocked"

    @pytest.mark.asyncio
    async def test_error_response_format(self, temp_project_dir):
        """Test that error responses are properly formatted."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_error_format_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create tool call that will be blocked
        outside_path = "/tmp/outside.txt"
        response = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": outside_path, "content": "test"}
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Verify error response format
        assert result.metadata.get("tool_call_swallowed") is True
        # Extract content from OpenAI-compatible response structure
        if isinstance(result.content, dict):
            content = result.content["choices"][0]["message"]["content"]
        else:
            # Parse JSON string if needed
            try:
                parsed = json.loads(result.content)
                content = parsed["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, KeyError, TypeError):
                content = result.content
        assert "paths outside project root" in content.lower()
        assert str(temp_project_dir) in content
        # The error message should explain the violation clearly
        assert "file operation" in content.lower()

    # Test 16.2: Project directory detection integration

    @pytest.mark.asyncio
    async def test_sandboxing_inactive_before_project_detection(self):
        """Test that sandboxing is inactive when no project directory is detected."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session WITHOUT project directory
        session_id = "test_no_project_session"
        await session_service.get_or_create_session(session_id)

        # Create tool call with path outside any project
        response = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": "/tmp/file.txt", "content": "test"}
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Verify the tool call was NOT blocked (sandboxing inactive)
        assert result.metadata.get("tool_call_swallowed") is not True
        assert result.content == response.content

    @pytest.mark.asyncio
    async def test_sandboxing_activates_after_project_detection(self, temp_project_dir):
        """Test that sandboxing activates after project directory is detected."""
        config = self.create_config_with_sandboxing(enabled=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session without project directory initially
        session_id = "test_activation_session"
        session = await session_service.get_or_create_session(session_id)

        # First tool call - should be allowed (no project dir)
        response1 = self.create_llm_response_with_tool_call(
            "write_to_file",
            {"path": "/tmp/file.txt", "content": "test"},
            tool_id="call_first",
        )

        result1 = await reactor_middleware.process(
            response=response1,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        assert result1.metadata.get("tool_call_swallowed") is not True

        # Now set project directory (simulating detection)
        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Second tool call - should be blocked (project dir set)
        # Use different ID to ensure it's processed as a new call
        response2 = self.create_llm_response_with_tool_call(
            "write_to_file",
            {"path": "/tmp/file.txt", "content": "test"},
            tool_id="call_second",
        )

        result2 = await reactor_middleware.process(
            response=response2,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Now it should be blocked
        assert result2.metadata.get("tool_call_swallowed") is True

    @pytest.mark.asyncio
    async def test_different_resolution_modes(self, temp_project_dir):
        """Test sandboxing works with different project directory resolution modes."""
        # Test with deterministic mode (already set in create_config_with_sandboxing)
        config = self.create_config_with_sandboxing(enabled=True)

        provider = self.create_service_provider(config)
        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        session_id = "test_resolution_mode_session"
        session = await session_service.get_or_create_session(session_id)
        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create tool call
        outside_path = "/tmp/outside.txt"
        response = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": outside_path, "content": "test"}
        )

        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should be blocked
        assert result.metadata.get("tool_call_swallowed") is True

    # Test 16.3: Configuration loading and precedence

    @pytest.mark.asyncio
    async def test_sandboxing_disabled_by_config(self, temp_project_dir):
        """Test that sandboxing can be disabled via configuration."""
        config = self.create_config_with_sandboxing(enabled=False)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_disabled_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create tool call with path outside project
        outside_path = "/tmp/outside.txt"
        response = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": outside_path, "content": "test"}
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should NOT be blocked (sandboxing disabled)
        assert result.metadata.get("tool_call_swallowed") is not True

    @pytest.mark.asyncio
    async def test_strict_mode_blocks_unparseable_paths(self, temp_project_dir):
        """Test that strict mode blocks tool calls with unparseable paths."""
        config = self.create_config_with_sandboxing(enabled=True, strict_mode=True)
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_strict_mode_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create tool call with invalid path
        response = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": "\x00invalid\x00path", "content": "test"}
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should be blocked in strict mode
        assert result.metadata.get("tool_call_swallowed") is True

    @pytest.mark.asyncio
    async def test_allow_parent_access_configuration(self, temp_project_dir):
        """Test that allow_parent_access configuration works correctly."""
        config = self.create_config_with_sandboxing(
            enabled=True, allow_parent_access=True
        )
        provider = self.create_service_provider(config)

        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create a subdirectory within temp_project_dir to use as the project root
        # This way we can test accessing the parent (temp_project_dir)
        sub_project_dir = temp_project_dir / "subproject"
        sub_project_dir.mkdir()

        # Create session with subdirectory as project directory
        session_id = "test_parent_access_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(sub_project_dir))
        await session_service.update_session(session)

        # Create tool call with path that is the parent directory itself
        # allow_parent_access allows access when the path is an ancestor of the project root
        # In this case, temp_project_dir is the parent of sub_project_dir
        parent_path = str(temp_project_dir)
        response = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": parent_path, "content": "test"}
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should be allowed with allow_parent_access=True
        # because temp_project_dir is a parent directory of sub_project_dir
        assert result.metadata.get("tool_call_swallowed") is not True

    @pytest.mark.asyncio
    async def test_custom_tool_patterns(self, temp_project_dir):
        """Test that custom tool patterns can be configured."""
        # Create config with custom tool pattern
        sandboxing_config = SandboxingConfiguration(
            enabled=True,
            custom_tool_patterns=[r"custom_write_.*", r"my_file_editor"],
        )

        session_config = SessionConfig(
            project_dir_resolution_mode="deterministic",
            cleanup_enabled=False,
        )

        config = AppConfig()
        config = config.model_copy(
            update={
                "sandboxing": sandboxing_config,
                "session": session_config,
            }
        )

        provider = self.create_service_provider(config)
        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_custom_patterns_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Test custom tool pattern
        outside_path = "/tmp/outside.txt"
        response = self.create_llm_response_with_tool_call(
            "custom_write_file", {"path": outside_path, "content": "test"}
        )

        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should be blocked (custom pattern matched)
        assert result.metadata.get("tool_call_swallowed") is True

    @pytest.mark.asyncio
    async def test_excluded_tools_not_sandboxed(self, temp_project_dir):
        """Test that excluded tools are not subject to sandboxing."""
        # Create config with excluded tool
        sandboxing_config = SandboxingConfiguration(
            enabled=True,
            excluded_tools=[r"read_file", r"list_.*"],
        )

        session_config = SessionConfig(
            project_dir_resolution_mode="deterministic",
            cleanup_enabled=False,
        )

        config = AppConfig()
        config = config.model_copy(
            update={
                "sandboxing": sandboxing_config,
                "session": session_config,
            }
        )

        provider = self.create_service_provider(config)
        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_excluded_tools_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Test excluded tool (should not be sandboxed even if it looks like file-changing)
        outside_path = "/tmp/outside.txt"
        response = self.create_llm_response_with_tool_call(
            "read_file", {"path": outside_path}
        )

        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should NOT be blocked (tool is excluded)
        assert result.metadata.get("tool_call_swallowed") is not True

    # Test 16.4: Integration with tool access control

    @pytest.mark.asyncio
    async def test_sandboxing_after_tool_access_control(self, temp_project_dir):
        """Test that sandboxing runs after tool access control."""
        from src.core.config.app_config import ToolCallReactorConfig

        # Create config with both tool access control and sandboxing
        sandboxing_config = SandboxingConfiguration(enabled=True)

        # Configure tool access control to allow write_to_file
        reactor_config = ToolCallReactorConfig(
            enabled=True,
            access_policies=[
                {
                    "name": "allow_write",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "allowed_patterns": ["write_.*"],
                    "blocked_patterns": [],
                    "block_message": "Tool blocked by access control.",
                    "priority": 0,
                }
            ],
        )

        session_config = SessionConfig(
            project_dir_resolution_mode="deterministic",
            cleanup_enabled=False,
            tool_call_reactor=reactor_config,
        )

        config = AppConfig()
        config = config.model_copy(
            update={
                "sandboxing": sandboxing_config,
                "session": session_config,
            }
        )

        provider = self.create_service_provider(config)
        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_tac_sandboxing_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create tool call that passes access control but fails sandboxing
        outside_path = "/tmp/outside.txt"
        response = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": outside_path, "content": "test"}
        )

        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should be blocked by sandboxing (not access control)
        assert result.metadata.get("tool_call_swallowed") is True
        # Extract content from OpenAI-compatible response structure
        if isinstance(result.content, dict):
            content = result.content["choices"][0]["message"]["content"]
        else:
            content = result.content

        # Handle case where content is a dict (e.g. structured content)
        if isinstance(content, dict):
            content = json.dumps(content)

        assert "paths outside project root" in content.lower()

    @pytest.mark.asyncio
    async def test_tool_access_control_blocks_before_sandboxing(self, temp_project_dir):
        """Test that tool access control blocks before sandboxing validation."""
        from src.core.config.app_config import ToolCallReactorConfig

        # Create config with both tool access control and sandboxing
        sandboxing_config = SandboxingConfiguration(enabled=True)

        # Configure tool access control to block write_to_file
        reactor_config = ToolCallReactorConfig(
            enabled=True,
            access_policies=[
                {
                    "name": "block_write",
                    "model_pattern": ".*",
                    "default_policy": "deny",
                    "allowed_patterns": [],
                    "blocked_patterns": ["write_.*"],
                    "block_message": "Write operations blocked by policy.",
                    "priority": 0,
                }
            ],
        )

        session_config = SessionConfig(
            project_dir_resolution_mode="deterministic",
            cleanup_enabled=False,
            tool_call_reactor=reactor_config,
        )

        config = AppConfig()
        config = config.model_copy(
            update={
                "sandboxing": sandboxing_config,
                "session": session_config,
            }
        )

        provider = self.create_service_provider(config)
        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_tac_first_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Create tool call that would be blocked by access control
        inside_path = str(temp_project_dir / "file.txt")
        response = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": inside_path, "content": "test"}
        )

        result = await reactor_middleware.process(
            response=response,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should be blocked by access control (not sandboxing)
        assert result.metadata.get("tool_call_swallowed") is True
        # Extract content from OpenAI-compatible response structure
        if isinstance(result.content, dict):
            content = result.content["choices"][0]["message"]["content"]
        else:
            content = result.content
        assert "blocked by policy" in content.lower()

    @pytest.mark.asyncio
    async def test_independent_operation_of_systems(self, temp_project_dir):
        """Test that sandboxing and tool access control operate independently."""
        from src.core.config.app_config import ToolCallReactorConfig

        # Create config with tool access control but sandboxing disabled
        sandboxing_config = SandboxingConfiguration(enabled=False)

        reactor_config = ToolCallReactorConfig(
            enabled=True,
            access_policies=[
                {
                    "name": "block_delete",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "allowed_patterns": [],
                    "blocked_patterns": ["delete_.*"],
                    "block_message": "Delete operations blocked.",
                    "priority": 0,
                }
            ],
        )

        session_config = SessionConfig(
            project_dir_resolution_mode="deterministic",
            cleanup_enabled=False,
            tool_call_reactor=reactor_config,
        )

        config = AppConfig()
        config = config.model_copy(
            update={
                "sandboxing": sandboxing_config,
                "session": session_config,
            }
        )

        provider = self.create_service_provider(config)
        session_service = provider.get_required_service(ISessionService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create session with project directory
        session_id = "test_independent_session"
        session = await session_service.get_or_create_session(session_id)

        session.state = session.state.with_project_dir(str(temp_project_dir))
        await session_service.update_session(session)

        # Test 1: delete_file should be blocked by access control
        response1 = self.create_llm_response_with_tool_call(
            "delete_file", {"path": str(temp_project_dir / "file.txt")}
        )

        result1 = await reactor_middleware.process(
            response=response1,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should be blocked by access control
        assert result1.metadata.get("tool_call_swallowed") is True

        # Test 2: write_to_file outside project should be allowed (sandboxing disabled)
        outside_path = "/tmp/outside.txt"
        response2 = self.create_llm_response_with_tool_call(
            "write_to_file", {"path": outside_path, "content": "test"}
        )

        result2 = await reactor_middleware.process(
            response=response2,
            session_id=session_id,
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Should NOT be blocked (sandboxing disabled, access control allows)
        assert result2.metadata.get("tool_call_swallowed") is not True
