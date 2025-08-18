import asyncio
import httpx
from src.core.config.app_config import AppConfig
from src.core.services.backend_service import BackendService
from src.core.services.backend_factory_service import BackendFactory
from src.core.services.rate_limiter_service import RateLimiter
from src.core.interfaces.configuration_interface import IConfig
from src.core.services.backend_registry_service import backend_registry


async def test_backend_service():
    # Create a mock config
    config = AppConfig.from_env()
    
    # Create mock services
    httpx_client = httpx.AsyncClient()
    factory = BackendFactory(httpx_client, backend_registry)
    rate_limiter = RateLimiter()
    
    # Create backend service
    backend_service = BackendService(
        factory,
        rate_limiter,
        config,
        backend_configs=config.backends,
    )
    
    # Test _get_or_create_backend method
    try:
        backend = await backend_service._get_or_create_backend("openai")
        print("Backend service fix is working correctly")
        print(f"Backend type: {type(backend)}")
    except Exception as e:
        print(f"Backend service fix is not working correctly: {e}")


if __name__ == "__main__":
    asyncio.run(test_backend_service())