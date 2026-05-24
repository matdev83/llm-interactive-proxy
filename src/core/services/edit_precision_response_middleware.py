from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, cast

from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)


class EditPrecisionFeature(IResponseFeature):
    """Feature to detect edit failures with enforced streaming/non-streaming parity.

    This feature detects edit failures in model responses and flags next-call tuning.
    Both streaming and non-streaming paths use identical logic.
    """

    _FILE_EDIT_TOOL_NAMES = {"patch_file", "turbo_edit_file"}
    _FAILURE_KEYWORDS = (
        "error",
        "failed",
        "diff_error",
        "hunk failed",
        "conflict",
        "no sufficiently similar match",
        "unable to apply",
    )
    _MAX_ARGUMENT_PARSE_CHARS = 12_000
    _MAX_TEXT_SCAN_CHARS = 16_000

    _TOOL_NAME_PATTERN = re.compile(
        r'["\']?(tool_name|name|tool)["\']?\s*[:=]\s*["\']?([A-Za-z0-9_\-]+)'
    )

    _DEFAULT_PATTERNS = [
        re.compile(r"<diff_error>|diff_error", re.IGNORECASE | re.DOTALL),
        re.compile(r"hunk\s+failed\s+to\s+apply", re.IGNORECASE | re.DOTALL),
        re.compile(
            r"No\s+sufficiently\s+similar\s+match\s+found", re.IGNORECASE | re.DOTALL
        ),
        re.compile(
            r"\[(?:patch_file|turbo_edit_file)\]\s*Error",
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    def __init__(self, app_state: IApplicationState, priority: int = 10) -> None:
        """Initialize the edit precision feature."""
        super().__init__(priority)
        self._logger = logging.getLogger(__name__)
        self._app_state = app_state
        self._compiled = list(self._DEFAULT_PATTERNS)
        self._last_stream_ids: dict[str, str] = {}
        self._combined_pattern: re.Pattern[str] | None = None

        try:
            from src.core.services.edit_precision_patterns import get_response_patterns

            config_patterns = get_response_patterns()
            default_pattern_strings = {
                r"<diff_error>|diff_error",
                r"hunk\s+failed\s+to\s+apply",
                r"No\s+sufficiently\s+similar\s+match\s+found",
            }
            for pattern in config_patterns:
                if pattern not in default_pattern_strings:
                    try:
                        self._compiled.append(
                            re.compile(pattern, re.IGNORECASE | re.DOTALL)
                        )
                    except re.error as err:
                        if self._logger.isEnabledFor(logging.WARNING):
                            self._logger.warning(
                                "Invalid edit precision pattern: %s - %s",
                                pattern,
                                err,
                                exc_info=True,
                            )
        except (ImportError, ModuleNotFoundError) as err:
            # Module import failures - expected if edit_precision_patterns module not available
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    "Edit precision patterns module not available: %s - using default patterns only",
                    err,
                    exc_info=True,
                )
        except Exception as err:
            # Catch any truly unexpected errors during config loading
            # Expected exceptions (ImportError, ModuleNotFoundError, re.error) are handled above
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    "Unexpected error loading edit precision patterns: %s - using default patterns only",
                    err,
                    exc_info=True,
                )

        # Pre-compile a combined regex for fast-fail checks
        # This converts O(N) regex searches into O(1) for the common case (no errors)
        try:
            pattern_strings = []
            for p in self._compiled:
                if hasattr(p, "pattern"):
                    pattern_strings.append(p.pattern)
                else:
                    pattern_strings.append(str(p))

            if pattern_strings:
                # Use non-capturing groups for safety
                combined = "|".join(f"(?:{p})" for p in pattern_strings)
                self._combined_pattern = re.compile(combined, re.IGNORECASE | re.DOTALL)
            else:
                self._combined_pattern = None
        except Exception as err:
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    "Failed to compile combined edit precision pattern: %s",
                    err,
                    exc_info=True,
                )
            self._combined_pattern = None

    @staticmethod
    def _extract_text_from_chunk(chunk: dict) -> str:
        """Extract text content from an OpenAI-format streaming chunk."""
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return ""
        delta = first_choice.get("delta") or first_choice.get("message")
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content")
        return content if isinstance(content, str) else ""

    def _process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool,
    ) -> Any:
        """Shared processing logic for both streaming and non-streaming."""
        if isinstance(response, ProcessedResponse):
            content = response.content
            if isinstance(content, dict):
                text = self._extract_text_from_chunk(content)
            elif isinstance(content, str):
                text = content
            else:
                text = ""
            out = response
        else:
            text = str(response) if response is not None else ""
            out = ProcessedResponse(content=text)

        metadata = getattr(out, "metadata", {}) or {}

        text_sources: list[str] = []
        if text:
            text_sources.append(text)
        metadata_text = self._extract_text_from_metadata(metadata)
        if metadata_text:
            text_sources.extend(metadata_text)

        combined_text = "\n".join(segment for segment in text_sources if segment)
        tool_failure_detected = self._has_file_edit_failure(metadata)

        if not combined_text and not tool_failure_detected:
            return out

        matched_pattern: str | None = None
        if combined_text:
            # OPTIMIZATION: Use combined pattern for O(1) fast-fail check
            # If combined pattern exists and doesn't match, we can skip individual checks
            should_scan = True
            if self._combined_pattern and not self._combined_pattern.search(
                combined_text
            ):
                should_scan = False

            for p in self._compiled if should_scan else []:
                try:
                    if p.search(combined_text):
                        matched_pattern = getattr(p, "pattern", None) or str(p)
                        break
                except re.error as exc:
                    # Invalid regex pattern (should not happen with compiled patterns, but defensive)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Regex pattern error during edit precision detection: %s",
                            exc,
                            exc_info=True,
                            extra={"pattern": getattr(p, "pattern", None) or str(p)},
                        )
                    continue
                except (TypeError, AttributeError) as exc:
                    # Wrong argument type or pattern attribute access issues
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Pattern matching type/attribute error during edit precision detection: %s",
                            exc,
                            exc_info=True,
                            extra={"pattern": getattr(p, "pattern", None) or str(p)},
                        )
                    continue
                except Exception:
                    # Unexpected errors (defensive guard for truly unexpected errors)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Unexpected error during pattern matching in edit precision detection",
                            exc_info=True,
                            extra={"pattern": getattr(p, "pattern", None) or str(p)},
                        )
                    continue

        if matched_pattern is None and tool_failure_detected:
            matched_pattern = "__file_edit_tool_failure__"

        if matched_pattern is not None:
            self._handle_match(session_id, context, out, matched_pattern, is_streaming)

        return out

    def _handle_match(
        self,
        session_id: str,
        context: dict[str, Any],
        out: ProcessedResponse,
        matched_pattern: str,
        is_streaming: bool,
    ) -> None:
        """Handle pattern match - flag for edit precision tuning."""
        active_disable_map = self._load_session_flag_map(
            "edit_precision_hybrid_reasoning_active"
        )

        pending_map = self._app_state.get_setting("edit_precision_pending", {})
        try:
            if not isinstance(pending_map, dict):
                pending_map = {}
            else:
                pending_map = dict(pending_map)
        except (TypeError, ValueError):
            # Log failures when converting pending_map to dict
            # TypeError: if pending_map is not iterable or doesn't support dict conversion
            # ValueError: if dict conversion fails (less common, but possible)
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Failed to convert pending_map to dict in edit precision handler",
                    exc_info=True,
                )
            pending_map = {}

        key = session_id or ""
        if key:
            if active_disable_map.get(key):
                self._update_stream_tracking(key, context, out)
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Edit-precision: session %s already has hybrid reasoning "
                        "disable flag",
                        key,
                    )
                return

            response_type = ""
            try:
                response_type = str((context or {}).get("response_type") or "")
            except (TypeError, AttributeError):
                # TypeError: if context is not dict-like (e.g., None, int, etc.)
                # AttributeError: if context doesn't have get method (custom object without dict interface)
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Failed to extract response_type from context in edit precision handler",
                        exc_info=True,
                    )
                response_type = ""

            stream_id = ""
            if response_type == "stream":
                try:
                    metadata = getattr(out, "metadata", {}) or {}
                    stream_id = str(
                        metadata.get("stream_id")
                        or (context or {}).get("stream_id")
                        or ""
                    )
                except (TypeError, AttributeError, KeyError):
                    # TypeError: if metadata/context is not dict-like or str() conversion fails
                    # AttributeError: if getattr() fails or metadata/context doesn't have .get() method
                    # KeyError: if dict access fails unexpectedly (shouldn't happen with .get(), but defensive)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Failed to extract stream_id from metadata/context in edit precision handler",
                            exc_info=True,
                        )
                    stream_id = ""
                last_stream_id = self._last_stream_ids.get(key)
                if stream_id and last_stream_id == stream_id:
                    return

            pending_map[key] = int(pending_map.get(key, 0)) + 1
            if response_type == "stream" and stream_id:
                self._last_stream_ids[key] = stream_id
            elif response_type != "stream":
                self._last_stream_ids.pop(key, None)
            self._app_state.set_setting("edit_precision_pending", pending_map)

            active_disable_map[key] = {"timestamp": time.time()}
            self._app_state.set_setting(
                "edit_precision_hybrid_reasoning_active", active_disable_map
            )

            hybrid_reasoning_disabled_map = self._app_state.get_setting(
                "edit_precision_hybrid_reasoning_disabled", {}
            )
            try:
                if not isinstance(hybrid_reasoning_disabled_map, dict):
                    hybrid_reasoning_disabled_map = {}
                else:
                    hybrid_reasoning_disabled_map = dict(hybrid_reasoning_disabled_map)
            except (TypeError, ValueError):
                # TypeError: if hybrid_reasoning_disabled_map is not iterable or doesn't support dict conversion
                # ValueError: if dict conversion fails (less common, but possible)
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Failed to convert hybrid_reasoning_disabled_map to dict in edit precision handler",
                        exc_info=True,
                    )
                hybrid_reasoning_disabled_map = {}

            hybrid_reasoning_disabled_map[key] = True
            self._app_state.set_setting(
                "edit_precision_hybrid_reasoning_disabled",
                hybrid_reasoning_disabled_map,
            )

            try:
                response_type = (
                    str((context or {}).get("response_type")) if context else ""
                )
                self._logger.info(
                    "Edit-precision trigger detected; session_id=%s pattern=%s "
                    "count=%s response_type=%s",
                    key,
                    matched_pattern,
                    pending_map.get(key, 0),
                    response_type,
                )
                self._logger.info(
                    "Hybrid reasoning disabled for next request in session %s "
                    "due to edit failure",
                    key,
                )
            except Exception as e:
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Error logging edit-precision trigger: %s", e, exc_info=True
                    )

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        """Process one response unit for edit failures."""
        return self._process_response(
            payload,
            session_id,
            cast(dict[str, Any], context),
            is_streaming=is_streaming,
        )

    def _update_stream_tracking(
        self,
        session_id: str,
        context: dict[str, Any] | None,
        response: ProcessedResponse,
    ) -> None:
        """Update stream tracking for duplicate detection."""
        response_type = ""
        try:
            response_type = str((context or {}).get("response_type") or "")
        except (TypeError, AttributeError):
            # TypeError: if context is not dict-like (e.g., None, int, etc.)
            # AttributeError: if context doesn't have get method (custom object without dict interface)
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Failed to extract response_type from context in stream tracking",
                    exc_info=True,
                )
            response_type = ""

        stream_id = ""
        if response_type == "stream":
            try:
                metadata = getattr(response, "metadata", {}) or {}
                stream_id = str(
                    metadata.get("stream_id") or (context or {}).get("stream_id") or ""
                )
            except (TypeError, AttributeError, KeyError):
                # TypeError: if metadata/context is not dict-like or str() conversion fails
                # AttributeError: if getattr() fails or metadata/context doesn't have .get() method
                # KeyError: if dict access fails unexpectedly (shouldn't happen with .get(), but defensive)
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Failed to extract stream_id from metadata/context in stream tracking",
                        exc_info=True,
                    )
                stream_id = ""
            if stream_id:
                self._last_stream_ids[session_id] = stream_id
        elif response_type != "stream":
            self._last_stream_ids.pop(session_id, None)

    def _extract_text_from_metadata(self, metadata: Any) -> list[str]:
        """Extract text from metadata tool calls."""
        if not isinstance(metadata, dict):
            return []

        texts: list[str] = []
        tool_calls = metadata.get("tool_calls")
        if isinstance(tool_calls, list):
            for item in tool_calls:
                if not isinstance(item, dict):
                    continue
                function_payload = item.get("function")
                if isinstance(function_payload, dict):
                    arguments = function_payload.get("arguments")
                    if isinstance(arguments, str):
                        texts.append(self._prepare_text_snippet(arguments))
                    elif isinstance(arguments, dict | list):
                        try:
                            dumped = json.dumps(arguments, ensure_ascii=False)
                        except (TypeError, ValueError):
                            continue
                        else:
                            texts.append(self._prepare_text_snippet(dumped))

        result_text = metadata.get("result")
        if isinstance(result_text, str):
            texts.append(self._prepare_text_snippet(result_text))

        return texts

    def _load_session_flag_map(self, setting_name: str) -> dict[str, Any]:
        """Load session flag map from app state."""
        try:
            stored = self._app_state.get_setting(setting_name, {})
            if isinstance(stored, dict):
                return dict(stored)
            if isinstance(stored, list):
                return {str(item): {"legacy": True} for item in stored}
        except (TypeError, AttributeError):
            # TypeError: if isinstance() fails or dict()/list conversion fails
            # AttributeError: if get_setting() raises AttributeError from internal getattr()
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Failed to load session flag map from app state: %s",
                    setting_name,
                    exc_info=True,
                )
        return {}

    def _has_file_edit_failure(self, metadata: Any) -> bool:
        """Check if metadata contains file edit failure indicators."""
        if not isinstance(metadata, dict):
            return False

        tool_calls = metadata.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                tool_name, raw_arguments = self._extract_tool_call_info(tool_call)
                if not tool_name or tool_name.lower() not in self._FILE_EDIT_TOOL_NAMES:
                    continue
                if self._tool_call_has_error(tool_call, raw_arguments):
                    return True

        aggregated = []
        for key in ("result", "tool_results", "tool_call_results"):
            value = metadata.get(key)
            if isinstance(value, str):
                aggregated.append(self._prepare_text_snippet(value))
            elif isinstance(value, list):
                aggregated.extend(
                    self._prepare_text_snippet(
                        json.dumps(item, ensure_ascii=False)
                        if isinstance(item, dict | list)
                        else str(item)
                    )
                    for item in value
                    if isinstance(item, str | dict | list)
                )
            elif isinstance(value, dict):
                aggregated.append(
                    self._prepare_text_snippet(json.dumps(value, ensure_ascii=False))
                )

        for snippet in aggregated:
            if isinstance(snippet, str) and self._contains_tool_error_text(snippet):
                return True

        return False

    def _extract_tool_call_info(
        self, tool_call: dict[str, Any]
    ) -> tuple[str | None, Any]:
        """Extract tool name and arguments from tool call."""
        function_payload = tool_call.get("function")
        raw_arguments: Any = None
        tool_name: str | None = None

        if isinstance(function_payload, dict):
            raw_name = function_payload.get("name")
            if isinstance(raw_name, str):
                candidate = raw_name.strip()
                if candidate and not candidate.startswith("__proxy"):
                    tool_name = candidate
            raw_arguments = function_payload.get("arguments")

        if not tool_name:
            raw_name = tool_call.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                tool_name = raw_name.strip()

        if raw_arguments is None:
            raw_arguments = tool_call.get("arguments")

        if not tool_name and raw_arguments is not None:
            tool_name = self._lookup_tool_name_from_arguments(raw_arguments)

        return tool_name, raw_arguments

    def _lookup_tool_name_from_arguments(self, arguments: Any) -> str | None:
        """Look up tool name from arguments."""
        if isinstance(arguments, dict):
            for key in ("tool_name", "name", "tool"):
                candidate = arguments.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()

            nested = arguments.get("tool_arguments")
            if isinstance(nested, dict):
                for key in ("tool_name", "name", "tool"):
                    candidate = nested.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()

        if isinstance(arguments, list):
            for item in arguments:
                candidate = self._lookup_tool_name_from_arguments(item)
                if candidate:
                    return candidate

        if isinstance(arguments, str):
            lowered = arguments.lower()
            for candidate in self._FILE_EDIT_TOOL_NAMES:
                if candidate in lowered:
                    return candidate

            match = self._TOOL_NAME_PATTERN.search(arguments)
            if match:
                return match.group(2)

        return None

    def _tool_call_has_error(
        self, tool_call: dict[str, Any], raw_arguments: Any
    ) -> bool:
        """Check if tool call has error indicators."""
        status = tool_call.get("status")
        if isinstance(status, str) and any(
            token in status.lower() for token in ("error", "fail")
        ):
            return True

        success = tool_call.get("success")
        if isinstance(success, bool) and success is False:
            return True

        for key in ("error", "error_type", "error_message", "failure_reason"):
            if key in tool_call and tool_call.get(key):
                return True

        if "result" in tool_call and self._nested_struct_has_error(tool_call["result"]):
            return True

        if "metadata" in tool_call and self._nested_struct_has_error(
            tool_call["metadata"]
        ):
            return True

        parsed_arguments = self._parse_arguments(raw_arguments)
        return bool(
            parsed_arguments and self._nested_struct_has_error(parsed_arguments)
        )

    def _parse_arguments(self, arguments: Any) -> Any:
        """Parse arguments from various formats."""
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, list):
            return [self._parse_arguments(item) for item in arguments]
        if isinstance(arguments, str):
            stripped = arguments.strip()
            if not stripped:
                return {}
            if len(stripped) > self._MAX_ARGUMENT_PARSE_CHARS:
                return stripped
            if stripped[0] not in "[{":
                return stripped
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
        return {}

    def _nested_struct_has_error(
        self, value: Any, seen: set[int] | None = None
    ) -> bool:
        """Check if nested structure has error indicators."""
        if seen is None:
            seen = set()

        if isinstance(value, dict):
            obj_id = id(value)
            if obj_id in seen:
                return False
            seen.add(obj_id)

            success_flag = value.get("success")
            if isinstance(success_flag, bool) and success_flag is False:
                return True

            status = value.get("status")
            if isinstance(status, str):
                lowered = status.lower()
                if any(token in lowered for token in ("error", "fail")):
                    return True

            for key in ("error", "error_type", "error_message", "failure_reason"):
                if key in value and value.get(key):
                    return True

            for sub_value in value.values():
                if self._nested_struct_has_error(sub_value, seen):
                    return True
            return False

        if isinstance(value, list):
            obj_id = id(value)
            if obj_id in seen:
                return False
            seen.add(obj_id)
            return any(self._nested_struct_has_error(item, seen) for item in value)

        if isinstance(value, str):
            return self._contains_tool_error_text(value)

        return False

    def _contains_tool_error_text(self, text: str) -> bool:
        """Check if text contains tool error keywords."""
        snippet = self._prepare_text_snippet(text)
        lowered = snippet.lower()
        if not any(name in lowered for name in self._FILE_EDIT_TOOL_NAMES):
            return "diff_error" in lowered
        return any(token in lowered for token in self._FAILURE_KEYWORDS)

    def _prepare_text_snippet(self, text: str) -> str:
        """Prepare text snippet for analysis."""
        if len(text) <= self._MAX_TEXT_SCAN_CHARS:
            return text

        half = self._MAX_TEXT_SCAN_CHARS // 2
        if half <= 0:
            return text

        prefix = text[:half]
        suffix = text[-half:]
        return f"{prefix}...{suffix}"


# Legacy middleware kept for backward compatibility during transition
# DEPRECATED: Use EditPrecisionFeature instead
class EditPrecisionResponseMiddleware(IResponseMiddleware):
    """DEPRECATED: Use EditPrecisionFeature instead.

    Legacy middleware that detects edit failures in model responses.
    This class is kept for backward compatibility only.
    """

    _FILE_EDIT_TOOL_NAMES = {"patch_file", "turbo_edit_file"}
    _FAILURE_KEYWORDS = (
        "error",
        "failed",
        "diff_error",
        "hunk failed",
        "conflict",
        "no sufficiently similar match",
        "unable to apply",
    )
    _MAX_ARGUMENT_PARSE_CHARS = 12_000
    _MAX_TEXT_SCAN_CHARS = 16_000

    _TOOL_NAME_PATTERN = re.compile(
        r'["\']?(tool_name|name|tool)["\']?\s*[:=]\s*["\']?([A-Za-z0-9_\-]+)'
    )

    @staticmethod
    def _extract_text_from_chunk(chunk: dict) -> str:
        """Extract text content from an OpenAI-format streaming chunk.

        Args:
            chunk: A dict that may be an OpenAI-format chunk with choices/delta/content

        Returns:
            The extracted text content, or empty string if not found
        """
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return ""
        delta = first_choice.get("delta") or first_choice.get("message")
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content")
        return content if isinstance(content, str) else ""

    # Pre-compiled regex patterns for performance optimization
    # These patterns are compiled once at class definition time instead of on every instantiation
    _DEFAULT_PATTERNS = [
        re.compile(r"<diff_error>|diff_error", re.IGNORECASE | re.DOTALL),
        re.compile(r"hunk\s+failed\s+to\s+apply", re.IGNORECASE | re.DOTALL),
        re.compile(
            r"No\s+sufficiently\s+similar\s+match\s+found", re.IGNORECASE | re.DOTALL
        ),
        re.compile(
            r"\[(?:patch_file|turbo_edit_file)\]\s*Error",
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    def __init__(self, app_state: IApplicationState) -> None:
        logger = logging.getLogger(__name__)
        logger.error(
            "DEPRECATED: EditPrecisionResponseMiddleware instantiated. "
            "Use EditPrecisionFeature instead for proper streaming/non-streaming parity."
        )
        super().__init__(priority=10)
        self._logger = logger
        self._app_state = app_state

        # Start with pre-compiled default patterns for performance
        self._compiled = list(self._DEFAULT_PATTERNS)
        # Track last flagged stream per session to avoid double-counting streaming chunks
        self._last_stream_ids: dict[str, str] = {}

        # Load additional patterns from external config if available
        try:
            from src.core.services.edit_precision_patterns import (
                get_response_patterns,
            )

            config_patterns = get_response_patterns()
            # Only compile patterns that aren't already in defaults
            default_pattern_strings = {
                r"<diff_error>|diff_error",
                r"hunk\s+failed\s+to\s+apply",
                r"No\s+sufficiently\s+similar\s+match\s+found",
            }
            for pattern in config_patterns:
                if pattern not in default_pattern_strings:
                    self._compiled.append(
                        re.compile(pattern, re.IGNORECASE | re.DOTALL)
                    )
        except Exception:
            # Use only default patterns if config loading fails
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    "Failed to load edit precision patterns in EditPrecisionResponseMiddleware; using defaults only",
                    exc_info=True,
                )

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        # Normalize to ProcessedResponse for chaining
        if isinstance(response, ProcessedResponse):
            content = response.content
            # Handle structured content (OpenAI-format dicts, StopChunkWithUsage)
            # These should pass through unchanged - we only analyze text content
            if isinstance(content, dict):
                # For dict content, extract text from delta.content if present
                text = self._extract_text_from_chunk(content)
            elif isinstance(content, str):
                text = content
            else:
                text = ""
            out = response
        else:
            text = str(response) if response is not None else ""
            out = ProcessedResponse(content=text)

        metadata = getattr(out, "metadata", {}) or {}

        text_sources: list[str] = []
        if text:
            text_sources.append(text)
        metadata_text = self._extract_text_from_metadata(metadata)
        if metadata_text:
            text_sources.extend(metadata_text)

        combined_text = "\n".join(segment for segment in text_sources if segment)
        tool_failure_detected = self._has_file_edit_failure(metadata)

        if not combined_text and not tool_failure_detected:
            return out

        matched_pattern: str | None = None
        if combined_text:
            for p in self._compiled:
                try:
                    if p.search(combined_text):
                        matched_pattern = getattr(p, "pattern", None) or str(p)
                        break
                except re.error as exc:
                    # Invalid regex pattern (should not happen with compiled patterns, but defensive)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Regex pattern error during edit precision detection: %s",
                            exc,
                            exc_info=True,
                            extra={"pattern": getattr(p, "pattern", None) or str(p)},
                        )
                    continue
                except (TypeError, AttributeError) as exc:
                    # Wrong argument type or pattern attribute access issues
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Pattern matching type/attribute error during edit precision detection: %s",
                            exc,
                            exc_info=True,
                            extra={"pattern": getattr(p, "pattern", None) or str(p)},
                        )
                    continue
                except Exception:
                    # Unexpected errors (defensive guard for truly unexpected errors)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Unexpected error during pattern matching in edit precision detection",
                            exc_info=True,
                            extra={"pattern": getattr(p, "pattern", None) or str(p)},
                        )
                    continue

        if matched_pattern is None and tool_failure_detected:
            matched_pattern = "__file_edit_tool_failure__"

        if matched_pattern is not None:
            active_disable_map = self._load_session_flag_map(
                "edit_precision_hybrid_reasoning_active"
            )

            # Set pending flag for this session (one-shot)
            pending_map = self._app_state.get_setting("edit_precision_pending", {})
            try:
                # Expect a dict[str, int]
                if not isinstance(pending_map, dict):
                    pending_map = {}
                else:
                    pending_map = dict(pending_map)
            except (TypeError, ValueError):
                # TypeError: if pending_map is not iterable or doesn't support dict conversion
                # ValueError: if dict conversion fails (less common, but possible)
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Failed to convert pending_map to dict in EditPrecisionResponseMiddleware.process",
                        exc_info=True,
                    )
                pending_map = {}

            key = session_id or ""
            if key:
                if active_disable_map.get(key):
                    # We already flagged this response; still update stream tracking
                    self._update_stream_tracking(key, context, out)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Edit-precision: session %s already has hybrid reasoning disable flag",
                            key,
                        )
                    return out

                response_type = ""
                try:
                    response_type = str((context or {}).get("response_type") or "")
                except (TypeError, AttributeError):
                    # TypeError: if context is not dict-like (e.g., None, int, etc.)
                    # AttributeError: if context doesn't have get method (custom object without dict interface)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Failed to extract response_type from context in EditPrecisionResponseMiddleware.process",
                            exc_info=True,
                        )
                    response_type = ""

                stream_id = ""
                if response_type == "stream":
                    try:
                        metadata = getattr(out, "metadata", {}) or {}
                        stream_id = str(
                            metadata.get("stream_id")
                            or (context or {}).get("stream_id")
                            or ""
                        )
                    except (TypeError, AttributeError, KeyError):
                        # TypeError: if metadata/context is not dict-like or str() conversion fails
                        # AttributeError: if getattr() fails or metadata/context doesn't have .get() method
                        # KeyError: if dict access fails unexpectedly (shouldn't happen with .get(), but defensive)
                        if self._logger.isEnabledFor(logging.DEBUG):
                            self._logger.debug(
                                "Failed to extract stream_id from metadata/context in EditPrecisionResponseMiddleware.process",
                                exc_info=True,
                            )
                        stream_id = ""
                    last_stream_id = self._last_stream_ids.get(key)
                    if stream_id and last_stream_id == stream_id:
                        return out

                pending_map[key] = int(pending_map.get(key, 0)) + 1
                if response_type == "stream" and stream_id:
                    self._last_stream_ids[key] = stream_id
                elif response_type != "stream":
                    self._last_stream_ids.pop(key, None)
                self._app_state.set_setting("edit_precision_pending", pending_map)

                # Mark hybrid reasoning disable active until consumed by request processor
                active_disable_map[key] = {"timestamp": time.time()}
                self._app_state.set_setting(
                    "edit_precision_hybrid_reasoning_active", active_disable_map
                )

                # NEW: Set flag to disable hybrid reasoning for next request in this session
                hybrid_reasoning_disabled_map = self._app_state.get_setting(
                    "edit_precision_hybrid_reasoning_disabled", {}
                )
                try:
                    if not isinstance(hybrid_reasoning_disabled_map, dict):
                        hybrid_reasoning_disabled_map = {}
                    else:
                        hybrid_reasoning_disabled_map = dict(
                            hybrid_reasoning_disabled_map
                        )
                except (TypeError, ValueError):
                    # TypeError: if hybrid_reasoning_disabled_map is not iterable or doesn't support dict conversion
                    # ValueError: if dict conversion fails (less common, but possible)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Failed to convert hybrid_reasoning_disabled_map to dict in EditPrecisionResponseMiddleware.process",
                            exc_info=True,
                        )
                    hybrid_reasoning_disabled_map = {}

                # Mark that hybrid reasoning should be disabled for next request
                hybrid_reasoning_disabled_map[key] = True
                self._app_state.set_setting(
                    "edit_precision_hybrid_reasoning_disabled",
                    hybrid_reasoning_disabled_map,
                )

                # Best-effort logging; do not let logging failures affect flow
                try:
                    response_type = (
                        str((context or {}).get("response_type")) if context else ""
                    )
                    self._logger.info(
                        "Edit-precision trigger detected; session_id=%s pattern=%s count=%s response_type=%s",
                        key,
                        matched_pattern,
                        pending_map.get(key, 0),
                        response_type,
                    )
                    self._logger.info(
                        "Hybrid reasoning disabled for next request in session %s due to edit failure",
                        key,
                    )
                except Exception as e:
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Error logging edit-precision trigger: %s", e, exc_info=True
                        )
        return out

    def _update_stream_tracking(
        self,
        session_id: str,
        context: dict[str, Any] | None,
        response: ProcessedResponse,
    ) -> None:
        response_type = ""
        try:
            response_type = str((context or {}).get("response_type") or "")
        except (TypeError, AttributeError):
            # TypeError: if context is not dict-like (e.g., None, int, etc.)
            # AttributeError: if context doesn't have get method (custom object without dict interface)
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Failed to extract response_type from context in EditPrecisionResponseMiddleware._update_stream_tracking",
                    exc_info=True,
                )
            response_type = ""

        stream_id = ""
        if response_type == "stream":
            try:
                metadata = getattr(response, "metadata", {}) or {}
                stream_id = str(
                    metadata.get("stream_id") or (context or {}).get("stream_id") or ""
                )
            except (TypeError, AttributeError, KeyError):
                # TypeError: if metadata/context is not dict-like or str() conversion fails
                # AttributeError: if getattr() fails or metadata/context doesn't have .get() method
                # KeyError: if dict access fails unexpectedly (shouldn't happen with .get(), but defensive)
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Failed to extract stream_id from metadata/context in EditPrecisionResponseMiddleware._update_stream_tracking",
                        exc_info=True,
                    )
                stream_id = ""
            if stream_id:
                self._last_stream_ids[session_id] = stream_id
        elif response_type != "stream":
            self._last_stream_ids.pop(session_id, None)

    def _extract_text_from_metadata(self, metadata: Any) -> list[str]:
        if not isinstance(metadata, dict):
            return []

        texts: list[str] = []

        tool_calls = metadata.get("tool_calls")
        if isinstance(tool_calls, list):
            for item in tool_calls:
                if not isinstance(item, dict):
                    continue
                function_payload = item.get("function")
                if isinstance(function_payload, dict):
                    arguments = function_payload.get("arguments")
                    if isinstance(arguments, str):
                        texts.append(self._prepare_text_snippet(arguments))
                    elif isinstance(arguments, dict | list):
                        try:
                            dumped = json.dumps(arguments, ensure_ascii=False)
                        except (TypeError, ValueError):
                            continue
                        else:
                            texts.append(self._prepare_text_snippet(dumped))

        # Some backends may include tool result summaries in metadata
        result_text = metadata.get("result")
        if isinstance(result_text, str):
            texts.append(self._prepare_text_snippet(result_text))

        return texts

    def _load_session_flag_map(self, setting_name: str) -> dict[str, Any]:
        try:
            stored = self._app_state.get_setting(setting_name, {})
            if isinstance(stored, dict):
                return dict(stored)
            if isinstance(stored, list):
                # Support legacy list storage by converting to dict with True values
                return {str(item): {"legacy": True} for item in stored}
        except (TypeError, AttributeError):
            # TypeError: if isinstance() fails or dict()/list conversion fails
            # AttributeError: if get_setting() raises AttributeError from internal getattr()
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Failed to load session flag map from app state in EditPrecisionResponseMiddleware: %s",
                    setting_name,
                    exc_info=True,
                )
        return {}

    def _has_file_edit_failure(self, metadata: Any) -> bool:
        if not isinstance(metadata, dict):
            return False

        tool_calls = metadata.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                tool_name, raw_arguments = self._extract_tool_call_info(tool_call)
                if not tool_name or tool_name.lower() not in self._FILE_EDIT_TOOL_NAMES:
                    continue
                if self._tool_call_has_error(tool_call, raw_arguments):
                    return True

        # Check aggregated tool results if present
        aggregated = []
        for key in ("result", "tool_results", "tool_call_results"):
            value = metadata.get(key)
            if isinstance(value, str):
                aggregated.append(self._prepare_text_snippet(value))
            elif isinstance(value, list):
                aggregated.extend(
                    self._prepare_text_snippet(
                        json.dumps(item, ensure_ascii=False)
                        if isinstance(item, dict | list)
                        else str(item)
                    )
                    for item in value
                    if isinstance(item, str | dict | list)
                )
            elif isinstance(value, dict):
                aggregated.append(
                    self._prepare_text_snippet(json.dumps(value, ensure_ascii=False))
                )

        for snippet in aggregated:
            if isinstance(snippet, str) and self._contains_tool_error_text(snippet):
                return True

        return False

    def _extract_tool_call_info(
        self, tool_call: dict[str, Any]
    ) -> tuple[str | None, Any]:
        function_payload = tool_call.get("function")
        raw_arguments: Any = None
        tool_name: str | None = None

        if isinstance(function_payload, dict):
            raw_name = function_payload.get("name")
            if isinstance(raw_name, str):
                candidate = raw_name.strip()
                if candidate and not candidate.startswith("__proxy"):
                    tool_name = candidate
            raw_arguments = function_payload.get("arguments")

        if not tool_name:
            raw_name = tool_call.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                tool_name = raw_name.strip()

        if raw_arguments is None:
            raw_arguments = tool_call.get("arguments")

        if not tool_name and raw_arguments is not None:
            tool_name = self._lookup_tool_name_from_arguments(raw_arguments)

        return tool_name, raw_arguments

    def _lookup_tool_name_from_arguments(self, arguments: Any) -> str | None:
        if isinstance(arguments, dict):
            for key in ("tool_name", "name", "tool"):
                candidate = arguments.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()

            nested = arguments.get("tool_arguments")
            if isinstance(nested, dict):
                for key in ("tool_name", "name", "tool"):
                    candidate = nested.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()

        if isinstance(arguments, list):
            for item in arguments:
                candidate = self._lookup_tool_name_from_arguments(item)
                if candidate:
                    return candidate

        if isinstance(arguments, str):
            lowered = arguments.lower()
            for candidate in self._FILE_EDIT_TOOL_NAMES:
                if candidate in lowered:
                    return candidate

            match = self._TOOL_NAME_PATTERN.search(arguments)
            if match:
                return match.group(2)

        return None

    def _tool_call_has_error(
        self, tool_call: dict[str, Any], raw_arguments: Any
    ) -> bool:
        status = tool_call.get("status")
        if isinstance(status, str) and any(
            token in status.lower() for token in ("error", "fail")
        ):
            return True

        success = tool_call.get("success")
        if isinstance(success, bool) and success is False:
            return True

        for key in ("error", "error_type", "error_message", "failure_reason"):
            if key in tool_call and tool_call.get(key):
                return True

        if "result" in tool_call and self._nested_struct_has_error(tool_call["result"]):
            return True

        if "metadata" in tool_call and self._nested_struct_has_error(
            tool_call["metadata"]
        ):
            return True

        parsed_arguments = self._parse_arguments(raw_arguments)
        return bool(
            parsed_arguments and self._nested_struct_has_error(parsed_arguments)
        )

    def _parse_arguments(self, arguments: Any) -> Any:
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, list):
            return [self._parse_arguments(item) for item in arguments]
        if isinstance(arguments, str):
            stripped = arguments.strip()
            if not stripped:
                return {}
            if len(stripped) > self._MAX_ARGUMENT_PARSE_CHARS:
                return stripped
            if stripped[0] not in "[{":
                return stripped
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
        return {}

    def _nested_struct_has_error(
        self, value: Any, seen: set[int] | None = None
    ) -> bool:
        if seen is None:
            seen = set()

        if isinstance(value, dict):
            obj_id = id(value)
            if obj_id in seen:
                return False
            seen.add(obj_id)

            success_flag = value.get("success")
            if isinstance(success_flag, bool) and success_flag is False:
                return True

            status = value.get("status")
            if isinstance(status, str):
                lowered = status.lower()
                if any(token in lowered for token in ("error", "fail")):
                    return True

            for key in ("error", "error_type", "error_message", "failure_reason"):
                if key in value and value.get(key):
                    return True

            for sub_value in value.values():
                if self._nested_struct_has_error(sub_value, seen):
                    return True
            return False

        if isinstance(value, list):
            obj_id = id(value)
            if obj_id in seen:
                return False
            seen.add(obj_id)
            return any(self._nested_struct_has_error(item, seen) for item in value)

        if isinstance(value, str):
            return self._contains_tool_error_text(value)

        return False

    def _contains_tool_error_text(self, text: str) -> bool:
        snippet = self._prepare_text_snippet(text)
        lowered = snippet.lower()
        if not any(name in lowered for name in self._FILE_EDIT_TOOL_NAMES):
            return "diff_error" in lowered
        return any(token in lowered for token in self._FAILURE_KEYWORDS)

    def _prepare_text_snippet(self, text: str) -> str:
        if len(text) <= self._MAX_TEXT_SCAN_CHARS:
            return text

        half = self._MAX_TEXT_SCAN_CHARS // 2
        if half <= 0:
            return text

        prefix = text[:half]
        suffix = text[-half:]
        return f"{prefix}...{suffix}"
