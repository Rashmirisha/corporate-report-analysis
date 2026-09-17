"""Stage 3 comparative-analysis package."""
from .schemas import (
    ComparisonEvidence,
    ComparisonFinancials,
    ComparisonMetric,
    ComparisonRunState,
    ComparisonSection,
    ComparisonSide,
    ComparativeAnalysis,
    ComparativeInsight,
    KeyDifference,
    Trend,
)
from .prompts import (
    coerce_llm_json,
    comparative_user_prompt,
    comparative_system_prompt,
    fill_comparison_metadata,
)
from .runner import (
    ComparisonUnavailableError,
    ComparativeResult,
    get_comparison,
    reset_comparison,
    run_comparison,
)

__all__ = [
    "ComparisonEvidence",
    "ComparisonFinancials",
    "ComparisonMetric",
    "ComparisonRunState",
    "ComparisonSection",
    "ComparisonSide",
    "ComparativeAnalysis",
    "ComparativeInsight",
    "KeyDifference",
    "Trend",
    "comparative_system_prompt",
    "comparative_user_prompt",
    "coerce_llm_json",
    "fill_comparison_metadata",
    "ComparisonUnavailableError",
    "ComparativeResult",
    "get_comparison",
    "reset_comparison",
    "run_comparison",
]
