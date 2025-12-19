"""
Meta test to force disable testmon cache.

This is a hack to ease out running of the whole test suite.
Since this project is using testmon, it is now hard to run the whole test suite.
By simply adding the param `-m "not testmon_cache"` agents can force full pytest run,
since the presence of the `-m` option allows for that (testmon disables its selection
when `-m` is used).

This is a dummy test that always passes, used solely for the marker it provides.
"""

import pytest


@pytest.mark.testmon_cache
def test_meta_force_disable_testmon_cache():
    """Dummy test that always passes."""
    assert True
