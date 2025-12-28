"""Test runner pattern registry for test execution reminder system."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Maximum number of patterns to prevent unbounded memory growth
# Each pattern contains compiled regex objects that can consume significant memory
# Set high enough to accommodate default patterns while still preventing unbounded growth
_MAX_PATTERNS = 50


@dataclass
class TestRunnerPattern:
    """Pattern for detecting test execution commands.

    This dataclass defines a test runner pattern with associated metadata
    for language and framework identification.
    """

    language: str
    """Programming language (e.g., 'python', 'javascript')."""

    framework: str | None
    """Test framework name (e.g., 'pytest', 'jest')."""

    patterns: list[re.Pattern[str]]
    """Compiled regex patterns for matching commands."""

    priority: int = 0
    """Priority for pattern matching (higher = more specific)."""


class TestRunnerMatch(BaseModel):
    """Result of a test runner pattern match."""

    is_match: bool = Field(description="True if command matches a test runner pattern")
    language: str | None = Field(
        default=None, description="The programming language or None"
    )
    framework: str | None = Field(
        default=None, description="The test framework or None"
    )

    def __iter__(self):
        """Allow unpacking for backward compatibility."""
        yield self.is_match
        yield self.language
        yield self.framework


class TestRunnerRegistry:
    """Registry of test runner patterns for multiple languages.

    This registry maintains a collection of test runner patterns organized
    by language and framework, supporting pattern matching for test execution
    command detection across multiple programming languages.
    """

    def __init__(self, max_patterns: int = _MAX_PATTERNS) -> None:
        """Initialize with default patterns for popular languages.

        Args:
            max_patterns: Maximum number of patterns to store (prevents memory leaks)
        """
        self._patterns: list[TestRunnerPattern] = []
        self._max_patterns = max_patterns
        self._load_default_patterns()

    def match_command(self, command: str) -> TestRunnerMatch:
        """Match command against registered patterns.

        Attempts to match the given command against all registered test runner
        patterns. Returns the first match found, prioritizing patterns with
        higher priority values.

        Args:
            command: The command string to match

        Returns:
            TestRunnerMatch object containing match status and metadata.

        Examples:
            >>> registry = TestRunnerRegistry()
            >>> match = registry.match_command("pytest tests/")
            >>> match.is_match
            True
            >>> match.language
            'python'
            >>> match.framework
            'pytest'
        """
        if not command:
            return TestRunnerMatch(is_match=False)

        # Sort patterns by priority (highest first)
        sorted_patterns = sorted(self._patterns, key=lambda p: p.priority, reverse=True)

        for pattern_def in sorted_patterns:
            for pattern in pattern_def.patterns:
                if pattern.search(command):
                    return TestRunnerMatch(
                        is_match=True,
                        language=pattern_def.language,
                        framework=pattern_def.framework,
                    )

        return TestRunnerMatch(is_match=False)

    def register_pattern(self, pattern: TestRunnerPattern) -> None:
        """Register a new test runner pattern.

        Adds a new test runner pattern to the registry, enabling extensibility
        for custom or additional test frameworks.

        Args:
            pattern: The TestRunnerPattern to register

        Examples:
            >>> registry = TestRunnerRegistry()
            >>> custom_pattern = TestRunnerPattern(
            ...     language="python",
            ...     framework="custom_test",
            ...     patterns=[re.compile(r"\\bcustom_test\\b")],
            ...     priority=10
            ... )
            >>> registry.register_pattern(custom_pattern)
        """
        # Enforce maximum pattern limit to prevent memory leaks
        if len(self._patterns) >= self._max_patterns:
            # Remove oldest patterns (simple FIFO eviction)
            # Remove the oldest pattern(s) to make room for new one
            excess = len(self._patterns) - self._max_patterns + 1

            # Simple approach: remove oldest excess patterns
            # Keep patterns from index 'excess' to end
            self._patterns = self._patterns[excess:]

            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Evicted %d oldest patterns to maintain max_patterns=%d limit",
                    excess,
                    self._max_patterns,
                )

        self._patterns.append(pattern)

    def get_pattern_count(self) -> int:
        """Get the number of registered patterns.

        Returns:
            Count of patterns currently registered
        """
        return len(self._patterns)

    def _load_default_patterns(self) -> None:
        """Load default patterns for popular languages.

        Initializes the registry with patterns for Python test runners
        (pytest and unittest). This method is called automatically during
        initialization.
        """
        # Python - pytest
        # Use specific patterns that match pytest as the primary command,
        # not just mentioned somewhere in the command line.
        # The key is to ensure pytest/unittest is the actual command being executed,
        # not just an argument or package name.
        pytest_patterns = [
            # Direct pytest invocation at start of command
            re.compile(r"^pytest(?:\s|$)"),
            re.compile(r"^py\.test(?:\s|$)"),
            # Python module invocation (pytest must be the module, not an argument)
            re.compile(r"^python\s+-m\s+pytest(?:\s|$)"),
            re.compile(r"^python3\s+-m\s+pytest(?:\s|$)"),
            # Wrapper invocations (pytest must be the command after 'run')
            re.compile(r"^pipenv\s+run\s+pytest(?:\s|$)"),
            re.compile(r"^poetry\s+run\s+pytest(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="python",
                framework="pytest",
                patterns=pytest_patterns,
                priority=10,
            )
        )

        # Python - unittest
        unittest_patterns = [
            # Python module invocation (unittest must be the module, not an argument)
            re.compile(r"^python\s+-m\s+unittest(?:\s|$)"),
            re.compile(r"^python3\s+-m\s+unittest(?:\s|$)"),
            # Direct unittest invocation at start of command
            re.compile(r"^unittest(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="python",
                framework="unittest",
                patterns=unittest_patterns,
                priority=10,
            )
        )

        # JavaScript/TypeScript - jest
        jest_patterns = [
            # Direct jest invocation at start of command
            re.compile(r"^jest(?:\s|$)"),
            # NPM/Yarn script invocations
            re.compile(r"^npm\s+test(?:\s|$)"),
            re.compile(r"^npm\s+run\s+test(?:\s|$)"),
            re.compile(r"^npm\s+run\s+jest(?:\s|$)"),
            re.compile(r"^yarn\s+test(?:\s|$)"),
            re.compile(r"^yarn\s+run\s+test(?:\s|$)"),
            re.compile(r"^yarn\s+run\s+jest(?:\s|$)"),
            # Node module invocation
            re.compile(r"^node\s+.*node_modules/\.bin/jest(?:\s|$)"),
            re.compile(r"^npx\s+jest(?:\s|$)"),
            # Wrapper invocations
            re.compile(r"^pnpm\s+test(?:\s|$)"),
            re.compile(r"^pnpm\s+run\s+test(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="javascript",
                framework="jest",
                patterns=jest_patterns,
                priority=10,
            )
        )

        # JavaScript/TypeScript - vitest
        vitest_patterns = [
            # Direct vitest invocation at start of command
            re.compile(r"^vitest(?:\s|$)"),
            # NPM/Yarn script invocations
            re.compile(r"^npm\s+run\s+vitest(?:\s|$)"),
            re.compile(r"^yarn\s+run\s+vitest(?:\s|$)"),
            # Node module invocation
            re.compile(r"^npx\s+vitest(?:\s|$)"),
            # Wrapper invocations
            re.compile(r"^pnpm\s+run\s+vitest(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="javascript",
                framework="vitest",
                patterns=vitest_patterns,
                priority=10,
            )
        )

        # JavaScript/TypeScript - mocha
        mocha_patterns = [
            # Direct mocha invocation at start of command
            re.compile(r"^mocha(?:\s|$)"),
            # NPM/Yarn script invocations
            re.compile(r"^npm\s+run\s+mocha(?:\s|$)"),
            re.compile(r"^yarn\s+run\s+mocha(?:\s|$)"),
            # Node module invocation
            re.compile(r"^node\s+.*node_modules/\.bin/mocha(?:\s|$)"),
            re.compile(r"^npx\s+mocha(?:\s|$)"),
            # Wrapper invocations
            re.compile(r"^pnpm\s+run\s+mocha(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="javascript",
                framework="mocha",
                patterns=mocha_patterns,
                priority=10,
            )
        )

        # JavaScript/TypeScript - ava
        ava_patterns = [
            # Direct ava invocation at start of command
            re.compile(r"^ava(?:\s|$)"),
            # NPM/Yarn script invocations
            re.compile(r"^npm\s+run\s+ava(?:\s|$)"),
            re.compile(r"^yarn\s+run\s+ava(?:\s|$)"),
            # Node module invocation
            re.compile(r"^npx\s+ava(?:\s|$)"),
            # Wrapper invocations
            re.compile(r"^pnpm\s+run\s+ava(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="javascript",
                framework="ava",
                patterns=ava_patterns,
                priority=10,
            )
        )

        # Rust - cargo test
        rust_patterns = [
            # Direct cargo test invocation
            re.compile(r"^cargo\s+test(?:\s|$)"),
            # With additional flags
            re.compile(r"^cargo\s+test\s+"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="rust",
                framework="cargo",
                patterns=rust_patterns,
                priority=10,
            )
        )

        # Go - go test
        go_patterns = [
            # Direct go test invocation
            re.compile(r"^go\s+test(?:\s|$)"),
            # With additional flags or paths
            re.compile(r"^go\s+test\s+"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="go",
                framework="go test",
                patterns=go_patterns,
                priority=10,
            )
        )

        # Java - Maven
        maven_patterns = [
            # Direct mvn test invocation (with or without clean/other goals)
            re.compile(r"^mvn\s+.*\btest\b"),
            re.compile(r"^mvn\s+.*\bverify\b"),
            # Maven wrapper
            re.compile(r"^\.\/mvnw\s+.*\btest\b"),
            re.compile(r"^mvnw\s+.*\btest\b"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="java",
                framework="maven",
                patterns=maven_patterns,
                priority=10,
            )
        )

        # Java - Gradle (higher priority than Kotlin to match first)
        gradle_patterns = [
            # Direct gradle test invocation (with or without clean/other tasks)
            re.compile(r"^gradle\s+.*\btest\b"),
            # Gradle wrapper
            re.compile(r"^\.\/gradlew\s+.*\btest\b"),
            re.compile(r"^gradlew\s+.*\btest\b"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="java",
                framework="gradle",
                patterns=gradle_patterns,
                priority=15,  # Higher priority to match before Kotlin
            )
        )

        # C# - dotnet test
        csharp_patterns = [
            # Direct dotnet test invocation
            re.compile(r"^dotnet\s+test(?:\s|$)"),
            # With additional flags
            re.compile(r"^dotnet\s+test\s+"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="csharp",
                framework="dotnet",
                patterns=csharp_patterns,
                priority=10,
            )
        )

        # Ruby - RSpec
        rspec_patterns = [
            # Direct rspec invocation
            re.compile(r"^rspec(?:\s|$)"),
            # Bundle exec invocation
            re.compile(r"^bundle\s+exec\s+rspec(?:\s|$)"),
            # Rake test
            re.compile(r"^rake\s+test(?:\s|$)"),
            re.compile(r"^bundle\s+exec\s+rake\s+test(?:\s|$)"),
            # Ruby test invocation
            re.compile(r"^ruby\s+-Itest(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="ruby",
                framework="rspec",
                patterns=rspec_patterns,
                priority=10,
            )
        )

        # PHP - PHPUnit
        php_patterns = [
            # Direct phpunit invocation
            re.compile(r"^phpunit(?:\s|$)"),
            # Vendor bin invocation
            re.compile(r"^vendor/bin/phpunit(?:\s|$)"),
            re.compile(r"^\.\/vendor/bin/phpunit(?:\s|$)"),
            # Composer test
            re.compile(r"^composer\s+test(?:\s|$)"),
            re.compile(r"^composer\s+run\s+test(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="php",
                framework="phpunit",
                patterns=php_patterns,
                priority=10,
            )
        )

        # C/C++ - CTest and Make
        cpp_patterns = [
            # CTest invocation
            re.compile(r"^ctest(?:\s|$)"),
            # Make test
            re.compile(r"^make\s+test(?:\s|$)"),
            # CMake build with test target
            re.compile(r"^cmake\s+--build\s+.*--target\s+test(?:\s|$)"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="cpp",
                framework="ctest",
                patterns=cpp_patterns,
                priority=10,
            )
        )

        # Swift - swift test
        swift_patterns = [
            # Direct swift test invocation
            re.compile(r"^swift\s+test(?:\s|$)"),
            # With additional flags
            re.compile(r"^swift\s+test\s+"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="swift",
                framework="swift test",
                patterns=swift_patterns,
                priority=10,
            )
        )

        # Note: Kotlin projects also use Gradle for testing, but we treat all
        # Gradle test commands as Java since we cannot distinguish between
        # Java and Kotlin projects from the command alone. This covers both
        # Java and Kotlin test execution.

        # Scala - sbt test
        scala_patterns = [
            # Direct sbt test invocation (matches test, testOnly, testQuick, etc.)
            re.compile(r"^sbt\s+.*\btest\b"),
            re.compile(r"^sbt\s+.*\btestOnly\b"),
            re.compile(r"^sbt\s+.*\btestQuick\b"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="scala",
                framework="sbt",
                patterns=scala_patterns,
                priority=10,
            )
        )

        # Elixir - mix test
        elixir_patterns = [
            # Direct mix test invocation
            re.compile(r"^mix\s+test(?:\s|$)"),
            # With additional flags
            re.compile(r"^mix\s+test\s+"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="elixir",
                framework="mix",
                patterns=elixir_patterns,
                priority=10,
            )
        )

        # Dart/Flutter - dart test and flutter test
        dart_patterns = [
            # Direct dart test invocation
            re.compile(r"^dart\s+test(?:\s|$)"),
            # Flutter test invocation
            re.compile(r"^flutter\s+test(?:\s|$)"),
            # With additional flags
            re.compile(r"^dart\s+test\s+"),
            re.compile(r"^flutter\s+test\s+"),
        ]
        self.register_pattern(
            TestRunnerPattern(
                language="dart",
                framework="dart test",
                patterns=dart_patterns,
                priority=10,
            )
        )

        # Note: Kotlin projects also use Gradle for testing, but we treat all
        # Gradle test commands as Java since we cannot distinguish between
        # Java and Kotlin projects from the command alone. This covers both
        # Java and Kotlin test execution.
