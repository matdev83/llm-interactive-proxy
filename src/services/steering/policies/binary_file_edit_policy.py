"""Binary file edit steering policy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from src.core.domain.tool_constants import FileEditingTools
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext

from ..interfaces import ISteeringPolicy
from ..models import SteeringResult

logger = logging.getLogger(__name__)


# Comprehensive set of binary file extensions
BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Executables & Libraries
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".elf",
        ".com",
        ".msi",
        ".app",
        ".deb",
        ".rpm",
        ".dmg",
        ".iso",
        ".img",
        ".apk",
        ".ipa",
        # Compiled/Object Files
        ".o",
        ".obj",
        ".a",
        ".lib",
        ".pyc",
        ".pyo",
        ".pyd",
        ".class",
        ".jar",
        ".war",
        ".ear",
        ".whl",
        ".egg",
        # Databases
        ".db",
        ".sqlite",
        ".sqlite3",
        ".mdb",
        ".accdb",
        ".dbf",
        ".frm",
        ".ibd",
        ".myd",
        ".myi",
        ".ldf",
        ".mdf",
        ".ndf",
        # Media - Audio
        ".mp3",
        ".wav",
        ".flac",
        ".aac",
        ".ogg",
        ".wma",
        ".m4a",
        ".opus",
        ".aiff",
        ".ape",
        ".mid",
        ".midi",
        # Media - Video
        ".mp4",
        ".avi",
        ".mkv",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".3gp",
        ".mpeg",
        ".mpg",
        ".vob",
        ".ogv",
        # Images
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".ico",
        ".webp",
        ".psd",
        ".ai",
        ".eps",
        ".raw",
        ".cr2",
        ".nef",
        ".heic",
        ".heif",
        ".dng",
        ".arw",
        ".orf",
        # Documents (Binary formats)
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".pdf",
        ".odt",
        ".ods",
        ".odp",
        ".rtf",
        # Archives
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".cab",
        ".arj",
        ".lzh",
        ".lzma",
        ".z",
        ".tgz",
        ".tbz2",
        # Fonts
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".eot",
        ".fon",
        # 3D/CAD/Game Assets
        ".blend",
        ".fbx",
        ".3ds",
        ".max",
        ".dwg",
        ".dxf",
        ".stl",
        ".gltf",
        ".glb",
        ".unity3d",
        ".asset",
        ".pak",
        ".bundle",
        # Other Binary
        ".dat",
        ".swf",
        ".fla",
        ".pdb",
        ".dmp",
        ".core",
    }
)

# Common parameter names that contain file paths
PATH_PARAMETER_NAMES: tuple[str, ...] = (
    "path",
    "file_path",
    "target_file",
    "filename",
    "file",
    "destination",
    "dest",
    "target",
    "filepath",
    "file_name",
    "new_path",
    "old_path",
    "source",
    "src",
)


class BinaryFileEditPolicy(ISteeringPolicy):
    """Policy that detects and warns when agents attempt to edit binary files.

    Binary files (executables, media, databases, etc.) should not be modified
    through text-based file editing operations as this typically corrupts the files.
    """

    DEFAULT_MESSAGE: Final[str] = (
        "You are attempting to edit a binary file using a text-based file editing tool. "
        "This will likely corrupt the file. Binary files (executables, images, media, "
        "databases, archives, etc.) should not be edited as text. "
        "If you need to modify such files, please use appropriate tools or explain "
        "what you're trying to achieve so an alternative approach can be suggested."
    )

    def __init__(
        self,
        message: str | None = None,
        enabled: bool = True,
        prompt_override_path: Path | None = None,
    ) -> None:
        """Initialize the policy.

        Args:
            message: Custom steering message
            enabled: Whether the policy is enabled
            prompt_override_path: Path to a file to override the default message
        """
        self._enabled = enabled
        self._file_editing_tools = {
            FileEditingTools.WRITE_TO_FILE,
            FileEditingTools.WRITE_FILE,
            FileEditingTools.FS_WRITE,
            FileEditingTools.REPLACE_IN_FILE,
            FileEditingTools.STR_REPLACE,
            FileEditingTools.STR_REPLACE_CAMEL,
            FileEditingTools.EDIT_FILE,
            FileEditingTools.PATCH_FILE,
            FileEditingTools.APPLY_DIFF,
            FileEditingTools.APPLY_PATCH,
            FileEditingTools.DELETE_FILE,
            FileEditingTools.DELETE_FILE_CAMEL,
            FileEditingTools.REMOVE_FILE,
            FileEditingTools.CREATE_FILE,
            FileEditingTools.MOVE_FILE,
            FileEditingTools.RENAME_FILE,
            FileEditingTools.COPY_FILE,
            FileEditingTools.INSERT_CONTENT,
            FileEditingTools.SEARCH_AND_REPLACE,
        }

        final_message = message or self.DEFAULT_MESSAGE
        if prompt_override_path and prompt_override_path.is_file():
            try:
                final_message = prompt_override_path.read_text(encoding="utf-8")
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Loaded binary file edit steering prompt from %s",
                        prompt_override_path,
                    )
            except Exception:
                logger.warning(
                    "Failed to read binary file edit steering prompt from %s, using default.",
                    prompt_override_path,
                    exc_info=True,
                )
        self._message = final_message

    @property
    def name(self) -> str:
        return "binary_file_edit"

    @property
    def priority(self) -> int:
        # High priority to catch before file operations execute
        return 90

    async def evaluate(
        self, context: ToolCallContext, command: str, dry_run: bool = False
    ) -> SteeringResult | None:
        """Evaluate if tool call targets a binary file.

        Args:
            context: Tool call context containing session_id, tool_name, arguments
            command: Normalized command string (may not be used for file tools)
            dry_run: If True, do not apply side effects

        Returns:
            SteeringResult if binary file edit detected, None otherwise
        """
        if not self._enabled:
            return None

        tool_name = (context.tool_name or "").strip()

        # Check if tool is a file editing tool
        if tool_name not in self._file_editing_tools:
            return None

        # Extract all file paths from arguments (tools like move_file/copy_file have multiple)
        file_paths = self._extract_all_file_paths(context.tool_arguments)
        if not file_paths:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Could not extract file path from arguments in session %s",
                    context.session_id,
                )
            return None

        # Check if any file has a binary extension
        binary_path = None
        binary_extension = None
        for file_path in file_paths:
            extension = self._get_extension(file_path)
            if extension and self._is_binary_extension(extension):
                binary_path = file_path
                binary_extension = extension
                break

        if not binary_path:
            return None

        # Binary file edit detected
        if logger.isEnabledFor(logging.INFO):
            # Log only basename to avoid leaking sensitive path components
            from pathlib import Path as PathObj

            try:
                basename = PathObj(file_path).name
            except Exception:
                basename = "<unknown>"

            logger.info(
                "Intercepted binary file edit attempt: %s (extension: %s) in session %s",
                basename,
                binary_extension,
                context.session_id,
            )

        return SteeringResult(
            message=self._message,
            should_block=True,
            policy_name=self.name,
            severity="warning",
            metadata={
                "tool_name": context.tool_name,
                "file_path": binary_path,
                "extension": binary_extension,
                "source": "binary_file_edit_steering",
            },
        )

    def _extract_all_file_paths(self, arguments: dict[str, Any] | None) -> list[str]:
        """Extract all file paths from tool arguments.

        Args:
            arguments: Tool arguments dictionary

        Returns:
            List of file path strings found
        """
        if not arguments:
            return []

        paths: list[str] = []

        # Try common parameter names and collect all found paths
        for param_name in PATH_PARAMETER_NAMES:
            if param_name in arguments:
                path_value = arguments[param_name]
                if isinstance(path_value, str) and path_value:
                    paths.append(path_value)
                # Handle Path objects
                elif hasattr(path_value, "__str__"):
                    paths.append(str(path_value))

        return paths

    def _get_extension(self, file_path: str) -> str | None:
        """Extract file extension from path.

        Args:
            file_path: File path string

        Returns:
            Lowercase file extension including the dot (e.g., '.exe'), or None
        """
        if not file_path:
            return None

        try:
            path_obj = Path(file_path)
            ext = path_obj.suffix
            if ext:
                return ext.lower()
        except Exception:
            # Fallback for edge cases
            if "." in file_path:
                parts = file_path.rsplit(".", 1)
                if len(parts) == 2:
                    return "." + parts[1].lower()

        return None

    def _is_binary_extension(self, extension: str) -> bool:
        """Check if extension is in the binary set.

        Args:
            extension: File extension (should include the dot and be lowercase)

        Returns:
            True if extension is binary, False otherwise
        """
        return extension.lower() in BINARY_EXTENSIONS


__all__ = ["BinaryFileEditPolicy", "BINARY_EXTENSIONS", "PATH_PARAMETER_NAMES"]
