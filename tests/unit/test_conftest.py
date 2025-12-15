import os
import xml.etree.ElementTree
from unittest.mock import Mock

from tests.conftest import pytest_cmdline_main


def create_test_results_xml(failures: int):
    root = xml.etree.ElementTree.Element("testsuites")
    testsuite = xml.etree.ElementTree.SubElement(
        root, "testsuite", failures=str(failures)
    )
    xml.etree.ElementTree.SubElement(
        testsuite, "testcase", classname="dummy", name="dummy_test"
    )
    tree = xml.etree.ElementTree.ElementTree(root)
    tree.write("test-results.xml")


def test_pytest_cmdline_main(monkeypatch):
    # Ensure xdist detection is disabled so the hook runs
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    # 1. No test-results.xml file
    if os.path.exists("test-results.xml"):
        os.remove("test-results.xml")

    config = Mock()
    config.args = []
    config.getini.return_value = ["tests"]
    # Mock xdist attributes to disable xdist logic in the hook
    config.option = Mock()
    config.option.numprocesses = None
    pytest_cmdline_main(config)
    assert "--maxfail=1" in config.args
    assert "--ff" not in config.args

    # 2. test-results.xml with 0 failures
    create_test_results_xml(0)
    config.args = []
    pytest_cmdline_main(config)
    assert "--maxfail=1" in config.args
    assert "--ff" not in config.args

    # 3. test-results.xml with 5 failures
    create_test_results_xml(5)
    config.args = []
    pytest_cmdline_main(config)
    assert "--maxfail=5" in config.args
    assert "--ff" in config.args

    # 4. User specifies --maxfail
    create_test_results_xml(5)
    config.args = ["--maxfail=10"]
    pytest_cmdline_main(config)
    assert "--maxfail=5" not in config.args
    assert "--ff" not in config.args

    # 5. User specifies --lf
    create_test_results_xml(5)
    config.args = ["--lf"]
    pytest_cmdline_main(config)
    assert "--maxfail=5" not in config.args
    assert "--ff" not in config.args
