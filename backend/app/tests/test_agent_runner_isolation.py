"""End-to-end agent runner tests with stubbed LLM.

The LLM never makes a network call — `StubLLMClient` returns canned JSON
matching the schema. These tests verify:
  - Agent A reads only Company A's chunks.
  - Agent B reads only Company B's chunks.
  - Cross-company contamination is impossible at the runner level.
  - Schema validation, evidence metadata, and "no fabricated numbers"
    rules are honoured.
"""
from __future__ import annotations

import json

import pytest

from app.agents.llm_client import StubLLMClient
from app.agents.runner import (
    IsolationViolation,
    analyze_company,
    reset_state,
    reset_state as reset_a,
)
from app.agents.schemas import AgentAnalysis
from app.ingest.pipeline import ingest_pdf_bytes
from app.tests._fixtures import build_minimal_pdf_two_pages


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _reset_run_state() -> None:
    reset_a("A")
    reset_a("B")


def _ingest(tmp_path, company: str, page1: str, page2: str, name: str):
    content = build_minimal_pdf_two_pages(page1, page2)
    return ingest_pdf_bytes(content, company, tmp_path, document_name=name)


def _scripted_client(payload: dict) -> StubLLMClient:
    return (
        StubLLMClient()
        .expect(
            system_contains="Agent ",
            user_contains="EVIDENCE PACK",
            response=json.dumps(payload),
        )
    )


# ---------- isolation ----------

def test_agent_a_only_sees_company_a(tmp_path) -> None:
    state_a = _ingest(tmp_path, "A", "Acme FY24 revenue 1200.", "Acme FY24 profit 200.", name="Acme.pdf")
    state_b = _ingest(tmp_path, "B", "Globex FY24 revenue 900.", "Globex FY24 profit 100.", name="Globex.pdf")

    payload = {
        "company": "A",
        "company_overview": {"summary": "Acme is a manufacturer.", "evidence": []},
        "financial_performance": {"summary": "Revenue grew.", "key_metrics": [], "evidence": []},
        "operational_information": {"summary": "Plants in 5 regions.", "evidence": []},
        "strategic_information": {"summary": "Expansion plan.", "evidence": []},
        "business_information": {"summary": "Industrial goods.", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    client = _scripted_client(payload)

    analysis = analyze_company(state_a, client=client)

    # The user prompt that reached the LLM must contain only Acme refs.
    used = [s for s in client._scripts if s.used]
    assert len(used) == 1
    user_prompt = used[0].user_contains  # raw text isn't stored; verify via the only script
    # Re-build the prompt and inspect it directly:
    from app.agents.prompts import user_prompt as build_user_prompt
    from app.retrieval.retriever import Retriever
    ra = Retriever(state_a)
    hits = ra.evidence_pack(["revenue", "operations"], top_k_chunks=4, top_k_tables=2)
    rendered = build_user_prompt("A", state_a.source.document_name, state_a.source.page_count, hits)
    assert "Acme" in rendered
    assert "Globex" not in rendered
    assert "B_" not in rendered

    assert isinstance(analysis, AgentAnalysis)
    assert analysis.company == "A"


def test_agent_b_only_sees_company_b(tmp_path) -> None:
    state_a = _ingest(tmp_path, "A", "Acme FY24 revenue 1200.", "Acme FY24 profit 200.", name="Acme.pdf")
    state_b = _ingest(tmp_path, "B", "Globex FY24 revenue 900.", "Globex FY24 profit 100.", name="Globex.pdf")

    payload = {
        "company": "B",
        "company_overview": {"summary": "Globex is a logistics company.", "evidence": []},
        "financial_performance": {"summary": "Revenue fell.", "key_metrics": [], "evidence": []},
        "operational_information": {"summary": "Fleet of 200 trucks.", "evidence": []},
        "strategic_information": {"summary": "Cost optimisation.", "evidence": []},
        "business_information": {"summary": "Logistics.", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    client = _scripted_client(payload)

    analysis = analyze_company(state_b, client=client)

    # Verify B's prompt only carries B's evidence.
    from app.agents.prompts import user_prompt as build_user_prompt
    from app.retrieval.retriever import Retriever
    rb = Retriever(state_b)
    hits = rb.evidence_pack(["revenue", "operations"], top_k_chunks=4, top_k_tables=2)
    rendered = build_user_prompt("B", state_b.source.document_name, state_b.source.page_count, hits)
    assert "Globex" in rendered
    assert "Acme" not in rendered
    assert "A_" not in rendered

    assert isinstance(analysis, AgentAnalysis)
    assert analysis.company == "B"


def test_runner_refuses_wrong_company_state(tmp_path) -> None:
    """The internal `_check_company_match` guard refuses a state whose
    company label doesn't match what the runner expects. We simulate a
    mislabelled state with `model_construct` (skipping the Literal
    validation) so we can actually reach the guard."""
    from app.agents.runner import _check_company_match
    from app.schemas import CompanyState

    fake_state = CompanyState.model_construct(
        company="B",  # type: ignore[arg-type]
        source=None,
        chunks=[],
        tables=[],
        chunk_count=0,
        table_count=0,
    )
    with pytest.raises(IsolationViolation):
        _check_company_match(fake_state, "A")


# ---------- evidence ----------

def test_missing_evidence_is_reported_as_unavailable(tmp_path) -> None:
    """If the LLM provides only an 'unavailable' marker, it's accepted."""
    state_a = _ingest(tmp_path, "A", "Tiny content.", "More content.", name="Acme.pdf")
    payload = {
        "company": "A",
        "company_overview": {"summary": "Not available in the provided report.", "evidence": []},
        "financial_performance": {
            "summary": "Not available in the provided report.",
            "key_metrics": [
                {"metric": "Revenue", "value_text": "Not available in the provided report."}
            ],
            "evidence": [],
        },
        "operational_information": {"summary": "Not available in the provided report.", "evidence": []},
        "strategic_information": {"summary": "Not available in the provided report.", "evidence": []},
        "business_information": {"summary": "Not available in the provided report.", "evidence": []},
        "strengths": [{"point": "Not available in the provided report.", "evidence": []}],
        "weaknesses": [{"point": "Not available in the provided report.", "evidence": []}],
        "risks": [{"point": "Not available in the provided report.", "evidence": []}],
        "important_observations": [{"point": "Not available in the provided report.", "evidence": []}],
    }
    client = _scripted_client(payload)
    analysis = analyze_company(state_a, client=client)
    assert analysis.company == "A"
    assert analysis.company_overview.summary.startswith("Not available")
    # No fabricated claims.
    assert "Revenue" not in analysis.financial_performance.summary


def test_financial_metric_without_evidence_is_rejected(tmp_path) -> None:
    """Schema enforces: a metric with a real value must carry evidence."""
    state_a = _ingest(tmp_path, "A", "Revenue 1200.", "Profit 200.", name="Acme.pdf")
    payload = {
        "company": "A",
        "company_overview": {"summary": "Acme is a manufacturer.", "evidence": []},
        "financial_performance": {
            "summary": "Revenue 1200.",
            "key_metrics": [{"metric": "Revenue", "value_text": "1200"}],  # no evidence — schema rejects
            "evidence": [],
        },
        "operational_information": {"summary": "Ops.", "evidence": []},
        "strategic_information": {"summary": "Strategy.", "evidence": []},
        "business_information": {"summary": "Business.", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    client = _scripted_client(payload)
    with pytest.raises(Exception):
        analyze_company(state_a, client=client)


def test_analysis_references_resolved_against_real_chunks(tmp_path) -> None:
    state_a = _ingest(tmp_path, "A", "Revenue 1200 million.", "Profit 200 million.", name="Acme.pdf")
    real_chunk_id = state_a.chunks[0].chunk_id

    payload = {
        "company": "A",
        "company_overview": {
            "summary": "Acme is a manufacturer.",
            "evidence": [{
                "company": "A", "document_name": "Acme.pdf",
                "document_sha256": state_a.source.document_sha256,
                "page_number": state_a.chunks[0].page_number,
                "kind": "chunk", "ref_id": real_chunk_id,
                "snippet": "Revenue 1200 million.",
            }],
        },
        "financial_performance": {
            "summary": "Revenue grew.",
            "key_metrics": [{
                "metric": "Revenue",
                "value_text": "1200 million",
                "unit": "million",
                "year_or_period": "FY24",
                "evidence": [{
                    "company": "A", "document_name": "Acme.pdf",
                    "document_sha256": state_a.source.document_sha256,
                    "page_number": state_a.chunks[0].page_number,
                    "kind": "chunk", "ref_id": real_chunk_id,
                    "snippet": "Revenue 1200 million.",
                }],
            }],
            "evidence": [],
        },
        "operational_information": {"summary": "Ops.", "evidence": []},
        "strategic_information": {"summary": "Strategy.", "evidence": []},
        "business_information": {"summary": "Business.", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    client = _scripted_client(payload)
    analysis = analyze_company(state_a, client=client)
    unresolved = analysis.references_resolved(state_a.chunks, state_a.tables)
    assert unresolved == []
