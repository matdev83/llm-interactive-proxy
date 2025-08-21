"""
Example usage of the comprehensive testing framework.

This file demonstrates how to use the safe test stages and mock factories
to prevent coroutine warnings in your test suites.
"""

import asyncio
import pytest
from unittest.mock import Mock

from testing_framework import (
    SafeTestSession,
    SafeSessionService, 
    EnforcedMockFactory,
    MockBackendTestStage,
    RealBackendTestStage,
    ValidatedTestStage,
    CoroutineWarningDetector,
    SyncOnlyService,
    AsyncOnlyService
)


# Example 1: Basic usage with MockBackendTestStage
class TestBasicFeature(MockBackendTestStage):
    """Example test class using the mock backend stage."""
    
    def setup(self):
        # Call parent setup to get validated default mocks
        super().setup()
        
        # Add custom service mocks
        self.register_service(
            'auth_service',
            EnforcedMockFactory.create_sync_mock()
        )
        
        self.register_service(
            'notification_service', 
            EnforcedMockFactory.create_async_mock()
        )
    
    def test_user_authentication(self):
        """Test that demonstrates safe session usage."""
        session = self.get_service('session_service')
        auth_service = self.get_service('auth_service')
        
        # Session service is safely synchronous
        assert session.is_authenticated
        session.set('user_role', 'admin')
        
        # Auth service mock is properly configured
        auth_service.validate_token.return_value = True
        
        # No coroutine warnings here!
        result = auth_service.validate_token('test-token')
        assert result is True


# Example 2: Advanced usage with custom test stage
class DatabaseTestStage(ValidatedTestStage):
    """Custom test stage for database-related tests."""
    
    def setup(self):
        # Register database service as async (it should be)
        self.register_service(
            'database_service',
            EnforcedMockFactory.create_async_mock(),
            force_sync=False
        )
        
        # Register cache service as sync
        self.register_service(
            'cache_service',
            EnforcedMockFactory.create_sync_mock(),
            force_sync=True
        )
        
        # Session service should always be sync
        self.register_service(
            'session_service',
            EnforcedMockFactory.create_session_mock(),
            force_sync=True
        )


class TestDatabaseOperations(DatabaseTestStage):
    """Example test using custom database test stage."""
    
    async def test_async_database_operations(self):
        """Test that demonstrates proper async/sync separation."""
        db = self.get_service('database_service')
        cache = self.get_service('cache_service')
        session = self.get_service('session_service')
        
        # Setup mock returns
        db.fetch_user.return_value = {'id': 1, 'name': 'Test User'}
        cache.get.return_value = None
        
        # Async database call (properly awaited)
        user_data = await db.fetch_user(1)
        
        # Sync cache operation
        cache.set('user:1', user_data)
        
        # Sync session operation  
        session.set('current_user', user_data['id'])
        
        assert user_data['name'] == 'Test User'
        assert session.get('current_user') == 1


# Example 3: Real backend testing with HTTPX mocking
class TestExternalAPI(RealBackendTestStage):
    """Example test using real backend stage for external API calls."""
    
    def setup(self):
        super().setup()
        
        # Add HTTP client mock for external API calls
        self.register_service(
            'external_api_client',
            EnforcedMockFactory.create_async_mock()
        )
    
    async def test_external_api_integration(self):
        """Test external API integration with safe session handling."""
        session = self.get_service('session_service')
        api_client = self.get_service('external_api_client')
        
        # Session is safely synchronous even in real backend tests
        session.set('api_token', 'test-token')
        token = session.get('api_token')
        
        # Mock external API response
        api_client.get.return_value = {'status': 'success', 'data': {}}
        
        # Make async API call
        response = await api_client.get('/api/data', headers={'Authorization': f'Bearer {token}'})
        
        assert response['status'] == 'success'


# Example 4: Using protocols for type safety
class SyncConfigService:
    """Example synchronous service."""
    
    def get_setting(self, key: str) -> str:
        return f"setting_{key}"
    
    def update_setting(self, key: str, value: str) -> None:
        pass


class AsyncNotificationService:
    """Example asynchronous service."""
    
    async def send_notification(self, user_id: int, message: str) -> bool:
        await asyncio.sleep(0.1)  # Simulate async work
        return True
    
    async def get_notification_history(self, user_id: int) -> list:
        await asyncio.sleep(0.1)  # Simulate async work
        return []


def test_protocol_enforcement():
    """Example of how protocols help enforce correct usage."""
    
    # Auto-mock determines correct mock type based on service inspection
    config_mock = EnforcedMockFactory.auto_mock(SyncConfigService)
    notification_mock = EnforcedMockFactory.auto_mock(AsyncNotificationService)
    
    # config_mock will be a regular Mock (sync)
    # notification_mock will be an AsyncMock (async)
    
    assert not hasattr(config_mock, '_mock_calls')  # Regular mock
    assert hasattr(notification_mock, '_mock_calls')  # AsyncMock has this


# Example 5: Using the coroutine warning detector
def test_coroutine_warning_detection():
    """Example of detecting potential coroutine warning issues."""
    
    class ProblematicTestClass:
        def __init__(self):
            # This would cause coroutine warnings
            self.bad_session = Mock()
            self.bad_session.get_user = asyncio.coroutine(lambda: {'id': 1})()
            
            # This is safe
            self.good_session = SafeSessionService()
    
    problematic = ProblematicTestClass()
    
    # Detect issues
    warnings = CoroutineWarningDetector.check_for_unawaited_coroutines(problematic)
    
    # Would find the unawaited coroutine in bad_session
    assert len(warnings) > 0
    assert "Unawaited coroutine found" in warnings[0]


# Example 6: Safe session service usage
def test_safe_session_service():
    """Example of using SafeSessionService directly."""
    
    # Create safe session with initial data
    session = SafeSessionService({
        'user_id': 123,
        'authenticated': True,
        'permissions': ['read', 'write']
    })
    
    # All operations are synchronous
    assert session.get('user_id') == 123
    assert session.is_authenticated
    
    # Modify session data
    session.set('last_activity', '2023-01-01T10:00:00Z')
    session.set('theme', 'dark')
    
    # Get with default
    theme = session.get('theme', 'light')
    assert theme == 'dark'
    
    # Clear specific data or all data
    session.clear()
    assert session.get('user_id') is None


if __name__ == "__main__":
    # Run examples
    print("Running testing framework examples...")
    
    # Example 1: Basic mock setup
    test_stage = MockBackendTestStage()
    test_stage.setup()
    
    session = test_stage.get_service('session_service')
    print(f"✓ Safe session created: {type(session).__name__}")
    
    # Example 2: Safe session usage
    safe_session = SafeSessionService({'test': 'data'})
    safe_session.set('key', 'value')
    print(f"✓ Session data: {safe_session.get('key')}")
    
    # Example 3: Mock factory usage
    sync_mock = EnforcedMockFactory.create_sync_mock()
    async_mock = EnforcedMockFactory.create_async_mock()
    print(f"✓ Created sync mock: {type(sync_mock).__name__}")
    print(f"✓ Created async mock: {type(async_mock).__name__}")
    
    print("All examples completed successfully! 🎉")
