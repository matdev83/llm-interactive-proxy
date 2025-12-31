from __future__ import annotations

"""Service for resolving project directories from the first user prompt."""

import logging
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.model_utils import parse_model_backend
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.session_service_interface import ISessionService
from src.core.utils.xml_safety import XMLSafetyError, safe_xml_parse

logger = logging.getLogger(__name__)

# Type alias for recognized absolute path categories
_PathType = Literal["windows", "unc", "unix"]

# Pre-compiled regex patterns for performance optimization
# Note: Patterns allow spaces within path components (for Unicode paths like "Mi Proyecto")
# but stop at trailing punctuation. The pattern matches non-forbidden characters including spaces,
# but the lookahead ensures we stop at punctuation or whitespace that clearly ends the path.
# Note: Patterns allow spaces within path components (for Unicode paths like "Mi Proyecto")
# but stop at trailing punctuation. The pattern matches non-forbidden characters including spaces,
# but the lookahead ensures we stop at punctuation or whitespace that clearly ends the path.
# We explicitly exclude common punctuation characters from the path components to prevent
# greedy matching from consuming sentence punctuation (e.g. "path, but...").
# We also detect double-separators (empty components) to handle concatenation cases.


# Regex helper to match allowed chars OR a dot that is NOT followed by a space.
# This ensures we match "v1.5" but stop at "Start." in "Start. Next sentence."
def _safe_comp(forbidden: str) -> str:
    # Forbidden must include . so we can handle it specially
    return rf"(?:[^{forbidden}.]|\.(?!\s))"


_WIN_FORBIDDEN = r":*?<>|\r\n\\/,\"';!?"
_UNC_FORBIDDEN = r"\\:\r\n,\"';!?"
_UNIX_FORBIDDEN = r"/\\:\r\n,\"';!?"

_WINDOWS_PATH_PATTERN = re.compile(
    rf"\b([a-zA-Z]:\\+(?:{_safe_comp(_WIN_FORBIDDEN)}+"
    rf"(?:\\+{_safe_comp(_WIN_FORBIDDEN)}*)*))(?=[\s,.;!?]|$)"
)
# UNC pattern: Match 2+ backslashes at start (will be normalized later), then path components
_UNC_PATH_PATTERN = re.compile(
    rf"(?:^|\s)(\\{{2,}}(?:{_safe_comp(_UNC_FORBIDDEN)}+(?:\\+{_safe_comp(_UNC_FORBIDDEN)}*)*))"
    r"(?=[\s,.;!?]|$)"
)
_UNIX_PATH_PATTERN = re.compile(
    rf"(?:^|\s)(/+(?:{_safe_comp(_UNIX_FORBIDDEN)}+(?:/+{_safe_comp(_UNIX_FORBIDDEN)}*)*))"
    r"(?=[\s,.;!?]|$)"
)
_UNC_NORMALIZE_PATTERN = re.compile(r"\\{3,}")

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
            parsed = parse_model_backend(self._model_spec, "")
            if parsed.backend_type and parsed.model_name:
                backend_type = parsed.backend_type
                model_name = parsed.model_name
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
        except ValueError as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to normalize directory candidate path '%s' (type=%s): %s",
                    path,
                    path_type,
                    str(e),
                    exc_info=True,
                )
            return None
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Unexpected error normalizing directory candidate path '%s' (type=%s): %s",
                    path,
                    path_type,
                    str(e),
                    exc_info=True,
                )
            return None

        # If the path points inside a dot-folder (e.g. `.git/...`, `.vscode/...`),
        # treat the parent directory as the project root candidate.
        parts = pure_path.parts
        start_index = 1 if path_type in ("windows", "unc") else 0
        for index in range(start_index, len(parts)):
            part = parts[index]
            if part.startswith(".") and part not in {".", ".."}:
                if index > start_index:
                    pure_path = pure_path.__class__(*parts[:index])
                break

        # Drop filename component if present
        if pure_path.suffix:
            pure_path = pure_path.parent

        # Heuristic: If the path ends in a common source/test directory (e.g. src, lib, tests),
        # assume the user meant the parent project root.
        if pure_path.name.lower() in (
            "src",
            "source",
            "lib",
            "tests",
            "test",
            "bin",
        ) and len(pure_path.parts) > (1 if path_type in ("windows", "unc") else 1):
            # Ensure we don't strip the root (though unlikely with these names)
            pure_path = pure_path.parent

        normalized = str(pure_path)
        if path_type == "unc":
            normalized = self._normalize_unc_path(normalized)
        return normalized

    def _is_valid_project_directory_candidate(
        self, path: str, path_type: _PathType
    ) -> bool:
        """Validate whether a candidate directory is structurally plausible.

        Intentionally avoids hardcoded allow/deny lists. We only require:
        - Absolute path (in its own path style)
        - At least three directory components after the root/drive/share
        This rejects root directories, shallow directories like C:\\Users, and
        system directories like C:\\Windows\\System32 or /usr/bin, while accepting
        valid project paths like C:\\Users\\test\\project
        """
        try:
            pure_path = (
                PureWindowsPath(path)
                if path_type in ("windows", "unc")
                else PurePosixPath(path)
            )
        except (ValueError, TypeError) as e:
            # Invalid path format - expected for malformed input
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Invalid path format in _is_valid_project_path: %s", e)
            return False
        except Exception as e:
            # Unexpected exception during path parsing
            logger.warning(
                "Unexpected error parsing path in _is_valid_project_path: %s",
                e,
                exc_info=True,
            )
            return False

        parts = pure_path.parts
        # Require at least 4 parts total (root + 3 directory levels)
        # This rejects:
        # - Root directories (1 part): C:\\ or /
        # - Shallow directories (2 parts): C:\\Users or /home
        # - System directories (3 parts): C:\\Windows\\System32 or /usr/bin
        # While accepting deeper project paths (4+ parts): C:\\Users\\test\\project
        # For UNC paths, require server\\share\\directory\\subdirectory (4+ parts)
        return len(parts) >= 4

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
        except (ValueError, TypeError) as e:
            # Invalid path format - expected for malformed input
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Invalid path format in _longest_common_directory: %s", e)
            return None
        except Exception as e:
            # Unexpected exception during path parsing
            logger.warning(
                "Unexpected error parsing paths in _longest_common_directory: %s",
                e,
                exc_info=True,
            )
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

    def _score_path_candidate(self, directory: str, path_type: _PathType) -> int:
        """Score an individual path candidate based on depth (more specific wins)."""
        try:
            pure_path = (
                PureWindowsPath(directory)
                if path_type in ("windows", "unc")
                else PurePosixPath(directory)
            )
            return len(pure_path.parts)
        except (ValueError, TypeError) as e:
            # Invalid path format - expected for malformed input
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Invalid path format in _score_path_candidate: %s", e)
            return 0
        except Exception as e:
            # Unexpected exception during path parsing
            logger.warning(
                "Unexpected error parsing path in _score_path_candidate: %s",
                e,
                exc_info=True,
            )
            return 0

    def _looks_like_path_list_line(self, line: str) -> bool:
        """Heuristic to skip environment-like PATH lines without directory allow/deny lists."""
        if ";" not in line:
            return False

        match_count = 0
        for pattern in (_WINDOWS_PATH_PATTERN, _UNC_PATH_PATTERN, _UNIX_PATH_PATTERN):
            match_count += len(list(pattern.finditer(line)))
            if match_count >= 2:
                return True
        return False

    def _dot_entries_status(self, directory: str) -> bool | None:
        """Return whether directory contains dot entries, or None if unknown/uncheckable."""
        path_type = self._detect_path_type(directory)
        if not path_type:
            return None

        candidate_path = directory
        if os.name != "nt" and path_type in ("windows", "unc"):
            # Best-effort translation for WSL-style paths (e.g. /mnt/c/...) used in tests/dev.
            match = re.match(r"^([A-Za-z]):\\(.*)$", directory)
            if match:
                drive = match.group(1).lower()
                rest = match.group(2).replace("\\", "/")
                candidate_path = f"/mnt/{drive}/{rest}"
            else:
                return None
        elif os.name == "nt" and path_type == "unix":
            return None

        # Skip network I/O for UNC paths to avoid timeouts on non-existent servers
        # In production, UNC paths should be validated by user intent anyway
        if path_type == "unc":
            return None

        try:
            dir_path = Path(candidate_path)
            if not dir_path.exists():
                return None
            if not dir_path.is_dir():
                return None
            for entry in dir_path.iterdir():
                name = entry.name
                if name.startswith(".") and name not in {".", ".."}:
                    return True
            return False
        except (OSError, PermissionError) as e:
            # Expected filesystem errors
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Filesystem error in _has_hidden_files: %s", e)
            return None
        except Exception as e:
            # Unexpected exception during directory inspection
            logger.warning(
                "Unexpected error checking for hidden files: %s", e, exc_info=True
            )
            return None

    def _find_absolute_path_in_prompt(self, prompt_text: str) -> str | None:
        """
        Find the best project directory from all absolute paths in the prompt.
        When multiple paths are found, prefers the deepest, most specific valid path.
        """
        candidates: list[tuple[str, _PathType]] = []
        patterns = (_WINDOWS_PATH_PATTERN, _UNC_PATH_PATTERN, _UNIX_PATH_PATTERN)

        # Step 1: Extract and validate all path candidates (line-by-line).
        # This makes it easy to skip PATH-like lines without directory blacklists.
        for line in prompt_text.splitlines():
            if self._looks_like_path_list_line(line):
                continue

            for pattern in patterns:
                for match in pattern.finditer(line):
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

                    final_path_type = self._detect_path_type(directory)
                    if not final_path_type:
                        continue

                    if not self._is_valid_project_directory_candidate(
                        directory, final_path_type
                    ):
                        continue

                    candidates.append((directory, final_path_type))

        if not candidates:
            return None

        # Step 2: Group candidates by path type
        candidates_by_type: dict[_PathType, list[str]] = {}
        for directory, path_type in candidates:
            if path_type not in candidates_by_type:
                candidates_by_type[path_type] = []
            candidates_by_type[path_type].append(directory)

        # Step 3: For each type, evaluate paths and find the best one
        best_result: tuple[int, str] | None = None  # (score, path)

        for path_type, paths in candidates_by_type.items():
            # First, score all individual paths to find the best candidate
            best_individual: tuple[int, str] | None = None
            for path in paths:
                score = self._score_path_candidate(path, path_type)
                if best_individual is None or score > best_individual[0]:
                    best_individual = (score, path)

            # If only one path, use it directly
            if len(paths) == 1:
                if best_result is None or (
                    best_individual and best_individual[0] > best_result[0]
                ):
                    best_result = best_individual
                continue

            # For multiple paths, find their common directory
            common_result = self._longest_common_directory(paths, path_type)
            if common_result:
                common_path, common_depth = common_result
                # Validate the common path is a valid project directory
                if self._is_valid_project_directory_candidate(common_path, path_type):
                    common_score = self._score_path_candidate(common_path, path_type)

                    # Only use the common path if it's deeper/better than the best individual
                    # This ensures we prefer C:\Users\Test\ProjectA over C:\Users\Test
                    if best_individual:
                        # Logic: If all paths are subpaths (prefixes) of the best individual,
                        # then the best individual is the deepest specific project directory
                        # that encompasses the user's intent (e.g. they mentioned root and src).
                        # But if paths diverge (e.g. ProjectA and ProjectB), we must use the common root.

                        all_are_prefixes = True
                        best_parts = self._get_path_parts(best_individual[1], path_type)

                        for path in paths:
                            path_parts = self._get_path_parts(path, path_type)
                            if len(path_parts) > len(best_parts):
                                all_are_prefixes = False
                                break
                            # Check if path_parts is a prefix of best_parts
                            if best_parts[: len(path_parts)] != path_parts:
                                all_are_prefixes = False
                                break

                        if all_are_prefixes:
                            # Individual path is deeper and contains all others, use it
                            candidate = best_individual
                        else:
                            # Paths diverge, use common path
                            candidate = (common_score, common_path)
                    else:
                        candidate = (common_score, common_path)

                    if best_result is None or candidate[0] > best_result[0]:
                        best_result = candidate
                elif best_individual:
                    # Common path is invalid, use best individual
                    if best_result is None or best_individual[0] > best_result[0]:
                        best_result = best_individual
            elif best_individual:
                # No common path found, use best individual
                if best_result is None or best_individual[0] > best_result[0]:
                    best_result = best_individual

        return best_result[1] if best_result else None

    def _get_path_parts(self, path: str, path_type: _PathType) -> list[str]:
        """Get the parts of a path for depth comparison."""
        try:
            pure_path = (
                PureWindowsPath(path)
                if path_type in ("windows", "unc")
                else PurePosixPath(path)
            )
            return list(pure_path.parts)
        except (ValueError, TypeError) as e:
            # Invalid path format - expected for malformed input
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Invalid path format in _get_path_parts: %s", e)
            return []
        except Exception as e:
            # Unexpected exception during path parsing
            logger.warning(
                "Unexpected error parsing path in _get_path_parts: %s", e, exc_info=True
            )
            return []

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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"maybe_resolve_project_directory called: mode={self._resolution_mode}, "
                f"session_id={session.id}, history_length={len(session.history)}"
            )

        if self._resolution_mode == "disabled":
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Project directory resolution is disabled")
            return

        if getattr(session.state, "project_dir_resolution_attempted", False):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Project directory resolution already attempted for this session"
                )
            return

        if session.history:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Session has history, skipping project directory resolution"
                )
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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Extracted prompt text length: {len(prompt_text) if prompt_text else 0}"
            )

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
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Attempting deterministic resolution (mode: {self._resolution_mode})"
                )
            found_path = self._find_absolute_path_in_prompt(prompt_text)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Deterministic resolution result: {found_path}")
            dot_status: bool | None = None  # Initialize to avoid unbound variable
            if found_path:
                dot_status = self._dot_entries_status(found_path)
                if dot_status is False:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Deterministic project directory candidate rejected (no dot entries): %s",
                            found_path,
                        )
                else:
                    await self._persist_state(
                        session,
                        directory=found_path,
                        message=f"Project directory auto-detected (deterministic): {found_path}",
                    )
                    return

            # If deterministic produced a candidate but it was rejected due to lacking dot
            # entries, fall back to the server CWD if it looks like a project.
            #
            # Only applies to `deterministic` mode; `hybrid` should continue to LLM.
            if (
                self._resolution_mode == "deterministic"
                and found_path
                and dot_status is False
            ):
                cwd_candidate = str(Path.cwd().resolve())
                if self._dot_entries_status(cwd_candidate) is True:
                    await self._persist_state(
                        session,
                        directory=cwd_candidate,
                        message=(
                            "Project directory auto-detected (deterministic fallback): "
                            f"{cwd_candidate}"
                        ),
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
            logger.warning(
                "Failed to persist project directory detection state: %s",
                exc,
                exc_info=True,
            )
        if logger.isEnabledFor(logging.INFO):
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
            except UnicodeDecodeError:
                # Expected for non-UTF-8 content, fallback to ignore errors
                return content.decode("utf-8", "ignore")
            except Exception as e:
                # Unexpected exception during decoding
                logger.warning(
                    "Unexpected error decoding response content: %s", e, exc_info=True
                )
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
            root = safe_xml_parse(response_text.strip())
        except XMLSafetyError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to parse XML in directory response: %s",
                    e,
                    exc_info=True,
                )
            return None, f"invalid XML: {e}"
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
