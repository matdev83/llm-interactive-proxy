"""
File watching for Gemini OAuth credentials.

This module handles file system monitoring for credential changes including:
- Starting/stopping file observers
- Scheduling credential reloads
- Debouncing file change events
"""

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

from src.connectors.gemini_base.credentials import GeminiPersonalCredentialsFileHandler

logger = logging.getLogger(__name__)


class FileWatcherState:
    """State container for file watching operations.

    This class holds all the state needed for file watching and scheduling,
    allowing it to be managed independently of the connector class.
    """

    def __init__(self) -> None:
        """Initialize file watcher state."""
        self.file_observer: BaseObserver | None = None
        self.pending_reload_task: asyncio.Future[Any] | None = None
        self.reload_task_lock = threading.Lock()
        self.reload_scheduling_in_progress = False
        self.main_loop: asyncio.AbstractEventLoop | None = None
        self.last_reload_event_ts: float = 0.0


class FileWatcher:
    """Manages file watching for Gemini OAuth credentials.

    This class handles starting/stopping file observers, scheduling credential
    reloads, and debouncing rapid file change events. It is designed to be
    composed into connector classes.
    """

    @staticmethod
    def start_file_watching(
        credentials_path: Path | None,
        connector: Any,
        state: FileWatcherState,
    ) -> None:
        """Start watching the credentials file for changes.

        Args:
            credentials_path: Path to the credentials file to watch.
            connector: The connector instance for the file handler callback.
            state: File watcher state container.
        """
        if not credentials_path or state.file_observer:
            return

        try:
            event_handler = GeminiPersonalCredentialsFileHandler(connector)
            state.file_observer = Observer()
            # Watch the parent directory of the credentials file
            watch_dir = credentials_path.parent
            state.file_observer.schedule(event_handler, str(watch_dir), recursive=False)
            state.file_observer.start()
            logger.info(f"Started watching credentials file: {credentials_path}")
        except Exception as e:
            logger.warning(f"Failed to start file watching: {e}")

    @staticmethod
    def stop_file_watching(state: FileWatcherState) -> None:
        """Stop watching the credentials file.

        Args:
            state: File watcher state container.
        """
        observer = state.file_observer
        if observer:
            try:
                if observer.is_alive():
                    observer.stop()
                    # Only join if we're not in the observer thread to avoid
                    # "cannot join current thread" error
                    current_thread = threading.current_thread()
                    if (
                        hasattr(observer, "_thread")
                        and observer._thread != current_thread
                    ):
                        observer.join()
                state.file_observer = None
                logger.info("Stopped watching credentials file")
            except Exception as e:
                logger.warning(f"Error stopping file watcher: {e}")

    @staticmethod
    def schedule_credentials_reload(
        state: FileWatcherState,
        reload_callback: Callable[[], Coroutine[Any, Any, None]],
        stop_watching_callback: Callable[[], None],
    ) -> None:
        """Schedule an asynchronous reload when the credentials file changes.

        Args:
            state: File watcher state container.
            reload_callback: Async function to call for reloading credentials.
            stop_watching_callback: Function to call when file watching should stop.
        """
        now = time.time()
        # Drop duplicate events that happen too frequently (e.g., editor/temp-file noise)
        if now - state.last_reload_event_ts < 5.0:
            return
        state.last_reload_event_ts = now

        with state.reload_task_lock:
            if (
                state.pending_reload_task is not None
                and not state.pending_reload_task.done()
            ):
                return
            if state.reload_scheduling_in_progress:
                return
            state.reload_scheduling_in_progress = True

        async def reload_task() -> None:
            await reload_callback()

        loop = state.main_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            state.main_loop = loop

        if loop is None:
            logger.warning(
                "Cannot schedule credentials reload: no running event loop available."
            )
            with state.reload_task_lock:
                state.reload_scheduling_in_progress = False
            return

        if loop.is_closed():
            logger.debug(
                "Skipping credentials reload scheduling: event loop is closed. "
                "Stopping file watcher."
            )
            stop_watching_callback()
            state.main_loop = None
            with state.reload_task_lock:
                state.pending_reload_task = None
                state.reload_scheduling_in_progress = False
            return

        def _clear(_: asyncio.Future[Any]) -> None:
            with state.reload_task_lock:
                state.pending_reload_task = None
                state.reload_scheduling_in_progress = False

        def _assign_task(task: asyncio.Future[None]) -> None:
            task.add_done_callback(_clear)
            with state.reload_task_lock:
                state.pending_reload_task = task
                state.reload_scheduling_in_progress = False

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is loop:
            task = loop.create_task(reload_task())
            _assign_task(task)
            return

        def schedule_task() -> None:
            try:
                task = loop.create_task(reload_task())  # type: ignore[union-attr]
                _assign_task(task)
            except Exception as exc:
                logger.warning("Failed to schedule credentials reload: %s", exc)
                with state.reload_task_lock:
                    state.reload_scheduling_in_progress = False

        try:
            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.debug(
                "Event loop unavailable for credentials reload scheduling: %s",
                exc,
            )
            stop_watching_callback()
            state.main_loop = None
            with state.reload_task_lock:
                state.pending_reload_task = None
                state.reload_scheduling_in_progress = False


__all__ = [
    "FileWatcher",
    "FileWatcherState",
]
