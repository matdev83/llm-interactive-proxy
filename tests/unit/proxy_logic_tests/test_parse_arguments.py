from src.command_processor import parse_arguments


class TestParseArguments:
    def test_parse_valid_arguments(self):
        args_str = "model=gpt-4, temperature=0.7, max_tokens=100"
        expected = {"model": "gpt-4", "temperature": "0.7", "max_tokens": "100"}
        assert parse_arguments(args_str) == expected

    def test_parse_empty_arguments(self):
        assert parse_arguments("") == {}
        assert parse_arguments("   ") == {}

    def test_parse_arguments_with_slashes_in_model_name(self):
        args_str = "model=organization/model-name, temperature=0.5"
        expected = {"model": "organization/model-name", "temperature": "0.5"}
        assert parse_arguments(args_str) == expected

    def test_parse_arguments_single_argument(self):
        args_str = "model=gpt-3.5-turbo"
        expected = {"model": "gpt-3.5-turbo"}
        assert parse_arguments(args_str) == expected

    def test_parse_arguments_with_spaces(self):
        args_str = " model = gpt-4 , temperature = 0.8 "
        expected = {"model": "gpt-4", "temperature": "0.8"}
        assert parse_arguments(args_str) == expected

    def test_parse_flag_argument(self):
        # E.g. !/unset(model) -> model is a key, not key=value
        args_str = "model"
        expected = {"model": True}
        assert parse_arguments(args_str) == expected

    def test_parse_mixed_arguments(self):
        args_str = "model=claude/opus, debug_mode"
        expected = {"model": "claude/opus", "debug_mode": True}
        assert parse_arguments(args_str) == expected

    def test_parse_project_with_spaces_and_quotes(self):
        args_str = "project='my cool project'"
        expected = {"project": "my cool project"}
        assert parse_arguments(args_str) == expected

    def test_parse_project_with_double_quotes(self):
        args_str = 'project="another project"'
        expected = {"project": "another project"}
        assert parse_arguments(args_str) == expected

    def test_parse_project_without_quotes(self):
        args_str = "project=myproject"
        expected = {"project": "myproject"}
        assert parse_arguments(args_str) == expected

    def test_parse_project_name_alias_quotes(self):
        args_str = "project-name='my project'"
        expected = {"project-name": "my project"}
        assert parse_arguments(args_str) == expected

    def test_parse_project_name_alias_no_quotes(self):
        args_str = "project-name=myproj"
        expected = {"project-name": "myproj"}
        assert parse_arguments(args_str) == expected
