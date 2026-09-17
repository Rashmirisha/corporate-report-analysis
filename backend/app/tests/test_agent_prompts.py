"""Agent prompt tests.

Verifies:
- The system prompt for Company A never mentions Company B and vice versa.
- The user prompt for Company A only carries Company A hits.
- Schema coercion handles LLM-side shape drift.
"""
from __future__ import annotations

import json

import pytest

from app.agents.prompts import (
    coerce_llm_json,
    fill_company_metadata,
    system_prompt,
    user_prompt,
)
from app.agents.schemas import AgentAnalysis
from app.retrieval.retriever import RetrievalHit


def _hit(company: str, kind: str = "chunk", page: int = 1, ref: str | None = None, doc: str = "Acme.pdf", sha: str | None = None) -> RetrievalHit:
    return RetrievalHit(
        kind=kind,
        id=ref or f"{company}_deadbeef_p{page:03d}_c000",
        company=company,  # type: ignore[arg-type]
        document_name=doc,
        document_sha256=sha or ("a" * 64 if company == "A" else "b" * 64),
        page_number=page,
        score=1.0,
        snippet=f"{company} evidence snippet for {kind}",
        chunk=None,
        table=None,
    )


def test_system_prompt_a_does_not_mention_b() -> None:
    s = system_prompt("A")
    assert "Agent A" in s
    assert "Company B" not in s
    # The agent should be told it never sees the other company's data.
    assert "never" in s.lower() or "do not" in s.lower()


def test_system_prompt_b_does_not_mention_a() -> None:
    s = system_prompt("B")
    assert "Agent B" in s
    assert "Company A" not in s


def test_user_prompt_carries_only_own_company_hits() -> None:
    hits = [_hit("A", ref="A_aa_p01_c000"), _hit("A", kind="table", ref="A_aa_p02_t001")]
    p = user_prompt("A", "Acme.pdf", 5, hits)
    assert "Acme.pdf" in p
    assert "A_aa_p01_c000" in p
    # Cross-company ref must NOT appear in the user prompt.
    assert "B_" not in p


def test_user_prompt_no_hits_announces_empty_evidence() -> None:
    p = user_prompt("A", "Acme.pdf", 5, [])
    assert "No evidence chunks" in p or "no evidence" in p.lower()


def test_coerce_llm_json_strips_fences() -> None:
    raw = "```json\n{\"foo\": 1}\n```"
    out = coerce_llm_json(raw)
    assert out == {"foo": 1}


def test_coerce_llm_json_extracts_inner_object() -> None:
    raw = "Sure, here is the JSON:\n{\"foo\": 2}\nThanks!"
    assert coerce_llm_json(raw) == {"foo": 2}


def test_fill_company_metadata_overrides_wrong_company() -> None:
    payload = {
        "company": "B",  # LLM mistakenly set this to B
        "document_name": "Globex.pdf",
        "document_sha256": "b" * 64,
        "page_count": 5,
        "company_overview": {"summary": "x", "evidence": [{"company": "B", "page_number": 1, "ref_id": "B_x", "snippet": "s", "document_name": "Globex.pdf", "document_sha256": "b" * 64}]},
        "financial_performance": {"summary": "x", "key_metrics": [], "evidence": []},
        "operational_information": {"summary": "x", "evidence": []},
        "strategic_information": {"summary": "x", "evidence": []},
        "business_information": {"summary": "x", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    parsed = AgentAnalysis.model_validate(payload)
    fixed = fill_company_metadata(parsed, company="A", document_name="Acme.pdf", document_sha256="a" * 64, page_count=5)
    assert fixed.company == "A"
    assert fixed.document_name == "Acme.pdf"
    # All evidence refs should now carry company=A + document_name.
    for ev in fixed.cited_evidence():
        assert ev.company == "A"
        assert ev.document_name == "Acme.pdf"
