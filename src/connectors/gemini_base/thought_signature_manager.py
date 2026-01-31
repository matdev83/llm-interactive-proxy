"""
Thought signature management for Gemini Code Assist.

This module handles server-side storage and injection of thought_signatures
for clients (like Droid) that don't preserve extra_content.
"""

import contextlib
import hashlib
import json
import logging
import os
import pathlib
import threading
import time
from collections import OrderedDict
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL

logger = logging.getLogger(__name__)


class ThoughtSignatureManager:
    """Manages thought signatures for tool calls.

    Droid and similar clients don't preserve extra_content, so we store
    mapping of tool_call_id -> thought_signature server-side and
    inject it when processing subsequent requests.

    Key format: "session_id:tool_call_id" -> thought_signature
    """

    _NAMESPACE_SEPARATOR = "|"
    _PERSIST_NAMESPACE_PREFIX = "thought_signatures_ns_"

    def __init__(self, max_cache_size: int = 10000, ttl_seconds: int = 86400) -> None:
        # Allow runtime overrides for long-running interactive sessions.
        # Environment variables are read here (not at import time) so tests can
        # override them safely.
        ttl_override = os.environ.get("LLM_PROXY_THOUGHT_SIGNATURE_TTL_SECONDS")
        if ttl_override:
            with contextlib.suppress(Exception):
                ttl_seconds = int(ttl_override)

        self._max_cache_size = max_cache_size
        self._ttl_seconds = ttl_seconds

        # Optional persistence for restart-safe interactive sessions.
        # Enabled by default outside pytest, writing under var/cache.
        # Can be overridden/disabled with env vars.
        self._persist_path: pathlib.Path | None = None
        self._persist_dir: pathlib.Path | None = None
        self._load_legacy_persist_file = True
        self._persist_min_interval_seconds = 5.0
        self._persist_last_write = 0.0
        self._persist_dirty = False
        self._persist_namespaced = False
        self._persist_namespaced_last_write: dict[str, float] = {}
        self._persist_namespaced_dirty: set[str] = set()
        self._configure_persistence()

        # OrderedDict for LRU eviction with timestamps.
        # NOTE: Some tests and legacy paths may still assign raw strings as values.
        # Treat those as "timestamp unknown" and normalize on read.
        self._cache: OrderedDict[str, tuple[str, float] | str] = OrderedDict()
        # Secondary index by tool_call_id to survive session-id changes
        self._by_tool_call: dict[str, str] = {}
        # Lock to protect cache access
        self._lock = threading.Lock()

        # Load persisted signatures after initializing state.
        self._load_persisted_signatures()

    def _is_namespaced_session_id(self, session_id: str) -> bool:
        """Return True if the session id includes a signature namespace."""
        return bool(session_id) and self._NAMESPACE_SEPARATOR in session_id

    def _split_session_id(self, session_id: str) -> tuple[str, str | None]:
        """Split a session id into base and namespace parts."""
        if not session_id:
            return "", None
        if self._NAMESPACE_SEPARATOR in session_id:
            base, namespace = session_id.split(self._NAMESPACE_SEPARATOR, 1)
            return base, namespace or None
        return session_id, None

    def _is_namespaced_cache_key(self, cache_key: str) -> bool:
        """Return True if a cache key belongs to a namespaced session."""
        if cache_key.startswith("anon:"):
            return False
        session_part = cache_key.split(":", 1)[0]
        return self._is_namespaced_session_id(session_part)

    def _extract_namespace_from_session_id(self, session_id: str) -> str | None:
        if not session_id or self._NAMESPACE_SEPARATOR not in session_id:
            return None
        base, namespace = session_id.rsplit(self._NAMESPACE_SEPARATOR, 1)
        if not base or not namespace:
            return None
        return namespace

    def _extract_namespace_from_cache_key(self, cache_key: str) -> str | None:
        if cache_key.startswith("anon:"):
            return None
        session_part = cache_key.split(":", 1)[0]
        return self._extract_namespace_from_session_id(session_part)

    def _configure_persistence(self) -> None:
        """Configure optional on-disk persistence.

        Persistence is enabled by default outside pytest to avoid losing
        thought signatures across process restarts.
        """

        # Explicit disable always wins.
        if os.environ.get("LLM_PROXY_THOUGHT_SIGNATURE_PERSIST", "").strip() in {
            "0",
            "false",
            "False",
            "no",
            "NO",
        }:
            self._persist_path = None
            self._persist_dir = None
            self._load_legacy_persist_file = False
            self._persist_namespaced = False
            return

        # During pytest runs, do not persist by default to avoid polluting the repo.
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
            "LLM_PROXY_THOUGHT_SIGNATURE_PERSIST_PATH"
        ):
            self._persist_path = None
            self._persist_dir = None
            self._load_legacy_persist_file = False
            self._persist_namespaced = False
            return

        raw_path = os.environ.get("LLM_PROXY_THOUGHT_SIGNATURE_PERSIST_PATH")
        if raw_path:
            # If explicitly configured, do not implicitly load/write the legacy
            # single-file store under var/cache.
            self._load_legacy_persist_file = False

            configured = pathlib.Path(raw_path)
            if configured.suffix.lower() == ".json":
                self._persist_path = configured
                self._persist_dir = configured.parent
            else:
                # Treat as directory.
                self._persist_dir = configured
                self._persist_path = (
                    configured / f"thought_signatures_{os.getpid()}.json"
                )
            self._configure_namespaced_persistence()
            return

        # Default persistence location (per-process shard files).
        self._persist_dir = pathlib.Path("var") / "cache" / "thought_signatures"
        self._persist_path = (
            self._persist_dir / f"thought_signatures_{os.getpid()}.json"
        )
        self._configure_namespaced_persistence()

    def _configure_namespaced_persistence(self) -> None:
        if self._persist_dir is None:
            self._persist_namespaced = False
            return

        setting = os.environ.get("LLM_PROXY_THOUGHT_SIGNATURE_PERSIST_NAMESPACED")
        if setting is None:
            self._persist_namespaced = True
            return

        self._persist_namespaced = setting.strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

    def _iter_persist_files(self) -> list[pathlib.Path]:
        """Return all persistence files to load for this process."""

        files: list[pathlib.Path] = []

        if self._load_legacy_persist_file:
            legacy = pathlib.Path("var") / "cache" / "thought_signatures.json"
            with contextlib.suppress(Exception):
                if legacy.exists() and legacy.is_file():
                    files.append(legacy)

        persist_dir = self._persist_dir
        if persist_dir is not None:
            with contextlib.suppress(Exception):
                if persist_dir.exists() and persist_dir.is_dir():
                    files.extend(sorted(persist_dir.glob("thought_signatures_*.json")))

        persist_path = self._persist_path
        if persist_path is not None:
            with contextlib.suppress(Exception):
                if (
                    persist_path.exists()
                    and persist_path.is_file()
                    and persist_path not in files
                ):
                    files.append(persist_path)

        return files

    def _load_persisted_signatures(self) -> None:
        persist_files = self._iter_persist_files()
        if not persist_files:
            return

        current_time = time.time()
        merged_anon: dict[str, tuple[str, float]] = {}
        merged_namespaced: dict[str, tuple[str, float]] = {}
        loaded_files = 0

        for path in persist_files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.debug(
                    "Failed to load persisted thought signatures from %s",
                    str(path),
                    exc_info=True,
                )
                continue

            entries: dict[str, Any] = {}
            namespace_hint: str | None = None
            if isinstance(data, dict):
                if isinstance(data.get("entries"), dict):
                    entries = data["entries"]
                    namespace_raw = data.get("namespace")
                    if isinstance(namespace_raw, str) and namespace_raw.strip():
                        namespace_hint = namespace_raw.strip()
                else:
                    # Legacy format: {tool_call_id: signature}
                    entries = data

            if not entries:
                continue

            loaded_files += 1

            for key, entry in entries.items():
                if not isinstance(key, str) or not key:
                    continue

                if isinstance(entry, dict):
                    sig = entry.get("sig")
                    ts = entry.get("ts")
                else:
                    sig = entry
                    ts = None

                if not isinstance(sig, str) or not sig:
                    continue

                timestamp = float(ts) if isinstance(ts, int | float) else current_time
                if current_time - timestamp > self._ttl_seconds:
                    continue

                if key.startswith("anon:"):
                    tc_id = key.split(":", 1)[1]
                    existing = merged_anon.get(tc_id)
                    if existing is None or timestamp > existing[1]:
                        merged_anon[tc_id] = (sig, timestamp)
                    continue

                if self._is_namespaced_cache_key(key):
                    if not self._persist_namespaced:
                        continue
                    namespace = self._extract_namespace_from_cache_key(key)
                    if not namespace:
                        continue
                    if namespace_hint and namespace != namespace_hint:
                        continue
                    existing = merged_namespaced.get(key)
                    if existing is None or timestamp > existing[1]:
                        merged_namespaced[key] = (sig, timestamp)
                    continue

                tc_id = key.split(":", 1)[1] if ":" in key else key
                existing = merged_anon.get(tc_id)
                if existing is None or timestamp > existing[1]:
                    merged_anon[tc_id] = (sig, timestamp)

        if not merged_anon and not merged_namespaced:
            return

        loaded_anon = [(tc_id, sig, ts) for tc_id, (sig, ts) in merged_anon.items()]
        loaded_anon.sort(key=lambda x: x[2])
        loaded_namespaced = [
            (cache_key, sig, ts) for cache_key, (sig, ts) in merged_namespaced.items()
        ]
        loaded_namespaced.sort(key=lambda x: x[2])

        with self._lock:
            for tc_id, sig, timestamp in loaded_anon[-self._max_cache_size :]:
                key = f"anon:{tc_id}"
                self._cache[key] = (sig, timestamp)
                self._cache.move_to_end(key)
                self._by_tool_call[tc_id] = sig

            for cache_key, sig, timestamp in loaded_namespaced[-self._max_cache_size :]:
                self._cache[cache_key] = (sig, timestamp)
                self._cache.move_to_end(cache_key)

            self._enforce_size_limit_locked()

        if logger.isEnabledFor(logging.INFO):
            namespaces: set[str] = set()
            for cache_key, _, _ in loaded_namespaced:
                namespace = self._extract_namespace_from_cache_key(cache_key)
                if namespace:
                    namespaces.add(namespace)
            logger.info(
                "Loaded %d persisted thought_signature(s) from %d file(s) (anon=%d namespaced=%d namespaces=%d)",
                len(loaded_anon) + len(loaded_namespaced),
                loaded_files,
                len(loaded_anon),
                len(loaded_namespaced),
                len(namespaces),
            )

    def _namespace_cache_filename(self, namespace: str) -> str:
        digest = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
        return f"{self._PERSIST_NAMESPACE_PREFIX}{digest}.json"

    def _get_namespaced_persist_path(self, namespace: str) -> pathlib.Path | None:
        persist_dir = self._persist_dir
        if persist_dir is None:
            return None
        return persist_dir / self._namespace_cache_filename(namespace)

    def _mark_namespace_dirty(self, session_id: str) -> None:
        if not self._persist_namespaced:
            return
        namespace = self._extract_namespace_from_session_id(session_id)
        if not namespace:
            return
        self._persist_namespaced_dirty.add(namespace)

    def _maybe_persist_locked(self, current_time: float | None = None) -> None:
        """Persist anonymous thought signatures to disk (must hold lock)."""
        if current_time is None:
            current_time = time.time()

        path = self._persist_path
        if path is None:
            self._maybe_persist_namespaced_locked(current_time)
            return

        if not self._persist_dirty:
            self._maybe_persist_namespaced_locked(current_time)
            return

        if (
            current_time - self._persist_last_write
        ) < self._persist_min_interval_seconds:
            self._maybe_persist_namespaced_locked(current_time)
            return

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.debug("Failed to create persistence directory", exc_info=True)
            return

        # Serialize only anonymous entries, which are session-id independent.
        entries_out: dict[str, dict[str, Any]] = {}
        for key, entry in self._cache.items():
            if not key.startswith("anon:"):
                continue
            tc_id = key.split(":", 1)[1]
            if isinstance(entry, tuple) and len(entry) == 2:
                sig, ts = entry
            else:
                sig, ts = str(entry), current_time
            if not sig:
                continue
            if current_time - float(ts) > self._ttl_seconds:
                continue
            entries_out[tc_id] = {"sig": sig, "ts": float(ts)}

        payload = {
            "version": 1,
            "generated_at": float(current_time),
            "ttl_seconds": int(self._ttl_seconds),
            "entries": entries_out,
        }

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp_path.write_text(
                json.dumps(payload, separators=(",", ":")), encoding="utf-8"
            )
            os.replace(str(tmp_path), str(path))
            self._persist_last_write = float(current_time)
            self._persist_dirty = False
        except Exception:
            logger.debug("Failed to persist thought signatures", exc_info=True)
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)

        self._maybe_persist_namespaced_locked(current_time)

    def _maybe_persist_namespaced_locked(self, current_time: float) -> None:
        if not self._persist_namespaced or not self._persist_namespaced_dirty:
            return

        for namespace in list(self._persist_namespaced_dirty):
            last_write = self._persist_namespaced_last_write.get(namespace, 0.0)
            if (current_time - last_write) < self._persist_min_interval_seconds:
                continue

            path = self._get_namespaced_persist_path(namespace)
            if path is None:
                continue

            entries_out: dict[str, dict[str, Any]] = {}
            for key, entry in self._cache.items():
                if not self._is_namespaced_cache_key(key):
                    continue
                if self._extract_namespace_from_cache_key(key) != namespace:
                    continue

                if isinstance(entry, tuple) and len(entry) == 2:
                    sig, ts = entry
                else:
                    sig, ts = str(entry), current_time
                if not sig:
                    continue
                if current_time - float(ts) > self._ttl_seconds:
                    continue
                entries_out[key] = {"sig": sig, "ts": float(ts)}

            payload = {
                "version": 2,
                "generated_at": float(current_time),
                "ttl_seconds": int(self._ttl_seconds),
                "namespace": namespace,
                "entries": entries_out,
            }

            tmp_path = path.with_suffix(path.suffix + ".tmp")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path.write_text(
                    json.dumps(payload, separators=(",", ":")), encoding="utf-8"
                )
                os.replace(str(tmp_path), str(path))
                self._persist_namespaced_last_write[namespace] = float(current_time)
                self._persist_namespaced_dirty.discard(namespace)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Persisted %d namespaced thought_signature(s) for namespace %s",
                        len(entries_out),
                        namespace,
                    )
            except Exception:
                logger.debug(
                    "Failed to persist thought signatures for namespace %s",
                    namespace,
                    exc_info=True,
                )
                with contextlib.suppress(Exception):
                    tmp_path.unlink(missing_ok=True)

    @property
    def cache(self) -> dict[str, str]:
        """Access to cache for backward compatibility."""
        with self._lock:
            # Convert from (sig, timestamp) tuples back to just signatures.
            normalized: dict[str, str] = {}
            for key, entry in self._cache.items():
                if isinstance(entry, tuple) and len(entry) == 2:
                    sig = entry[0]
                else:
                    sig = str(entry)
                normalized[key] = sig
            return normalized

    @cache.setter
    def cache(self, value: dict[str, str]) -> None:
        """Set cache for backward compatibility (stores with current timestamp)."""
        with self._lock:
            # Convert from just signatures to (sig, timestamp) tuples
            current_time = time.time()
            self._cache = OrderedDict(
                (key, (sig, current_time)) for key, sig in value.items()
            )

    def update(self, updates: dict[str, str]) -> None:
        """Update cache with new values (for backward compatibility)."""
        with self._lock:
            current_time = time.time()
            for key, sig in updates.items():
                self._cache[key] = (sig, current_time)
                self._cache.move_to_end(key)

    def inject_signatures(self, canonical_request: Any, session_id: str) -> None:
        """Inject stored thought_signatures into tool_calls that are missing them.

        Args:
            canonical_request: The canonical request with messages to process
            session_id: The session ID for cache key lookup
        """
        if not hasattr(canonical_request, "messages"):
            return

        for message in canonical_request.messages:
            if getattr(message, "role", None) != "assistant":
                continue
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                continue

            for tc in tool_calls:
                self._inject_signature_for_tool_call(tc, session_id)

    def _inject_signature_for_tool_call(self, tc: Any, session_id: str) -> None:
        """Inject signature for a single tool call if missing."""
        # Get tool call ID
        tc_id = None
        if isinstance(tc, dict):
            tc_id = tc.get("id")
        elif hasattr(tc, "id"):
            tc_id = tc.id

        if not tc_id:
            return

        # Check if already has thought_signature
        extra_content = None
        if isinstance(tc, dict):
            extra_content = tc.get("extra_content")
        elif hasattr(tc, "extra_content"):
            extra_content = tc.extra_content

        if extra_content:
            google_extra = (
                extra_content.get("google", {})
                if isinstance(extra_content, dict)
                else {}
            )
            existing_sig = google_extra.get("thought_signature")
            if isinstance(existing_sig, str) and existing_sig:
                if self._is_namespaced_session_id(session_id):
                    cached_sig = self._lookup_signature(tc_id, session_id)
                    if cached_sig and cached_sig == existing_sig:
                        self._store_or_touch_signature(tc_id, session_id, existing_sig)
                    return

                # Already has a signature. Refresh the cache entry so long-running
                # sessions don't lose signatures due to TTL cleanup.
                self._store_or_touch_signature(tc_id, session_id, existing_sig)
                return

        # Look up in cache with TTL check
        sig = self._lookup_signature(tc_id, session_id)
        if not sig:
            # No cached signature available; avoid injecting placeholders that
            # can trigger "corrupted thought signature" errors.
            return

        # Inject the signature
        if isinstance(tc, dict):
            tc["extra_content"] = {"google": {"thought_signature": sig}}
        elif hasattr(tc, "extra_content"):
            tc.extra_content = {"google": {"thought_signature": sig}}

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "Injected thought_signature for tool_call_id=%s (session=%s)",
                tc_id,
                session_id[:8] if session_id else "none",
            )

    def _store_or_touch_signature(self, tc_id: str, session_id: str, sig: str) -> None:
        """Upsert a signature and refresh its timestamp.

        This is used both when we observe an existing signature in the request
        and when we inject one from cache.
        """
        if not tc_id or not sig:
            return

        current_time = time.time()
        with self._lock:
            use_anonymous_cache = session_id and not self._is_namespaced_session_id(
                session_id
            )
            if session_id:
                cache_key = f"{session_id}:{tc_id}"
                self._cache[cache_key] = (sig, current_time)
                self._cache.move_to_end(cache_key)
                if self._is_namespaced_session_id(session_id):
                    self._mark_namespace_dirty(session_id)

            if use_anonymous_cache:
                # Always keep an anonymous copy so signatures survive session-id changes
                # and can optionally be persisted across restarts.
                anon_key = f"anon:{tc_id}"
                self._cache[anon_key] = (sig, current_time)
                self._cache.move_to_end(anon_key)
                self._by_tool_call[tc_id] = sig
                self._persist_dirty = True

            self._enforce_size_limit_locked()
            if use_anonymous_cache:
                self._maybe_persist_locked(current_time)
            elif session_id and self._is_namespaced_session_id(session_id):
                self._maybe_persist_namespaced_locked(current_time)

    def _lookup_signature(self, tc_id: str, session_id: str) -> str | None:
        """Look up a signature by tool_call_id and session_id.

        Returns:
            The signature if found and not expired, None otherwise.
        """
        current_time = time.time()
        namespaced = self._is_namespaced_session_id(session_id)
        with self._lock:
            cache_key = f"{session_id}:{tc_id}"

            sig = self._get_cache_entry_locked(cache_key, current_time)

            if not sig and namespaced:
                base_session_id, _ = self._split_session_id(session_id)
                if base_session_id and base_session_id != session_id:
                    base_key = f"{base_session_id}:{tc_id}"
                    sig = self._get_cache_entry_locked(base_key, current_time)
                    if not sig:
                        sig = self._lookup_namespaced_fallback_locked(
                            base_session_id, tc_id, current_time
                        )
                    if sig:
                        self._cache[cache_key] = (sig, current_time)
                        self._cache.move_to_end(cache_key)
                        self._enforce_size_limit_locked()

            if not sig and not namespaced:
                # Try anonymous cache if session_id was missing at store time
                anon_key = f"anon:{tc_id}"
                sig = self._get_cache_entry_locked(anon_key, current_time)
                if sig:
                    self._persist_dirty = True
                    self._maybe_persist_locked(current_time)

            if not sig and not namespaced:
                # Fallback to global index by tool_call_id (handles session re-keying)
                sig = self._by_tool_call.get(tc_id)

                # If we recovered via fallback, store under the current session
                # so subsequent lookups are fast and get TTL refresh.
                if sig and session_id:
                    self._cache[cache_key] = (sig, current_time)
                    self._cache.move_to_end(cache_key)
                    self._enforce_size_limit_locked()

                if sig:
                    anon_key = f"anon:{tc_id}"
                    self._cache[anon_key] = (sig, current_time)
                    self._cache.move_to_end(anon_key)
                    self._persist_dirty = True
                    self._maybe_persist_locked(current_time)

            return sig

    def _get_cache_entry_locked(
        self, cache_key: str, current_time: float
    ) -> str | None:
        """Return cached signature for a key (lock must be held)."""
        cache_entry = self._cache.get(cache_key)
        if not cache_entry:
            return None

        if isinstance(cache_entry, tuple) and len(cache_entry) == 2:
            cached_sig, timestamp = cache_entry
        else:
            cached_sig, timestamp = str(cache_entry), current_time
            # Normalize legacy entry to include a timestamp
            self._cache[cache_key] = (cached_sig, timestamp)

        if current_time - timestamp > self._ttl_seconds:
            del self._cache[cache_key]
            return None

        # Sliding TTL: refresh timestamp on use.
        self._cache[cache_key] = (cached_sig, current_time)
        self._cache.move_to_end(cache_key)
        return cached_sig

    def _lookup_namespaced_fallback_locked(
        self, base_session_id: str, tc_id: str, current_time: float
    ) -> str | None:
        """Search for a signature under any namespace for the same base session."""
        if not base_session_id or not tc_id:
            return None

        prefix = f"{base_session_id}{self._NAMESPACE_SEPARATOR}"
        suffix = f":{tc_id}"
        best_sig: str | None = None
        best_ts: float | None = None
        best_key: str | None = None

        for cache_key, entry in self._cache.items():
            if not cache_key.startswith(prefix) or not cache_key.endswith(suffix):
                continue
            if isinstance(entry, tuple) and len(entry) == 2:
                cached_sig, timestamp = entry
            else:
                cached_sig, timestamp = str(entry), current_time
                self._cache[cache_key] = (cached_sig, timestamp)
            if current_time - timestamp > self._ttl_seconds:
                continue
            if best_ts is None or timestamp > best_ts:
                best_sig = cached_sig
                best_ts = timestamp
                best_key = cache_key

        if best_sig and best_key:
            self._cache[best_key] = (best_sig, current_time)
            self._cache.move_to_end(best_key)
            return best_sig

        return None

    def store_signatures_from_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        session_id: str | None,
    ) -> None:
        """Store thought_signatures from streaming tool call responses.

        Args:
            tool_calls: List of tool call dictionaries with potential signatures
            session_id: The session ID for cache key construction
        """
        with self._lock:
            anonymous_key = None if session_id else "anon"
            use_anonymous_cache = (
                session_id is None or not self._is_namespaced_session_id(session_id)
            )
            current_time = time.time()
            namespaced_dirty = False

            # Clean expired entries first
            self._clean_expired_entries_locked(current_time)

            for tc in tool_calls:
                tc_id = tc.get("id", "")
                extra: Any = tc.get("extra_content")
                if not isinstance(extra, dict):
                    continue

                google_extra = extra.get("google", {})
                sig = google_extra.get("thought_signature")
                if not sig or not tc_id:
                    continue

                cache_key = (
                    f"{session_id}:{tc_id}"
                    if session_id
                    else f"{anonymous_key}:{tc_id}"
                )
                if cache_key:
                    # Store with timestamp for TTL
                    self._cache[cache_key] = (sig, current_time)
                    if use_anonymous_cache:
                        self._by_tool_call[tc_id] = sig
                    elif session_id and self._is_namespaced_session_id(session_id):
                        namespaced_dirty = True

                    # Always store an anonymous copy for restart/session-id safety.
                    if use_anonymous_cache:
                        anon_key = f"anon:{tc_id}"
                        self._cache[anon_key] = (sig, current_time)
                        self._cache.move_to_end(anon_key)

                    # Move to end for LRU
                    self._cache.move_to_end(cache_key)

                    self._enforce_size_limit_locked()

                    if use_anonymous_cache:
                        self._persist_dirty = True

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Stored thought_signature for tool_call_id=%s (key=%s, cache_size=%d)",
                            tc_id,
                            cache_key[:16],
                            len(self._cache),
                        )

            if use_anonymous_cache:
                self._maybe_persist_locked(current_time)
            elif namespaced_dirty and session_id:
                self._mark_namespace_dirty(session_id)
                self._maybe_persist_namespaced_locked(current_time)

    def log_signature_state(
        self,
        canonical_request: Any,
        session_id: str,
        effective_model: str,
    ) -> None:
        """Log presence/absence of thought signatures on assistant tool calls."""
        if not logger.isEnabledFor(logging.INFO):
            return

        try:
            tool_call_summaries: list[tuple[str, bool, str]] = []
            for message in getattr(canonical_request, "messages", []) or []:
                if getattr(message, "role", None) != "assistant":
                    continue
                tool_calls = getattr(message, "tool_calls", None) or []
                for tc in tool_calls:
                    tc_id = None
                    if isinstance(tc, dict):
                        tc_id = tc.get("id")
                        extra_content = tc.get("extra_content")
                    else:
                        tc_id = getattr(tc, "id", None)
                        extra_content = getattr(tc, "extra_content", None)

                    sig = None
                    if isinstance(extra_content, dict):
                        google_extra = extra_content.get("google")
                        if isinstance(google_extra, dict):
                            sig = google_extra.get("thought_signature")
                        if not sig:
                            sig = extra_content.get("thought_signature")

                    tool_call_summaries.append(
                        (
                            str(tc_id) if tc_id else "unknown",
                            bool(sig),
                            str(sig)[:12] if sig else "none",
                        )
                    )

            logger.info(
                "Thought signature state: session=%s model=%s tool_calls=%d details=%s",
                session_id[:8] if session_id else "none",
                effective_model,
                len(tool_call_summaries),
                tool_call_summaries[:5],
            )
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            IndexError,
            UnicodeDecodeError,
            UnicodeEncodeError,
        ):
            # Expected exceptions during debug logging:
            # - AttributeError: message/tool_calls/sig attributes missing
            # - KeyError: dict.get() (though we use safe .get())
            # - TypeError: str() conversion or slice failures
            # - ValueError: string slice indices invalid
            # - IndexError: string slice out of bounds
            # - UnicodeError: encoding/decoding failures
            logger.debug("Failed to log tool call signature state", exc_info=True)

    def _clean_expired_entries(self, current_time: float | None = None) -> int:
        """Remove expired entries from cache.

        Args:
            current_time: Current timestamp (defaults to time.time())

        Returns:
            Number of entries removed
        """
        with self._lock:
            return self._clean_expired_entries_locked(current_time)

    def _clean_expired_entries_locked(self, current_time: float | None = None) -> int:
        """Remove expired entries from cache (must hold lock).

        Args:
            current_time: Current timestamp (defaults to time.time())

        Returns:
            Number of entries removed
        """
        if current_time is None:
            current_time = time.time()

        expired_keys: list[str] = []
        for key, entry in list(self._cache.items()):
            if isinstance(entry, tuple) and len(entry) == 2:
                _, timestamp = entry
            else:
                # Legacy entries without timestamps: keep them (fail-open).
                continue
            if current_time - timestamp > self._ttl_seconds:
                expired_keys.append(key)

        # Remove all expired keys first
        for key in expired_keys:
            del self._cache[key]

        self._rebuild_by_tool_call_locked()

        return len(expired_keys)

    def clear_all_anonymous(self) -> int:
        """Clear all anonymous cached signatures (session_id was None).

        Returns:
            Number of entries cleared from cache
        """
        with self._lock:
            keys_to_remove = [key for key in self._cache if key.startswith("anon:")]

            # Remove all keys first
            for key in keys_to_remove:
                self._cache.pop(key, None)

            self._rebuild_by_tool_call_locked()

            if keys_to_remove and logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Cleared %d anonymous thought_signature(s)",
                    len(keys_to_remove),
                )

            return len(keys_to_remove)

    def clear_session_cache(self, session_id: str) -> int:
        """Clear all cached signatures for a session.

        Used when switching backends mid-session to prevent incompatible
        thought signatures from being injected into requests to be new backend.

        Args:
            session_id: The session ID prefix to match and clear

        Returns:
            Number of entries cleared from cache
        """
        if not session_id:
            return 0

        with self._lock:
            prefix = f"{session_id}:"
            namespaced_prefix = f"{session_id}{self._NAMESPACE_SEPARATOR}"
            keys_to_remove: list[str] = [
                key
                for key in self._cache
                if key.startswith((prefix, namespaced_prefix))
            ]
            namespaces_to_dirty: set[str] = set()

            # Also collect tool_call_ids to remove from secondary index
            tool_call_ids_to_remove: list[str] = []
            for key in keys_to_remove:
                # Key format is "session_id:tool_call_id"
                parts = key.split(":", 1)
                if len(parts) == 2:
                    tool_call_ids_to_remove.append(parts[1])
                namespace = self._extract_namespace_from_cache_key(key)
                if namespace:
                    namespaces_to_dirty.add(namespace)

            # Remove from primary cache and anonymous cache
            for key in keys_to_remove:
                del self._cache[key]

            for tc_id in tool_call_ids_to_remove:
                self._cache.pop(f"anon:{tc_id}", None)
                self._by_tool_call.pop(tc_id, None)

            if self._persist_namespaced and namespaces_to_dirty:
                self._persist_namespaced_dirty.update(namespaces_to_dirty)
                self._maybe_persist_namespaced_locked(time.time())

            if keys_to_remove and logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Cleared %d thought_signature(s) for session %s",
                    len(keys_to_remove),
                    session_id[:8] if session_id else "none",
                )

            return len(keys_to_remove)

    def _enforce_size_limit_locked(self) -> None:
        """Enforce cache size limit (must hold lock)."""
        if self._max_cache_size <= 0:
            return

        if len(self._cache) <= self._max_cache_size:
            return

        # Evict LRU entries until within limit.
        while len(self._cache) > self._max_cache_size:
            with contextlib.suppress(Exception):
                self._cache.popitem(last=False)

        self._rebuild_by_tool_call_locked()

    def _rebuild_by_tool_call_locked(self) -> None:
        """Rebuild secondary index from cache (must hold lock)."""
        new_by_tool_call: dict[str, str] = {}
        for cache_key, entry in self._cache.items():
            if self._is_namespaced_cache_key(cache_key):
                continue
            if isinstance(entry, tuple) and len(entry) == 2:
                sig = entry[0]
            else:
                sig = str(entry)

            tc_id = cache_key.split(":", 1)[1] if ":" in cache_key else cache_key
            new_by_tool_call[tc_id] = sig
        self._by_tool_call = new_by_tool_call

    def get_cached_signature(self, session_id: str, tool_call_id: str) -> str | None:
        """Return cached signature for session and tool call id."""
        if not session_id or not tool_call_id:
            return None
        return self._lookup_signature(tool_call_id, session_id)


# Global instance for backward compatibility with class-level cache
_global_thought_signature_manager = ThoughtSignatureManager()


def get_global_thought_signature_manager() -> ThoughtSignatureManager:
    """Get the global thought signature manager instance."""
    return _global_thought_signature_manager
