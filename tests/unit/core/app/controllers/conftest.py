from __future__ import annotations

from typing import Any

import pytest

from tests.utils.responses_controller_test_deps import (
    build_responses_controller_backend_kwargs,
)


@pytest.fixture()
def responses_controller_backend_deps() -> dict[str, Any]:
    return build_responses_controller_backend_kwargs()
