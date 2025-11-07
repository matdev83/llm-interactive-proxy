from __future__ import annotations

import pytest
from src.core.di.container import ServiceCollection


class _AsyncDisposable:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.mark.asyncio
async def test_scope_dispose_awaits_async_dispose() -> None:
    services = ServiceCollection()
    services.add_scoped(
        _AsyncDisposable,
        implementation_factory=lambda _provider: _AsyncDisposable(),
    )

    provider = services.build_service_provider()
    scope = provider.create_scope()

    service = scope.service_provider.get_required_service(_AsyncDisposable)
    assert service.disposed is False

    await scope.dispose()

    assert service.disposed is True
