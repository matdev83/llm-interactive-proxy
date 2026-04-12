"""Text-oriented compression strategies (ANSI, dedupe, truncate, similarity)."""

from __future__ import annotations

import re
from collections import OrderedDict

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services._compression_strategies_common import (
    _CONTROL_CHAR_RE,
    _CSI_RE,
    _DCS_PM_APC_RE,
    _ESC_SINGLE_RE,
    _OSC_RE,
    _line_indicates_failure,
    _preserve_trailing_newline,
)


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
