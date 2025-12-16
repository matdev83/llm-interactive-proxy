import re
from pathlib import Path

file_path = Path("src/core/services/backend_service.py")
content = file_path.read_text(encoding="utf-8")

# Map of legacy method calls to new service calls
replacements = [
    (r"self\._apply_model_aliases\(", "self._model_alias_resolver.resolve("),
    # _stream_as_sse_bytes was static in legacy but service method is instance
    # BUT wait, StreamFormattingService.stream_as_sse_bytes expects an iterator.
    # The legacy wrapper was:
    # def _stream_as_sse_bytes(self, it: Any) -> Any:
    #     return self._stream_formatting_service.stream_as_sse_bytes(it)
    # So replacement is straightforward.
    (
        r"self\._stream_as_sse_bytes\(",
        "self._stream_formatting_service.stream_as_sse_bytes(",
    ),
    (
        r"self\._is_valid_completion_token\(",
        "self._stream_formatting_service.is_valid_completion_token(",
    ),
    (
        r"self\._wrap_stream_for_usage\(",
        "self._usage_tracking_wrapper.wrap_stream_for_usage(",
    ),
    (r"self\._normalize_provider_exception\(", "self._exception_normalizer.normalize("),
    (r"self\._apply_uri_parameters\(", "self._uri_parameter_applicator.apply("),
    (r"self\._apply_reasoning_config\(", "self._reasoning_config_applicator.apply("),
    # Async methods need await if they are not already awaited?
    # In wrapper: await self._planning_phase_manager.apply_if_needed(session, default_backend)
    # Call sites likely already await self._apply_planning_phase_if_needed(...)
    # Let's check call sites for await.
    (
        r"self\._apply_planning_phase_if_needed\(",
        "self._planning_phase_manager.apply_if_needed(",
    ),
    (
        r"self\._update_planning_phase_counters\(",
        "self._planning_phase_manager.update_counters(",
    ),
    (
        r"self\._count_file_writes_in_response\(",
        "self._planning_phase_manager.count_file_writes(",
    ),
    (
        r"self\._get_or_create_backend\(",
        "self._backend_lifecycle_manager.get_or_create(",
    ),
    (r"self\._shutdown_backend\(", "self._backend_lifecycle_manager.shutdown("),
    (r"self\._discard_backend\(", "self._backend_lifecycle_manager.discard("),
    (
        r"self\._restore_planning_phase_route\(",
        "# self._restore_planning_phase_route(",
    ),  # This was no-op in wrapper?
    # Actually, the wrapper was:
    # async def _restore_planning_phase_route(self, session: Any) -> None:
    #     # Managed by PlanningPhaseManager, no-op in BackendService
    #     pass
    # So we can just comment out calls or remove them.
    # But wait, logic was moved to PlanningPhaseManager methods (apply_if_needed and update_counters handle restoration internally).
    # So explicit calls from BackendService are likely redundant if they were only used inside the legacy methods which we are also replacing/removing.
    # Let's see where it is called.
    (
        r"self\._enforce_per_session_backend_limit\(",
        "# self._enforce_per_session_backend_limit(",
    ),  # No-op wrapper
]

# Note: _restore_planning_phase_route and _enforce_per_session_backend_limit calls can be effectively removed
# or commented out if they were no-ops.
# But we need to check if they are called.
# _enforce_per_session_backend_limit call inside _get_or_create_backend (legacy) is gone.
# _restore_planning_phase_route call inside _apply_planning_phase_if_needed (legacy) is gone.

# Let's apply replacements.
for old, new in replacements:
    content = re.sub(old, new, content)

# Special handling for _restore_planning_phase_route calls if any remain
# (e.g. if called from somewhere else than the legacy methods themselves)
# If we replaced the body of legacy methods in previous steps with delegation,
# and now we replace calls to legacy methods with direct delegation,
# we effectively bypass the legacy methods.

file_path.write_text(content, encoding="utf-8")
print("Replaced internal calls to legacy methods")
