from __future__ import annotations

from src.core.di.container import ServiceCollection
from src.core.interfaces.di import IServiceCollection, IServiceProvider

_global_services: IServiceCollection | None = None
_global_provider: IServiceProvider | None = None


def get_service_collection() -> IServiceCollection:
    """Get the global service collection, creating it if it doesn't exist.
    
    Returns:
        The global service collection
    """
    global _global_services
    if _global_services is None:
        _global_services = ServiceCollection()
    return _global_services


def build_service_provider() -> IServiceProvider:
    """Build a service provider from the global service collection.
    
    Returns:
        A new service provider
    """
    return get_service_collection().build_service_provider()


def get_service_provider() -> IServiceProvider:
    """Get the global service provider, building it if it doesn't exist.
    
    Returns:
        The global service provider
    """
    global _global_provider
    if _global_provider is None:
        _global_provider = build_service_provider()
    return _global_provider


def set_service_provider(provider: IServiceProvider) -> None:
    """Set the global service provider.
    
    Args:
        provider: The service provider to use
    """
    global _global_provider
    _global_provider = provider
