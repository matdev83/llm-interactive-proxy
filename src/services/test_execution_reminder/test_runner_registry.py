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


# Pre-compiled regex patterns for performance optimization
# Python
_PYTEST_PATTERNS = [
    re.compile(r"^pytest(?:\s|$)"),
    re.compile(r"^py\.test(?:\s|$)"),
    re.compile(r"^python\s+-m\s+pytest(?:\s|$)"),
    re.compile(r"^python3\s+-m\s+pytest(?:\s|$)"),
    re.compile(r"^pipenv\s+run\s+pytest(?:\s|$)"),
    re.compile(r"^poetry\s+run\s+pytest(?:\s|$)"),
]

_UNITTEST_PATTERNS = [
    re.compile(r"^python\s+-m\s+unittest(?:\s|$)"),
    re.compile(r"^python3\s+-m\s+unittest(?:\s|$)"),
    re.compile(r"^unittest(?:\s|$)"),
]

# JavaScript/TypeScript
_JEST_PATTERNS = [
    re.compile(r"^jest(?:\s|$)"),
    re.compile(r"^npm\s+test(?:\s|$)"),
    re.compile(r"^npm\s+run\s+test(?:\s|$)"),
    re.compile(r"^npm\s+run\s+jest(?:\s|$)"),
    re.compile(r"^yarn\s+test(?:\s|$)"),
    re.compile(r"^yarn\s+run\s+test(?:\s|$)"),
    re.compile(r"^yarn\s+run\s+jest(?:\s|$)"),
    re.compile(r"^node\s+.*node_modules/\.bin/jest(?:\s|$)"),
    re.compile(r"^npx\s+jest(?:\s|$)"),
    re.compile(r"^pnpm\s+test(?:\s|$)"),
    re.compile(r"^pnpm\s+run\s+test(?:\s|$)"),
]

_VITEST_PATTERNS = [
    re.compile(r"^vitest(?:\s|$)"),
    re.compile(r"^npm\s+run\s+vitest(?:\s|$)"),
    re.compile(r"^yarn\s+run\s+vitest(?:\s|$)"),
    re.compile(r"^npx\s+vitest(?:\s|$)"),
    re.compile(r"^pnpm\s+run\s+vitest(?:\s|$)"),
]

_MOCHA_PATTERNS = [
    re.compile(r"^mocha(?:\s|$)"),
    re.compile(r"^npm\s+run\s+mocha(?:\s|$)"),
    re.compile(r"^yarn\s+run\s+mocha(?:\s|$)"),
    re.compile(r"^node\s+.*node_modules/\.bin/mocha(?:\s|$)"),
    re.compile(r"^npx\s+mocha(?:\s|$)"),
    re.compile(r"^pnpm\s+run\s+mocha(?:\s|$)"),
]

_AVA_PATTERNS = [
    re.compile(r"^ava(?:\s|$)"),
    re.compile(r"^npm\s+run\s+ava(?:\s|$)"),
    re.compile(r"^yarn\s+run\s+ava(?:\s|$)"),
    re.compile(r"^npx\s+ava(?:\s|$)"),
    re.compile(r"^pnpm\s+run\s+ava(?:\s|$)"),
]

# Rust
_CARGO_PATTERNS = [
    re.compile(r"^cargo\s+test(?:\s|$)"),
    re.compile(r"^cargo\s+test\s+"),
]

# Go
_GO_PATTERNS = [
    re.compile(r"^go\s+test(?:\s|$)"),
    re.compile(r"^go\s+test\s+"),
]

# Java
_MAVEN_PATTERNS = [
    re.compile(r"^mvn\s+.*\btest\b"),
    re.compile(r"^mvn\s+.*\bverify\b"),
    re.compile(r"^\.\/mvnw\s+.*\btest\b"),
    re.compile(r"^mvnw\s+.*\btest\b"),
]

_GRADLE_PATTERNS = [
    re.compile(r"^gradle\s+.*\btest\b"),
    re.compile(r"^\.\/gradlew\s+.*\btest\b"),
    re.compile(r"^gradlew\s+.*\btest\b"),
]

# C#
_DOTNET_PATTERNS = [
    re.compile(r"^dotnet\s+test(?:\s|$)"),
    re.compile(r"^dotnet\s+test\s+"),
]

# Ruby
_RSPEC_PATTERNS = [
    re.compile(r"^rspec(?:\s|$)"),
    re.compile(r"^bundle\s+exec\s+rspec(?:\s|$)"),
    re.compile(r"^rake\s+test(?:\s|$)"),
    re.compile(r"^bundle\s+exec\s+rake\s+test(?:\s|$)"),
    re.compile(r"^ruby\s+-Itest(?:\s|$)"),
]

# PHP
_PHPUNIT_PATTERNS = [
    re.compile(r"^phpunit(?:\s|$)"),
    re.compile(r"^vendor/bin/phpunit(?:\s|$)"),
    re.compile(r"^\.\/vendor/bin/phpunit(?:\s|$)"),
    re.compile(r"^composer\s+test(?:\s|$)"),
    re.compile(r"^composer\s+run\s+test(?:\s|$)"),
]

# C/C++
_CPP_PATTERNS = [
    re.compile(r"^ctest(?:\s|$)"),
    re.compile(r"^make\s+test(?:\s|$)"),
    re.compile(r"^cmake\s+--build\s+.*--target\s+test(?:\s|$)"),
]

# Swift
_SWIFT_PATTERNS = [
    re.compile(r"^swift\s+test(?:\s|$)"),
    re.compile(r"^swift\s+test\s+"),
]

# Scala
_SCALA_PATTERNS = [
    re.compile(r"^sbt\s+.*\btest\b"),
    re.compile(r"^sbt\s+.*\btestOnly\b"),
    re.compile(r"^sbt\s+.*\btestQuick\b"),
]

# Elixir
_ELIXIR_PATTERNS = [
    re.compile(r"^mix\s+test(?:\s|$)"),
    re.compile(r"^mix\s+test\s+"),
]

# Dart/Flutter
_DART_PATTERNS = [
    re.compile(r"^dart\s+test(?:\s|$)"),
    re.compile(r"^flutter\s+test(?:\s|$)"),
    re.compile(r"^dart\s+test\s+"),
    re.compile(r"^flutter\s+test\s+"),
]


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

    def __iter__(self):  # type: ignore[override]
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
        self.register_pattern(
            TestRunnerPattern(
                language="python",
                framework="pytest",
                patterns=_PYTEST_PATTERNS,
                priority=10,
            )
        )

        # Python - unittest
        self.register_pattern(
            TestRunnerPattern(
                language="python",
                framework="unittest",
                patterns=_UNITTEST_PATTERNS,
                priority=10,
            )
        )

        # JavaScript/TypeScript - jest
        self.register_pattern(
            TestRunnerPattern(
                language="javascript",
                framework="jest",
                patterns=_JEST_PATTERNS,
                priority=10,
            )
        )

        # JavaScript/TypeScript - vitest
        self.register_pattern(
            TestRunnerPattern(
                language="javascript",
                framework="vitest",
                patterns=_VITEST_PATTERNS,
                priority=10,
            )
        )

        # JavaScript/TypeScript - mocha
        self.register_pattern(
            TestRunnerPattern(
                language="javascript",
                framework="mocha",
                patterns=_MOCHA_PATTERNS,
                priority=10,
            )
        )

        # JavaScript/TypeScript - ava
        self.register_pattern(
            TestRunnerPattern(
                language="javascript",
                framework="ava",
                patterns=_AVA_PATTERNS,
                priority=10,
            )
        )

        # Rust - cargo test
        self.register_pattern(
            TestRunnerPattern(
                language="rust",
                framework="cargo",
                patterns=_CARGO_PATTERNS,
                priority=10,
            )
        )

        # Go - go test
        self.register_pattern(
            TestRunnerPattern(
                language="go",
                framework="go test",
                patterns=_GO_PATTERNS,
                priority=10,
            )
        )

        # Java - Maven
        self.register_pattern(
            TestRunnerPattern(
                language="java",
                framework="maven",
                patterns=_MAVEN_PATTERNS,
                priority=10,
            )
        )

        # Java - Gradle (higher priority than Kotlin to match first)
        self.register_pattern(
            TestRunnerPattern(
                language="java",
                framework="gradle",
                patterns=_GRADLE_PATTERNS,
                priority=15,  # Higher priority to match before Kotlin
            )
        )

        # C# - dotnet test
        self.register_pattern(
            TestRunnerPattern(
                language="csharp",
                framework="dotnet",
                patterns=_DOTNET_PATTERNS,
                priority=10,
            )
        )

        # Ruby - RSpec
        self.register_pattern(
            TestRunnerPattern(
                language="ruby",
                framework="rspec",
                patterns=_RSPEC_PATTERNS,
                priority=10,
            )
        )

        # PHP - PHPUnit
        self.register_pattern(
            TestRunnerPattern(
                language="php",
                framework="phpunit",
                patterns=_PHPUNIT_PATTERNS,
                priority=10,
            )
        )

        # C/C++ - CTest and Make
        self.register_pattern(
            TestRunnerPattern(
                language="cpp",
                framework="ctest",
                patterns=_CPP_PATTERNS,
                priority=10,
            )
        )

        # Swift - swift test
        self.register_pattern(
            TestRunnerPattern(
                language="swift",
                framework="swift test",
                patterns=_SWIFT_PATTERNS,
                priority=10,
            )
        )

        # Note: Kotlin projects also use Gradle for testing, but we treat all
        # Gradle test commands as Java since we cannot distinguish between
        # Java and Kotlin projects from the command alone. This covers both
        # Java and Kotlin test execution.

        # Scala - sbt test
        self.register_pattern(
            TestRunnerPattern(
                language="scala",
                framework="sbt",
                patterns=_SCALA_PATTERNS,
                priority=10,
            )
        )

        # Elixir - mix test
        self.register_pattern(
            TestRunnerPattern(
                language="elixir",
                framework="mix",
                patterns=_ELIXIR_PATTERNS,
                priority=10,
            )
        )

        # Dart/Flutter - dart test and flutter test
        self.register_pattern(
            TestRunnerPattern(
                language="dart",
                framework="dart test",
                patterns=_DART_PATTERNS,
                priority=10,
            )
        )

        # Note: Kotlin projects also use Gradle for testing, but we treat all
        # Gradle test commands as Java since we cannot distinguish between
        # Java and Kotlin projects from the command alone. This covers both
        # Java and Kotlin test execution.
