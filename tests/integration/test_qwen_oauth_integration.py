# Skip all tests in this file due to missing Qwen OAuth dependencies
import pytest
pytestmark = pytest.mark.skip("Qwen OAuth dependencies not available or incompatible")