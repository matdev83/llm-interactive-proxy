from __future__ import annotations

"""Service for resolving project directories from the first user prompt."""

import logging
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal
from xml.etree import ElementTree
from xml.etree.ElementTree import ParseError

from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.model_utils import parse_model_backend
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)

# Type alias for recognized absolute path categories
_PathType = Literal["windows", "unc", "unix"]

# Pre-compiled regex patterns for performance optimization
_WINDOWS_PATH_PATTERN = re.compile(
    r"\b([a-zA-Z]:\\(?:[^:*?<>|\r\n\\\s]*(?:\\[^:*?<>|\r\n\\\s]*)*))(?=\s|$|[,;!?])"
)
_UNC_PATH_PATTERN = re.compile(
    r"(\\{2}[^\\:\r\n\s]*(?:\\[^\\:\r\n\s]*)*)(?=\s|$|[,;!?])"
)
_UNIX_PATH_PATTERN = re.compile(
    r"(?:^|\s)(/[^/\\\s:\r\n]*(?:/[^/\\\s:\r\n]*)*)(?=\s|$|[,;!?])"
)
_UNC_NORMALIZE_PATTERN = re.compile(r"\\{3,}")

_COMMON_PROJECT_SUBDIRS = {
    "src",
    "lib",
    "bin",
    "include",
    "static",
    "assets",
    "public",
    "docs",
    "tests",
    "test",
}
_LEADING_STRIP_CHARS = "\"'`([{<"
_TRAILING_STRIP_CHARS = ",.;:!?)]}`>\"'`"


class ProjectDirectoryResolutionService:
    """Resolve absolute project directories using a dedicated backend model."""

    def __init__(
        self,
        app_config: AppConfig,
        backend_service: IBackendService,
        session_service: ISessionService,
    ) -> None:
        self._backend_service = backend_service
        self._session_service = session_service
        self._resolution_mode = app_config.session.project_dir_resolution_mode
        self._model_spec = (
            app_config.session.project_dir_resolution_model
            if hasattr(app_config, "session")
            else None
        )
        self._model_spec = self._model_spec.strip() if self._model_spec else ""

        backend_type: str | None = None
        model_name: str | None = None
        if self._model_spec:
            backend_candidate, model_candidate = parse_model_backend(
                self._model_spec, ""
            )
            if backend_candidate and model_candidate:
                backend_type = backend_candidate
                model_name = model_candidate
            else:
                logger.warning(
                    "Invalid project directory resolution model specification: %s",
                    self._model_spec,
                )

        self._backend_type = backend_type
        self._model_name = model_name
        self._model_identifier = (
            f"{self._backend_type}:{self._model_name}"
            if self._backend_type and self._model_name
            else None
        )

        self._system_prompt = (
            "You examine the user's initial instructions to determine the absolute "
            "project directory path they intend to work with. Respond using the "
            "exact XML formats shown below.\n"
            "If the directory can be determined:\n"
            "<directory-resolution-response>\n"
            "<project-absolute-directory>PATH_HERE</project-absolute-directory>\n"
            "</directory-resolution-response>\n"
            "If the directory cannot be determined:\n"
            "<directory-resolution-response>\n"
            "<error>SHORT_REASON</error>\n"
            "</directory-resolution-response>\n"
            "Rules:\n"
            "- Do not execute, simulate, or reason about running any tools or commands.\n"
            "- Operate strictly in a headless, non-interactive environment.\n"
            "- Communicate only via the XML response; no commentary or markdown.\n"
        )

    def _normalize_unc_path(self, path: str) -> str:
        """Normalize UNC path backslashes to the expected format (\\\\server\\share\\folder)."""
        # Handle various UNC path formats:
        # 1. Reduce excessive backslashes (3+) to exactly 2
        # 2. Ensure path starts with exactly 2 backslashes
        # 3. Clean up mixed separator patterns

        # First, reduce any sequence of 3+ backslashes to exactly 2
        path = _UNC_NORMALIZE_PATTERN.sub("\\\\", path)

        # Ensure path starts with exactly 2 backslashes
        if path.startswith("\\\\"):
            return path
        elif path.startswith("\\") and not path.startswith("\\\\"):
            # Single backslash - this might be malformed UNC
            # Try to normalize by adding another backslash if it looks like a server name
            remaining = path[1:]
            if remaining and not remaining.startswith("\\") and "\\" in remaining:
                return "\\\\" + remaining

        return path

    def _strip_outer_tokens(self, value: str) -> str:
        """Strip wrapping punctuation, quotes, and whitespace commonly surrounding paths."""
        trimmed = value.strip()
        if not trimmed:
            return ""

        changed = True
        while trimmed and changed:
            changed = False
            if trimmed[0] in _LEADING_STRIP_CHARS:
                trimmed = trimmed[1:].lstrip()
                changed = True
                continue
            if trimmed and trimmed[-1] in _TRAILING_STRIP_CHARS:
                trimmed = trimmed[:-1].rstrip()
                changed = True
        return trimmed

    def _detect_path_type(self, path: str) -> _PathType | None:
        if not path:
            return None
        if path.startswith("\\\\"):
            return "unc"
        if re.match(r"^[a-zA-Z]:\\", path):
            return "windows"
        if path.startswith("/"):
            return "unix"
        return None

    def _normalize_directory_candidate(
        self, path: str, path_type: _PathType
    ) -> str | None:
        try:
            pure_path = (
                PureWindowsPath(path)
                if path_type in ("windows", "unc")
                else PurePosixPath(path)
            )
        except Exception:
            return None

        # Drop filename component if present
        if pure_path.suffix:
            pure_path = pure_path.parent

        # Remove common leaf directories such as src/tests when we have higher-level context
        while pure_path.name and pure_path.name.lower() in _COMMON_PROJECT_SUBDIRS:
            if len(pure_path.parts) <= 2:
                break
            parent = pure_path.parent
            if parent == pure_path:
                break
            pure_path = parent

        normalized = str(pure_path)
        if path_type == "unc":
            normalized = self._normalize_unc_path(normalized)
        return normalized

    def _longest_common_directory(
        self, directories: list[str], path_type: _PathType
    ) -> tuple[str, int] | None:
        if not directories:
            return None

        path_class = (
            PureWindowsPath if path_type in ("windows", "unc") else PurePosixPath
        )
        try:
            parts_lists = [path_class(directory).parts for directory in directories]
        except Exception:
            return None

        min_length = min(len(parts) for parts in parts_lists)
        if min_length == 0:
            return None

        common_parts: list[str] = []
        for index in range(min_length):
            candidate = parts_lists[0][index]
            if path_type in ("windows", "unc"):
                if all(
                    part[index].lower() == candidate.lower() for part in parts_lists
                ):
                    common_parts.append(candidate)
                else:
                    break
            else:
                if all(part[index] == candidate for part in parts_lists):
                    common_parts.append(candidate)
                else:
                    break

        if not common_parts:
            return None

        common_path = str(path_class(*common_parts))
        if path_type == "unc":
            common_path = self._normalize_unc_path(common_path)
        return common_path, len(common_parts)

    def _find_absolute_path_in_prompt(self, prompt_text: str) -> str | None:
        """
        Try to find the common base project directory from all absolute paths
        found in the prompt.
        """
        path_buckets: dict[_PathType, list[tuple[str, int]]] = {}
        patterns = [
            _WINDOWS_PATH_PATTERN,
            _UNC_PATH_PATTERN,
            _UNIX_PATH_PATTERN,
        ]

        for pattern in patterns:
            for match in pattern.finditer(prompt_text):
                raw_value = match.group(1) if match.lastindex else match.group(0)
                cleaned = self._strip_outer_tokens(raw_value)
                if not cleaned:
                    continue

                path_type = self._detect_path_type(cleaned)
                if path_type is None:
                    continue

                if path_type == "unc":
                    cleaned = self._normalize_unc_path(cleaned)

                if not self._looks_like_absolute_path(cleaned):
                    continue

                directory = self._normalize_directory_candidate(cleaned, path_type)
                if not directory:
                    continue

                path_buckets.setdefault(path_type, []).append(
                    (directory, match.start())
                )

        if not path_buckets:
            return None

        best_path: str | None = None
        best_score = (-1, 0, 0, 0)
        for path_type, entries in path_buckets.items():
            directories = [directory for directory, _ in entries]
            lcp_result = self._longest_common_directory(directories, path_type)
            if not lcp_result:
                continue
            common_path, depth = lcp_result
            earliest_index = min(index for _, index in entries)
            score = (len(directories), -earliest_index, depth, len(common_path))
            if score > best_score:
                best_score = score
                best_path = common_path

        return best_path

    def _extract_directory_from_path(self, path: str) -> str:
        """Extract directory portion from a path that may include a filename."""
        path_type = self._detect_path_type(path)
        if not path_type:
            return path
        normalized = self._normalize_directory_candidate(path, path_type)
        return normalized or path

    async def maybe_resolve_project_directory(
        self, session: Session, request: ChatRequest
    ) -> None:
        """Attempt to resolve the project directory for the very first prompt."""
        if self._resolution_mode == "disabled":
            return

        if getattr(session.state, "project_dir_resolution_attempted", False):
            return

        if session.history:
            return

        existing_dir = getattr(session.state, "project_dir", None)
        if existing_dir:
            await self._persist_state(
                session,
                directory=None,
                message=(
                    "Project directory auto-detection skipped: directory already set to"
                    f" {existing_dir}"
                ),
            )
            return

        prompt_text = self._extract_user_prompt(request)
        if not prompt_text:
            await self._persist_state(
                session,
                directory=None,
                message=(
                    "Project directory auto-detection did not identify a directory"
                    " (empty prompt)"
                ),
            )
            return

        # Deterministic resolution
        if self._resolution_mode in ("deterministic", "hybrid"):
            found_path = self._find_absolute_path_in_prompt(prompt_text)
            if found_path:
                await self._persist_state(
                    session,
                    directory=found_path,
                    message=f"Project directory auto-detected (deterministic): {found_path}",
                )
                return

        # LLM resolution (if applicable)
        if self._resolution_mode in ("llm", "hybrid"):
            if not self._model_identifier:
                if self._resolution_mode == "llm":
                    logger.warning(
                        "LLM project directory resolution is enabled but no model is configured."
                    )
                if self._resolution_mode == "hybrid":
                    # In hybrid mode, if deterministic fails, we just mark as attempted and move on
                    # without logging a warning if no LLM is configured.
                    await self._persist_state(
                        session,
                        directory=None,
                        message="Project directory auto-detection did not identify a directory (hybrid mode, no LLM configured).",
                    )
                return

            try:
                response = await self._call_resolution_model(prompt_text)
            except Exception as exc:  # pragma: no cover - defensive logging
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Project directory auto-detection call failed: %s",
                        exc,
                        exc_info=True,
                    )
                await self._persist_state(
                    session,
                    directory=None,
                    message="Project directory auto-detection did not identify a directory (request failure)",
                )
                return

            if isinstance(response, StreamingResponseEnvelope):
                await self._persist_state(
                    session,
                    directory=None,
                    message=(
                        "Project directory auto-detection did not identify a directory"
                        " (streaming response unsupported)"
                    ),
                )
                return

            response_text = self._extract_response_text(response)
            if not response_text:
                await self._persist_state(
                    session,
                    directory=None,
                    message=(
                        "Project directory auto-detection did not identify a directory"
                        " (empty model response)"
                    ),
                )
                return

            directory, error_reason = self._parse_directory_response(response_text)
            if directory:
                await self._persist_state(
                    session,
                    directory=directory,
                    message=f"Project directory auto-detected (LLM): {directory}",
                )
            else:
                reason_suffix = f" ({error_reason})" if error_reason else ""
                await self._persist_state(
                    session,
                    directory=None,
                    message=(
                        "Project directory auto-detection did not identify a directory"
                        f"{reason_suffix}"
                    ),
                )
        else:  # This handles deterministic mode when nothing is found
            await self._persist_state(
                session,
                directory=None,
                message="Project directory auto-detection did not identify a directory (deterministic mode).",
            )

    async def _persist_state(
        self, session: Session, *, directory: str | None, message: str
    ) -> None:
        # Use Pydantic-style immutable updates from local
        session_state = session.state.with_project_dir_resolution_attempted(True)
        if directory is not None:
            session_state = session_state.with_project_dir(directory)
        session.state = session_state
        try:
            await self._session_service.update_session(session)
        except Exception as exc:  # pragma: no cover - defensive logging
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to persist project directory detection state: %s",
                    exc,
                    exc_info=True,
                )
        logger.info(message)

    async def _call_resolution_model(self, prompt_text: str) -> ResponseEnvelope:
        request = ChatRequest(
            model=self._model_identifier or "gpt-4",
            messages=[
                ChatMessage(role="system", content=self._system_prompt),
                ChatMessage(role="user", content=prompt_text),
            ],
            extra_body=(
                {"backend_type": self._backend_type} if self._backend_type else None
            ),
        )
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id=None,
            agent="project-dir-resolution",
        )
        response = await self._backend_service.call_completion(
            request,
            stream=False,
            allow_failover=False,
            context=context,
        )
        if isinstance(response, StreamingResponseEnvelope):
            raise TypeError(
                "Streaming response returned for project directory resolution"
            )
        return response

    def _extract_user_prompt(self, request: ChatRequest) -> str | None:
        """Extract and concatenate content from all messages in the request."""
        full_prompt_parts: list[str] = []
        for message in request.messages:
            content = self._normalize_content(message.content)
            if content.strip():
                full_prompt_parts.append(content)

        if not full_prompt_parts:
            return None

        return "\n".join(full_prompt_parts)

    def _normalize_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                text: Any | None = None
                if hasattr(part, "text"):
                    text = part.text
                elif isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                else:
                    text = str(part)
                if text:
                    parts.append(str(text))
            return "\n".join(parts)
        if content is None:
            return ""
        return str(content)

    def _extract_response_text(self, response: ResponseEnvelope) -> str | None:
        content = response.content
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except Exception:
                return content.decode("utf-8", "ignore")
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            text = self._extract_from_openai_like_response(content)
            if text:
                return text
            text = self._extract_from_gemini_like_response(content)
            if text:
                return text
            if "output_text" in content:
                value = content.get("output_text")
                if isinstance(value, str):
                    return value
        return None

    def _extract_from_openai_like_response(self, payload: dict[str, Any]) -> str | None:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        if not isinstance(first, dict):
            return None
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("content")
                        if text:
                            parts.append(str(text))
                if parts:
                    return "\n".join(parts)
        text_value = first.get("text")
        if isinstance(text_value, str):
            return text_value
        return None

    def _extract_from_gemini_like_response(self, payload: dict[str, Any]) -> str | None:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None
        first = candidates[0]
        if not isinstance(first, dict):
            return None
        content = first.get("content")
        parts: list[str] = []
        if isinstance(content, dict):
            raw_parts = content.get("parts")
            if isinstance(raw_parts, list):
                for part in raw_parts:
                    if isinstance(part, dict) and part.get("text"):
                        parts.append(str(part["text"]))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
        if parts:
            return "\n".join(parts)
        text_value = first.get("output_text")
        if isinstance(text_value, str):
            return text_value
        return None

    def _parse_directory_response(
        self, response_text: str
    ) -> tuple[str | None, str | None]:
        try:
            root = ElementTree.fromstring(response_text.strip())
        except ParseError:
            return None, "invalid XML"
        if root.tag != "directory-resolution-response":
            return None, "unexpected root tag"
        directory_elem = root.find("project-absolute-directory")
        if directory_elem is not None and directory_elem.text:
            candidate = directory_elem.text.strip()
            if self._looks_like_absolute_path(candidate):
                return candidate, None
            return None, "not an absolute path"
        error_elem = root.find("error")
        if error_elem is not None and error_elem.text:
            return None, error_elem.text.strip()
        return None, "no directory element"

    def _looks_like_absolute_path(self, value: str) -> bool:
        if not value:
            return False
        if "\n" in value or "\r" in value:
            return False
        # Linux/Unix
        if value.startswith("/"):
            return True
        # UNC
        if value.startswith("\\\\"):
            return True
        # Windows
        return bool(re.match(r"^[a-zA-Z]:\\", value))


__all__ = ["ProjectDirectoryResolutionService"]
