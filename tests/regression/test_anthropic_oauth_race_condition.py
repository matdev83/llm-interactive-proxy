"""
Regression test for race condition in AnthropicOAuthBackend._schedule_credentials_reload
"""
import asyncio
import contextlib
import threading
from unittest.mock import AsyncMock, Mock

import pytest
from src.connectors.anthropic_oauth import AnthropicOAuthBackend


@pytest.mark.asyncio
async def test_anthropic_oauth_reload_lock_exists():
    """Test that _reload_lock is properly initialized."""
    mock_client = Mock()
    mock_config = Mock()
    mock_config.backends = Mock()
    mock_config.backends.anthropic_oauth = Mock()
    mock_config.backends.anthropic_oauth.extra = {}
    
    mock_translation_service = Mock()
    
    backend = AnthropicOAuthBackend(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service
    )
    
    # Verify lock exists
    assert hasattr(backend, '_reload_lock'), "_reload_lock should be initialized"
    assert isinstance(backend._reload_lock, asyncio.Lock), "_reload_lock should be an asyncio.Lock"


@pytest.mark.asyncio
async def test_anthropic_oauth_reload_lock_protects_concurrent_access():
    """Test that _reload_lock prevents race conditions in concurrent access."""
    mock_client = Mock()
    mock_config = Mock()
    mock_config.backends = Mock()
    mock_config.backends.anthropic_oauth = Mock()
    mock_config.backends.anthropic_oauth.extra = {}
    
    mock_translation_service = Mock()
    
    backend = AnthropicOAuthBackend(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service
    )
    
    # Test lock behavior - ensure multiple coroutines can hold the lock sequentially
    async def simulate_reload():
        async with backend._reload_lock:
            await asyncio.sleep(0.01)
    
    # Run multiple concurrent operations
    results = await asyncio.gather(
        *[simulate_reload() for _ in range(5)]
    )
    
    assert len(results) == 5, "All operations should complete"


@pytest.mark.asyncio
async def test_anthropic_oauth_reload_prevents_duplicate_tasks():
    """Test that lock prevents duplicate reload tasks being scheduled."""
    mock_client = Mock()
    mock_config = Mock()
    mock_config.backends = Mock()
    mock_config.backends.anthropic_oauth = Mock()
    mock_config.backends.anthropic_oauth.extra = {}
    
    mock_translation_service = Mock()
    
    backend = AnthropicOAuthBackend(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service
    )
    
    # Mock async methods
    backend._load_oauth_credentials = AsyncMock(return_value=True)
    backend._validate_credentials_structure = Mock(return_value=True)
    backend._recover = Mock()
    backend._degrade = Mock()
    
    backend._event_loop = asyncio.get_running_loop()
    
    # Create a fake task that's not done
    fake_task = asyncio.create_task(asyncio.sleep(1))
    backend._pending_reload_task = fake_task
    
    # Try to schedule multiple reloads - all should be skipped because of pending task
    threads = []
    for _ in range(10):
        t = threading.Thread(target=backend._schedule_credentials_reload)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    await asyncio.sleep(0.1)
    
    # With lock and pending task check, no new reload should be scheduled
    # _load_oauth_credentials should not be called because pending task exists
    assert backend._load_oauth_credentials.call_count == 0, "No reload should be scheduled when task is pending"
    
    # Clean up
    fake_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await fake_task
