"""Structural JSON/NDJSON, XML safeguards, log dedupe, and sensitive-field projection."""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ElementTree
from collections import Counter
from collections.abc import Mapping
from typing import Any

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContentType, ToolOutputContext

logger = logging.getLogger(__name__)

_URL_START_RE = re.compile(r"^https?://", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?")
_LOG_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
)
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_HEX_LONG_RE = re.compile(r"\b[0-9a-f]{32,128}\b", re.IGNORECASE)
_NUMERIC_ID_RE = re.compile(
    r"(?i)\b(?:request|req|trace|span|job|task|run|build|process|proc|pid|tid|uid|gid|id)[_-]?id?\s*[:=]\s*\d+\b"
)
_LONG_NUM_RE = re.compile(r"\b\d{4,}\b")
_EPHEMERAL_UNIX_PATH_RE = re.compile(
    r"(?:/(?:private/)?tmp|/var/tmp|/dev/shm|/run/user/\d+|/(?:private/)?var/folders)/[^\s\"']+"
)
_EPHEMERAL_WIN_PATH_RE = re.compile(
    r"[A-Za-z]:(?:\\|/)(?:Users(?:\\|/)[^\\/\s]+(?:\\|/)AppData(?:\\|/)Local(?:\\|/)Temp|Windows(?:\\|/)Temp|Temp)(?:\\|/)[^\s\"']+",
    re.IGNORECASE,
)
_LOG_ERR_RE = re.compile(r"(?i)\b(error|fatal|panic|exception|traceback|critical)\b")
_ENV_KEYVAL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_EXPORT_RE = re.compile(
    r"^export\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", re.IGNORECASE
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(secret|password|passwd|token|api_?key|credential|auth|private|bearer|session)"
)


class JsonNdjsonStructuralStrategy:
    """Depth/key/array limited JSON summaries and NDJSON shape histograms."""

    def __init__(
        self,
        *,
        max_depth: int = 8,
        max_keys_per_object: int = 40,
        max_array_elements: int = 12,
        string_max_len: int = 120,
        min_bytes: int = 512,
    ) -> None:
        self._max_depth = max(0, max_depth)
        self._max_keys = max(1, max_keys_per_object)
        self._max_arr = max(1, max_array_elements)
        self._str_max = max(8, string_max_len)
        self._min_bytes = max(0, min_bytes)

    def _scale(self, level: CompressionLevel) -> tuple[int, int, int, int]:
        if level == CompressionLevel.AGGRESSIVE:
            return (
                max(1, self._max_depth - 2),
                max(1, self._max_keys // 2),
                max(1, self._max_arr // 2),
                max(8, self._str_max // 2),
            )
        if level == CompressionLevel.BALANCED:
            return (
                self._max_depth,
                max(1, int(self._max_keys * 0.85)),
                max(1, int(self._max_arr * 0.85)),
                self._str_max,
            )
        return self._max_depth, self._max_keys, self._max_arr, self._str_max

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        try:
            if context.has_explicit_format:
                return content
            if context.content_type not in (
                ToolOutputContentType.JSON,
                ToolOutputContentType.NDJSON,
            ):
                return content
            if len(content.encode("utf-8")) < self._min_bytes:
                return content

            md, mk, ma, ms = self._scale(level)
            if context.content_type == ToolOutputContentType.JSON:
                data = json.loads(content)
                summarized = self._summarize_value(data, 0, md, mk, ma, ms)
                return json.dumps(
                    summarized,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )

            return self._summarize_ndjson(content, md, mk, ma, ms)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("json_ndjson_structural failed open", exc_info=True)
            return content

    def _annotate_string(self, s: str, str_max: int) -> Any:
        if _URL_START_RE.match(s):
            if len(s) > str_max:
                return f"url[{len(s)}]"
            return "url"
        if _ISO_DATE_RE.match(s):
            if len(s) > str_max:
                return f"date[{len(s)}]"
            return "date"
        if len(s) <= str_max:
            return "string"
        return f"string[{len(s)}]"

    def _summarize_value(
        self,
        val: Any,
        depth: int,
        max_depth: int,
        max_keys: int,
        max_arr: int,
        str_max: int,
    ) -> Any:
        if depth >= max_depth:
            if isinstance(val, Mapping):
                return {"_truncated_object": len(val)}
            if isinstance(val, list):
                return {"_truncated_array": len(val)}
            return self._annotate_primitive(val, str_max)

        if isinstance(val, Mapping):
            keys = sorted(val.keys(), key=lambda k: str(k))
            out: dict[str, Any] = {}
            for k in keys[:max_keys]:
                out[str(k)] = self._summarize_value(
                    val[k], depth + 1, max_depth, max_keys, max_arr, str_max
                )
            omitted = len(keys) - min(len(keys), max_keys)
            if omitted > 0:
                out["_omitted_keys"] = omitted
            return out

        if isinstance(val, list):
            head = val[:max_arr]
            out_list = [
                self._summarize_value(
                    x, depth + 1, max_depth, max_keys, max_arr, str_max
                )
                for x in head
            ]
            extra = len(val) - len(head)
            if extra > 0:
                out_list.append({"_more_elements": extra})
            return out_list

        return self._annotate_primitive(val, str_max)

    def _annotate_primitive(self, val: Any, str_max: int) -> Any:
        if isinstance(val, str):
            return self._annotate_string(val, str_max)
        if isinstance(val, bool):
            return "bool"
        if isinstance(val, int):
            return "int"
        if isinstance(val, float):
            return "float"
        if val is None:
            return "null"
        return type(val).__name__

    def _summarize_ndjson(
        self,
        content: str,
        max_depth: int,
        max_keys: int,
        max_arr: int,
        str_max: int,
    ) -> str:
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if len(lines) < 2:
            return content

        parsed: list[Any] = []
        for ln in lines:
            try:
                parsed.append(json.loads(ln))
            except (TypeError, ValueError):
                return content

        shape_counts: Counter[tuple[str, ...]] = Counter()
        shape_sample: dict[tuple[str, ...], Any] = {}
        for obj in parsed:
            if isinstance(obj, Mapping):
                key = tuple(sorted(str(k) for k in obj))
            else:
                key = (f"<{type(obj).__name__}>",)
            shape_counts[key] += 1
            if key not in shape_sample:
                shape_sample[key] = obj

        shapes_out: list[dict[str, Any]] = []
        for key in sorted(shape_counts.keys(), key=lambda t: t):
            sample = self._summarize_value(
                shape_sample[key],
                0,
                max_depth,
                max_keys,
                max_arr,
                str_max,
            )
            shapes_out.append(
                {
                    "count": shape_counts[key],
                    "keys": list(key),
                    "sample": sample,
                }
            )

        payload = {
            "_ndjson_shape_summary": True,
            "shapes": shapes_out,
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )


class XmlMachineSafeguardStrategy:
    """Truncate XML text nodes while keeping a parseable document."""

    def __init__(
        self,
        *,
        text_max_len: int = 240,
        min_bytes: int = 256,
    ) -> None:
        self._text_max = max(16, text_max_len)
        self._min_bytes = max(0, min_bytes)

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        try:
            if context.has_explicit_format:
                return content
            if context.content_type != ToolOutputContentType.XML:
                return content
            if len(content.encode("utf-8")) < self._min_bytes:
                return content

            text_max = self._text_max
            if level == CompressionLevel.AGGRESSIVE:
                text_max = max(16, text_max // 2)

            root = ElementTree.fromstring(content)

            def truncate_el(el: ElementTree.Element) -> None:
                if el.text:
                    raw = el.text
                    if len(raw) > text_max:
                        el.text = raw[:text_max] + f"[len={len(raw)}]"
                for child in list(el):
                    truncate_el(child)
                if el.tail:
                    raw = el.tail
                    if len(raw) > text_max:
                        el.tail = raw[:text_max] + f"[len={len(raw)}]"

            truncate_el(root)
            out = ElementTree.tostring(root, encoding="unicode", method="xml")
            return out
        except ElementTree.ParseError:
            return content
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("xml_machine_safeguard failed open", exc_info=True)
            return content


class LogLineDedupeStrategy:
    """Near-duplicate log line folding with volatile token normalization."""

    def __init__(
        self,
        *,
        min_repeat: int = 4,
        min_bytes: int = 4096,
    ) -> None:
        self._min_repeat = max(2, min_repeat)
        self._min_bytes = max(0, min_bytes)

    def _normalize(self, line: str) -> str:
        s = _LOG_TS_RE.sub("<ts>", line)
        s = _UUID_RE.sub("<uuid>", s)
        s = _HEX_LONG_RE.sub("<hex>", s)
        s = _EPHEMERAL_UNIX_PATH_RE.sub("<ephemeral_path>", s)
        s = _EPHEMERAL_WIN_PATH_RE.sub("<ephemeral_path>", s)
        s = _NUMERIC_ID_RE.sub("<id>", s)
        s = _LONG_NUM_RE.sub("<num>", s)
        return s

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        try:
            if context.content_type != ToolOutputContentType.TEXT:
                return content
            if len(content.encode("utf-8")) < self._min_bytes:
                return content

            min_rep = self._min_repeat
            if level == CompressionLevel.AGGRESSIVE:
                min_rep = max(2, min_rep - 1)

            lines = content.split("\n")
            out: list[str] = []
            i = 0
            while i < len(lines):
                line = lines[i]
                if _LOG_ERR_RE.search(line):
                    out.append(line)
                    i += 1
                    continue

                norm = self._normalize(line)
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if _LOG_ERR_RE.search(nxt):
                        break
                    if self._normalize(nxt) != norm:
                        break
                    j += 1
                run_len = j - i
                if run_len >= min_rep:
                    out.append(lines[i])
                    out.append(f"[log-dedupe repeated x{run_len}]")
                    i = j
                else:
                    for k in range(i, j):
                        out.append(lines[k])
                    i = j

            return "\n".join(out)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("log_line_dedupe failed open", exc_info=True)
            return content


class SensitiveFieldProjectionStrategy:
    """Mask sensitive KEY=VALUE / export lines with safe diagnostics."""

    def __init__(
        self,
        *,
        skip_command_prefixes: tuple[str, ...] = (),
    ) -> None:
        self._skip_prefixes = tuple(
            x.strip().lower() for x in skip_command_prefixes if x.strip()
        )

    def _should_skip(self, context: ToolOutputContext) -> bool:
        prefix = (context.identity.command_prefix or "").lower()
        return any(prefix.startswith(skip) for skip in self._skip_prefixes)

    @staticmethod
    def _mask_value(value: str) -> str:
        if not value:
            return value
        return "*" * len(value)

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        try:
            if context.has_explicit_format:
                return content
            if context.content_type != ToolOutputContentType.TEXT:
                return content
            if self._should_skip(context):
                return content

            sig = (context.identity.command_signature or "").lower()
            if sig not in {
                "printenv",
                "env",
                "aws",
                "gcloud",
                "terraform",
            }:
                return content

            masked = 0
            out_lines: list[str] = []
            for raw in content.splitlines():
                line = raw.rstrip("\n")
                stripped = line.strip()
                m = _EXPORT_RE.match(stripped)
                if m:
                    key, val = m.group(1), m.group(2)
                    if _SENSITIVE_KEY_RE.search(key):
                        out_lines.append(f"export {key}={self._mask_value(val)}")
                        masked += 1
                        continue
                    out_lines.append(line)
                    continue

                m2 = _ENV_KEYVAL_RE.match(stripped)
                if m2:
                    key, val = m2.group(1), m2.group(2)
                    if _SENSITIVE_KEY_RE.search(key):
                        out_lines.append(f"{key}={self._mask_value(val)}")
                        masked += 1
                        continue

                if sig in {"aws", "gcloud", "terraform"} and stripped:
                    new_line, did = self._maybe_mask_cloud_line(line)
                    if did:
                        masked += 1
                    out_lines.append(new_line)
                    continue

                out_lines.append(line)

            result = "\n".join(out_lines)
            if masked == 0:
                return content
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "sensitive_field_projection applied",
                    extra={"policy": "kv_mask", "masked_lines": masked},
                )
            return result
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("sensitive_field_projection failed open", exc_info=True)
            return content

    def _maybe_mask_cloud_line(self, line: str) -> tuple[str, bool]:
        stripped = line.strip()
        if "\t" in stripped:
            key, _sep, val = stripped.partition("\t")
            if _SENSITIVE_KEY_RE.search(key):
                return f"{key}\t{self._mask_value(val)}", True
        whitespace_split = re.match(r"^(\S+)(\s{2,})(.+)$", stripped)
        if whitespace_split and _SENSITIVE_KEY_RE.search(whitespace_split.group(1)):
            key = whitespace_split.group(1)
            separator = whitespace_split.group(2)
            value = whitespace_split.group(3)
            return f"{key}{separator}{self._mask_value(value)}", True
        return line, False
