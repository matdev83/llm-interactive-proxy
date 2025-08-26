import pytest


# Neutralize the heavy global autouse fixture for unit tests only
@pytest.fixture(autouse=True)
def _global_mock_backend_init():
    yield
