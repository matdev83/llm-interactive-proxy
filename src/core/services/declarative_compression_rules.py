"""Declarative compression rule registry and 8-stage filter pipeline."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None  # type: ignore

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_NESTED_QUANTIFIER_PATTERN_RE = re.compile(
    r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]"
)
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
_REGEX_REPLACE_STAGE_SUBPROCESS_SNIPPET = (
    "import json\n"
    "import re\n"
    "import sys\n"
    "payload = json.loads(sys.stdin.read())\n"
    "lines = payload.get('lines')\n"
    "rules = payload.get('rules')\n"
    "response = {'ok': False, 'lines': []}\n"
    "if isinstance(lines, list) and isinstance(rules, list):\n"
    "    try:\n"
    "        compiled = [\n"
    "            (\n"
    "                re.compile(str(item.get('pattern', '')), int(item.get('flags', 0))),\n"
    "                str(item.get('replacement', '')),\n"
    "            )\n"
    "            for item in rules\n"
    "        ]\n"
    "        transformed = []\n"
    "        for raw_line in lines:\n"
    "            current = str(raw_line)\n"
    "            for pattern, replacement in compiled:\n"
    "                current = pattern.sub(replacement, current)\n"
    "            transformed.append(current)\n"
    "        response = {'ok': True, 'lines': transformed}\n"
    "    except Exception:\n"
    "        response = {'ok': False, 'lines': []}\n"
    "sys.stdout.write(json.dumps(response))\n"
)
_REGEX_FILTER_STAGE_SUBPROCESS_SNIPPET = (
    "import json\n"
    "import re\n"
    "import sys\n"
    "payload = json.loads(sys.stdin.read())\n"
    "lines = payload.get('lines')\n"
    "patterns = payload.get('patterns')\n"
    "keep_matches = bool(payload.get('keep_matches', False))\n"
    "response = {'ok': False, 'lines': []}\n"
    "if isinstance(lines, list) and isinstance(patterns, list):\n"
    "    try:\n"
    "        compiled = [\n"
    "            re.compile(str(item.get('pattern', '')), int(item.get('flags', 0)))\n"
    "            for item in patterns\n"
    "        ]\n"
    "        transformed = []\n"
    "        for raw_line in lines:\n"
    "            line = str(raw_line)\n"
    "            matched = any(pattern.search(line) is not None for pattern in compiled)\n"
    "            if (keep_matches and matched) or ((not keep_matches) and (not matched)):\n"
    "                transformed.append(line)\n"
    "        response = {'ok': True, 'lines': transformed}\n"
    "    except Exception:\n"
    "        response = {'ok': False, 'lines': []}\n"
    "sys.stdout.write(json.dumps(response))\n"
)
_DEFAULT_PRIORITY = 1000
_SUPPORTED_DECLARATIVE_RULE_KEYS = frozenset(
    {
        "name",
        "priority",
        "override",
        "match_command",
        "tool_category",
        "tool_name_pattern",
        "strip_ansi",
        "replace",
        "match_output",
        "strip_lines",
        "strip_lines_matching",
        "keep_lines",
        "keep_lines_matching",
        "truncate_lines_at",
        "head_lines",
        "tail_lines",
        "max_lines",
        "on_empty",
    }
)


@dataclass(frozen=True)
class _CompiledReplaceRule:
    pattern: re.Pattern[str]
    replacement: str


@dataclass(frozen=True)
class _CompiledMatchOutputRule:
    pattern: re.Pattern[str]
    message: str
    unless: re.Pattern[str] | None


@dataclass(frozen=True)
class CompiledDeclarativeRule:
    """Validated declarative rule compiled for deterministic matching and execution."""

    name: str
    source: str
    priority: int
    order: int
    override: bool
    match_command: re.Pattern[str] | None
    tool_category: str | None
    tool_name_pattern: re.Pattern[str] | None
    strip_ansi: bool
    replace: tuple[_CompiledReplaceRule, ...]
    match_output: tuple[_CompiledMatchOutputRule, ...]
    strip_lines: tuple[re.Pattern[str], ...]
    keep_lines: tuple[re.Pattern[str], ...]
    truncate_lines_at: int | None
    head_lines: int | None
    tail_lines: int | None
    max_lines: int | None
    on_empty: str | None


@dataclass(frozen=True)
class ResolvedDeclarativeRules:
    """Compiled declarative rules plus operator-visible warnings."""

    rules: tuple[CompiledDeclarativeRule, ...]
    warnings: tuple[str, ...]


class DeclarativeRulePipelineError(RuntimeError):
    """Raised when declarative filter execution must fail open."""


@dataclass(frozen=True)
class _RegexTimeoutResult:
    matched: bool
    timed_out: bool


@dataclass(frozen=True)
class _RegexWorkerExecutionResult:
    stdout: str
    timed_out: bool


@dataclass(frozen=True)
class _RegexLinesTimeoutResult:
    lines: tuple[str, ...]
    timed_out: bool


class DeclarativeFilterPipeline:
    """RTK-style deterministic 8-stage declarative text filter pipeline."""

    def __init__(self, *, regex_timeout_ms: int = 25) -> None:
        self._regex_timeout_ms = max(1, int(regex_timeout_ms))

    def apply(self, *, rule: CompiledDeclarativeRule, content: str) -> str:
        lines = content.splitlines()
        had_trailing_newline = content.endswith("\n")

        # 1. strip_ansi
        if rule.strip_ansi:
            lines = [_ANSI_RE.sub("", line) for line in lines]

        # 2. replace (line-by-line, chained)
        if rule.replace:
            replace_result = self._replace_lines_with_timeout(
                replace_rules=rule.replace,
                lines=lines,
            )
            if replace_result.timed_out:
                raise DeclarativeRulePipelineError(
                    f"Regex timeout in rule '{rule.name}' replace stage."
                )
            lines = list(replace_result.lines)

        # 3. match_output (short-circuit full output)
        if rule.match_output:
            blob = "\n".join(lines)
            for match_rule in rule.match_output:
                matched_result = self._search_with_timeout(match_rule.pattern, blob)
                if matched_result.timed_out:
                    raise DeclarativeRulePipelineError(
                        f"Regex timeout in rule '{rule.name}' match_output stage."
                    )
                if not matched_result.matched:
                    continue
                if match_rule.unless is not None:
                    unless_result = self._search_with_timeout(match_rule.unless, blob)
                    if unless_result.timed_out:
                        raise DeclarativeRulePipelineError(
                            f"Regex timeout in rule '{rule.name}' match_output unless stage."
                        )
                    if unless_result.matched:
                        continue
                return match_rule.message

        # 4. strip/keep lines (mutually exclusive by validation)
        if rule.strip_lines:
            strip_result = self._filter_lines_with_timeout(
                patterns=rule.strip_lines,
                lines=lines,
                keep_matches=False,
            )
            if strip_result.timed_out:
                raise DeclarativeRulePipelineError(
                    f"Regex timeout in rule '{rule.name}' strip_lines stage."
                )
            lines = list(strip_result.lines)
        elif rule.keep_lines:
            keep_result = self._filter_lines_with_timeout(
                patterns=rule.keep_lines,
                lines=lines,
                keep_matches=True,
            )
            if keep_result.timed_out:
                raise DeclarativeRulePipelineError(
                    f"Regex timeout in rule '{rule.name}' keep_lines stage."
                )
            lines = list(keep_result.lines)

        # 5. truncate_lines_at
        if rule.truncate_lines_at is not None:
            lines = [
                self._truncate_line(line, rule.truncate_lines_at) for line in lines
            ]

        # 6. head/tail lines
        total = len(lines)
        if rule.head_lines is not None and rule.tail_lines is not None:
            if total > rule.head_lines + rule.tail_lines:
                omitted = total - rule.head_lines - rule.tail_lines
                lines = [
                    *lines[: rule.head_lines],
                    f"... ({omitted} lines omitted)",
                    *lines[total - rule.tail_lines :],
                ]
        elif rule.head_lines is not None:
            if total > rule.head_lines:
                omitted = total - rule.head_lines
                lines = [*lines[: rule.head_lines], f"... ({omitted} lines omitted)"]
        elif rule.tail_lines is not None and total > rule.tail_lines:
            omitted = total - rule.tail_lines
            lines = [
                f"... ({omitted} lines omitted)",
                *lines[omitted:],
            ]

        # 7. max_lines
        if rule.max_lines is not None and len(lines) > rule.max_lines:
            truncated = len(lines) - rule.max_lines
            lines = [
                *lines[: rule.max_lines],
                f"... ({truncated} lines truncated)",
            ]

        # 8. on_empty
        result = "\n".join(lines)
        if not result.strip() and rule.on_empty:
            return rule.on_empty
        return self._preserve_trailing_newline(
            original_had_newline=had_trailing_newline,
            transformed=result,
        )

    @staticmethod
    def _preserve_trailing_newline(
        *,
        original_had_newline: bool,
        transformed: str,
    ) -> str:
        if original_had_newline:
            return transformed if transformed.endswith("\n") else f"{transformed}\n"
        return transformed.rstrip("\n")

    @staticmethod
    def _truncate_line(value: str, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        if len(value) <= max_chars:
            return value
        if max_chars <= 3:
            return value[:max_chars]
        return f"{value[: max_chars - 3]}..."

    def _search_with_timeout(
        self,
        pattern: re.Pattern[str],
        text: str,
    ) -> _RegexTimeoutResult:
        if not self._pattern_requires_timeout_worker(pattern):
            return _RegexTimeoutResult(
                matched=pattern.search(text) is not None,
                timed_out=False,
            )
        worker_result = self._execute_regex_worker(
            snippet=_REGEX_EVAL_SUBPROCESS_SNIPPET,
            payload={
                "pattern": pattern.pattern,
                "flags": int(pattern.flags),
                "text": text,
            },
        )
        if worker_result.timed_out:
            return _RegexTimeoutResult(matched=False, timed_out=True)
        return _RegexTimeoutResult(
            matched=worker_result.stdout.strip() == "1",
            timed_out=False,
        )

    def _replace_lines_with_timeout(
        self,
        *,
        replace_rules: tuple[_CompiledReplaceRule, ...],
        lines: list[str],
    ) -> _RegexLinesTimeoutResult:
        if not any(
            self._pattern_requires_timeout_worker(rule.pattern)
            for rule in replace_rules
        ):
            replaced: list[str] = []
            for line in lines:
                current = line
                for replace_rule in replace_rules:
                    current = replace_rule.pattern.sub(
                        replace_rule.replacement,
                        current,
                    )
                replaced.append(current)
            return _RegexLinesTimeoutResult(lines=tuple(replaced), timed_out=False)

        worker_result = self._execute_regex_worker(
            snippet=_REGEX_REPLACE_STAGE_SUBPROCESS_SNIPPET,
            payload={
                "rules": [
                    {
                        "pattern": replace_rule.pattern.pattern,
                        "flags": int(replace_rule.pattern.flags),
                        "replacement": replace_rule.replacement,
                    }
                    for replace_rule in replace_rules
                ],
                "lines": lines,
            },
        )
        if worker_result.timed_out:
            return _RegexLinesTimeoutResult(lines=tuple(lines), timed_out=True)
        parsed_lines = self._parse_lines_worker_output(worker_result.stdout)
        if parsed_lines is None:
            return _RegexLinesTimeoutResult(lines=tuple(lines), timed_out=True)
        return _RegexLinesTimeoutResult(lines=tuple(parsed_lines), timed_out=False)

    def _filter_lines_with_timeout(
        self,
        *,
        patterns: tuple[re.Pattern[str], ...],
        lines: list[str],
        keep_matches: bool,
    ) -> _RegexLinesTimeoutResult:
        if not any(
            self._pattern_requires_timeout_worker(pattern) for pattern in patterns
        ):
            transformed: list[str] = []
            for line in lines:
                matched = any(pattern.search(line) is not None for pattern in patterns)
                if (keep_matches and matched) or ((not keep_matches) and (not matched)):
                    transformed.append(line)
            return _RegexLinesTimeoutResult(lines=tuple(transformed), timed_out=False)

        worker_result = self._execute_regex_worker(
            snippet=_REGEX_FILTER_STAGE_SUBPROCESS_SNIPPET,
            payload={
                "patterns": [
                    {"pattern": pattern.pattern, "flags": int(pattern.flags)}
                    for pattern in patterns
                ],
                "lines": lines,
                "keep_matches": keep_matches,
            },
        )
        if worker_result.timed_out:
            return _RegexLinesTimeoutResult(lines=tuple(lines), timed_out=True)
        parsed_lines = self._parse_lines_worker_output(worker_result.stdout)
        if parsed_lines is None:
            return _RegexLinesTimeoutResult(lines=tuple(lines), timed_out=True)
        return _RegexLinesTimeoutResult(lines=tuple(parsed_lines), timed_out=False)

    def _execute_regex_worker(
        self,
        *,
        snippet: str,
        payload: dict[str, Any],
    ) -> _RegexWorkerExecutionResult:
        timeout_seconds = self._regex_timeout_ms / 1000.0
        worker: subprocess.Popen[str] | None = None
        try:
            worker = subprocess.Popen(
                [sys.executable, "-c", snippet],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            stdout_data, _ = worker.communicate(
                json.dumps(payload),
                timeout=timeout_seconds,
            )
            if worker.returncode not in (0, None):
                return _RegexWorkerExecutionResult(stdout="", timed_out=True)
            return _RegexWorkerExecutionResult(
                stdout=stdout_data,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            if worker is not None:
                worker.kill()
                worker.communicate(timeout=0.05)
            return _RegexWorkerExecutionResult(stdout="", timed_out=True)
        except Exception:
            logger.debug(
                "Declarative regex timeout evaluator failed; failing open",
                exc_info=True,
            )
            return _RegexWorkerExecutionResult(stdout="", timed_out=True)
        finally:
            if worker is not None and worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=0.05)

    @staticmethod
    def _parse_lines_worker_output(stdout_data: str) -> list[str] | None:
        try:
            payload = json.loads(stdout_data)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return None
        lines = payload.get("lines")
        if not isinstance(lines, list):
            return None
        return [str(line) for line in lines]

    @staticmethod
    def _pattern_requires_timeout_worker(pattern: re.Pattern[str]) -> bool:
        return _NESTED_QUANTIFIER_PATTERN_RE.search(pattern.pattern) is not None


class DeclarativeRuleFilterStrategy:
    """One-shot strategy wrapper for executing one compiled declarative rule."""

    def __init__(
        self,
        *,
        pipeline: DeclarativeFilterPipeline,
        rule: CompiledDeclarativeRule,
    ) -> None:
        self._pipeline = pipeline
        self._rule = rule

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        del context, level
        return self._pipeline.apply(rule=self._rule, content=content)


class DeclarativeRuleRegistry:
    """Compile, validate, match, and execute declarative compression rules."""

    def __init__(self) -> None:
        self._pipeline = DeclarativeFilterPipeline()
        self._builtin_rules, self._builtin_warnings = self._compile_rule_defs(
            _builtin_declarative_rule_defs(),
            source="builtin",
            start_order=0,
        )

    def resolve(self, config: DynamicCompressionConfig) -> ResolvedDeclarativeRules:
        warnings: list[str] = list(self._builtin_warnings)
        custom_defs: list[dict[str, Any]] = []

        file_paths = self._normalize_str_list(
            getattr(config, "declarative_rule_files", None)
        )
        file_order = 0
        for file_path in file_paths:
            loaded_rules, load_warnings = self._load_rule_file(file_path=file_path)
            warnings.extend(load_warnings)
            for loaded_rule in loaded_rules:
                if isinstance(loaded_rule, dict):
                    custom_defs.append(loaded_rule)
                    file_order += 1

        inline_rules = getattr(config, "declarative_rules", None)
        if isinstance(inline_rules, list):
            for inline_rule in inline_rules:
                if isinstance(inline_rule, dict):
                    custom_defs.append(inline_rule)
                else:
                    warnings.append(
                        "Invalid declarative rule ignored: expected mapping definition."
                    )

        compiled_custom, custom_warnings = self._compile_rule_defs(
            custom_defs,
            source="operator",
            start_order=len(self._builtin_rules) + file_order,
        )
        warnings.extend(custom_warnings)

        all_rules = [*compiled_custom, *self._builtin_rules]
        ordered_rules = tuple(
            sorted(all_rules, key=lambda rule: (rule.priority, rule.order))
        )
        return ResolvedDeclarativeRules(
            rules=ordered_rules,
            warnings=tuple(warnings),
        )

    def match_rule(
        self,
        *,
        context: ToolOutputContext,
        rules: tuple[CompiledDeclarativeRule, ...],
    ) -> CompiledDeclarativeRule | None:
        command_probe = (
            context.identity.command_prefix
            or context.identity.command_signature
            or context.identity.tool_name
        )
        tool_name = context.identity.tool_name
        tool_category = context.identity.tool_category

        for rule in rules:
            if rule.match_command is not None and not rule.match_command.search(
                command_probe
            ):
                continue
            if rule.tool_category is not None and rule.tool_category != tool_category:
                continue
            if (
                rule.tool_name_pattern is not None
                and not rule.tool_name_pattern.search(tool_name)
            ):
                continue
            return rule
        return None

    def apply_rule(self, *, rule: CompiledDeclarativeRule, content: str) -> str:
        return self._pipeline.apply(rule=rule, content=content)

    def make_strategy(
        self,
        *,
        rule: CompiledDeclarativeRule,
        regex_timeout_ms: int | None = None,
    ) -> DeclarativeRuleFilterStrategy:
        if regex_timeout_ms is None:
            pipeline = self._pipeline
        else:
            pipeline = DeclarativeFilterPipeline(regex_timeout_ms=regex_timeout_ms)
        return DeclarativeRuleFilterStrategy(pipeline=pipeline, rule=rule)

    @property
    def pipeline(self) -> DeclarativeFilterPipeline:
        return self._pipeline

    @staticmethod
    def _normalize_str_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _load_rule_file(file_path: str) -> tuple[list[dict[str, Any]], list[str]]:
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return [], [f"Declarative rule file not found: {path}"]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return [], [f"Failed to read declarative rule file {path}: {exc}"]

        loaded: object
        if path.suffix.lower() in {".yaml", ".yml"} and yaml is not None:
            try:
                loaded = yaml.safe_load(text)
            except Exception as exc:
                return [], [f"Failed to parse declarative rule file {path}: {exc}"]
        else:
            try:
                loaded = json.loads(text)
            except Exception:
                if yaml is None:
                    return [], [
                        f"Failed to parse declarative rule file {path} as JSON."
                    ]
                try:
                    loaded = yaml.safe_load(text)
                except Exception as exc:
                    return [], [f"Failed to parse declarative rule file {path}: {exc}"]

        if isinstance(loaded, dict):
            candidate = loaded.get("declarative_rules")
            if isinstance(candidate, list):
                return [entry for entry in candidate if isinstance(entry, dict)], []
            return [], [
                f"Declarative rule file {path} has no 'declarative_rules' list."
            ]
        if isinstance(loaded, list):
            return [entry for entry in loaded if isinstance(entry, dict)], []
        return [], [f"Declarative rule file {path} must contain a list or mapping."]

    def _compile_rule_defs(
        self,
        rule_defs: list[dict[str, Any]],
        *,
        source: str,
        start_order: int,
    ) -> tuple[list[CompiledDeclarativeRule], list[str]]:
        compiled: list[CompiledDeclarativeRule] = []
        warnings: list[str] = []

        order = start_order
        for raw_rule in rule_defs:
            maybe_rule = self._compile_rule_def(
                raw_rule,
                source=source,
                order=order,
                warnings=warnings,
            )
            order += 1
            if maybe_rule is not None:
                compiled.append(maybe_rule)
        return compiled, warnings

    def _compile_rule_def(
        self,
        rule_def: dict[str, Any],
        *,
        source: str,
        order: int,
        warnings: list[str],
    ) -> CompiledDeclarativeRule | None:
        name_raw = rule_def.get("name")
        name = str(name_raw).strip() if name_raw is not None else ""
        if not name:
            warnings.append("Declarative rule ignored: missing non-empty 'name'.")
            return None

        unknown_keys = sorted(
            str(key)
            for key in rule_def
            if str(key) not in _SUPPORTED_DECLARATIVE_RULE_KEYS
        )
        for unknown_key in unknown_keys:
            warnings.append(
                f"Declarative rule '{name}' ignored unknown key '{unknown_key}'."
            )

        priority = self._as_non_negative_int(
            rule_def.get("priority"),
            default=_DEFAULT_PRIORITY,
        )
        override = bool(rule_def.get("override", False))

        try:
            match_command = self._compile_optional_regex(
                rule_def.get("match_command"),
                field_name="match_command",
                rule_name=name,
            )
            tool_name_pattern = self._compile_optional_regex(
                rule_def.get("tool_name_pattern"),
                field_name="tool_name_pattern",
                rule_name=name,
            )
        except ValueError as exc:
            warnings.append(str(exc))
            return None

        tool_category_raw = rule_def.get("tool_category")
        tool_category = (
            str(tool_category_raw).strip().lower() if tool_category_raw else None
        )

        replace_defs = rule_def.get("replace", [])
        if isinstance(replace_defs, dict):
            replace_defs = [replace_defs]
        if not isinstance(replace_defs, list):
            warnings.append(
                f"Declarative rule '{name}' ignored: invalid 'replace' definition."
            )
            return None
        replace_rules: list[_CompiledReplaceRule] = []
        for item in replace_defs:
            if not isinstance(item, dict):
                warnings.append(
                    f"Declarative rule '{name}' ignored one invalid replace entry."
                )
                continue
            pattern_text = str(item.get("pattern", "")).strip()
            replacement = str(item.get("replacement", ""))
            if not pattern_text:
                warnings.append(
                    f"Declarative rule '{name}' ignored one replace entry with empty pattern."
                )
                continue
            try:
                replace_rules.append(
                    _CompiledReplaceRule(
                        pattern=re.compile(pattern_text),
                        replacement=replacement,
                    )
                )
            except re.error as exc:
                warnings.append(
                    f"Declarative rule '{name}' has invalid replace regex "
                    f"{pattern_text!r}: {exc}"
                )
                return None

        match_output_defs = rule_def.get("match_output", [])
        if isinstance(match_output_defs, dict):
            match_output_defs = [match_output_defs]
        if not isinstance(match_output_defs, list):
            warnings.append(
                f"Declarative rule '{name}' ignored: invalid 'match_output' definition."
            )
            return None
        match_output_rules: list[_CompiledMatchOutputRule] = []
        for item in match_output_defs:
            if not isinstance(item, dict):
                warnings.append(
                    f"Declarative rule '{name}' ignored one invalid match_output entry."
                )
                continue
            pattern_text = str(item.get("pattern", "")).strip()
            message = str(item.get("message", ""))
            unless_text_raw = item.get("unless")
            unless_text = (
                str(unless_text_raw).strip() if unless_text_raw is not None else None
            )
            if not pattern_text:
                warnings.append(
                    f"Declarative rule '{name}' ignored one match_output entry with empty pattern."
                )
                continue
            try:
                compiled_pattern = re.compile(pattern_text)
                compiled_unless = re.compile(unless_text) if unless_text else None
            except re.error as exc:
                warnings.append(
                    f"Declarative rule '{name}' has invalid match_output regex: {exc}"
                )
                return None
            match_output_rules.append(
                _CompiledMatchOutputRule(
                    pattern=compiled_pattern,
                    message=message,
                    unless=compiled_unless,
                )
            )

        strip_lines_defs = self._normalize_regex_list(
            rule_def.get("strip_lines", rule_def.get("strip_lines_matching"))
        )
        keep_lines_defs = self._normalize_regex_list(
            rule_def.get("keep_lines", rule_def.get("keep_lines_matching"))
        )
        if strip_lines_defs and keep_lines_defs:
            warnings.append(
                f"Declarative rule '{name}' ignored: strip_lines and keep_lines are mutually exclusive."
            )
            return None
        try:
            strip_lines = tuple(re.compile(pattern) for pattern in strip_lines_defs)
            keep_lines = tuple(re.compile(pattern) for pattern in keep_lines_defs)
        except re.error as exc:
            warnings.append(
                f"Declarative rule '{name}' has invalid strip/keep regex: {exc}"
            )
            return None

        truncate_lines_at = self._as_optional_non_negative_int(
            rule_def.get("truncate_lines_at")
        )
        head_lines = self._as_optional_non_negative_int(rule_def.get("head_lines"))
        tail_lines = self._as_optional_non_negative_int(rule_def.get("tail_lines"))
        max_lines = self._as_optional_non_negative_int(rule_def.get("max_lines"))
        on_empty_raw = rule_def.get("on_empty")
        on_empty = str(on_empty_raw) if on_empty_raw is not None else None

        return CompiledDeclarativeRule(
            name=name,
            source=source,
            priority=priority,
            order=order,
            override=override,
            match_command=match_command,
            tool_category=tool_category,
            tool_name_pattern=tool_name_pattern,
            strip_ansi=bool(rule_def.get("strip_ansi", False)),
            replace=tuple(replace_rules),
            match_output=tuple(match_output_rules),
            strip_lines=strip_lines,
            keep_lines=keep_lines,
            truncate_lines_at=truncate_lines_at,
            head_lines=head_lines,
            tail_lines=tail_lines,
            max_lines=max_lines,
            on_empty=on_empty,
        )

    @staticmethod
    def _compile_optional_regex(
        value: object,
        *,
        field_name: str,
        rule_name: str,
    ) -> re.Pattern[str] | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return re.compile(text)
        except re.error as exc:
            raise ValueError(
                f"Declarative rule '{rule_name}' has invalid {field_name} regex "
                f"{text!r}: {exc}"
            ) from exc

    @staticmethod
    def _normalize_regex_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            normalized = value.strip()
            return [normalized] if normalized else []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _as_non_negative_int(value: object, *, default: int) -> int:
        if value is None:
            return default
        if not isinstance(value, int | float | str | bytes | bytearray):
            return default
        try:
            converted = int(value)
        except (TypeError, ValueError):
            return default
        return converted if converted >= 0 else default

    @staticmethod
    def _as_optional_non_negative_int(value: object) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int | float | str | bytes | bytearray):
            return None
        try:
            converted = int(value)
        except (TypeError, ValueError):
            return None
        return converted if converted >= 0 else None


def _builtin_declarative_rule_defs() -> list[dict[str, Any]]:
    """Built-in declarative rule set modeled after RTK filter coverage."""

    # The rule names mirror RTK built-ins and provide 50+ baseline entries.
    command_specs: list[tuple[str, str, str]] = [
        ("ansible-playbook", r"^ansible-playbook\b", "ansible-playbook: ok"),
        ("brew-install", r"^brew\s+(install|upgrade|update)\b", "brew: ok"),
        ("bundle-install", r"^bundle\s+install\b", "bundle: ok"),
        ("cargo-build", r"^cargo\s+build\b", "cargo build: ok"),
        ("cargo-test", r"^cargo\s+test\b", "cargo test: ok"),
        ("composer-install", r"^composer\s+install\b", "composer: ok"),
        ("curl", r"^curl\b", "curl: ok"),
        ("df", r"^df\b", "df: ok"),
        ("docker-build", r"^docker\s+build\b", "docker build: ok"),
        ("dotnet-build", r"^dotnet\s+build\b", "dotnet build: ok"),
        ("du", r"^du\b", "du: ok"),
        ("fail2ban-client", r"^fail2ban-client\b", "fail2ban: ok"),
        ("gcloud", r"^gcloud\b", "gcloud: ok"),
        ("gcc", r"^(gcc|clang)\b", "compiler: ok"),
        ("go-test", r"^go\s+test\b", "go test: ok"),
        ("golangci-lint", r"^golangci-lint\b", "golangci-lint: ok"),
        ("gradle-build", r"^gradle\b", "gradle: ok"),
        ("gradlew-build", r"^gradlew\b", "gradle: ok"),
        ("hadolint", r"^hadolint\b", "hadolint: ok"),
        ("helm", r"^helm\b", "helm: ok"),
        ("iptables", r"^iptables\b", "iptables: ok"),
        ("kubectl-apply", r"^kubectl\s+apply\b", "kubectl apply: ok"),
        ("kubectl-get", r"^kubectl\s+get\b", "kubectl get: ok"),
        ("make", r"^make\b", "make: ok"),
        ("markdownlint", r"^markdownlint\b", "markdownlint: ok"),
        ("mix-compile", r"^mix\s+compile\b", "mix compile: ok"),
        ("mix-format", r"^mix\s+format\b", "mix format: ok"),
        ("mvn-build", r"^mvn\b", "mvn: ok"),
        ("npm-install", r"^npm\s+(install|ci)\b", "npm: ok"),
        ("ping", r"^ping\b", "ping: ok"),
        ("pio-run", r"^pio\s+run\b", "pio run: ok"),
        ("pnpm-install", r"^pnpm\s+(install|up)\b", "pnpm: ok"),
        ("poetry-install", r"^poetry\s+(install|update)\b", "poetry: ok"),
        ("pre-commit", r"^pre-commit\b", "pre-commit: ok"),
        ("ps", r"^ps\b", "ps: ok"),
        ("psql", r"^psql\b", "psql: ok"),
        ("quarto-render", r"^quarto\s+render\b", "quarto: ok"),
        ("ruff-check", r"^ruff\s+check\b", "ruff: ok"),
        ("rsync", r"^rsync\b", "rsync: ok"),
        ("rubocop", r"^rubocop\b", "rubocop: ok"),
        ("shellcheck", r"^shellcheck\b", "shellcheck: ok"),
        ("shopify-theme", r"^shopify\s+theme\b", "shopify theme: ok"),
        ("sops", r"^sops\b", "sops: ok"),
        ("ssh", r"^ssh\b", "ssh: ok"),
        ("swift-build", r"^swift\s+build\b", "swift build: ok"),
        ("systemctl", r"^systemctl\b", "systemctl: ok"),
        ("systemctl-status", r"^systemctl\s+status\b", "systemctl status: ok"),
        ("terraform-plan", r"^terraform\s+plan\b", "terraform plan: ok"),
        ("tofu-fmt", r"^tofu\s+fmt\b", "tofu fmt: ok"),
        ("tofu-init", r"^tofu\s+init\b", "tofu init: ok"),
        ("tofu-plan", r"^tofu\s+plan\b", "tofu plan: ok"),
        ("tofu-validate", r"^tofu\s+validate\b", "tofu validate: ok"),
        ("trunk-build", r"^trunk\s+build\b", "trunk build: ok"),
        ("tsc", r"^tsc\b", "tsc: ok"),
        ("uv-sync", r"^uv\s+sync\b", "uv sync: ok"),
        ("vite-build", r"^vite\s+build\b", "vite build: ok"),
        ("wget", r"^wget\b", "wget: ok"),
        ("yamllint", r"^yamllint\b", "yamllint: ok"),
        ("yarn-install", r"^yarn\s+(install|up)\b", "yarn: ok"),
    ]

    defaults: list[dict[str, Any]] = []
    for name, command_pattern, on_empty in command_specs:
        defaults.append(
            {
                "name": name,
                "priority": 1500,
                "match_command": command_pattern,
                "strip_ansi": True,
                "strip_lines": [
                    r"^\s*$",
                    r"^\s*(Downloading|Resolving|Fetching|Using|Already|Progress|info:)\b",
                ],
                "max_lines": 60,
                "on_empty": on_empty,
            }
        )

    # RTK-like short-circuit success patterns with unless guards.
    defaults.append(
        {
            "name": "make-success-short-circuit",
            "priority": 1499,
            "match_command": r"^make\b",
            "match_output": [
                {
                    "pattern": r"Nothing to be done|is up to date",
                    "message": "make: ok",
                    "unless": r"error|failed|fatal",
                }
            ],
            "on_empty": "make: ok",
        }
    )
    defaults.append(
        {
            "name": "gradle-success-short-circuit",
            "priority": 1499,
            "match_command": r"^(gradle|gradlew)\b",
            "match_output": [
                {
                    "pattern": r"BUILD SUCCESSFUL",
                    "message": "gradle: ok",
                    "unless": r"FAILED|error:",
                }
            ],
            "on_empty": "gradle: ok",
        }
    )
    defaults.append(
        {
            "name": "terraform-success-short-circuit",
            "priority": 1499,
            "match_command": r"^terraform\s+plan\b",
            "match_output": [
                {
                    "pattern": r"No changes\.",
                    "message": "terraform plan: no changes",
                    "unless": r"Error:|failed",
                }
            ],
            "on_empty": "terraform plan: ok",
        }
    )
    return defaults
