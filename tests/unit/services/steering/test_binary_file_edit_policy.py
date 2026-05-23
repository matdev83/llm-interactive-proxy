"""Unit tests for BinaryFileEditPolicy."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.services.steering.policies.binary_file_edit_policy import (
    BINARY_EXTENSIONS,
    BinaryFileEditPolicy,
)
from src.services.steering.unified_steering_handler import UnifiedSteeringHandler


class TestBinaryFileEditPolicy:
    """Test suite for BinaryFileEditPolicy."""

    @pytest.fixture
    def policy(self) -> BinaryFileEditPolicy:
        """Create a policy instance for testing."""
        return BinaryFileEditPolicy(enabled=True)

    @pytest.fixture
    def disabled_policy(self) -> BinaryFileEditPolicy:
        """Create a disabled policy instance for testing."""
        return BinaryFileEditPolicy(enabled=False)

    @pytest.fixture
    def context(self) -> ToolCallContext:
        """Create a basic tool call context."""
        return ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"file_path": "test.txt"},
        )

    @pytest.mark.asyncio
    async def test_binary_extension_triggers_steering(
        self, policy: BinaryFileEditPolicy, context: ToolCallContext
    ) -> None:
        """Test that binary file extensions trigger steering result."""
        # RED: This should fail because policy doesn't exist yet
        context.tool_name = "write_file"
        context.tool_arguments = {"file_path": "test.exe"}

        result = await policy.evaluate(context, "write_file test.exe")

        assert result is not None
        assert result.should_block is True
        assert "binary" in result.message.lower()
        assert result.policy_name == "binary_file_edit"

    @pytest.mark.asyncio
    async def test_non_binary_extension_passes_through(
        self, policy: BinaryFileEditPolicy, context: ToolCallContext
    ) -> None:
        """Test that non-binary file extensions return None."""
        context.tool_name = "write_file"
        context.tool_arguments = {"file_path": "test.py"}

        result = await policy.evaluate(context, "write_file test.py")

        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_policy_returns_none(
        self, disabled_policy: BinaryFileEditPolicy, context: ToolCallContext
    ) -> None:
        """Test that disabled policy returns None for any extension."""
        context.tool_name = "write_file"
        context.tool_arguments = {"file_path": "test.exe"}

        result = await disabled_policy.evaluate(context, "write_file test.exe")

        assert result is None

    @pytest.mark.asyncio
    async def test_non_file_editing_tool_returns_none(
        self, policy: BinaryFileEditPolicy, context: ToolCallContext
    ) -> None:
        """Test that non-file-editing tools return None."""
        context.tool_name = "run_shell_command"
        context.tool_arguments = {"command": "ls"}

        result = await policy.evaluate(context, "ls")

        assert result is None

    @pytest.mark.parametrize(
        "extension",
        [
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".bin",
            ".pyc",
            ".db",
            ".sqlite",
            ".mp3",
            ".mp4",
            ".jpg",
            ".png",
            ".pdf",
            ".zip",
            ".tar",
            ".ttf",
        ],
    )
    @pytest.mark.asyncio
    async def test_various_binary_extensions_detected(
        self, policy: BinaryFileEditPolicy, context: ToolCallContext, extension: str
    ) -> None:
        """Test that various binary extensions are detected."""
        context.tool_name = "write_file"
        context.tool_arguments = {"file_path": f"test{extension}"}

        result = await policy.evaluate(context, f"write_file test{extension}")

        assert result is not None
        assert result.should_block is True

    @pytest.mark.parametrize(
        "tool_name",
        [
            "write_to_file",
            "write_file",
            "fsWrite",
            "replace_in_file",
            "str_replace",
            "edit_file",
            "patch_file",
            "delete_file",
            "create_file",
            "move_file",
            "rename_file",
        ],
    )
    @pytest.mark.asyncio
    async def test_file_editing_tools_recognized(
        self, policy: BinaryFileEditPolicy, context: ToolCallContext, tool_name: str
    ) -> None:
        """Test that all file editing tools are recognized."""
        context.tool_name = tool_name
        context.tool_arguments = {"file_path": "test.exe"}

        result = await policy.evaluate(context, f"{tool_name} test.exe")

        assert result is not None

    @pytest.mark.parametrize(
        "param_name",
        [
            "path",
            "file_path",
            "target_file",
            "filename",
            "file",
            "destination",
        ],
    )
    @pytest.mark.asyncio
    async def test_path_extraction_from_various_parameter_names(
        self, policy: BinaryFileEditPolicy, context: ToolCallContext, param_name: str
    ) -> None:
        """Test that file paths are extracted from various parameter names."""
        context.tool_name = "write_file"
        context.tool_arguments = {param_name: "test.exe"}

        result = await policy.evaluate(context, "write_file test.exe")

        assert result is not None

    @pytest.mark.parametrize(
        "extension",
        [".EXE", ".Exe", ".DLL", ".Dll", ".SO", ".So", ".MP3", ".Mp3"],
    )
    @pytest.mark.asyncio
    async def test_case_insensitive_extension_matching(
        self, policy: BinaryFileEditPolicy, context: ToolCallContext, extension: str
    ) -> None:
        """Test that extension matching is case-insensitive."""
        context.tool_name = "write_file"
        context.tool_arguments = {"file_path": f"test{extension}"}

        result = await policy.evaluate(context, f"write_file test{extension}")

        assert result is not None
        assert result.should_block is True


class TestBinaryFileEditPolicyEndToEnd:
    """End-to-end tests for BinaryFileEditPolicy through UnifiedSteeringHandler."""

    @pytest.fixture
    def handler(self) -> UnifiedSteeringHandler:
        """Create a unified steering handler with binary file edit policy."""
        policy = BinaryFileEditPolicy(enabled=True)
        return UnifiedSteeringHandler(
            policies=[policy],
            enabled=True,
        )

    @pytest.fixture
    def context_with_binary_file(self) -> ToolCallContext:
        """Create context for a file edit tool targeting a binary file."""
        return ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"file_path": "program.exe", "content": "test"},
        )

    @pytest.fixture
    def context_with_text_file(self) -> ToolCallContext:
        """Create context for a file edit tool targeting a text file."""
        return ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"file_path": "script.py", "content": "test"},
        )

    @pytest.mark.asyncio
    async def test_handler_can_handle_binary_file_edit(
        self,
        handler: UnifiedSteeringHandler,
        context_with_binary_file: ToolCallContext,
    ) -> None:
        """Test that handler can_handle returns True for binary file edits."""
        can_handle = await handler.can_handle(context_with_binary_file)
        assert can_handle is True

    @pytest.mark.asyncio
    async def test_handler_handles_binary_file_edit(
        self,
        handler: UnifiedSteeringHandler,
        context_with_binary_file: ToolCallContext,
    ) -> None:
        """Test that handler blocks binary file edits end-to-end."""
        result = await handler.handle(context_with_binary_file)

        assert result.should_swallow is True
        assert result.replacement_response is not None
        assert "binary" in result.replacement_response.lower()
        assert result.metadata["matched_policy"] == "binary_file_edit"

    @pytest.mark.asyncio
    async def test_handler_allows_text_file_edit(
        self,
        handler: UnifiedSteeringHandler,
        context_with_text_file: ToolCallContext,
    ) -> None:
        """Test that handler allows text file edits."""
        result = await handler.handle(context_with_text_file)

        assert result.should_swallow is False
        assert result.replacement_response is None

    @pytest.mark.asyncio
    async def test_handler_works_without_command_argument(
        self,
        handler: UnifiedSteeringHandler,
        context_with_binary_file: ToolCallContext,
    ) -> None:
        """Test that handler works for file tools that don't have a 'command' argument."""
        # File editing tools typically don't have a 'command' field
        assert "command" not in context_with_binary_file.tool_arguments

        result = await handler.handle(context_with_binary_file)

        # Should still trigger because we now allow empty commands
        assert result.should_swallow is True

    @pytest.mark.asyncio
    async def test_handler_checks_multiple_path_parameters(
        self, handler: UnifiedSteeringHandler
    ) -> None:
        """Test that handler checks all path parameters (e.g., for move_file/copy_file)."""
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="copy_file",
            tool_arguments={"source": "data.txt", "destination": "backup.exe"},
        )

        result = await handler.handle(context)

        # Should trigger because destination is binary
        assert result.should_swallow is True
        assert "binary" in result.replacement_response.lower()


class TestBinaryFileEditPolicyProperties:
    """Property-based tests for BinaryFileEditPolicy using Hypothesis."""

    @given(extension=st.sampled_from(list(BINARY_EXTENSIONS)))
    @pytest.mark.asyncio
    async def test_property_all_binary_extensions_trigger_steering(
        self, extension: str
    ) -> None:
        """Property: Any file with a binary extension should trigger steering."""
        # Arrange
        policy = BinaryFileEditPolicy(enabled=True)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={},
        )
        filename = f"testfile{extension}"
        context.tool_arguments = {"file_path": filename}

        # Act
        result = await policy.evaluate(context, f"write_file {filename}")

        # Assert
        assert result is not None, f"Extension {extension} should trigger steering"
        assert result.should_block is True

    @given(
        extension=st.text(
            alphabet=st.characters(
                blacklist_characters=".\\/",
                blacklist_categories=("Cs",),  # Also exclude path separators
            ),
            min_size=1,
            max_size=10,
        ).filter(lambda x: f".{x.lower()}" not in BINARY_EXTENSIONS)
    )
    @pytest.mark.asyncio
    async def test_property_non_binary_extensions_pass_through(
        self, extension: str
    ) -> None:
        """Property: Files with non-binary extensions should pass through."""
        # Arrange
        policy = BinaryFileEditPolicy(enabled=True)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={},
        )
        filename = f"testfile.{extension}"
        context.tool_arguments = {"file_path": filename}

        # Act
        result = await policy.evaluate(context, f"write_file {filename}")

        # Assert: Should not trigger (None result)
        assert result is None, f"Extension .{extension} should not trigger steering"

    @given(
        extension=st.sampled_from(list(BINARY_EXTENSIONS)),
        case_transform=st.sampled_from(["upper", "lower", "title", "mixed"]),
    )
    @pytest.mark.asyncio
    async def test_property_case_insensitive_matching(
        self,
        extension: str,
        case_transform: str,
    ) -> None:
        """Property: Extension matching should be case-insensitive."""
        # Arrange
        policy = BinaryFileEditPolicy(enabled=True)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={},
        )
        # Transform case based on strategy
        if case_transform == "upper":
            test_extension = extension.upper()
        elif case_transform == "lower":
            test_extension = extension.lower()
        elif case_transform == "title":
            test_extension = extension.title()
        else:  # mixed
            test_extension = "".join(
                c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(extension)
            )

        filename = f"testfile{test_extension}"
        context.tool_arguments = {"file_path": filename}

        # Act
        result = await policy.evaluate(context, f"write_file {filename}")

        # Assert: Should trigger regardless of case
        assert (
            result is not None
        ), f"Extension {test_extension} (from {extension}) should trigger steering"
        assert result.should_block is True

    @given(
        path_param=st.sampled_from(
            [
                "path",
                "file_path",
                "target_file",
                "filename",
                "file",
                "destination",
                "dest",
                "target",
                "filepath",
                "file_name",
                "new_path",
                "old_path",
                "source",
                "src",
            ]
        ),
        extension=st.sampled_from(list(BINARY_EXTENSIONS)),
    )
    @pytest.mark.asyncio
    async def test_property_all_path_parameters_extracted(
        self,
        path_param: str,
        extension: str,
    ) -> None:
        """Property: Binary files should be detected regardless of parameter name."""
        # Arrange
        policy = BinaryFileEditPolicy(enabled=True)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={},
        )
        filename = f"testfile{extension}"
        context.tool_arguments = {path_param: filename}

        # Act
        result = await policy.evaluate(context, f"write_file {filename}")

        # Assert
        assert (
            result is not None
        ), f"Should detect binary file via '{path_param}' parameter"
        assert result.should_block is True

    @given(
        tool_name=st.sampled_from(
            [
                "write_to_file",
                "write_file",
                "fsWrite",
                "replace_in_file",
                "str_replace",
                "edit_file",
                "patch_file",
                "delete_file",
                "create_file",
                "move_file",
                "rename_file",
            ]
        ),
        extension=st.sampled_from(list(BINARY_EXTENSIONS)),
    )
    @pytest.mark.asyncio
    async def test_property_all_file_tools_recognized(
        self,
        tool_name: str,
        extension: str,
    ) -> None:
        """Property: All file editing tools should be recognized."""
        # Arrange
        policy = BinaryFileEditPolicy(enabled=True)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name=tool_name,
            tool_arguments={},
        )
        filename = f"testfile{extension}"
        context.tool_arguments = {"file_path": filename}

        # Act
        result = await policy.evaluate(context, f"{tool_name} {filename}")

        # Assert
        assert result is not None, f"Tool '{tool_name}' should be recognized"
        assert result.should_block is True
