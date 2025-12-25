from unittest.mock import Mock

from tests.conftest import pytest_cmdline_main


def test_pytest_cmdline_main(monkeypatch):
    config = Mock()
    config.args = []
    pytest_cmdline_main(config)
    assert config.args == []
