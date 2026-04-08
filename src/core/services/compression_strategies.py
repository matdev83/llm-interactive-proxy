"""Built-in dynamic compression strategies used by the orchestrator."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from collections import OrderedDict, defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from re import Pattern

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.pytest_output_filter import (
    filter_pytest_output,
    looks_like_pytest_command,
    looks_like_pytest_output,
)

_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)")
_DCS_PM_APC_RE = re.compile(r"\x1B(?:P|_|\^)[\s\S]*?(?:\x1B\\)")
_ESC_SINGLE_RE = re.compile(r"\x1B[@-Z\\-_]")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1A\x1C-\x1F\x7F-\x9F]")
_FAILURE_INDICATOR_RE = re.compile(
    r"(?i)\b("
    r"error|errors|failed|failure|fatal|panic|exception|traceback|"
    r"assertion(?:error)?|segmentation fault|stack trace|"
    r"timed out|timeout|denied"
    r")\b|^\s*E\s+|^\s*FAILED\b|^\s*FAIL\b"
)
_ZERO_FAILURE_RE = re.compile(r"(?i)\b(?:0\s+failed|0\s+failures|0\s+errors?)\b")
_POSITIVE_FAILURE_COUNT_RE = re.compile(
    r"(?i)\b[1-9]\d*\s+(?:failed|failures|errors?)\b"
)
logger = logging.getLogger(__name__)

_REGEX_EVAL_SUBPROCESS_SNIPPET = (
    "import json\n"
    "import re\n"
    "import sys\n"
    "payload = json.loads(sys.stdin.read())\n"
    "try:\n"
    "    compiled = re.compile(payload['pattern'], payload['flags'])\n"
    "    matched = compiled.search(payload['text']) is not None\n"
    "except Exception:\n"
    "    matched = False\n"
    "sys.stdout.write('1' if matched else '0')\n"
)


def _line_indicates_failure(line: str) -> bool:
    if not _FAILURE_INDICATOR_RE.search(line):
        return False
    return not (
        _ZERO_FAILURE_RE.search(line) and not _POSITIVE_FAILURE_COUNT_RE.search(line)
    )


def _preserve_trailing_newline(*, original: str, transformed: str) -> str:
    """Keep only trailing-newline presence aligned to the source string."""
    if original.endswith("\n"):
        return transformed if transformed.endswith("\n") else f"{transformed}\n"
    return transformed.rstrip("\n")


class AnsiNormalizeStrategy:
    """Remove ANSI/control escape sequences."""

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not content:
            return content
        normalized = content.replace("\r\n", "\n")
        normalized = self._collapse_overwritten_lines(normalized)
        normalized = self._strip_backspaces(normalized)
        normalized = _OSC_RE.sub("", normalized)
        normalized = _DCS_PM_APC_RE.sub("", normalized)
        normalized = _CSI_RE.sub("", normalized)
        normalized = _ESC_SINGLE_RE.sub("", normalized)
        normalized = _CONTROL_CHAR_RE.sub("", normalized)
        if level != CompressionLevel.CONSERVATIVE:
            normalized = self._drop_spinner_only_lines(normalized)
        return _preserve_trailing_newline(original=content, transformed=normalized)

    @staticmethod
    def _collapse_overwritten_lines(text: str) -> str:
        """Handle carriage-return line rewrites common in progress spinners."""
        had_trailing_newline = text.endswith("\n")
        lines: list[str] = []
        current: list[str] = []
        for char in text:
            if char == "\r":
                current = []
                continue
            if char == "\n":
                lines.append("".join(current))
                current = []
                continue
            current.append(char)
        if current:
            lines.append("".join(current))

        collapsed = "\n".join(lines)
        if had_trailing_newline:
            collapsed = f"{collapsed}\n"
        return collapsed

    @staticmethod
    def _strip_backspaces(text: str) -> str:
        buffer: list[str] = []
        for char in text:
            if char == "\b":
                if buffer and buffer[-1] != "\n":
                    buffer.pop()
                continue
            buffer.append(char)
        return "".join(buffer)

    @classmethod
    def _drop_spinner_only_lines(cls, text: str) -> str:
        had_trailing_newline = text.endswith("\n")
        if not text:
            return text
        lines = text.splitlines()
        if len(lines) < 2:
            return text

        filtered = [line for line in lines if not cls._is_spinner_only_line(line)]
        if not filtered:
            return ""

        result = "\n".join(filtered)
        if had_trailing_newline:
            result = f"{result}\n"
        return result

    @staticmethod
    def _is_spinner_only_line(line: str) -> bool:
        stripped = line.strip()
        if not stripped or len(stripped) > 4:
            return False
        spinner_ascii = {"|", "/", "-", "\\"}
        for char in stripped:
            if char in spinner_ascii:
                continue
            code = ord(char)
            if (0x25D0 <= code <= 0x25D3) or (0x25F4 <= code <= 0x25F7):
                continue
            if 0x2800 <= ord(char) <= 0x28FF:
                continue
            return False
        return True


class LineDedupeStrategy:
    """Collapse duplicate lines while preserving first occurrence order."""

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not content:
            return content

        lines = content.splitlines()
        if len(lines) < 2:
            return content

        if level == CompressionLevel.BALANCED:
            lines = self._dedupe_repeated_blocks(lines, level=level)

        if level == CompressionLevel.AGGRESSIVE:
            compressed = self._dedupe_global(lines)
        else:
            min_run = 3 if level == CompressionLevel.CONSERVATIVE else 2
            compressed = self._dedupe_consecutive(lines, min_run=min_run)
        result = "\n".join(compressed)
        return _preserve_trailing_newline(original=content, transformed=result)

    @classmethod
    def _dedupe_repeated_blocks(
        cls,
        lines: list[str],
        *,
        level: CompressionLevel,
    ) -> list[str]:
        if len(lines) < 4:
            return lines

        max_block_len = 4 if level == CompressionLevel.AGGRESSIVE else 3
        min_repeats = 2 if level == CompressionLevel.AGGRESSIVE else 3
        compressed: list[str] = []
        index = 0

        while index < len(lines):
            best_match: tuple[int, int] | None = None
            for block_len in range(max_block_len, 1, -1):
                if index + (block_len * min_repeats) > len(lines):
                    continue

                block = lines[index : index + block_len]
                if any(_line_indicates_failure(line) for line in block):
                    continue

                repeats = 1
                cursor = index + block_len
                while (
                    cursor + block_len <= len(lines)
                    and lines[cursor : cursor + block_len] == block
                ):
                    repeats += 1
                    cursor += block_len

                if repeats >= min_repeats:
                    best_match = (block_len, repeats)
                    break

            if best_match is None:
                compressed.append(lines[index])
                index += 1
                continue

            block_len, repeats = best_match
            compressed.extend(lines[index : index + block_len])
            compressed.append(
                f"... (previous {block_len}-line block repeated x{repeats})"
            )
            index += block_len * repeats

        return compressed

    @staticmethod
    def _dedupe_consecutive(lines: list[str], *, min_run: int) -> list[str]:
        compressed: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            run_length = 1
            while index + run_length < len(lines) and lines[index + run_length] == line:
                run_length += 1

            if _line_indicates_failure(line):
                compressed.extend([line] * run_length)
            elif line and run_length >= min_run:
                compressed.append(f"{line} (x{run_length})")
            else:
                compressed.extend([line] * run_length)
            index += run_length
        return compressed

    @staticmethod
    def _dedupe_global(lines: list[str]) -> list[str]:
        counts: OrderedDict[str, int] = OrderedDict()
        ordered_unique: list[str] = []
        failure_lines: list[str] = []
        for line in lines:
            if not line or _line_indicates_failure(line):
                failure_lines.append(line)
                ordered_unique.append(line)
                continue
            counts[line] = counts.get(line, 0) + 1
            if counts[line] == 1:
                ordered_unique.append(line)

        result: list[str] = []
        for line in ordered_unique:
            if line in failure_lines:
                result.append(line)
            elif line and counts.get(line, 1) > 1:
                result.append(f"{line} (x{counts[line]})")
            else:
                result.append(line)
        return result


class FailurePreservingTruncateStrategy:
    """Bound oversized outputs while prioritizing failure context."""

    _level_limits: dict[CompressionLevel, int] = {
        CompressionLevel.CONSERVATIVE: 300,
        CompressionLevel.BALANCED: 180,
        CompressionLevel.AGGRESSIVE: 120,
    }
    _failure_window: dict[CompressionLevel, int] = {
        CompressionLevel.CONSERVATIVE: 8,
        CompressionLevel.BALANCED: 6,
        CompressionLevel.AGGRESSIVE: 4,
    }

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        lines = content.splitlines()
        max_lines = self._level_limits[level]
        if len(lines) <= max_lines:
            return content

        failure_indices = self._find_failure_indices(lines)
        if not failure_indices:
            selected_indices = self._select_head_tail_only(
                total_lines=len(lines),
                max_lines=max_lines,
            )
        else:
            required_failure_indices = self._required_failure_context_indices(
                total_lines=len(lines),
                failure_indices=failure_indices,
                window=self._failure_window[level],
            )
            if len(required_failure_indices) > max_lines:
                return content

            selected_indices = self._select_failure_preserving_indices(
                total_lines=len(lines),
                max_lines=max_lines,
                level=level,
                failure_indices=failure_indices,
                required_failure_indices=required_failure_indices,
            )
            if not required_failure_indices.issubset(set(selected_indices)):
                return content
        rendered_lines = self._render_selected_lines(lines, selected_indices)
        result = "\n".join(rendered_lines)
        return _preserve_trailing_newline(original=content, transformed=result)

    @classmethod
    def _line_indicates_failure(cls, line: str) -> bool:
        return _line_indicates_failure(line)

    @classmethod
    def _find_failure_indices(cls, lines: list[str]) -> set[int]:
        return {
            idx for idx, line in enumerate(lines) if cls._line_indicates_failure(line)
        }

    @staticmethod
    def _required_failure_context_indices(
        *,
        total_lines: int,
        failure_indices: set[int],
        window: int,
    ) -> set[int]:
        required: set[int] = set()
        for failure_idx in sorted(failure_indices):
            start = max(0, failure_idx - window)
            end = min(total_lines, failure_idx + window + 1)
            required.update(range(start, end))
        return required

    @staticmethod
    def _select_head_tail_only(*, total_lines: int, max_lines: int) -> list[int]:
        head = max(1, max_lines // 2)
        tail = max(0, max_lines - head - 1)
        selected = list(range(min(head, total_lines)))
        tail_start = max(total_lines - tail, len(selected))
        selected.extend(range(tail_start, total_lines))
        return selected

    @classmethod
    def _select_failure_preserving_indices(
        cls,
        *,
        total_lines: int,
        max_lines: int,
        level: CompressionLevel,
        failure_indices: set[int],
        required_failure_indices: set[int],
    ) -> list[int]:
        head_budget = max(8, max_lines // 5)
        tail_budget = max(12, max_lines // 3)
        window = cls._failure_window[level]

        scores: dict[int, int] = {}
        for idx in range(min(head_budget, total_lines)):
            scores[idx] = max(scores.get(idx, 0), 150)
        for idx in range(max(total_lines - tail_budget, 0), total_lines):
            scores[idx] = max(scores.get(idx, 0), 250)

        for failure_idx in sorted(failure_indices):
            scores[failure_idx] = max(scores.get(failure_idx, 0), 10_000)
            for idx in range(
                max(0, failure_idx - window),
                min(total_lines, failure_idx + window + 1),
            ):
                proximity_score = 1_200 - (abs(idx - failure_idx) * 80)
                if proximity_score > 0:
                    scores[idx] = max(scores.get(idx, 0), proximity_score)

        for required_idx in sorted(required_failure_indices):
            scores[required_idx] = max(scores.get(required_idx, 0), 8_000)

        selected = sorted(scores.keys())
        if not selected:
            return [total_lines - 1]

        return cls._trim_selected_indices(
            selected_indices=selected,
            line_scores=scores,
            protected_indices=required_failure_indices,
            total_lines=total_lines,
            max_lines=max_lines,
        )

    @classmethod
    def _trim_selected_indices(
        cls,
        *,
        selected_indices: list[int],
        line_scores: dict[int, int],
        protected_indices: set[int],
        total_lines: int,
        max_lines: int,
    ) -> list[int]:
        selected = set(selected_indices)
        while (
            selected
            and cls._rendered_line_count(
                total_lines=total_lines, selected_indices=selected
            )
            > max_lines
        ):
            removable = [idx for idx in selected if idx not in protected_indices]
            if not removable:
                if len(selected) <= 1:
                    break
                newest = max(selected)
                removable = [idx for idx in selected if idx != newest]

            drop_idx = min(removable, key=lambda idx: (line_scores.get(idx, 0), idx))
            selected.remove(drop_idx)
        return sorted(selected) if selected else [total_lines - 1]

    @classmethod
    def _rendered_line_count(
        cls, *, total_lines: int, selected_indices: set[int]
    ) -> int:
        return len(
            cls._render_selected_lines(
                ["" for _ in range(total_lines)],
                sorted(selected_indices),
            )
        )

    @staticmethod
    def _render_selected_lines(
        lines: list[str], selected_indices: list[int]
    ) -> list[str]:
        if not selected_indices:
            return []

        rendered: list[str] = []
        previous_idx = -1
        first_idx = selected_indices[0]
        if first_idx > 0:
            rendered.append(f"... ({first_idx} lines omitted) ...")

        for idx in selected_indices:
            if previous_idx >= 0 and idx - previous_idx > 1:
                omitted = idx - previous_idx - 1
                rendered.append(f"... ({omitted} lines omitted) ...")
            rendered.append(lines[idx])
            previous_idx = idx

        last_idx = selected_indices[-1]
        if last_idx < len(lines) - 1:
            omitted_tail = len(lines) - last_idx - 1
            rendered.append(f"... ({omitted_tail} lines omitted) ...")
        return rendered


class SimilarityGroupingStrategy:
    """Group similar high-volume lines by deterministic inferred keys."""

    _path_with_line_re = re.compile(r"^([^:\s][^:]*\.[A-Za-z0-9_]+):\d+(?::\d+)?")
    _rule_code_re = re.compile(r"\b([A-Z]{1,4}\d{2,5})\b")
    _severity_re = re.compile(r"(?i)\b(error|warning|warn|info|fatal)\b")

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not content or level == CompressionLevel.CONSERVATIVE:
            return content

        lines = content.splitlines()
        if len(lines) < 4:
            return content

        min_group_size = 3 if level == CompressionLevel.BALANCED else 1
        sample_limit = 2 if level == CompressionLevel.BALANCED else 1

        grouped: OrderedDict[str, list[str]] = OrderedDict()
        passthrough_lines: list[str] = []
        for line in lines:
            key = self._infer_group_key(line)
            if key is None:
                passthrough_lines.append(line)
                continue
            grouped.setdefault(key, []).append(line)

        if not any(len(items) >= min_group_size for items in grouped.values()):
            return content

        rendered: list[str] = []
        for key, items in grouped.items():
            if len(items) < min_group_size:
                rendered.extend(items)
                continue

            rendered.append(f"[group {key}] ({len(items)} items)")
            for sample in items[:sample_limit]:
                rendered.append(f"  {sample}")
            omitted = len(items) - sample_limit
            if omitted > 0:
                rendered.append(f"  ... +{omitted} more")

        rendered.extend(passthrough_lines)
        result = "\n".join(rendered)
        return _preserve_trailing_newline(original=content, transformed=result)

    @classmethod
    def _infer_group_key(cls, line: str) -> str | None:
        stripped = line.strip()
        if not stripped:
            return None

        path_match = cls._path_with_line_re.match(stripped)
        if path_match:
            return path_match.group(1)

        first_token = stripped.split(maxsplit=1)[0].rstrip(":,")
        if "/" in first_token or "\\" in first_token:
            normalized = first_token.replace("\\", "/")
            token_path = normalized.rsplit("/", maxsplit=1)[0]
            if token_path:
                return token_path

        rule_match = cls._rule_code_re.search(stripped)
        if rule_match:
            return f"rule:{rule_match.group(1)}"

        severity_match = cls._severity_re.search(stripped)
        if severity_match:
            return f"severity:{severity_match.group(1).lower()}"

        return None


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
        r"^(?P<file>(?:[A-Za-z]:)?[^\-\n]+)-(?P<line>\d+)-\s?(?P<text>.*)$"
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
                continue

            lines.append(
                _SearchLine(line_no=line_no, text=clean_text, is_context=False)
            )
            match_counts[file_path] += 1
            context_budget[file_path] = self._context_lines

        if not by_file:
            return content

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


class FileDetailLevelsStrategy:
    """Apply RTK-style file detail levels with deterministic fallbacks."""

    _known_read_commands = frozenset(
        {"cat", "read", "head", "tail", "more", "less", "type", "bat"}
    )
    _known_read_categories = frozenset({"file_read", "view_file"})
    _data_extensions = frozenset(
        {
            "json",
            "jsonc",
            "json5",
            "yaml",
            "yml",
            "toml",
            "xml",
            "csv",
            "tsv",
            "graphql",
            "gql",
            "sql",
            "md",
            "markdown",
            "txt",
            "env",
            "lock",
        }
    )
    _signature_re = re.compile(
        r"^\s*(?:@[\w.]+|"
        r"(?:pub\s+)?(?:async\s+)?(?:fn|def|function|class|struct|enum|trait|interface|type)\s+\w+|"
        r"(?:export\s+)?(?:const|let|var)\s+\w+\s*=|"
        r"(?:import|from|use|#include|package|namespace)\b)"
    )
    _line_prefix_re = re.compile(r"^\s*(?P<line>\d+)(?:[:|])\s?(?P<text>.*)$")

    def __init__(
        self,
        *,
        detail_mode: str = "auto",
        fallback_mode: str = "full",
        auto_full_max_lines: int = 120,
        auto_structure_max_lines: int = 280,
        max_lines: int | None = None,
        last_n_lines: int | None = None,
        include_line_numbers: bool = False,
    ) -> None:
        self._detail_mode = detail_mode.strip().lower() or "auto"
        self._fallback_mode = fallback_mode.strip().lower() or "full"
        self._auto_full_max_lines = max(1, int(auto_full_max_lines))
        self._auto_structure_max_lines = max(1, int(auto_structure_max_lines))
        self._max_lines = max_lines if max_lines is None else max(0, int(max_lines))
        self._last_n_lines = (
            last_n_lines if last_n_lines is None else max(0, int(last_n_lines))
        )
        self._include_line_numbers = bool(include_line_numbers)

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not content:
            return content
        if not self._is_known_file_workflow(context):
            return content

        file_kind = self._detect_file_kind(context=context, content=content)
        line_numbers_enabled = self._include_line_numbers
        resolved_mode = self._resolve_mode(
            requested_mode=self._detail_mode,
            line_count=max(0, content.count("\n") + (1 if content else 0)),
            file_kind=file_kind,
            level=level,
        )

        try:
            reduced = self._apply_mode(
                content=content,
                mode=resolved_mode,
                file_kind=file_kind,
                line_numbers_enabled=line_numbers_enabled,
            )
        except Exception:
            logger.debug(
                "file_detail_levels extraction failed; using fallback",
                exc_info=True,
            )
            reduced = self._apply_fallback(
                content=content,
                file_kind=file_kind,
                preferred_mode=resolved_mode,
                line_numbers_enabled=line_numbers_enabled,
            )

        if not reduced.strip() and content.strip():
            logger.debug("file_detail_levels produced empty output; using fallback")
            reduced = self._apply_fallback(
                content=content,
                file_kind=file_kind,
                preferred_mode=resolved_mode,
                line_numbers_enabled=line_numbers_enabled,
            )

        windowed = self._apply_line_windows(reduced)
        return _preserve_trailing_newline(original=content, transformed=windowed)

    def _is_known_file_workflow(self, context: ToolOutputContext) -> bool:
        signature = (context.identity.command_signature or "").lower()
        if signature in self._known_read_commands:
            return True
        return context.identity.tool_category in self._known_read_categories

    def _detect_file_kind(self, *, context: ToolOutputContext, content: str) -> str:
        extension = self._extract_extension_from_context(context)
        if extension:
            if extension in self._data_extensions:
                return "data"
            return extension

        stripped = content.strip()
        if not stripped:
            return "unknown"
        if stripped.startswith(("{", "[")):
            try:
                json.loads(stripped)
                return "data"
            except (TypeError, ValueError):
                pass
        if stripped.startswith("<") and ">" in stripped:
            return "data"

        for line in content.splitlines()[:40]:
            clean = line.strip()
            if clean.startswith(("def ", "class ", "import ", "from ")):
                return "python"
            if clean.startswith(("function ", "const ", "let ", "var ", "export ")):
                return "javascript"
            if clean.startswith(("fn ", "struct ", "enum ", "impl ", "use ")):
                return "rust"
            if ":" in clean and clean.count(":") == 1 and clean.endswith(":"):
                return "data"
        return "unknown"

    def _extract_extension_from_context(self, context: ToolOutputContext) -> str | None:
        command_prefix = (context.identity.command_prefix or "").strip()
        if " " not in command_prefix:
            return None
        candidate = command_prefix.split(" ", maxsplit=1)[1].strip()
        if not candidate or candidate.startswith("-"):
            return None
        candidate = candidate.strip("\"'")
        if "/" in candidate or "\\" in candidate:
            candidate = candidate.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
        if "." not in candidate:
            return None
        return candidate.rsplit(".", maxsplit=1)[-1].lower()

    def _resolve_mode(
        self,
        *,
        requested_mode: str,
        line_count: int,
        file_kind: str,
        level: CompressionLevel,
    ) -> str:
        if requested_mode in {"full", "structure", "signatures"}:
            return requested_mode

        if file_kind == "data":
            if line_count <= self._auto_full_max_lines:
                return "full"
            return "structure"

        if line_count <= self._auto_full_max_lines:
            return "full"
        if line_count <= self._auto_structure_max_lines:
            return "signatures" if level == CompressionLevel.AGGRESSIVE else "structure"
        return "signatures" if level != CompressionLevel.CONSERVATIVE else "structure"

    def _apply_mode(
        self,
        *,
        content: str,
        mode: str,
        file_kind: str,
        line_numbers_enabled: bool,
    ) -> str:
        if mode == "full":
            return content
        if mode == "structure":
            return self._extract_structure(
                content=content,
                file_kind=file_kind,
                line_numbers_enabled=line_numbers_enabled,
            )
        return self._extract_signatures(
            content=content,
            file_kind=file_kind,
            line_numbers_enabled=line_numbers_enabled,
        )

    def _apply_fallback(
        self,
        *,
        content: str,
        file_kind: str,
        preferred_mode: str,
        line_numbers_enabled: bool,
    ) -> str:
        fallback_mode = self._fallback_mode
        if fallback_mode not in {"full", "structure", "signatures"}:
            fallback_mode = "full"
        if fallback_mode == preferred_mode:
            return content
        try:
            fallback = self._apply_mode(
                content=content,
                mode=fallback_mode,
                file_kind=file_kind,
                line_numbers_enabled=line_numbers_enabled,
            )
        except Exception:
            logger.debug(
                "file_detail_levels fallback failed; returning original", exc_info=True
            )
            return content
        if fallback.strip():
            return fallback
        return content

    def _extract_structure(
        self,
        *,
        content: str,
        file_kind: str,
        line_numbers_enabled: bool,
    ) -> str:
        if file_kind == "data":
            return content
        return self._extract_by_patterns(
            content=content,
            include_imports=True,
            line_numbers_enabled=line_numbers_enabled,
        )

    def _extract_signatures(
        self,
        *,
        content: str,
        file_kind: str,
        line_numbers_enabled: bool,
    ) -> str:
        if file_kind == "data":
            return content
        return self._extract_by_patterns(
            content=content,
            include_imports=False,
            line_numbers_enabled=line_numbers_enabled,
        )

    def _extract_by_patterns(
        self,
        *,
        content: str,
        include_imports: bool,
        line_numbers_enabled: bool,
    ) -> str:
        lines = content.splitlines()
        normalized_lines = list(lines)
        preserved_line_numbers: dict[int, int] = {}
        keep_indices: list[int] = []
        for index, raw_line in enumerate(lines):
            line_source = raw_line
            if line_numbers_enabled:
                preserved_number, line_source = self._parse_prefixed_line(raw_line)
                if preserved_number is not None:
                    preserved_line_numbers[index] = preserved_number
                    normalized_lines[index] = line_source

            line = line_source.strip()
            if not line:
                continue
            if self._signature_re.match(line):
                if not include_imports and line.startswith(
                    ("import ", "from ", "use ", "#include", "package ")
                ):
                    continue
                keep_indices.append(index)
        keep_indices = sorted(set(keep_indices))
        if not keep_indices:
            return ""
        if line_numbers_enabled:
            return self._render_selected_lines_with_numbers(
                lines=normalized_lines,
                keep_indices=keep_indices,
                preserved_line_numbers=preserved_line_numbers,
            )
        return self._render_selected_lines(lines=lines, keep_indices=keep_indices)

    @classmethod
    def _parse_prefixed_line(cls, raw_line: str) -> tuple[int | None, str]:
        match = cls._line_prefix_re.match(raw_line)
        if not match:
            return None, raw_line
        try:
            return int(match.group("line")), match.group("text")
        except (TypeError, ValueError):
            return None, raw_line

    def _apply_line_windows(self, content: str) -> str:
        lines = content.splitlines()
        if not lines:
            return content
        max_lines = self._max_lines
        last_n_lines = self._last_n_lines
        if max_lines is None and last_n_lines is None:
            return content

        def _marker(omitted: int) -> str:
            return f"... ({omitted} lines omitted) ..."

        total = len(lines)
        rendered: list[str]
        if max_lines is not None and last_n_lines is not None:
            if total <= max_lines + last_n_lines:
                rendered = lines
            else:
                omitted = total - max_lines - last_n_lines
                rendered = [
                    *lines[:max_lines],
                    _marker(omitted),
                    *lines[total - last_n_lines :],
                ]
        elif max_lines is not None:
            if total <= max_lines:
                rendered = lines
            else:
                omitted = total - max_lines
                rendered = [*lines[:max_lines], _marker(omitted)]
        else:
            tail = last_n_lines or 0
            if total <= tail:
                rendered = lines
            else:
                omitted = total - tail
                rendered = [_marker(omitted), *lines[omitted:]]

        result = "\n".join(rendered)
        return _preserve_trailing_newline(original=content, transformed=result)

    @staticmethod
    def _render_selected_lines(*, lines: list[str], keep_indices: list[int]) -> str:
        if not keep_indices:
            return ""
        rendered: list[str] = []
        previous = -1
        first = keep_indices[0]
        if first > 0:
            rendered.append(f"... ({first} lines omitted) ...")
        for index in keep_indices:
            if previous >= 0 and index - previous > 1:
                rendered.append(f"... ({index - previous - 1} lines omitted) ...")
            rendered.append(lines[index])
            previous = index
        last = keep_indices[-1]
        if last < len(lines) - 1:
            rendered.append(f"... ({len(lines) - last - 1} lines omitted) ...")
        return "\n".join(rendered)

    @staticmethod
    def _render_selected_lines_with_numbers(
        *,
        lines: list[str],
        keep_indices: list[int],
        preserved_line_numbers: dict[int, int],
    ) -> str:
        if not keep_indices:
            return ""
        rendered: list[str] = []
        previous = -1
        first = keep_indices[0]
        if first > 0:
            rendered.append(f"... ({first} lines omitted) ...")
        for index in keep_indices:
            if previous >= 0 and index - previous > 1:
                rendered.append(f"... ({index - previous - 1} lines omitted) ...")
            line_number = preserved_line_numbers.get(index, index + 1)
            rendered.append(f"{line_number}: {lines[index]}")
            previous = index
        last = keep_indices[-1]
        if last < len(lines) - 1:
            rendered.append(f"... ({len(lines) - last - 1} lines omitted) ...")
        return "\n".join(rendered)


@dataclass(frozen=True)
class OutputPatternMatchRule:
    """Declarative full-output replacement rule."""

    pattern: str
    message: str
    unless: str | None = None
    fallback_message: str = "tool: ok"


@dataclass(frozen=True)
class _CompiledOutputPatternRule:
    pattern: Pattern[str]
    message: str
    unless: Pattern[str] | None
    fallback_message: str


class OutputPatternMatchStrategy:
    """Match full output against patterns with unless guards and fallback."""

    _max_regex_input_chars = 200_000

    def __init__(
        self,
        *,
        rules: list[OutputPatternMatchRule] | None = None,
        regex_timeout_ms: int = 25,
    ) -> None:
        self._regex_timeout_ms = max(1, int(regex_timeout_ms))
        self._rules = self._compile_rules(rules or [])

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not self._rules:
            return content

        source_content = content
        content_reduced_to_empty = False
        if not source_content and context.content:
            source_content = context.content
            content_reduced_to_empty = True
        if not source_content:
            return content

        full_text = (
            source_content[: self._max_regex_input_chars]
            if len(source_content) > self._max_regex_input_chars
            else source_content
        )
        for rule in self._rules:
            matched, timed_out = self._search_with_timeout(rule.pattern, full_text)
            if timed_out:
                continue
            if not matched:
                continue

            if rule.unless is not None:
                excluded, timed_out = self._search_with_timeout(rule.unless, full_text)
                if timed_out:
                    continue
                if excluded:
                    continue

            replacement = rule.message.strip()
            if replacement:
                return replacement

            fallback = rule.fallback_message.strip() or "tool: ok"
            return fallback
        if content_reduced_to_empty:
            return self._resolve_empty_fallback_message()
        return content

    def _compile_rules(
        self,
        rules: list[OutputPatternMatchRule],
    ) -> list[_CompiledOutputPatternRule]:
        compiled: list[_CompiledOutputPatternRule] = []
        for rule in rules:
            try:
                pattern = re.compile(rule.pattern)
                unless = re.compile(rule.unless) if rule.unless else None
            except re.error:
                # Fail-open: skip malformed regex rules.
                continue
            compiled.append(
                _CompiledOutputPatternRule(
                    pattern=pattern,
                    message=rule.message,
                    unless=unless,
                    fallback_message=rule.fallback_message,
                )
            )
        return compiled

    def _search_with_timeout(
        self,
        pattern: Pattern[str],
        text: str,
    ) -> tuple[bool, bool]:
        timeout_seconds = self._regex_timeout_ms / 1000.0
        if sys.platform.startswith("win"):
            timeout_seconds = max(timeout_seconds, 0.2)
        payload = json.dumps(
            {
                "pattern": pattern.pattern,
                "flags": int(pattern.flags),
                "text": text,
            }
        )
        worker: subprocess.Popen[str] | None = None
        try:
            worker = subprocess.Popen(
                [sys.executable, "-c", _REGEX_EVAL_SUBPROCESS_SNIPPET],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            stdout_data, _ = worker.communicate(payload, timeout=timeout_seconds)
            if worker.returncode not in (0, None):
                return False, True
            return stdout_data.strip() == "1", False
        except subprocess.TimeoutExpired:
            if worker is not None:
                with suppress(Exception):
                    worker.kill()
                with suppress(Exception):
                    worker.communicate(timeout=0.05)
            return False, True
        except Exception:
            logger.debug(
                "output_pattern_match bounded regex evaluation failed",
                exc_info=True,
            )
            return False, True
        finally:
            if worker is not None:
                with suppress(Exception):
                    worker.kill()
                with suppress(Exception):
                    worker.communicate(timeout=0.05)

    def _resolve_empty_fallback_message(self) -> str:
        for rule in self._rules:
            fallback = rule.fallback_message.strip()
            if fallback:
                return fallback
        return "tool: ok"


class DiffCompactStrategy:
    """Compact unified diff output while preserving key review context."""

    _stat_format_flags = {"--stat", "--numstat", "--shortstat"}

    def __init__(
        self,
        *,
        max_hunk_lines: int = 100,
        max_total_lines: int = 500,
    ) -> None:
        self._max_hunk_lines = max(1, int(max_hunk_lines))
        self._max_total_lines = max(10, int(max_total_lines))

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not content:
            return content

        if context.has_explicit_format and any(
            flag in self._stat_format_flags
            for flag in context.identity.explicit_format_flags
        ):
            return content

        if not self._looks_like_unified_diff(content):
            return content

        max_hunk_lines, max_total_lines = self._limits_for_level(level)
        compacted = self._compact_diff(
            diff=content,
            max_hunk_lines=max_hunk_lines,
            max_total_lines=max_total_lines,
        )
        return _preserve_trailing_newline(original=content, transformed=compacted)

    def _limits_for_level(self, level: CompressionLevel) -> tuple[int, int]:
        if level == CompressionLevel.CONSERVATIVE:
            return self._max_hunk_lines + 20, self._max_total_lines + 200
        if level == CompressionLevel.AGGRESSIVE:
            return max(20, self._max_hunk_lines - 20), max(
                120, self._max_total_lines - 150
            )
        return self._max_hunk_lines, self._max_total_lines

    @staticmethod
    def _looks_like_unified_diff(content: str) -> bool:
        lines = content.splitlines()
        has_hunk_headers = any(line.startswith("@@ ") for line in lines)
        if not has_hunk_headers:
            return False
        has_git_header = any(line.startswith("diff --git ") for line in lines)
        has_unified_headers = any(line.startswith("--- ") for line in lines) and any(
            line.startswith("+++ ") for line in lines
        )
        return has_git_header or has_unified_headers

    @staticmethod
    def _extract_file_name(diff_header: str) -> str:
        if " b/" in diff_header:
            return diff_header.split(" b/", maxsplit=1)[1].strip()
        return "unknown"

    @staticmethod
    def _extract_file_name_from_unified_header(header: str) -> str | None:
        payload = header[4:].strip() if len(header) >= 4 else ""
        if not payload:
            return None
        if "\t" in payload:
            payload = payload.split("\t", maxsplit=1)[0].strip()
        payload = payload.strip('"')
        if payload.startswith(("a/", "b/")):
            payload = payload[2:]
        if payload == "/dev/null":
            return None
        return payload or None

    def _compact_diff(
        self,
        *,
        diff: str,
        max_hunk_lines: int,
        max_total_lines: int,
    ) -> str:
        result: list[str] = []
        current_file = ""
        added = 0
        removed = 0
        in_hunk = False
        hunk_shown = 0
        hunk_skipped = 0
        truncated = False

        def flush_hunk() -> None:
            nonlocal hunk_skipped, truncated
            if hunk_skipped > 0:
                result.append(f"  ... ({hunk_skipped} lines truncated)")
                truncated = True
                hunk_skipped = 0

        def flush_file_stats() -> None:
            if current_file and (added > 0 or removed > 0):
                result.append(f"  +{added} -{removed}")

        def begin_file(file_name: str) -> None:
            nonlocal current_file, added, removed, in_hunk, hunk_shown
            current_file = file_name or "unknown"
            if result:
                result.append("")
            result.append(current_file)
            added = 0
            removed = 0
            in_hunk = False
            hunk_shown = 0

        lines = diff.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.startswith("diff --git "):
                flush_hunk()
                flush_file_stats()
                begin_file(self._extract_file_name(line))
            elif line.startswith("--- ") and index + 1 < len(lines):
                next_line = lines[index + 1]
                if next_line.startswith("+++ "):
                    old_name = self._extract_file_name_from_unified_header(line)
                    new_name = (
                        self._extract_file_name_from_unified_header(next_line)
                        or old_name
                        or "unknown"
                    )
                    if not current_file:
                        begin_file(new_name)
                    elif new_name != current_file:
                        flush_hunk()
                        flush_file_stats()
                        begin_file(new_name)
                    else:
                        in_hunk = False
                        hunk_shown = 0
                    index += 2
                    if len(result) >= max_total_lines:
                        result.append("... (more changes truncated)")
                        truncated = True
                        break
                    continue
            elif line.startswith("@@ "):
                flush_hunk()
                if not current_file:
                    begin_file("unknown")
                in_hunk = True
                hunk_shown = 0
                result.append(f"  {line}")
            elif in_hunk:
                is_added = line.startswith("+") and not line.startswith("+++")
                is_removed = line.startswith("-") and not line.startswith("---")
                is_context = (
                    not is_added and not is_removed and not line.startswith("\\")
                )

                if is_added:
                    added += 1
                elif is_removed:
                    removed += 1

                if not (is_added or is_removed or is_context):
                    index += 1
                    continue

                # Keep bounded detail lines per hunk while retaining headers.
                if hunk_shown < max_hunk_lines:
                    if is_context and hunk_shown == 0:
                        pass
                    else:
                        result.append(f"  {line}")
                        hunk_shown += 1
                else:
                    hunk_skipped += 1

            if len(result) >= max_total_lines:
                result.append("... (more changes truncated)")
                truncated = True
                break
            index += 1

        flush_hunk()
        flush_file_stats()

        if truncated:
            result.append("[full diff available via explicit diff command]")

        return "\n".join(result)


class PytestFailureFocusStrategy:
    """Pytest-focused line filter aligned with legacy ``_filter_pytest_output``."""

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        try:
            if not content:
                return content
            sig = context.identity.command_signature
            prefix = context.identity.command_prefix
            if not (
                looks_like_pytest_command(sig, prefix)
                or looks_like_pytest_output(content)
            ):
                return content
            return filter_pytest_output(content)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "pytest_failure_focus failed open",
                    exc_info=True,
                )
            return content


class FailureFocusGenericStrategy:
    """Failure-prioritizing reduction for bulky test/build/lint-style plain text."""

    _CARGO_PROGRESS_RE = re.compile(
        r"^\s*(Compiling|Checking|Downloading|Blocking|Fresh|Documenting)\s+",
        re.IGNORECASE,
    )
    _CARGO_FINISHED_RE = re.compile(
        r"^\s*Finished\s+`[^`]+`\s+profile\b",
        re.IGNORECASE,
    )

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        try:
            if not content or context.has_explicit_format:
                return content
            lines = content.split("\n")
            if len(lines) < 12:
                return content

            joined = "\n".join(lines)
            has_failure = bool(_FAILURE_INDICATOR_RE.search(joined)) or bool(
                _POSITIVE_FAILURE_COUNT_RE.search(joined)
            )

            sig = (context.identity.command_signature or "").lower()

            if not _POSITIVE_FAILURE_COUNT_RE.search(joined) and (
                _ZERO_FAILURE_RE.search(joined)
                or re.search(r"(?i)\btest result:\s*ok\.?\b", joined)
            ):
                last = lines[-1]
                return (
                    f"[failure-focus] Condensed {len(lines)} lines (no failures detected).\n"
                    f"{last}"
                )

            if sig == "cargo":
                filtered = [
                    ln
                    for ln in lines
                    if not self._CARGO_PROGRESS_RE.match(ln)
                    and not self._CARGO_FINISHED_RE.match(ln)
                ]
                merged = "\n".join(filtered)
                if not merged.strip() or merged == content:
                    return content
                if has_failure and not (
                    _FAILURE_INDICATOR_RE.search(merged)
                    or _POSITIVE_FAILURE_COUNT_RE.search(merged)
                ):
                    return content
                return merged

            failure_indexes = [
                idx for idx, ln in enumerate(lines) if _FAILURE_INDICATOR_RE.search(ln)
            ]
            if len(failure_indexes) == 1:
                idx = failure_indexes[0]
                start = max(0, idx - 3)
                end = min(len(lines), idx + 25)
                window = lines[start:end]
                candidate = "\n".join(window)
                summary_line = lines[-1]
                if summary_line and summary_line not in candidate:
                    candidate = f"{candidate}\n{summary_line}"
                if not _FAILURE_INDICATOR_RE.search(candidate):
                    return content
                if len(candidate) >= len(content):
                    return content
                return candidate

            return content
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "failure_focus_generic failed open",
                    exc_info=True,
                )
            return content


@dataclass
class _DiagnosticAggregate:
    count: int = 0
    anchors: set[tuple[int, int | None]] = field(default_factory=set)


class DiagnosticsGroupingStrategy:
    """Group plain-text diagnostics by file/rule while preserving anchors."""

    _RUFF_LIKE_RE = re.compile(
        r"^(?P<path>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<code>[A-Z]{1,8}\d*)\s+(?P<msg>.+)$"
    )
    _MYPY_STYLE_RE = re.compile(
        r"^(?P<path>[^:]+):(?P<line>\d+):\s*(?P<kind>error|note|warning):\s*(?P<msg>.+)$",
        re.IGNORECASE,
    )
    _TSC_STYLE_RE = re.compile(
        r"^(?P<path>.+)\((?P<line>\d+),(?P<col>\d+)\):\s*"
        r"(?P<kind>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.+)$",
        re.IGNORECASE,
    )

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        try:
            if not content.strip() or context.has_explicit_format:
                return content
            lines = content.splitlines()
            parsed: list[tuple[str, str, str, int, int | None]] = []
            for raw in lines:
                line = raw.strip()
                if not line:
                    continue
                m = self._TSC_STYLE_RE.match(line)
                if m:
                    parsed.append(
                        (
                            m.group("path").strip(),
                            m.group("code"),
                            m.group("msg").strip(),
                            int(m.group("line")),
                            int(m.group("col")),
                        )
                    )
                    continue
                m = self._RUFF_LIKE_RE.match(line)
                if m:
                    parsed.append(
                        (
                            m.group("path").strip(),
                            m.group("code"),
                            m.group("msg").strip(),
                            int(m.group("line")),
                            int(m.group("col")),
                        )
                    )
                    continue
                m = self._MYPY_STYLE_RE.match(line)
                if m:
                    kind = m.group("kind").upper()
                    parsed.append(
                        (
                            m.group("path").strip(),
                            kind,
                            m.group("msg").strip(),
                            int(m.group("line")),
                            None,
                        )
                    )
                    continue

            if len(parsed) < 2:
                return content

            grouped: dict[str, dict[str, dict[str, _DiagnosticAggregate]]] = (
                defaultdict(
                    lambda: defaultdict(lambda: defaultdict(_DiagnosticAggregate))
                )
            )
            for path, code, msg, line_no, col_no in parsed:
                aggregate = grouped[path][code][msg]
                aggregate.count += 1
                aggregate.anchors.add((line_no, col_no))

            out_lines = ["=== grouped diagnostics ==="]
            for path in sorted(grouped.keys()):
                out_lines.append(path)
                for code in sorted(grouped[path].keys()):
                    for msg, aggregate in sorted(
                        grouped[path][code].items(), key=lambda item: item[0]
                    ):
                        anchor = self._format_primary_anchor(aggregate.anchors)
                        annotations: list[str] = []
                        if aggregate.count > 1:
                            annotations.append(f"x{aggregate.count}")
                        extra_locations = len(aggregate.anchors) - 1
                        if extra_locations > 0:
                            annotations.append(f"+{extra_locations} locations")
                        ann = f" ({', '.join(annotations)})" if annotations else ""
                        out_lines.append(f"  [{code}] {anchor} {msg}{ann}")
                out_lines.append("")

            while out_lines and not out_lines[-1].strip():
                out_lines.pop()
            result = "\n".join(out_lines)
            return _preserve_trailing_newline(original=content, transformed=result)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "diagnostics_grouping failed open",
                    exc_info=True,
                )
            return content

    @staticmethod
    def _anchor_sort_key(anchor: tuple[int, int | None]) -> tuple[int, int]:
        line_no, col_no = anchor
        return line_no, (-1 if col_no is None else col_no)

    @classmethod
    def _format_primary_anchor(cls, anchors: set[tuple[int, int | None]]) -> str:
        if not anchors:
            return "L?"
        line_no, col_no = min(anchors, key=cls._anchor_sort_key)
        if col_no is None:
            return f"L{line_no}"
        return f"L{line_no}:C{col_no}"
