"""Directory listing and search-result grouping compression strategies."""

from __future__ import annotations

import re
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services._compression_strategies_common import _preserve_trailing_newline


@dataclass
class _DirectoryTreeNode:
    children: dict[str, _DirectoryTreeNode] = field(default_factory=dict)
    files: set[str] = field(default_factory=set)


class DirectoryTreeSummaryStrategy:
    """Render listing-like outputs as a compact deterministic hierarchy."""

    _known_listing_commands = frozenset({"ls", "tree", "dir"})
    _ascii_tree_prefix_re = re.compile(r"^[\s|`+\-]+")
    _unicode_tree_prefix_codepoints = frozenset(
        {0x2502, 0x251C, 0x2514, 0x252C, 0x253C, 0x2500}
    )
    _ls_permissions_re = re.compile(r"^[\-dlcbsp][rwxStTs\-]{9}")
    _summary_line_re = re.compile(r"(?i)\b\d+\s+director(?:y|ies)\b.*\b\d+\s+files?\b")

    def __init__(
        self,
        *,
        noise_directories: list[str] | None = None,
        max_extension_buckets: int = 5,
    ) -> None:
        self._noise_directories = {
            entry.strip().lower()
            for entry in (noise_directories or [])
            if entry.strip()
        }
        self._max_extension_buckets = max(1, int(max_extension_buckets))

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not content:
            return content
        if not self._should_apply(context=context, content=content):
            return content

        entries = self._extract_entries(content)
        if entries is None:
            return content
        if not entries:
            return _preserve_trailing_newline(original=content, transformed="(empty)")

        tree = _DirectoryTreeNode()
        directory_paths: set[str] = set()
        extension_counts: dict[str, int] = {}
        file_paths: set[str] = set()

        for path, is_dir in sorted(entries.items()):
            parts = [segment for segment in path.split("/") if segment]
            if not parts:
                continue

            node = tree
            for depth in range(len(parts) - (0 if is_dir else 1)):
                segment = parts[depth]
                node = node.children.setdefault(segment, _DirectoryTreeNode())
                directory_paths.add("/".join(parts[: depth + 1]))

            if not is_dir:
                filename = parts[-1]
                if filename in node.files:
                    continue
                node.files.add(filename)
                file_paths.add(path)
                ext = self._extension_bucket(filename)
                extension_counts[ext] = extension_counts.get(ext, 0) + 1

        rendered = self._render_tree(tree, depth=0)
        if not rendered:
            return content

        summary = f"Summary: {len(file_paths)} files, {len(directory_paths)} dirs"
        if extension_counts:
            sorted_ext = sorted(
                extension_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
            parts = [
                f"{count} {ext}"
                for ext, count in sorted_ext[: self._max_extension_buckets]
            ]
            summary = f"{summary} ({', '.join(parts)})"
            if len(sorted_ext) > self._max_extension_buckets:
                summary = f"{summary[:-1]}, +{len(sorted_ext) - self._max_extension_buckets} more)"

        output = "\n".join([*rendered, summary])
        return _preserve_trailing_newline(original=content, transformed=output)

    def _should_apply(self, *, context: ToolOutputContext, content: str) -> bool:
        signature = (context.identity.command_signature or "").lower()
        if signature in self._known_listing_commands:
            return True
        if context.identity.tool_category == "list_dir":
            return True
        path_like_lines = 0
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if "/" in stripped or "\\" in stripped:
                path_like_lines += 1
            if path_like_lines >= 4:
                return True
        return False

    def _extract_entries(self, content: str) -> dict[str, bool] | None:
        entries: dict[str, bool] = {}
        parsed_any = False
        for raw_line in content.splitlines():
            parsed = self._parse_listing_line(raw_line)
            if parsed is None:
                continue
            parsed_any = True
            path, is_dir = parsed
            normalized = path.replace("\\", "/").strip().rstrip("/")
            normalized = normalized.lstrip("./")
            if not normalized or normalized in {".", ".."}:
                continue
            if self._is_noise_path(normalized):
                continue
            previous_is_dir = entries.get(normalized)
            entries[normalized] = bool(previous_is_dir or is_dir)
        if not parsed_any:
            return None
        return entries

    def _parse_listing_line(self, raw_line: str) -> tuple[str, bool] | None:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            return None
        if stripped.startswith("total "):
            return None
        if self._summary_line_re.search(stripped):
            return None
        if stripped in {".", ".."}:
            return None

        if self._ls_permissions_re.match(stripped):
            parts = stripped.split()
            if len(parts) >= 9:
                name = " ".join(parts[8:]).strip()
                if not name or name in {".", ".."}:
                    return None
                is_dir = parts[0].startswith("d")
                return name, is_dir

        normalized = self._strip_tree_prefix(stripped)
        if not normalized:
            return None
        if normalized == ".":
            return None

        if "  " in normalized:
            normalized = normalized.split("  ", maxsplit=1)[0].rstrip()
        is_dir = normalized.endswith("/")
        return normalized.rstrip("/"), is_dir

    def _is_noise_path(self, normalized_path: str) -> bool:
        if not self._noise_directories:
            return False
        root = normalized_path.split("/", maxsplit=1)[0].lower()
        return root in self._noise_directories

    def _render_tree(self, node: _DirectoryTreeNode, *, depth: int) -> list[str]:
        lines: list[str] = []
        for directory in sorted(node.children):
            lines.append(f"{'  ' * depth}{directory}/")
            lines.extend(self._render_tree(node.children[directory], depth=depth + 1))
        for filename in sorted(node.files):
            lines.append(f"{'  ' * depth}{filename}")
        return lines

    @classmethod
    def _strip_tree_prefix(cls, value: str) -> str:
        if not value:
            return value
        normalized = cls._ascii_tree_prefix_re.sub("", value)
        idx = 0
        while idx < len(normalized):
            char = normalized[idx]
            if ord(char) in cls._unicode_tree_prefix_codepoints or char.isspace():
                idx += 1
                continue
            break
        return normalized[idx:].strip()

    @staticmethod
    def _extension_bucket(filename: str) -> str:
        if "." not in filename:
            return "no ext"
        return filename[filename.rfind(".") :]


@dataclass(frozen=True)
class _SearchLine:
    line_no: int | None
    text: str
    is_context: bool


class SearchResultsGroupingStrategy:
    """Group grep/find-like output by file with bounded context retention."""

    _known_search_commands = frozenset({"rg", "grep", "find"})
    _match_line_re = re.compile(
        r"^(?P<file>(?:[A-Za-z]:)?[^:\n]+?):(?P<line>\d+)(?::\d+)?:\s?(?P<text>.*)$"
    )
    _context_line_re = re.compile(
        r"^(?P<file>(?:[A-Za-z]:)?[^:\n]+?)-(?P<line>\d+)-\s?(?P<text>.*)$"
    )

    def __init__(
        self,
        *,
        max_matches_per_file: int = 8,
        max_total_groups: int = 100,
        context_lines: int = 2,
        max_line_length: int = 240,
    ) -> None:
        self._max_matches_per_file = max(1, int(max_matches_per_file))
        self._max_total_groups = max(1, int(max_total_groups))
        self._context_lines = max(0, int(context_lines))
        self._max_line_length = max(20, int(max_line_length))

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not content:
            return content
        if not self._should_apply(context=context, content=content):
            return content

        by_file: OrderedDict[str, list[_SearchLine]] = OrderedDict()
        seen_matches: dict[str, set[tuple[int | None, str]]] = {}
        match_counts: dict[str, int] = {}
        duplicate_counts: dict[str, int] = {}
        omitted_context_counts: dict[str, int] = {}
        omitted_match_counts: dict[str, int] = {}
        context_budget: dict[str, int] = {}
        pending_leading_context: dict[str, deque[_SearchLine]] = {}

        for raw_line in content.splitlines():
            parsed = self._parse_search_line(raw_line)
            if parsed is None:
                continue
            file_path, line_no, raw_text, is_context = parsed
            clean_text = self._clean_line(raw_text)
            lines = by_file.setdefault(file_path, [])
            match_counts.setdefault(file_path, 0)
            duplicate_counts.setdefault(file_path, 0)
            omitted_context_counts.setdefault(file_path, 0)
            omitted_match_counts.setdefault(file_path, 0)
            context_budget.setdefault(file_path, 0)

            if is_context:
                if context_budget[file_path] > 0:
                    lines.append(
                        _SearchLine(
                            line_no=line_no,
                            text=clean_text,
                            is_context=True,
                        )
                    )
                    context_budget[file_path] -= 1
                elif (
                    self._context_lines > 0
                    and match_counts[file_path] < self._max_matches_per_file
                ):
                    pending_context = pending_leading_context.setdefault(
                        file_path,
                        deque(maxlen=self._context_lines),
                    )
                    if (
                        pending_context.maxlen is not None
                        and len(pending_context) == pending_context.maxlen
                    ):
                        omitted_context_counts[file_path] += 1
                    pending_context.append(
                        _SearchLine(
                            line_no=line_no,
                            text=clean_text,
                            is_context=True,
                        )
                    )
                else:
                    omitted_context_counts[file_path] += 1
                continue

            key = (line_no, clean_text)
            seen = seen_matches.setdefault(file_path, set())
            if key in seen:
                duplicate_counts[file_path] += 1
                continue
            seen.add(key)

            if match_counts[file_path] >= self._max_matches_per_file:
                omitted_match_counts[file_path] += 1
                context_budget[file_path] = 0
                pending_for_match = pending_leading_context.get(file_path)
                if pending_for_match:
                    omitted_context_counts[file_path] += len(pending_for_match)
                    pending_for_match.clear()
                continue

            pending_for_match = pending_leading_context.get(file_path)
            if pending_for_match:
                lines.extend(pending_for_match)
                pending_for_match.clear()
            lines.append(
                _SearchLine(line_no=line_no, text=clean_text, is_context=False)
            )
            match_counts[file_path] += 1
            context_budget[file_path] = self._context_lines

        if not by_file:
            return content
        for file_path, pending in pending_leading_context.items():
            if pending:
                omitted_context_counts[file_path] += len(pending)

        rendered: list[str] = []
        for file_path in sorted(by_file.keys())[: self._max_total_groups]:
            lines = by_file[file_path]
            rendered.append(f"[file] {file_path} ({match_counts[file_path]} matches)")
            for entry in lines:
                if entry.line_no is None:
                    rendered.append(f"  - {entry.text}")
                else:
                    rendered.append(f"  {entry.line_no:>4}: {entry.text}")
            if duplicate_counts[file_path] > 0:
                rendered.append(
                    f"  ... ({duplicate_counts[file_path]} duplicate lines removed)"
                )
            if omitted_context_counts[file_path] > 0:
                rendered.append(
                    f"  ... ({omitted_context_counts[file_path]} context lines omitted)"
                )
            if omitted_match_counts[file_path] > 0:
                rendered.append(
                    f"  ... (+{omitted_match_counts[file_path]} matches truncated)"
                )
            rendered.append("")

        if len(by_file) > self._max_total_groups:
            rendered.append(
                f"... (+{len(by_file) - self._max_total_groups} files truncated)"
            )

        output = "\n".join(rendered).rstrip("\n")
        return _preserve_trailing_newline(original=content, transformed=output)

    def _should_apply(self, *, context: ToolOutputContext, content: str) -> bool:
        signature = (context.identity.command_signature or "").lower()
        if signature in self._known_search_commands:
            return True
        if context.identity.tool_category == "search":
            return True
        recognized = 0
        for line in content.splitlines():
            if self._match_line_re.match(line.strip()):
                recognized += 1
            if recognized >= 3:
                return True
        return False

    def _parse_search_line(
        self,
        line: str,
    ) -> tuple[str, int | None, str, bool] | None:
        stripped = line.strip()
        if not stripped:
            return None

        match = self._match_line_re.match(stripped)
        if match:
            return (
                match.group("file").replace("\\", "/"),
                int(match.group("line")),
                match.group("text"),
                False,
            )

        context_match = self._context_line_re.match(stripped)
        if context_match:
            return (
                context_match.group("file").replace("\\", "/"),
                int(context_match.group("line")),
                context_match.group("text"),
                True,
            )

        if ":" in stripped:
            return None
        if "/" in stripped or "\\" in stripped:
            normalized = stripped.replace("\\", "/")
            if normalized.endswith("/"):
                normalized = normalized.rstrip("/")
            if not normalized:
                return None
            directory, _, filename = normalized.rpartition("/")
            file_key = directory or "."
            return file_key, None, filename or normalized, False

        return None

    def _clean_line(self, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) <= self._max_line_length:
            return trimmed
        prefix = trimmed[: self._max_line_length - 3]
        return f"{prefix}..."
