"""File detail tiering compression strategy."""

from __future__ import annotations

import json
import re

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services._compression_strategies_common import (
    _preserve_trailing_newline,
    logger,
)


class FileDetailLevelsStrategy:
    """Apply tiered file detail levels with deterministic fallbacks."""

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
