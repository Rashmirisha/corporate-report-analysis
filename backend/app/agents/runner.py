"""Stage 2 agent runner — enforces company isolation.

This module is the SINGLE place that builds an evidence pack for a company
and hands it to the LLM. Any code path that wants to run an agent must go
through `analyze_company(...)` here. That way "Agent A never sees Company
B" is enforced by construction, not by convention.

Public API:
    analyze_company(company, *, client=None, force_stub=False)
        → AgentAnalysis

    run_analysis_for(state_a, state_b, *, client=None) -> dict[Company, AgentAnalysis]
        → runs both agents with the same shared LLM client

    get_state(company) -> AgentRunState
        → latest run status + result for one company

    reset_state(company) -> None
"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable, Dict, List, Optional

from app.agents.llm_client import LLMClient, make_default_client
from app.agents.prompts import (
    coerce_llm_json,
    default_queries,
    fill_company_metadata,
    system_prompt,
    user_prompt,
)
from app.agents.schemas import AgentAnalysis, AgentRunState
from app.retrieval.retriever import RetrievalHit, Retriever, build_retrievers
from app.schemas import Company, CompanyState


# ---------- isolation guard ----------

class IsolationViolation(RuntimeError):
    """Raised when an agent is asked to operate on the wrong company's data."""


def _check_company_match(state: CompanyState, expected: Company) -> None:
    if state.company != expected:
        raise IsolationViolation(
            f"isolation violation: state belongs to Company {state.company} "
            f"but the agent expected Company {expected}"
        )


def _filter_hits_to_company(hits: List[RetrievalHit], company: Company) -> List[RetrievalHit]:
    """Defence-in-depth: even if the caller hands us mixed hits, drop any
    whose `company` field doesn't match."""
    return [h for h in hits if h.company == company]


# ---------- run state (process-local) ----------

class _RunStateRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: Dict[Company, AgentRunState] = {
            "A": AgentRunState(company="A", status="idle"),
            "B": AgentRunState(company="B", status="idle"),
        }

    def get(self, company: Company) -> AgentRunState:
        with self._lock:
            return self._states[company].model_copy(deep=True)

    def set(self, state: AgentRunState) -> None:
        with self._lock:
            self._states[state.company] = state

    def all(self) -> Dict[Company, AgentRunState]:
        with self._lock:
            return {c: s.model_copy(deep=True) for c, s in self._states.items()}

    def reset(self, company: Company) -> None:
        with self._lock:
            self._states[company] = AgentRunState(company=company, status="idle")


_states = _RunStateRegistry()


# ---------- main entry points ----------

def analyze_company(
    state: CompanyState,
    *,
    client: Optional[LLMClient] = None,
    queries: Optional[List[str]] = None,
) -> AgentAnalysis:
    """Run the agent for one company.

    Args:
        state: the CompanyState to analyze.
        client: optional LLMClient. If None, the default factory decides
                between stub and real client based on env vars.
        queries: optional list of retrieval queries. Defaults to a built-in
                set biased toward each section.

    Returns:
        AgentAnalysis — fully validated against the schema.

    Raises:
        IsolationViolation if the state's company label is unexpected.
        ValueError if no usable evidence pack can be built.
    """
    company = state.company
    _check_company_match(state, company)

    # Build retriever SCOPED to this state. The retriever refuses to return
    # any chunk whose id starts with a different company prefix.
    retriever = Retriever(state)

    qs = list(queries) if queries else default_queries()
    hits = retriever.evidence_pack(qs, top_k_chunks=6, top_k_tables=3)
    hits = _filter_hits_to_company(hits, company)  # belt-and-braces

    if not hits:
        # No retrievable text — we still produce a fully-formed analysis
        # with "Not available in the provided report." everywhere, plus a
        # warning so the caller knows the agent ran on an empty corpus.
        return _empty_analysis(state, reason="no retrievable evidence in PDF")

    sys_prompt = system_prompt(company)
    usr_prompt = user_prompt(
        company=company,
        document_name=state.source.document_name,
        page_count=state.source.page_count,
        hits=hits,
    )

    if client is None:
        client = make_default_client()

    raw = client.complete(system=sys_prompt, user=usr_prompt, json_mode=True)
    parsed = coerce_llm_json(raw)
    analysis_dict = _normalise_analysis_shape(parsed, company)

    # Pre-fill document metadata BEFORE schema validation so the agent
    # can't accidentally omit a required field.
    analysis_dict["document_name"] = state.source.document_name
    analysis_dict["document_sha256"] = state.source.document_sha256
    analysis_dict["page_count"] = state.source.page_count

    # Validate against the schema, then re-stamp metadata (defence in depth).
    analysis = AgentAnalysis.model_validate(analysis_dict)
    analysis = fill_company_metadata(
        analysis,
        company=company,
        document_name=state.source.document_name,
        document_sha256=state.source.document_sha256,
        page_count=state.source.page_count,
    )

    # Track what we actually consumed so the dashboard can show provenance.
    referenced_chunks = [h.id for h in hits if h.kind == "chunk"]
    referenced_tables = [h.id for h in hits if h.kind == "table"]
    extra_warnings: List[str] = []

    unresolved = analysis.references_resolved(state.chunks, state.tables)
    if unresolved:
        extra_warnings.append(
            f"{len(unresolved)} evidence ref(s) could not be resolved against the PDF: "
            + ", ".join(unresolved[:5])
        )

    analysis = analysis.model_copy(
        update={
            "referenced_chunk_ids": referenced_chunks,
            "referenced_table_ids": referenced_tables,
            "warnings": list(analysis.warnings) + extra_warnings,
        }
    )
    return analysis


def run_analysis_for(
    state_a: Optional[CompanyState],
    state_b: Optional[CompanyState],
    *,
    client: Optional[LLMClient] = None,
    on_progress: Optional[Callable[[Company, str], None]] = None,
) -> Dict[Company, Optional[AgentAnalysis]]:
    """Run Agent A and Agent B in sequence. Both share the same `client`.

    Each agent operates on its OWN state only. The `client` is the only
    shared resource (because it owns the HTTP connection pool); we pass it
    to both run calls, never any state.
    """
    results: Dict[Company, Optional[AgentAnalysis]] = {"A": None, "B": None}
    for company, state in (("A", state_a), ("B", state_b)):
        if state is None:
            if on_progress:
                on_progress(company, "skipped: no PDF uploaded for this company")
            continue
        _mark(company, "running")
        if on_progress:
            on_progress(company, "running")
        try:
            analysis = analyze_company(state, client=client)
        except Exception as exc:  # noqa: BLE001
            _mark(company, "failed", error=str(exc))
            if on_progress:
                on_progress(company, f"failed: {exc}")
            continue
        _mark(company, "completed", analysis=analysis)
        results[company] = analysis
        if on_progress:
            on_progress(company, "completed")
    return results


# ---------- run-state accessors ----------

def get_state(company: Company) -> AgentRunState:
    return _states.get(company)


def all_states() -> Dict[Company, AgentRunState]:
    return _states.all()


def reset_state(company: Company) -> None:
    _states.reset(company)


# ---------- helpers ----------

def _mark(company: Company, status: str, *, analysis: Optional[AgentAnalysis] = None, error: Optional[str] = None) -> None:
    prev = _states.get(company)
    now = time.time()
    new = AgentRunState(
        company=company,
        status=status,  # type: ignore[arg-type]
        started_at=prev.started_at if prev.started_at is not None and status == "running" else now,
        completed_at=now if status in ("completed", "failed") else prev.completed_at,
        error=error,
        analysis=analysis,
    )
    _states.set(new)


def _empty_analysis(state: CompanyState, *, reason: str) -> AgentAnalysis:
    """Fallback when the retriever returns nothing. Marks every section
    unavailable and produces a valid AgentAnalysis."""
    company = state.company
    doc_name = state.source.document_name
    sha = state.source.document_sha256
    page_count = state.source.page_count

    unavailable = {
        "summary": "Not available in the provided report.",
        "evidence": [],
    }
    empty_block = unavailable.copy()
    return AgentAnalysis.model_validate(
        {
            "company": company,
            "document_name": doc_name,
            "document_sha256": sha,
            "page_count": page_count,
            "company_overview": empty_block,
            "financial_performance": {
                **empty_block,
                "key_metrics": [],
            },
            "operational_information": empty_block,
            "strategic_information": empty_block,
            "business_information": empty_block,
            "strengths": [],
            "weaknesses": [],
            "risks": [],
            "important_observations": [],
            "warnings": [reason],
        }
    )


def _normalise_analysis_shape(parsed: dict, company: Company) -> dict:
    """Tolerate minor shape drift from the LLM and coerce into the schema."""
    if not isinstance(parsed, dict):
        raise ValueError(f"agent returned non-dict payload: {parsed!r}")

    UNAVAILABLE = "Not available in the provided report."

    parsed.setdefault("company", company)
    parsed.setdefault("company_overview", {"summary": UNAVAILABLE, "evidence": []})
    parsed.setdefault("operational_information", {"summary": UNAVAILABLE, "evidence": []})
    parsed.setdefault("strategic_information", {"summary": UNAVAILABLE, "evidence": []})
    parsed.setdefault("business_information", {"summary": UNAVAILABLE, "evidence": []})

    # Coerce empty summaries to the unavailable marker so the schema's
    # `min_length=1` constraint passes even when the LLM returned "".
    for key in ("company_overview", "operational_information", "strategic_information", "business_information"):
        sec = parsed.get(key)
        if isinstance(sec, dict) and not (sec.get("summary") or "").strip():
            sec["summary"] = UNAVAILABLE

    fp = parsed.get("financial_performance")
    if not isinstance(fp, dict):
        fp = {"summary": UNAVAILABLE, "evidence": [], "key_metrics": []}
    if not (fp.get("summary") or "").strip():
        fp["summary"] = UNAVAILABLE
    fp.setdefault("evidence", [])
    fp.setdefault("key_metrics", [])
    parsed["financial_performance"] = fp

    for group in ("strengths", "weaknesses", "risks", "important_observations"):
        val = parsed.get(group)
        if not isinstance(val, list):
            parsed[group] = []

    parsed.setdefault("warnings", [])
    return parsed


__all__ = [
    "analyze_company",
    "run_analysis_for",
    "get_state",
    "all_states",
    "reset_state",
    "IsolationViolation",
]
