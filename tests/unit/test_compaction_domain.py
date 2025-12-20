"""
Unit tests for context compaction domain models.

Tests coverage for:
- ResourceIdentity: equality, hashing, string representation
- ResourceIdentityExtractor: path extraction, command signature, edge cases
- CompactionStub: creation and content generation
- ToolCategory: categorization logic
- CompactionConfig: policy evaluation
- CompactionPolicies: combined allow/deny logic

Requirements covered: 1.1, 1.2, 1.3, 3.3, 3.4
"""

import pytest
from src.core.domain.compaction import (
    CompactionStub,
    ResourceIdentity,
    ResourceIdentityExtractor,
    ToolCategory,
    categorize_tool,
    is_tool_result_message,
)
from src.core.domain.configuration.compaction_config import (
    CompactionConfig,
    CompactionPolicies,
    TokenBudgetConfig,
)


class TestResourceIdentity:
    """Tests for ResourceIdentity domain model."""

    def test_equality_same_resource(self) -> None:
        """Two identities with same values are equal."""
        id1 = ResourceIdentity(tool_name="view_file", primary_key="/path/to/file.py")
        id2 = ResourceIdentity(tool_name="view_file", primary_key="/path/to/file.py")
        assert id1 == id2

    def test_equality_case_insensitive_tool_name(self) -> None:
        """Tool name comparison is case-insensitive."""
        id1 = ResourceIdentity(tool_name="View_File", primary_key="/path/file.py")
        id2 = ResourceIdentity(tool_name="view_file", primary_key="/path/file.py")
        assert id1 == id2

    def test_inequality_different_path(self) -> None:
        """Different paths create different identities."""
        id1 = ResourceIdentity(tool_name="view_file", primary_key="/path/a.py")
        id2 = ResourceIdentity(tool_name="view_file", primary_key="/path/b.py")
        assert id1 != id2

    def test_inequality_different_tool(self) -> None:
        """Different tools create different identities even for same path."""
        id1 = ResourceIdentity(tool_name="view_file", primary_key="/path/file.py")
        id2 = ResourceIdentity(tool_name="read_file", primary_key="/path/file.py")
        assert id1 != id2

    def test_hash_equality_for_equal_objects(self) -> None:
        """Equal objects have equal hashes."""
        id1 = ResourceIdentity(tool_name="view_file", primary_key="/path/file.py")
        id2 = ResourceIdentity(tool_name="view_file", primary_key="/path/file.py")
        assert hash(id1) == hash(id2)

    def test_usable_as_dict_key(self) -> None:
        """ResourceIdentity can be used as dictionary key."""
        id1 = ResourceIdentity(tool_name="view_file", primary_key="/path/file.py")
        data: dict[ResourceIdentity, int] = {id1: 42}

        id2 = ResourceIdentity(tool_name="view_file", primary_key="/path/file.py")
        assert data[id2] == 42

    def test_secondary_keys_affect_equality(self) -> None:
        """Secondary keys are considered in equality."""
        id1 = ResourceIdentity(
            tool_name="find_by_name",
            primary_key="/path",
            secondary_keys=("*.py",),
        )
        id2 = ResourceIdentity(
            tool_name="find_by_name",
            primary_key="/path",
            secondary_keys=("*.txt",),
        )
        assert id1 != id2

    def test_str_representation_simple(self) -> None:
        """String representation is human-readable."""
        identity = ResourceIdentity(tool_name="view_file", primary_key="/path/file.py")
        assert str(identity) == "view_file:/path/file.py"

    def test_str_representation_with_secondary(self) -> None:
        """String includes secondary keys."""
        identity = ResourceIdentity(
            tool_name="grep_search",
            primary_key="pattern",
            secondary_keys=("/src", "*.py"),
        )
        assert str(identity) == "grep_search:pattern:/src:*.py"


class TestResourceIdentityExtractor:
    """Tests for ResourceIdentityExtractor."""

    @pytest.fixture
    def extractor(self) -> ResourceIdentityExtractor:
        return ResourceIdentityExtractor()

    def test_extract_file_path_from_dict(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Extracts file path from dict arguments."""
        args = {"file_path": "/path/to/file.py", "other": "value"}
        result = extractor.extract("view_file", args)

        assert result is not None
        assert result.primary_key == "/path/to/file.py"
        assert result.tool_name == "view_file"

    def test_extract_absolute_path_param(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Extracts AbsolutePath parameter."""
        args = {"AbsolutePath": "c:\\Users\\test\\file.py"}
        result = extractor.extract("view_file", args)

        assert result is not None
        # Only drive letter is lowercased, path preserves case
        assert result.primary_key == "c:/Users/test/file.py"

    def test_extract_from_json_string(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Parses JSON string arguments."""
        args = '{"path": "/test/path.py"}'
        result = extractor.extract("read_file", args)

        assert result is not None
        assert result.primary_key == "/test/path.py"

    def test_extract_directory_with_pattern(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Extracts directory path with pattern as secondary key."""
        args = {"DirectoryPath": "/src", "Pattern": "*.py"}
        result = extractor.extract("find_by_name", args)

        assert result is not None
        assert result.primary_key == "/src"
        assert result.secondary_keys == ("*.py",)

    def test_extract_command_signature(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Creates command signature from command arguments."""
        args = {"CommandLine": "pytest tests/unit/test_file.py -v"}
        result = extractor.extract("run_command", args)

        assert result is not None
        assert result.primary_key == "pytest"  # Normalized to base command

    def test_extract_query_with_search_path(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Extracts search query with path as secondary key."""
        args = {"Query": "def test_", "SearchPath": "/tests"}
        result = extractor.extract("grep_search", args)

        assert result is not None
        assert result.primary_key == "def test_"
        assert result.secondary_keys == ("/tests",)

    def test_extract_returns_none_for_empty_args(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Returns None when arguments are empty (Req 1.3)."""
        result = extractor.extract("view_file", None)
        assert result is None

    def test_extract_returns_none_for_missing_identity(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Returns None when no identifiable resource (Req 1.3)."""
        args = {"unknown_param": "value"}
        result = extractor.extract("custom_tool", args)
        assert result is None

    def test_extract_simple_string_argument(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Treats simple string as primary key."""
        result = extractor.extract("custom_tool", "/some/path/file.txt")

        assert result is not None
        assert result.primary_key == "/some/path/file.txt"

    def test_path_normalization_backslashes(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Normalizes Windows backslashes to forward slashes."""
        args = {"path": "C:\\Users\\Test\\file.py"}
        result = extractor.extract("view_file", args)

        assert result is not None
        assert "\\" not in result.primary_key
        # Only drive letter is lowercased
        assert result.primary_key == "c:/Users/Test/file.py"

    def test_extract_file_with_offset_limit(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Extracts offset and limit as secondary keys for partial file reads (Req 1.1.1)."""
        args = {"file_path": "/path/to/file.py", "offset": 100, "limit": 50}
        result = extractor.extract("read_file", args)

        assert result is not None
        assert result.primary_key == "/path/to/file.py"
        assert result.secondary_keys == ("offset:100", "limit:50")

    def test_extract_file_with_offset_only(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Extracts only offset when limit is not present."""
        args = {"file_path": "/path/to/file.py", "offset": 985}
        result = extractor.extract("read_file", args)

        assert result is not None
        assert result.secondary_keys == ("offset:985",)

    def test_extract_file_with_limit_only(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Extracts only limit when offset is not present."""
        args = {"file_path": "/path/to/file.py", "limit": 40}
        result = extractor.extract("read_file", args)

        assert result is not None
        assert result.secondary_keys == ("limit:40",)

    def test_different_offsets_create_different_identities(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Different offset/limit combinations create different resource identities (Req 1.1.1)."""
        args1 = {"file_path": "/path/to/file.py", "offset": 985, "limit": 40}
        args2 = {"file_path": "/path/to/file.py", "offset": 905, "limit": 40}
        args3 = {"file_path": "/path/to/file.py", "offset": 1080, "limit": 50}

        result1 = extractor.extract("read_file", args1)
        result2 = extractor.extract("read_file", args2)
        result3 = extractor.extract("read_file", args3)

        assert result1 is not None
        assert result2 is not None
        assert result3 is not None

        # All three should be different identities
        assert result1 != result2
        assert result2 != result3
        assert result1 != result3

    def test_same_offset_limit_create_same_identity(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Same offset/limit combinations create same resource identity."""
        args1 = {"file_path": "/path/to/file.py", "offset": 100, "limit": 50}
        args2 = {"file_path": "/path/to/file.py", "offset": 100, "limit": 50}

        result1 = extractor.extract("read_file", args1)
        result2 = extractor.extract("read_file", args2)

        assert result1 is not None
        assert result2 is not None
        assert result1 == result2

    def test_extract_file_no_offset_limit(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Files without offset/limit have empty secondary keys."""
        args = {"file_path": "/path/to/file.py"}
        result = extractor.extract("view_file", args)

        assert result is not None
        assert result.secondary_keys == ()

    def test_extract_offset_limit_from_string_values(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Handles offset/limit as string values (JSON parsing)."""
        args = {"file_path": "/path/to/file.py", "offset": "100", "limit": "50"}
        result = extractor.extract("read_file", args)

        assert result is not None
        assert result.secondary_keys == ("offset:100", "limit:50")

    def test_extract_start_line_end_line_params(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Handles alternative param names like start_line/end_line."""
        args = {"file_path": "/path/to/file.py", "start_line": 10, "end_line": 20}
        result = extractor.extract("read_file", args)

        assert result is not None
        assert result.secondary_keys == ("offset:10", "limit:20")

    def test_extract_ignores_offset_limit_for_non_read_tools(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Offset/limit ignored for non-read tools (e.g. edit_file)."""
        # Edit file often has start_line/end_line but should be same resource identity
        args1 = {"file_path": "/path/to/file.py", "start_line": 10, "end_line": 20}
        args2 = {"file_path": "/path/to/file.py", "start_line": 30, "end_line": 40}

        # Using a FILE_WRITE category tool
        result1 = extractor.extract("edit_file", args1)
        result2 = extractor.extract("edit_file", args2)

        assert result1 is not None
        assert result2 is not None

        # Should be SAME identity despite different lines
        assert result1.primary_key == "/path/to/file.py"
        assert result2.primary_key == "/path/to/file.py"
        assert result1.secondary_keys == ()
        assert result2.secondary_keys == ()
        assert result1 == result2

    def test_extract_view_file_with_start_end_line(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Handles view_file with StartLine/EndLine pagination parameters (Req 1.1.1)."""
        args = {"AbsolutePath": "/path/to/file.py", "StartLine": 10, "EndLine": 50}
        result = extractor.extract("view_file", args)

        assert result is not None
        assert result.primary_key == "/path/to/file.py"
        # StartLine maps to offset, EndLine maps to limit
        assert result.secondary_keys == ("offset:10", "limit:50")

    def test_extract_view_file_with_start_line_only(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Handles view_file with only StartLine parameter."""
        args = {"AbsolutePath": "/path/to/file.py", "StartLine": 100}
        result = extractor.extract("view_file", args)

        assert result is not None
        assert result.secondary_keys == ("offset:100",)

    def test_extract_view_file_with_end_line_only(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Handles view_file with only EndLine parameter."""
        args = {"AbsolutePath": "/path/to/file.py", "EndLine": 200}
        result = extractor.extract("view_file", args)

        assert result is not None
        assert result.secondary_keys == ("limit:200",)

    def test_different_line_ranges_create_different_view_file_identities(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Different line ranges for view_file create different resource identities (Req 1.1.1).

        This test ensures that reading lines 1-100 and lines 200-300 of the same file
        are treated as DIFFERENT resources and will NOT be compacted against each other.
        """
        args1 = {"AbsolutePath": "/path/file.py", "StartLine": 1, "EndLine": 100}
        args2 = {"AbsolutePath": "/path/file.py", "StartLine": 200, "EndLine": 300}
        args3 = {"AbsolutePath": "/path/file.py", "StartLine": 1, "EndLine": 200}

        result1 = extractor.extract("view_file", args1)
        result2 = extractor.extract("view_file", args2)
        result3 = extractor.extract("view_file", args3)

        assert result1 is not None
        assert result2 is not None
        assert result3 is not None

        # All three should be different identities
        assert result1 != result2
        assert result2 != result3
        assert result1 != result3

    def test_same_line_range_creates_same_view_file_identity(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """Same line ranges for view_file create the same resource identity."""
        args1 = {"AbsolutePath": "/path/file.py", "StartLine": 50, "EndLine": 100}
        args2 = {"AbsolutePath": "/path/file.py", "StartLine": 50, "EndLine": 100}

        result1 = extractor.extract("view_file", args1)
        result2 = extractor.extract("view_file", args2)

        assert result1 is not None
        assert result2 is not None
        assert result1 == result2
        assert hash(result1) == hash(result2)

    def test_view_file_without_pagination_has_empty_secondary_keys(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """view_file without StartLine/EndLine has no secondary keys."""
        args = {"AbsolutePath": "/path/to/file.py"}
        result = extractor.extract("view_file", args)

        assert result is not None
        assert result.secondary_keys == ()

    def test_view_file_outline_with_pagination(
        self, extractor: ResourceIdentityExtractor
    ) -> None:
        """view_file_outline also respects pagination parameters."""
        args = {"AbsolutePath": "/path/to/file.py", "StartLine": 1, "EndLine": 50}
        result = extractor.extract("view_file_outline", args)

        assert result is not None
        assert result.secondary_keys == ("offset:1", "limit:50")


class TestCompactionStub:
    """Tests for CompactionStub creation."""

    def test_create_stub_generates_text(self) -> None:
        """Create generates appropriate stub text."""
        identity = ResourceIdentity(tool_name="view_file", primary_key="/path/file.py")
        stub = CompactionStub.create(
            resource_identity=identity,
            original_content="x" * 1000,
            message_index=5,
        )

        assert stub.original_byte_size == 1000
        assert stub.message_index == 5
        assert "/path/file.py" in stub.stub_text
        assert "1000 bytes" in stub.stub_text
        assert "newer result" in stub.stub_text

    def test_stub_byte_size_unicode(self) -> None:
        """Byte size accounts for unicode characters."""
        identity = ResourceIdentity(tool_name="view_file", primary_key="/file.py")
        content = "Hello 世界"  # 6 + 6 = 12 bytes in UTF-8
        stub = CompactionStub.create(identity, content, 0)

        assert stub.original_byte_size == len(content.encode("utf-8"))


class TestToolCategory:
    """Tests for tool categorization."""

    @pytest.mark.parametrize(
        "tool_name,expected",
        [
            ("view_file", ToolCategory.VIEW_FILE),
            ("VIEW_FILE", ToolCategory.VIEW_FILE),
            ("read_file", ToolCategory.FILE_READ),
            ("grep_search", ToolCategory.SEARCH),
            ("codebase_search", ToolCategory.SEARCH),
            ("run_command", ToolCategory.COMMAND_EXECUTION),
            ("write_file", ToolCategory.FILE_WRITE),
            ("list_dir", ToolCategory.LIST_DIRECTORY),
            ("run_pytest", ToolCategory.TEST_EXECUTION),
            ("unknown_tool", ToolCategory.OTHER),
        ],
    )
    def test_categorize_tool(self, tool_name: str, expected: ToolCategory) -> None:
        """Tools are categorized correctly."""
        assert categorize_tool(tool_name) == expected

    def test_categorize_handles_variations(self) -> None:
        """Handles underscore/hyphen variations."""
        assert categorize_tool("viewfile") == ToolCategory.VIEW_FILE
        assert categorize_tool("view-file") == ToolCategory.VIEW_FILE


class TestIsToolResultMessage:
    """Tests for tool result message detection."""

    def test_tool_role_with_id(self) -> None:
        """Role=tool with tool_call_id is a tool result."""
        assert is_tool_result_message("tool", "call_123") is True

    def test_tool_role_without_id(self) -> None:
        """Role=tool without tool_call_id is not valid."""
        assert is_tool_result_message("tool", None) is False

    def test_non_tool_role(self) -> None:
        """Non-tool roles are not tool results (Req 1.4)."""
        assert is_tool_result_message("user", "call_123") is False
        assert is_tool_result_message("assistant", "call_123") is False
        assert is_tool_result_message("system", None) is False


class TestCompactionConfig:
    """Tests for CompactionConfig."""

    def test_default_config(self) -> None:
        """Default config has sensible defaults."""
        config = CompactionConfig()
        assert config.enabled is False  # Changed: now disabled by default
        assert config.token_threshold == 100_000
        assert config.max_tokens == 150_000

    def test_disabled_factory(self) -> None:
        """Disabled factory creates disabled config."""
        config = CompactionConfig.disabled()
        assert config.enabled is False

    def test_default_factory_with_policies(self) -> None:
        """Default factory includes recommended policies."""
        config = CompactionConfig.default()
        assert config.enabled is False  # Changed: now disabled by default
        assert ToolCategory.FILE_READ.value in config.allowed_tool_categories
        assert ToolCategory.FILE_WRITE.value in config.denied_tool_categories

    def test_category_allowed_empty_lists(self) -> None:
        """Empty allow/deny means all categories allowed."""
        config = CompactionConfig()
        assert config.is_tool_category_allowed(ToolCategory.FILE_READ) is True
        assert config.is_tool_category_allowed(ToolCategory.FILE_WRITE) is True

    def test_category_denied_takes_precedence(self) -> None:
        """Deny list takes precedence over allow list."""
        config = CompactionConfig(
            allowed_tool_categories=["file_read", "file_write"],
            denied_tool_categories=["file_write"],
        )
        assert config.is_tool_category_allowed(ToolCategory.FILE_READ) is True
        assert config.is_tool_category_allowed(ToolCategory.FILE_WRITE) is False

    def test_category_must_be_in_allow_list(self) -> None:
        """Non-empty allow list requires membership."""
        config = CompactionConfig(
            allowed_tool_categories=["file_read"],
        )
        assert config.is_tool_category_allowed(ToolCategory.FILE_READ) is True
        assert config.is_tool_category_allowed(ToolCategory.SEARCH) is False

    def test_from_dict(self) -> None:
        """Creates config from dictionary."""
        data = {
            "enabled": False,
            "token_threshold": 50_000,
            "denied_tool_categories": ["command_execution"],
        }
        config = CompactionConfig.from_dict(data)

        assert config.enabled is False
        assert config.token_threshold == 50_000
        assert "command_execution" in config.denied_tool_categories


class TestCompactionPolicies:
    """Tests for CompactionPolicies runtime evaluation."""

    def test_tool_denylist_takes_precedence(self) -> None:
        """Tool-specific denylist overrides category policy."""
        config = CompactionConfig(
            allowed_tool_categories=["file_read"],
        )
        policies = CompactionPolicies.from_config(
            config,
            tool_denylist={"view_file"},
        )

        # view_file is in FILE_READ category but explicitly denied
        assert (
            policies.should_compact_tool("view_file", ToolCategory.FILE_READ) is False
        )

    def test_tool_allowlist_overrides_category(self) -> None:
        """Tool-specific allowlist overrides category denial."""
        config = CompactionConfig(
            denied_tool_categories=["command_execution"],
        )
        policies = CompactionPolicies.from_config(
            config,
            tool_allowlist={"run_command"},
        )

        assert (
            policies.should_compact_tool("run_command", ToolCategory.COMMAND_EXECUTION)
            is True
        )

    def test_falls_back_to_category_policy(self) -> None:
        """Uses category policy when no tool-specific rules."""
        config = CompactionConfig(
            allowed_tool_categories=["search"],
            denied_tool_categories=["file_write"],
        )
        policies = CompactionPolicies.from_config(config)

        assert policies.should_compact_tool("grep_search", ToolCategory.SEARCH) is True
        assert (
            policies.should_compact_tool("write_file", ToolCategory.FILE_WRITE) is False
        )
        assert (
            policies.should_compact_tool("list_dir", ToolCategory.LIST_DIRECTORY)
            is False
        )


class TestTokenBudgetConfig:
    """Tests for TokenBudgetConfig."""

    def test_needs_compaction_above_threshold(self) -> None:
        """Compaction needed when above threshold (Req 3.1)."""
        budget = TokenBudgetConfig(
            compaction_threshold=100_000,
            max_tokens=150_000,
            current_estimate=120_000,
        )
        assert budget.needs_compaction is True

    def test_no_compaction_below_threshold(self) -> None:
        """No compaction when below threshold (Req 3.5)."""
        budget = TokenBudgetConfig(
            compaction_threshold=100_000,
            max_tokens=150_000,
            current_estimate=80_000,
        )
        assert budget.needs_compaction is False

    def test_exceeds_max_warning(self) -> None:
        """Warning when exceeds max tokens (Req 3.2)."""
        budget = TokenBudgetConfig(
            compaction_threshold=100_000,
            max_tokens=150_000,
            current_estimate=200_000,
        )
        assert budget.exceeds_max is True
        assert budget.needs_compaction is True

    def test_from_config(self) -> None:
        """Creates from CompactionConfig."""
        config = CompactionConfig(token_threshold=50_000, max_tokens=80_000)
        budget = TokenBudgetConfig.from_config(config, current_estimate=60_000)

        assert budget.compaction_threshold == 50_000
        assert budget.max_tokens == 80_000
        assert budget.current_estimate == 60_000
        assert budget.needs_compaction is True
