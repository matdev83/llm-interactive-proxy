"""Stub implementation of IFailoverPlanner (temporary for Phase 2).

This stub will be replaced with the actual implementation in Phase 3.
"""

from __future__ import annotations

from src.core.interfaces.failover_planner_interface import IFailoverPlanner


class FailoverPlannerStub(IFailoverPlanner):
    """Temporary stub implementation of IFailoverPlanner.

    This stub raises NotImplementedError to ensure it's not accidentally used
    before the actual implementation is complete. It exists solely to establish
    the DI wiring during Phase 2 of the refactoring.
    """

    def get_failover_plan(
        self, model: str, backend: str | None = None
    ) -> list[tuple[str, str]]:
        """Not implemented - stub for Phase 2 DI wiring only."""
        raise NotImplementedError(
            "FailoverPlannerStub is a temporary placeholder. "
            "The actual implementation will be added in Phase 3."
        )
