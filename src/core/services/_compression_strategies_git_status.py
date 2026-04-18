"""Git status compression strategy inspired by lean-ctx structured section output."""

from __future__ import annotations

import re

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services._compression_strategies_common import (
    _preserve_trailing_newline,
)

_BRANCH_LONG_RE = re.compile(r"^On branch\s+(\S+)")
_AHEAD_LONG_RE = re.compile(
    r"ahead of\s+['\"]([^'\"]+)['\"]\s+by\s+(\d+)\s+commit", re.IGNORECASE
)
_BEHIND_LONG_RE = re.compile(
    r"behind\s+['\"]([^'\"]+)['\"]\s+by\s+(\d+)\s+commit", re.IGNORECASE
)
_NEW_FILE_RE = re.compile(r"^\s+new file:\s+(.+?)\s*$")
_MODIFIED_RE = re.compile(r"^\s+modified:\s+(.+?)\s*$")
_DELETED_RE = re.compile(r"^\s+deleted:\s+(.+?)\s*$")
_RENAMED_RE = re.compile(r"^\s+renamed:\s+(.+?)\s*$")
_COPIED_RE = re.compile(r"^\s+copied:\s+(.+?)\s*$")

_BRANCH_PORCELAIN_RE = re.compile(r"(\S+?)(?:\.\.\.|$)")
_UPSTREAM_PORCELAIN_RE = re.compile(r"\.\.\.(\S+)")
_AHEAD_PORCELAIN_RE = re.compile(r"\[ahead\s+(\d+)\]")
_BEHIND_PORCELAIN_RE = re.compile(r"\[behind\s+(\d+)\]")


class GitStatusStrategy:
    """Structured git status compression preserving all file names and sections.

    Inspired by lean-ctx's approach:
    - Parse branch, ahead/behind metadata
    - Separate staged / unstaged / untracked sections
    - Use change-kind markers: + (new), ~ (modified), - (deleted), -> (renamed)
    - Preserve full file lists within section caps
    """

    def __init__(
        self,
        *,
        section_cap_conservative: int = 80,
        section_cap_balanced: int = 40,
        section_cap_aggressive: int = 15,
    ) -> None:
        self._caps = {
            CompressionLevel.CONSERVATIVE: section_cap_conservative,
            CompressionLevel.BALANCED: section_cap_balanced,
            CompressionLevel.AGGRESSIVE: section_cap_aggressive,
        }

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if not content:
            return content
        if context.has_explicit_format:
            return content
        sig = (context.identity.command_signature or "").lower()
        prefix = (context.identity.command_prefix or "").lower()
        if sig != "git" or "status" not in prefix:
            return content
        if "diff" in prefix:
            return content

        result = self._compress_status(content, level)
        return _preserve_trailing_newline(original=content, transformed=result)

    def _section_cap(self, level: CompressionLevel) -> int:
        return self._caps.get(level, self._caps[CompressionLevel.BALANCED])

    def _compress_status(self, content: str, level: CompressionLevel) -> str:
        lines = content.splitlines()
        if any(line.startswith("## ") for line in lines[:5]):
            return self._compress_porcelain(lines, level)
        return self._compress_long_format(lines, level)

    def _compress_porcelain(self, lines: list[str], level: CompressionLevel) -> str:
        branch = ""
        upstream = ""
        ahead = ""
        behind = ""
        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []
        mixed: list[str] = []

        for line in lines:
            if line.startswith("## "):
                rest = line[3:]
                bm = _BRANCH_PORCELAIN_RE.match(rest)
                if bm:
                    branch = bm.group(1)
                um = _UPSTREAM_PORCELAIN_RE.search(rest)
                if um:
                    upstream = um.group(1)
                am = _AHEAD_PORCELAIN_RE.search(rest)
                if am:
                    ahead = am.group(1)
                bm2 = _BEHIND_PORCELAIN_RE.search(rest)
                if bm2:
                    behind = bm2.group(1)
                continue

            if len(line) < 4:
                continue
            xy = line[:2]
            path = line[3:].strip()
            if not path:
                continue

            if xy == "??":
                untracked.append(path)
            elif xy == "!!":
                pass
            elif xy[0] != " " and xy[1] != " ":
                x_marker = _porcelain_x_marker(xy[0])
                mixed.append(f"{x_marker} {path} (staged+unstaged)")
            elif xy[0] != " ":
                staged.append(f"{_porcelain_x_marker(xy[0])} {path}")
            elif xy[1] != " ":
                unstaged.append(f"{_porcelain_y_marker(xy[1])} {path}")

        return self._render(
            branch=branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            staged=staged + mixed,
            unstaged=unstaged,
            untracked=untracked,
            is_clean=bool(not staged and not unstaged and not untracked and not mixed),
            level=level,
        )

    def _compress_long_format(self, lines: list[str], level: CompressionLevel) -> str:
        branch = ""
        upstream = ""
        ahead = ""
        behind = ""
        section = ""
        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []

        for line in lines:
            bm = _BRANCH_LONG_RE.match(line)
            if bm:
                branch = bm.group(1)

            am = _AHEAD_LONG_RE.search(line)
            if am:
                upstream = am.group(1)
                ahead = am.group(2)

            bm2 = _BEHIND_LONG_RE.search(line)
            if bm2:
                upstream = bm2.group(1)
                behind = bm2.group(2)

            if "Changes to be committed" in line:
                section = "staged"
                continue
            if "Changes not staged" in line:
                section = "unstaged"
                continue
            if "Untracked files" in line:
                section = "untracked"
                continue

            if section == "staged":
                entry = self._parse_long_entry(line)
                if entry:
                    staged.append(entry)
            elif section == "unstaged":
                entry = self._parse_long_entry(line)
                if entry:
                    unstaged.append(entry)
            elif section == "untracked":
                trimmed = line.strip()
                if (
                    trimmed
                    and not trimmed.startswith("(")
                    and not trimmed.startswith("Untracked")
                    and not trimmed.startswith("nothing added to commit")
                    and not trimmed.startswith("nothing to commit")
                    and not trimmed.startswith("use ")
                ):
                    untracked.append(trimmed)

        is_clean = (
            "nothing to commit" in "\n".join(lines)
            and not staged
            and not unstaged
            and not untracked
        )

        return self._render(
            branch=branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
            is_clean=is_clean,
            level=level,
        )

    @staticmethod
    def _parse_long_entry(line: str) -> str | None:
        m = _NEW_FILE_RE.match(line)
        if m:
            return f"+ {m.group(1).strip()}"
        m = _MODIFIED_RE.match(line)
        if m:
            return f"~ {m.group(1).strip()}"
        m = _DELETED_RE.match(line)
        if m:
            return f"- {m.group(1).strip()}"
        m = _RENAMED_RE.match(line)
        if m:
            return f"-> {m.group(1).strip()}"
        m = _COPIED_RE.match(line)
        if m:
            return f"C {m.group(1).strip()}"
        return None

    def _render(
        self,
        *,
        branch: str,
        upstream: str,
        ahead: str,
        behind: str,
        staged: list[str],
        unstaged: list[str],
        untracked: list[str],
        is_clean: bool,
        level: CompressionLevel,
    ) -> str:
        parts: list[str] = []

        header = branch or "?"
        if ahead:
            header += f" (+{ahead})"
        if behind and level != CompressionLevel.AGGRESSIVE:
            header += f" (-{behind})"
        parts.append(header)

        cap = self._section_cap(level)

        if staged:
            parts.append("staged:")
            shown = staged[:cap]
            parts.extend(f"  {s}" for s in shown)
            if len(staged) > cap:
                parts.append(f"  ... {len(staged) - cap} more")

        if unstaged:
            parts.append("unstaged:")
            shown = unstaged[:cap]
            parts.extend(f"  {s}" for s in shown)
            if len(unstaged) > cap:
                parts.append(f"  ... {len(unstaged) - cap} more")

        if untracked:
            parts.append("untracked:")
            shown = untracked[:cap]
            parts.extend(f"  {s}" for s in shown)
            if len(untracked) > cap:
                parts.append(f"  ... {len(untracked) - cap} more")

        if is_clean:
            parts.append("clean")

        return "\n".join(parts)


def _porcelain_x_marker(x: str) -> str:
    return {
        "M": "~",
        "A": "+",
        "D": "-",
        "R": "->",
        "C": "C",
    }.get(x.upper(), x)


def _porcelain_y_marker(y: str) -> str:
    return {
        "M": "~",
        "D": "-",
        "R": "->",
        "C": "C",
    }.get(y.upper(), y)
