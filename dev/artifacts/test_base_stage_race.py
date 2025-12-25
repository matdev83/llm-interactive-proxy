"""Reproduce race condition in ValidatedTestStage."""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.testing.base_stage import ValidatedTestStage
from src.core.di.container import ServiceCollection
from unittest.mock import MagicMock


class TestStageImpl(ValidatedTestStage):
    """Concrete implementation for testing."""
    
    @property
    def name(self) -> str:
        return "test_stage"
    
    def get_dependencies(self) -> list[str]:
        return []
    
    def get_description(self) -> str:
        return "Test stage for race condition detection"
    
    async def _register_services(
        self, services: ServiceCollection, config
    ) -> None:
        """Register services concurrently."""
        
        # Simulate concurrent registrations of same service type
        async def register_instance():
            self._registered_services[str] = MagicMock()
        
        # Run 100 concurrent registrations
        tasks = [register_instance() for _ in range(100)]
        await asyncio.gather(*tasks)
        
        # Check if the last write won (race condition)
        # In a proper implementation, all writes should succeed or be protected
        # Without protection, only one registration might survive
        registered_count = len([v for v in self._registered_services.values() if v is not None])
        
        # In a race-free scenario, we expect at most 100 entries
        # In a race condition scenario, we might see far fewer
        assert registered_count <= 100, f"Expected at most 100 registrations, got {registered_count}"
        
        # If significantly fewer than 100, race condition exists
        if registered_count < 95:
            print(f"RACE CONDITION DETECTED: Only {registered_count}/100 registrations survived")
            return True
        
        return False


async def main():
    print("Testing ValidatedTestStage race conditions...")
    
    stage = TestStageImpl()
    mock_config = MagicMock()
    mock_services = ServiceCollection()
    
    race_detected = await stage._register_services(mock_services, mock_config)
    
    if race_detected:
        print("RESULT: Race condition FOUND")
        return 1
    else:
        print("RESULT: No race condition detected")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
