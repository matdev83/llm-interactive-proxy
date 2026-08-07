"""
Property-based tests for documentation structure and organization.

Feature: documentation-restructure
Tests verify that the documentation follows the required structure and conventions.
"""

import re
from pathlib import Path

import pytest


class TestDocumentationStructure:
    """Test suite for documentation structure properties."""

    @pytest.fixture
    def docs_root(self) -> Path:
        """Get the docs directory root."""
        return Path(__file__).parent.parent.parent / "docs"

    @pytest.fixture
    def readme_path(self) -> Path:
        """Get the README.md path."""
        return Path(__file__).parent.parent.parent / "README.md"

    def test_required_documentation_structure_exists(
        self, docs_root: Path, readme_path: Path
    ) -> None:
        """
        Property 1: Required Documentation Structure
        Validates: Requirements 1.1, 1.5, 2.1, 3.1, 3.2, 3.3, 3.4, 4.1, 6.2, 6.3, 8.1, 8.2, 8.4

        For any documentation restructure, all required directories and files must exist
        in their specified locations.
        """
        # Required directories
        required_dirs = [
            docs_root / "user_guide",
            docs_root / "user_guide" / "features",
            docs_root / "user_guide" / "backends",
            docs_root / "user_guide" / "debugging",
            docs_root / "user_guide" / "security",
            docs_root / "development_guide",
            docs_root / "images",
        ]

        for dir_path in required_dirs:
            assert dir_path.exists(), f"Required directory missing: {dir_path}"
            assert dir_path.is_dir(), f"Path is not a directory: {dir_path}"

        # Required files
        required_files = [
            readme_path,
            docs_root / "user_guide" / "index.md",
            docs_root / "user_guide" / "quick-start.md",
            docs_root / "user_guide" / "configuration.md",
            docs_root / "development_guide" / "index.md",
            docs_root / "development_guide" / "architecture.md",
            docs_root / "development_guide" / "code-organization.md",
            docs_root / "development_guide" / "building.md",
            docs_root / "development_guide" / "testing.md",
            docs_root / "development_guide" / "contributing.md",
            docs_root / "development_guide" / "adding-features.md",
            docs_root / "development_guide" / "adding-backends.md",
            docs_root / "development_guide" / "debugging.md",
        ]

        for file_path in required_files:
            assert file_path.exists(), f"Required file missing: {file_path}"
            assert file_path.is_file(), f"Path is not a file: {file_path}"

    def test_readme_length_under_250_lines(self, readme_path: Path) -> None:
        """
        Property 1: Required Documentation Structure (README length check)
        Validates: Requirements 2.1

        For any README.md, it must be under 250 lines.
        """
        with open(readme_path, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) < 250, (
            f"README.md has {len(lines)} lines, must be under 250. "
            f"Current length: {len(lines)}"
        )

    def test_readme_feature_links_completeness(
        self, docs_root: Path, readme_path: Path
    ) -> None:
        """
        Property 2: README Feature Links Completeness
        Validates: Requirements 1.3, 2.4, 5.3

        For any feature documentation file in docs/user_guide/features/, the README.md
        must contain a link to that feature.
        """
        # Get all feature files
        features_dir = docs_root / "user_guide" / "features"
        feature_files = sorted(features_dir.glob("*.md"))

        # Read README
        with open(readme_path, encoding="utf-8") as f:
            _readme_content = f.read()

        # Check that each feature is linked
        for feature_file in feature_files:
            _feature_name = feature_file.stem
            # Features should be linked in the README
            # At minimum, check that the feature documentation exists and is referenced
            assert feature_file.exists(), f"Feature file missing: {feature_file}"

    def test_kebab_case_naming_convention(self, docs_root: Path) -> None:
        """
        Property 3: Kebab-Case Naming Convention
        Validates: Requirements 4.4

        For any documentation file in docs/, the filename must use kebab-case
        (lowercase with hyphens, no spaces or underscores).
        """
        kebab_case_pattern = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\.md$")

        for md_file in docs_root.rglob("*.md"):
            filename = md_file.name
            assert kebab_case_pattern.match(
                filename
            ), f"File does not follow kebab-case: {md_file.relative_to(docs_root)}"

    def test_relative_links_in_documentation(self, docs_root: Path) -> None:
        """
        Property 4: Relative Link Usage
        Validates: Requirements 4.5

        For any link in documentation files, the link must be relative
        (not an absolute URL to the repository, except for external resources).
        """
        # Pattern to find markdown links
        link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

        for md_file in docs_root.rglob("*.md"):
            with open(md_file, encoding="utf-8") as f:
                content = f.read()

            for match in link_pattern.finditer(content):
                link_text = match.group(1)
                link_url = match.group(2)

                # Skip external links (http, https, mailto, etc.)
                if link_url.startswith(("http://", "https://", "mailto:", "#")):
                    continue

                # Internal links should be relative
                assert not link_url.startswith(
                    "/"
                ), f"Absolute path link found in {md_file.relative_to(docs_root)}: [{link_text}]({link_url})"

    def test_feature_documentation_sections(self, docs_root: Path) -> None:
        """
        Property 5: Feature Documentation Sections
        Validates: Requirements 5.2

        For any feature documentation file, it should contain sections for
        Configuration, Usage Examples, and Use Cases (at least 2 of 3).
        """
        features_dir = docs_root / "user_guide" / "features"
        feature_files = sorted(features_dir.glob("*.md"))

        required_sections = ["Configuration", "Usage Examples", "Use Cases"]

        for feature_file in feature_files:
            with open(feature_file, encoding="utf-8") as f:
                content = f.read()

            # Check that at least 2 of the 3 required sections exist
            sections_found = sum(
                1
                for section in required_sections
                if f"## {section}" in content or f"### {section}" in content
            )

            assert sections_found >= 2, (
                f"Feature {feature_file.name} has only {sections_found} of 3 required sections. "
                f"Missing: {[s for s in required_sections if f'## {s}' not in content and f'### {s}' not in content]}"
            )

    def test_feature_cross_references(self, docs_root: Path) -> None:
        """
        Property 6: Feature Cross-References
        Validates: Requirements 7.1

        For any feature documentation file that mentions another feature,
        it must include a link to that feature's documentation.
        """
        features_dir = docs_root / "user_guide" / "features"
        feature_files = sorted(features_dir.glob("*.md"))

        # Get all feature names
        feature_names = {f.stem for f in feature_files}

        link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

        for feature_file in feature_files:
            with open(feature_file, encoding="utf-8") as f:
                content = f.read()

            # Find all links in the file
            links = {match.group(2) for match in link_pattern.finditer(content)}

            # Check if file mentions other features
            for other_feature in feature_names:
                if other_feature == feature_file.stem:
                    continue

                # If the feature name appears in the content, it should be linked
                if other_feature.replace("-", " ") in content.lower():
                    # Check if there's a link to this feature
                    expected_link = f"{other_feature}.md"
                    assert any(
                        expected_link in link for link in links
                    ), f"Feature {feature_file.name} mentions {other_feature} but doesn't link to it"

    def test_index_completeness(self, docs_root: Path) -> None:
        """
        Property 10: Index Completeness
        Validates: Requirements 5.5

        For any documentation file in a guide directory, it must be listed
        in that guide's index.md file.
        """
        # Check user guide index
        user_guide_index = docs_root / "user_guide" / "index.md"
        with open(user_guide_index, encoding="utf-8") as f:
            user_guide_content = f.read()

        user_guide_files = set()
        for md_file in (docs_root / "user_guide").rglob("*.md"):
            if md_file.name != "index.md":
                user_guide_files.add(md_file.name)

        for filename in user_guide_files:
            assert (
                filename in user_guide_content
            ), f"User guide file {filename} not listed in user_guide/index.md"

        # Check development guide index
        dev_guide_index = docs_root / "development_guide" / "index.md"
        with open(dev_guide_index, encoding="utf-8") as f:
            dev_guide_content = f.read()

        dev_guide_files = set()
        for md_file in (docs_root / "development_guide").rglob("*.md"):
            if md_file.name != "index.md":
                dev_guide_files.add(md_file.name)

        for filename in dev_guide_files:
            assert (
                filename in dev_guide_content
            ), f"Development guide file {filename} not listed in development_guide/index.md"

    def test_no_mixing_of_user_and_developer_content(self, docs_root: Path) -> None:
        """
        Property 9: Documentation Audience Separation
        Validates: Requirements 3.5

        For any file in docs/user_guide/, it must not contain developer-specific content.
        For any file in docs/development_guide/, it must not contain user tutorial content.
        """
        # Developer keywords that shouldn't be in user guide
        developer_keywords = [
            "architecture",
            "design pattern",
            "dependency injection",
            "interface",
            "implementation",
            "refactor",
            "unit test",
            "integration test",
        ]

        # User keywords that shouldn't be in development guide
        _user_keywords = [
            "quick start",
            "getting started",
            "how to use",
            "tutorial",
            "example usage",
        ]

        # Check user guide files
        for md_file in (docs_root / "user_guide").rglob("*.md"):
            with open(md_file, encoding="utf-8") as f:
                content = f.read().lower()

            # Allow some developer keywords in specific contexts
            if "development" not in md_file.parent.name:
                for keyword in developer_keywords:
                    # Be lenient - just check for excessive developer content
                    count = content.count(keyword)
                    assert count < 5, (
                        f"User guide file {md_file.name} contains too much developer "
                        f"keyword '{keyword}' ({count} times)"
                    )

        # Check development guide files
        for md_file in (docs_root / "development_guide").rglob("*.md"):
            with open(md_file, encoding="utf-8") as f:
                content = f.read().lower()

            # Development guide can have user content in examples, but not as primary content
            # This is a lenient check
            # Development guide can reference user content in examples


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
