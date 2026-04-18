"""Built-in dynamic compression strategies used by the orchestrator."""

from __future__ import annotations

from src.core.services._compression_strategies_failure_stats import (
    DiagnosticsGroupingStrategy,
    FailureFocusGenericStrategy,
    MutatingSuccessAckStrategy,
    PytestFailureFocusStrategy,
    StatsExtractionSummaryStrategy,
)
from src.core.services._compression_strategies_file_detail import (
    FileDetailLevelsStrategy,
)
from src.core.services._compression_strategies_git_status import GitStatusStrategy
from src.core.services._compression_strategies_pattern_diff import (
    DiffCompactStrategy,
    OutputPatternMatchRule,
    OutputPatternMatchStrategy,
)
from src.core.services._compression_strategies_text import (
    AnsiNormalizeStrategy,
    FailurePreservingTruncateStrategy,
    LineDedupeStrategy,
    SimilarityGroupingStrategy,
)
from src.core.services._compression_strategies_tree_search import (
    DirectoryTreeSummaryStrategy,
    SearchResultsGroupingStrategy,
)

__all__ = [
    "AnsiNormalizeStrategy",
    "DiagnosticsGroupingStrategy",
    "DiffCompactStrategy",
    "DirectoryTreeSummaryStrategy",
    "FailureFocusGenericStrategy",
    "FailurePreservingTruncateStrategy",
    "FileDetailLevelsStrategy",
    "GitStatusStrategy",
    "LineDedupeStrategy",
    "MutatingSuccessAckStrategy",
    "OutputPatternMatchRule",
    "OutputPatternMatchStrategy",
    "PytestFailureFocusStrategy",
    "SearchResultsGroupingStrategy",
    "SimilarityGroupingStrategy",
    "StatsExtractionSummaryStrategy",
]
