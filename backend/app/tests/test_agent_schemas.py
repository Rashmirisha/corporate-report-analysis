"""Schema tests for Stage 2 agent outputs.

These pin down the no-hallucination contract:
- Claims require evidence unless explicitly marked unavailable.
- Financial metrics require evidence.
- Evidence requires page_number, ref_id, snippet.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.schemas import (
    AgentAnalysis,
    BulletWithEvidence,
    EvidenceBlock,
    EvidenceRef,
    FinancialMetric,
    FinancialPerformance,
    TextWithEvidence,
)


def _ev(company: str = "A", kind: str = "chunk", ref: str = "A_abc_p01_c000", page: int = 1) -> EvidenceRef:
    return EvidenceRef(
        company=company,  # type: ignore[arg-type]
        document_name="Acme.pdf",
        document_sha256="a" * 64,
        page_number=page,
        kind=kind,  # type: ignore[arg-type]
        ref_id=ref,
        snippet="snippet text",
    )


def test_text_with_evidence_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        TextWithEvidence(claim="Revenue increased.")


def test_text_with_evidence_unavailable_marker_ok_without_evidence() -> None:
    item = TextWithEvidence(claim="Not available in the provided report.")
    assert item.evidence == []


def test_bullet_with_evidence_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        BulletWithEvidence(point="Strong brand.")


def test_bullet_with_evidence_unavailable_marker_ok_without_evidence() -> None:
    item = BulletWithEvidence(point="Not available in the provided report.")
    assert item.evidence == []


def test_financial_metric_requires_evidence_unless_unavailable() -> None:
    with pytest.raises(ValidationError):
        FinancialMetric(metric="Revenue", value_text="1000 million")


def test_financial_metric_unavailable_marker_ok() -> None:
    m = FinancialMetric(metric="Revenue", value_text="Not available in the provided report.")
    assert m.evidence == []


def test_evidence_block_requires_summary() -> None:
    with pytest.raises(ValidationError):
        EvidenceBlock(summary="")


def test_full_agent_analysis_minimum_shape() -> None:
    payload = {
        "company": "A",
        "document_name": "Acme.pdf",
        "document_sha256": "a" * 64,
        "page_count": 5,
        "company_overview": {"summary": "x", "evidence": [_ev().model_dump()]},
        "financial_performance": {"summary": "x", "key_metrics": [], "evidence": []},
        "operational_information": {"summary": "x", "evidence": []},
        "strategic_information": {"summary": "x", "evidence": []},
        "business_information": {"summary": "x", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    a = AgentAnalysis.model_validate(payload)
    assert a.company == "A"


def test_full_agent_analysis_financial_metric_must_have_evidence() -> None:
    payload = {
        "company": "A",
        "document_name": "Acme.pdf",
        "document_sha256": "a" * 64,
        "page_count": 5,
        "company_overview": {"summary": "x", "evidence": [_ev().model_dump()]},
        "financial_performance": {
            "summary": "x",
            "key_metrics": [{"metric": "Revenue", "value_text": "1000"}],  # no evidence
            "evidence": [],
        },
        "operational_information": {"summary": "x", "evidence": []},
        "strategic_information": {"summary": "x", "evidence": []},
        "business_information": {"summary": "x", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    with pytest.raises(ValidationError):
        AgentAnalysis.model_validate(payload)


def test_references_resolved_flags_unresolved() -> None:
    payload = {
        "company": "A",
        "document_name": "Acme.pdf",
        "document_sha256": "a" * 64,
        "page_count": 5,
        "company_overview": {"summary": "x", "evidence": [_ev(ref="A_aaa_p01_c000").model_dump()]},
        "financial_performance": {"summary": "x", "key_metrics": [], "evidence": []},
        "operational_information": {"summary": "x", "evidence": []},
        "strategic_information": {"summary": "x", "evidence": []},
        "business_information": {"summary": "x", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    a = AgentAnalysis.model_validate(payload)
    # Build a Stage-1 state with no chunks matching the cited id.
    fake_state = {"chunks": [], "tables": []}
    unresolved = a.references_resolved([], [])
    assert "A_aaa_p01_c000" in unresolved
