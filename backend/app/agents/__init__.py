"""Stage 2 agents — public surface."""
from .llm_client import (
    LLMClient,
    LLMConfig,
    OllamaLLMClient,
    StubLLMClient,
    make_default_client,
)
from .runner import (
    IsolationViolation,
    all_states,
    analyze_company,
    get_state,
    reset_state,
    run_analysis_for,
)
from .schemas import (
    AgentAnalysis,
    AgentRunState,
    BulletWithEvidence,
    EvidenceBlock,
    EvidenceRef,
    FinancialMetric,
    FinancialPerformance,
    TextWithEvidence,
)
from .prompts import (
    coerce_llm_json,
    default_queries,
    fill_company_metadata,
    system_prompt,
    user_prompt,
)

__all__ = [
    "LLMClient",
    "LLMConfig",
    "OllamaLLMClient",
    "StubLLMClient",
    "make_default_client",
    "analyze_company",
    "run_analysis_for",
    "get_state",
    "all_states",
    "reset_state",
    "IsolationViolation",
    "AgentAnalysis",
    "AgentRunState",
    "BulletWithEvidence",
    "EvidenceBlock",
    "EvidenceRef",
    "FinancialMetric",
    "FinancialPerformance",
    "TextWithEvidence",
    "system_prompt",
    "user_prompt",
    "default_queries",
    "coerce_llm_json",
    "fill_company_metadata",
]
