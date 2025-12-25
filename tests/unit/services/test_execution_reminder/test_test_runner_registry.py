"""Unit tests for TestRunnerRegistry."""

from __future__ import annotations

import re

from src.services.test_execution_reminder.test_runner_registry import (
    TestRunnerPattern,
    TestRunnerRegistry,
)


class TestTestRunnerPattern:
    """Tests for TestRunnerPattern dataclass."""

    def test_pattern_creation(self) -> None:
        """Test creating a TestRunnerPattern."""
        pattern = TestRunnerPattern(
            language="python",
            framework="pytest",
            patterns=[re.compile(r"^pytest$")],
            priority=10,
        )

        assert pattern.language == "python"
        assert pattern.framework == "pytest"
        assert len(pattern.patterns) == 1
        assert pattern.priority == 10

    def test_pattern_with_none_framework(self) -> None:
        """Test creating a pattern with None framework."""
        pattern = TestRunnerPattern(
            language="python",
            framework=None,
            patterns=[re.compile(r"^test$")],
            priority=5,
        )

        assert pattern.language == "python"
        assert pattern.framework is None


class TestTestRunnerRegistry:
    """Tests for TestRunnerRegistry."""

    def test_registry_initialization(self) -> None:
        """Test that registry initializes with default patterns."""
        registry = TestRunnerRegistry()

        # Should have patterns loaded
        assert len(registry._patterns) > 0

    def test_pytest_command_detection(self) -> None:
        """Test detection of pytest commands."""
        registry = TestRunnerRegistry()

        # Direct pytest
        match = registry.match_command("pytest")

        assert match.is_match is True

        assert match.language == "python"
        assert match.framework == "pytest"

        # pytest with arguments
        match = registry.match_command("pytest tests/")
        assert match.is_match is True
        assert match.language == "python"
        assert match.framework == "pytest"

        # Python module invocation
        match = registry.match_command("python -m pytest")
        assert match.is_match is True
        assert match.language == "python"
        assert match.framework == "pytest"

        # Wrapper invocation
        match = registry.match_command("pipenv run pytest")
        assert match.is_match is True
        assert match.language == "python"
        assert match.framework == "pytest"

    def test_unittest_command_detection(self) -> None:
        """Test detection of unittest commands."""
        registry = TestRunnerRegistry()

        # Python module invocation
        match = registry.match_command("python -m unittest")
        assert match.is_match is True
        assert match.language == "python"
        assert match.framework == "unittest"

        # unittest with arguments
        match = registry.match_command("python -m unittest discover")
        assert match.is_match is True
        assert match.language == "python"
        assert match.framework == "unittest"

    def test_non_test_command_rejection(self) -> None:
        """Test that non-test commands are not detected."""
        registry = TestRunnerRegistry()

        # Python script execution
        match = registry.match_command("python script.py")
        assert match.is_match is False
        assert match.language is None
        assert match.framework is None

        # Package installation
        match = registry.match_command("python -m pip install pytest")
        assert match.is_match is False
        assert match.language is None
        assert match.framework is None

        # Other commands
        match = registry.match_command("npm install")
        assert match.is_match is False

    def test_empty_command_handling(self) -> None:
        """Test handling of empty commands."""
        registry = TestRunnerRegistry()

        match = registry.match_command("")
        assert match.is_match is False
        assert match.language is None
        assert match.framework is None

    def test_register_custom_pattern(self) -> None:
        """Test registering a custom pattern."""
        registry = TestRunnerRegistry()

        # Register a custom pattern
        custom_pattern = TestRunnerPattern(
            language="custom",
            framework="custom_test",
            patterns=[re.compile(r"^custom_test$")],
            priority=20,
        )
        registry.register_pattern(custom_pattern)

        # Should match the custom pattern
        match = registry.match_command("custom_test")
        assert match.is_match is True
        assert match.language == "custom"
        assert match.framework == "custom_test"

    def test_pattern_priority(self) -> None:
        """Test that higher priority patterns are matched first."""
        registry = TestRunnerRegistry()

        # Register two patterns that could match the same command
        # Lower priority pattern
        low_priority = TestRunnerPattern(
            language="lang1",
            framework="framework1",
            patterns=[re.compile(r"^test")],
            priority=5,
        )
        registry.register_pattern(low_priority)

        # Higher priority pattern
        high_priority = TestRunnerPattern(
            language="lang2",
            framework="framework2",
            patterns=[re.compile(r"^test")],
            priority=15,
        )
        registry.register_pattern(high_priority)

        # Should match the higher priority pattern
        match = registry.match_command("test")
        assert match.is_match is True
        assert match.language == "lang2"
        assert match.framework == "framework2"

    def test_pytest_variations(self) -> None:
        """Test various pytest command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "pytest",
            "py.test",
            "python -m pytest",
            "python3 -m pytest",
            "pipenv run pytest",
            "poetry run pytest",
            "pytest tests/",
            "pytest -v",
            "pytest --cov",
            "python -m pytest tests/unit/",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "python", f"Wrong language for: {command}"
            assert match.framework == "pytest", f"Wrong framework for: {command}"

    def test_unittest_variations(self) -> None:
        """Test various unittest command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "python -m unittest",
            "python3 -m unittest",
            "unittest",
            "python -m unittest discover",
            "python -m unittest test_module",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "python", f"Wrong language for: {command}"
            assert match.framework == "unittest", f"Wrong framework for: {command}"

    def test_false_positives(self) -> None:
        """Test that commands mentioning pytest/unittest are not false positives."""
        registry = TestRunnerRegistry()

        false_positive_cases = [
            "pip install pytest",
            "python -m pip install pytest",
            "echo pytest",
            "grep pytest file.txt",
            "cat pytest.ini",
            "which pytest",
            "find . -name pytest",
            "docker run pytest",
            "poetry add pytest",
            "pipenv install pytest",
        ]

        for command in false_positive_cases:
            match = registry.match_command(command)
            assert match.is_match is False, f"False positive for: {command}"
            assert match.language is None, f"Should have no language for: {command}"
            assert match.framework is None, f"Should have no framework for: {command}"


class TestJavaScriptTestRunners:
    """Tests for JavaScript/TypeScript test runner detection."""

    def test_jest_variations(self) -> None:
        """Test various jest command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "jest",
            "jest tests/",
            "jest --coverage",
            "npm test",
            "npm run test",
            "npm run jest",
            "yarn test",
            "yarn run test",
            "yarn run jest",
            "npx jest",
            "pnpm test",
            "pnpm run test",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "javascript", f"Wrong language for: {command}"
            assert match.framework == "jest", f"Wrong framework for: {command}"

    def test_vitest_variations(self) -> None:
        """Test various vitest command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "vitest",
            "vitest run",
            "vitest --coverage",
            "npm run vitest",
            "yarn run vitest",
            "npx vitest",
            "pnpm run vitest",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "javascript", f"Wrong language for: {command}"
            assert match.framework == "vitest", f"Wrong framework for: {command}"

    def test_mocha_variations(self) -> None:
        """Test various mocha command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "mocha",
            "mocha tests/",
            "mocha --reporter spec",
            "npm run mocha",
            "yarn run mocha",
            "npx mocha",
            "pnpm run mocha",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "javascript", f"Wrong language for: {command}"
            assert match.framework == "mocha", f"Wrong framework for: {command}"

    def test_ava_variations(self) -> None:
        """Test various ava command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "ava",
            "ava tests/",
            "ava --verbose",
            "npm run ava",
            "yarn run ava",
            "npx ava",
            "pnpm run ava",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "javascript", f"Wrong language for: {command}"
            assert match.framework == "ava", f"Wrong framework for: {command}"


class TestRustTestRunners:
    """Tests for Rust test runner detection."""

    def test_cargo_test_variations(self) -> None:
        """Test various cargo test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "cargo test",
            "cargo test --all",
            "cargo test --release",
            "cargo test my_test",
            "cargo test --lib",
            "cargo test --bin my_bin",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "rust", f"Wrong language for: {command}"
            assert match.framework == "cargo", f"Wrong framework for: {command}"


class TestGoTestRunners:
    """Tests for Go test runner detection."""

    def test_go_test_variations(self) -> None:
        """Test various go test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "go test",
            "go test ./...",
            "go test -v",
            "go test -cover",
            "go test ./pkg/...",
            "go test -race",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "go", f"Wrong language for: {command}"
            assert match.framework == "go test", f"Wrong framework for: {command}"


class TestJavaTestRunners:
    """Tests for Java test runner detection."""

    def test_maven_variations(self) -> None:
        """Test various Maven test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "mvn test",
            "mvn clean test",
            "mvn verify",
            "mvn clean verify",
            "./mvnw test",
            "mvnw test",
            "./mvnw clean test",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "java", f"Wrong language for: {command}"
            assert match.framework == "maven", f"Wrong framework for: {command}"

    def test_gradle_variations(self) -> None:
        """Test various Gradle test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "gradle test",
            "gradle clean test",
            "./gradlew test",
            "gradlew test",
            "./gradlew clean test",
            "gradle test --info",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "java", f"Wrong language for: {command}"
            assert match.framework == "gradle", f"Wrong framework for: {command}"


class TestCSharpTestRunners:
    """Tests for C# test runner detection."""

    def test_dotnet_test_variations(self) -> None:
        """Test various dotnet test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "dotnet test",
            "dotnet test MyProject.Tests",
            "dotnet test --configuration Release",
            "dotnet test --logger trx",
            'dotnet test --collect:"Code Coverage"',
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "csharp", f"Wrong language for: {command}"
            assert match.framework == "dotnet", f"Wrong framework for: {command}"


class TestRubyTestRunners:
    """Tests for Ruby test runner detection."""

    def test_rspec_variations(self) -> None:
        """Test various RSpec command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "rspec",
            "rspec spec/",
            "rspec spec/models/",
            "bundle exec rspec",
            "bundle exec rspec spec/",
            "rake test",
            "bundle exec rake test",
            "ruby -Itest",
            "ruby -Itest test/test_helper.rb",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "ruby", f"Wrong language for: {command}"
            assert match.framework == "rspec", f"Wrong framework for: {command}"


class TestPHPTestRunners:
    """Tests for PHP test runner detection."""

    def test_phpunit_variations(self) -> None:
        """Test various PHPUnit command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "phpunit",
            "phpunit tests/",
            "phpunit --coverage-html coverage",
            "vendor/bin/phpunit",
            "./vendor/bin/phpunit",
            "composer test",
            "composer run test",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "php", f"Wrong language for: {command}"
            assert match.framework == "phpunit", f"Wrong framework for: {command}"


class TestCppTestRunners:
    """Tests for C/C++ test runner detection."""

    def test_ctest_variations(self) -> None:
        """Test various CTest command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "ctest",
            "ctest -V",
            "ctest --output-on-failure",
            "make test",
            "cmake --build . --target test",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "cpp", f"Wrong language for: {command}"
            assert match.framework == "ctest", f"Wrong framework for: {command}"


class TestSwiftTestRunners:
    """Tests for Swift test runner detection."""

    def test_swift_test_variations(self) -> None:
        """Test various swift test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "swift test",
            "swift test --parallel",
            "swift test --filter MyTests",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "swift", f"Wrong language for: {command}"
            assert match.framework == "swift test", f"Wrong framework for: {command}"


class TestScalaTestRunners:
    """Tests for Scala test runner detection."""

    def test_sbt_test_variations(self) -> None:
        """Test various sbt test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "sbt test",
            "sbt testOnly MyTest",
            "sbt testQuick",
            "sbt clean test",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "scala", f"Wrong language for: {command}"
            assert match.framework == "sbt", f"Wrong framework for: {command}"


class TestElixirTestRunners:
    """Tests for Elixir test runner detection."""

    def test_mix_test_variations(self) -> None:
        """Test various mix test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "mix test",
            "mix test test/my_test.exs",
            "mix test --trace",
            "mix test --cover",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "elixir", f"Wrong language for: {command}"
            assert match.framework == "mix", f"Wrong framework for: {command}"


class TestDartTestRunners:
    """Tests for Dart/Flutter test runner detection."""

    def test_dart_test_variations(self) -> None:
        """Test various dart test command variations."""
        registry = TestRunnerRegistry()

        test_cases = [
            "dart test",
            "dart test test/my_test.dart",
            "flutter test",
            "flutter test test/widget_test.dart",
            "flutter test --coverage",
        ]

        for command in test_cases:
            match = registry.match_command(command)
            assert match.is_match is True, f"Failed to match: {command}"
            assert match.language == "dart", f"Wrong language for: {command}"
            assert match.framework == "dart test", f"Wrong framework for: {command}"


class TestPatternLoading:
    """Tests for pattern loading functionality."""

    def test_all_languages_loaded(self) -> None:
        """Test that all expected languages are loaded."""
        registry = TestRunnerRegistry()

        # Expected languages based on requirements
        expected_languages = {
            "python",
            "javascript",
            "rust",
            "go",
            "java",
            "csharp",
            "ruby",
            "php",
            "cpp",
            "swift",
            "scala",
            "elixir",
            "dart",
        }

        # Extract unique languages from patterns
        loaded_languages = {pattern.language for pattern in registry._patterns}

        assert loaded_languages == expected_languages, (
            f"Missing languages: {expected_languages - loaded_languages}, "
            f"Extra languages: {loaded_languages - expected_languages}"
        )

    def test_all_frameworks_loaded(self) -> None:
        """Test that all expected frameworks are loaded."""
        registry = TestRunnerRegistry()

        # Expected frameworks based on requirements
        expected_frameworks = {
            "pytest",
            "unittest",
            "jest",
            "vitest",
            "mocha",
            "ava",
            "cargo",
            "go test",
            "maven",
            "gradle",
            "dotnet",
            "rspec",
            "phpunit",
            "ctest",
            "swift test",
            "sbt",
            "mix",
            "dart test",
        }

        # Extract unique frameworks from patterns
        loaded_frameworks = {
            pattern.framework for pattern in registry._patterns if pattern.framework
        }

        assert loaded_frameworks == expected_frameworks, (
            f"Missing frameworks: {expected_frameworks - loaded_frameworks}, "
            f"Extra frameworks: {loaded_frameworks - expected_frameworks}"
        )

    def test_pattern_count(self) -> None:
        """Test that a reasonable number of patterns are loaded."""
        registry = TestRunnerRegistry()

        # Should have at least one pattern per framework
        # We have 18 frameworks, so at least 18 patterns
        assert (
            len(registry._patterns) >= 18
        ), f"Expected at least 18 patterns, got {len(registry._patterns)}"


class TestExtensibility:
    """Tests for registry extensibility."""

    def test_register_new_language(self) -> None:
        """Test registering a pattern for a new language."""
        registry = TestRunnerRegistry()

        # Register a custom language
        custom_pattern = TestRunnerPattern(
            language="haskell",
            framework="hspec",
            patterns=[re.compile(r"^stack\s+test(?:\s|$)")],
            priority=10,
        )
        registry.register_pattern(custom_pattern)

        # Should match the custom pattern
        match = registry.match_command("stack test")
        assert match.is_match is True
        assert match.language == "haskell"
        assert match.framework == "hspec"

    def test_register_new_framework_for_existing_language(self) -> None:
        """Test registering a new framework for an existing language."""
        registry = TestRunnerRegistry()

        # Register a custom Python framework
        custom_pattern = TestRunnerPattern(
            language="python",
            framework="nose2",
            patterns=[re.compile(r"^nose2(?:\s|$)")],
            priority=10,
        )
        registry.register_pattern(custom_pattern)

        # Should match the custom pattern
        match = registry.match_command("nose2")
        assert match.is_match is True
        assert match.language == "python"
        assert match.framework == "nose2"

    def test_override_with_higher_priority(self) -> None:
        """Test that higher priority patterns override lower priority ones."""
        registry = TestRunnerRegistry()

        # Register a low priority pattern
        low_priority = TestRunnerPattern(
            language="custom1",
            framework="framework1",
            patterns=[re.compile(r"^customtest")],
            priority=5,
        )
        registry.register_pattern(low_priority)

        # Register a high priority pattern with same regex
        high_priority = TestRunnerPattern(
            language="custom2",
            framework="framework2",
            patterns=[re.compile(r"^customtest")],
            priority=20,
        )
        registry.register_pattern(high_priority)

        # Should match the higher priority pattern
        match = registry.match_command("customtest")
        assert match.is_match is True
        assert match.language == "custom2"
        assert match.framework == "framework2"
