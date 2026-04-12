"""Ensure ``compression_strategies`` barrel keeps stable public symbols."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "name",
    [
        "AnsiNormalizeStrategy",
        "DiagnosticsGroupingStrategy",
        "DiffCompactStrategy",
        "DirectoryTreeSummaryStrategy",
        "FailureFocusGenericStrategy",
        "FailurePreservingTruncateStrategy",
        "FileDetailLevelsStrategy",
        "LineDedupeStrategy",
        "MutatingSuccessAckStrategy",
        "OutputPatternMatchRule",
        "OutputPatternMatchStrategy",
        "PytestFailureFocusStrategy",
        "SearchResultsGroupingStrategy",
        "SimilarityGroupingStrategy",
        "StatsExtractionSummaryStrategy",
    ],
)
def test_compression_strategies_barrel_exports(name: str) -> None:
    mod = importlib.import_module("src.core.services.compression_strategies")
    assert hasattr(mod, name)
    assert getattr(mod, name) is not None
