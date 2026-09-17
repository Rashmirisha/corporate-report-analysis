"""Stage 3 schema validation tests.

Pin down:
  * company label is mandatory on every ComparisonSide / ComparisonMetric
  * evidence in a side MUST match the side's company
  * insights with kind in {'fact','derived'} require evidence
  * 'insight' insights may omit evidence but must still be tagged
  * missing sections are normalised to "Not available in the provided reports."
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.comparator.schemas import (
    ComparativeAnalysis,
    ComparativeInsight,
    ComparisonEvidence,
    ComparisonFinancials,
    ComparisonMetric,
    ComparisonSection,
    ComparisonSide,
    KeyDifference,
    Trend,
)


def _ev(company: str = "A", kind: str = "chunk",
        doc: str = "Acme.pdf", sha: str = "a" * 64,
        page: int = 1, ref: str = "A_abc_p01_c000",
        claim_kind: str = "fact") -> ComparisonEvidence:
    return ComparisonEvidence(
        company=company,  # type: ignore[arg-type]
        document_name=doc,
        document_sha256=sha,
        page_number=page,
        ref_kind=kind,  # type: ignore[arg-type]
        ref_id=ref,
        snippet="snippet text",
        kind=claim_kind,  # type: ignore[arg-type]
    )


def _empty_section() -> dict:
    return {
        "a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
        "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
        "narrative": "Not available in the provided reports.",
        "narrative_kind": "insight",
        "evidence": [],
    }


def _minimal_analysis_payload() -> dict:
    return {
        "company_a_name": "Acme.pdf",
        "company_b_name": "Globex.pdf",
        "overview_comparison": _empty_section(),
        "financial_comparison": {"a": [], "b": [], "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "operational_comparison": _empty_section(),
        "business_comparison": _empty_section(),
        "strategic_comparison": _empty_section(),
        "strengths_comparison": _empty_section(),
        "weaknesses_comparison": _empty_section(),
        "risks_comparison": _empty_section(),
        "important_observations_comparison": _empty_section(),
        "trends": [],
        "key_differences": [],
        "evidence": [],
        "overall_comparative_insights": [],
        "warnings": [],
    }


# ----------------- evidence / side ------------------

def test_evidence_requires_company_and_snippet() -> None:
    with pytest.raises(ValidationError):
        ComparisonEvidence(
            company="A", document_name="Acme.pdf",
            document_sha256="a" * 64, page_number=1,
            ref_kind="chunk", ref_id="A_x", snippet="",
        )


def test_side_rejects_wrong_company_evidence() -> None:
    with pytest.raises(ValidationError):
        ComparisonSide(
            company="A",
            summary="ok",
            evidence=[_ev(company="B")],
        )


def test_section_rejects_unknown_company_evidence() -> None:
    # Build a 'Z'-company evidence object that bypasses the field-level
    # Literal type so we can actually reach the section-level validator.
    z_ev = ComparisonEvidence.model_construct(
        company="Z",  # type: ignore[arg-type]
        document_name="Z.pdf",
        document_sha256="z" * 64,
        page_number=1,
        ref_kind="chunk",
        ref_id="Z_x",
        snippet="x",
        kind="fact",
    )
    section_dict = {
        "a": {"company": "A", "summary": "x", "evidence": [_ev("A").model_dump()]},
        "b": {"company": "B", "summary": "x", "evidence": []},
        "narrative": "n",
        "narrative_kind": "derived",
        "evidence": [z_ev.model_dump()],
    }
    with pytest.raises(ValidationError):
        ComparisonSection.model_validate(section_dict)


def test_metric_requires_company_match() -> None:
    with pytest.raises(ValidationError):
        ComparisonMetric(
            company="A", metric="Revenue", value_text="1000",
            evidence=[_ev(company="B")],
        )


# ----------------- insights ------------------

def test_insight_with_fact_kind_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ComparativeInsight(title="x", claim="y", kind="fact", evidence=[])


def test_insight_with_insight_kind_may_omit_evidence() -> None:
    ins = ComparativeInsight(title="x", claim="y", kind="insight", evidence=[])
    assert ins.evidence == []


def test_insight_with_derived_kind_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ComparativeInsight(title="x", claim="y", kind="derived", evidence=[])


def test_insight_with_evidence_valid() -> None:
    ins = ComparativeInsight(
        title="Revenue trend",
        claim="Both companies report stable revenue.",
        kind="derived",
        evidence=[_ev("A"), _ev("B", doc="Globex.pdf", sha="b" * 64, ref="B_x")],
    )
    assert len(ins.evidence) == 2


# ----------------- trend / key_difference ------------------

def test_trend_requires_title_and_description() -> None:
    with pytest.raises(ValidationError):
        Trend(title="", description="d")


def test_key_difference_must_carry_evidence_when_derived() -> None:
    # kind defaults to "derived" -- evidence list must be non-empty.
    with pytest.raises(ValidationError):
        KeyDifference(title="x", description="y", kind="derived", evidence=[])


# ----------------- top-level shape ------------------

def test_minimum_valid_comparative_analysis() -> None:
    a = ComparativeAnalysis.model_validate(_minimal_analysis_payload())
    assert a.company_a_name == "Acme.pdf"
    assert a.company_b_name == "Globex.pdf"
    # All sections carry both A and B sides with correct company labels.
    for sec in (
        a.overview_comparison,
        a.operational_comparison,
        a.business_comparison,
        a.strategic_comparison,
        a.strengths_comparison,
        a.weaknesses_comparison,
        a.risks_comparison,
        a.important_observations_comparison,
    ):
        assert sec.a.company == "A"
        assert sec.b.company == "B"


def test_top_level_evidence_must_be_a_or_b() -> None:
    z_ev = ComparisonEvidence.model_construct(
        company="Z",  # type: ignore[arg-type]
        document_name="Z.pdf",
        document_sha256="z" * 64,
        page_number=1,
        ref_kind="chunk",
        ref_id="Z_x",
        snippet="x",
        kind="fact",
    )
    payload = _minimal_analysis_payload()
    payload["evidence"] = [z_ev.model_dump()]
    with pytest.raises(ValidationError):
        ComparativeAnalysis.model_validate(payload)


def test_financials_normalisation() -> None:
    payload = _minimal_analysis_payload()
    payload["financial_comparison"] = {
        "a": [{"company": "A", "metric": "Revenue", "value_text": "1000", "evidence": [_ev("A").model_dump()]}],
        "b": [{"company": "B", "metric": "Revenue", "value_text": "Not available in the provided reports.", "evidence": []}],
        "narrative": "Company A reports a revenue figure; Company B does not.",
        "narrative_kind": "derived",
        "evidence": [_ev("A").model_dump()],
    }
    a = ComparativeAnalysis.model_validate(payload)
    assert a.financial_comparison.a[0].metric == "Revenue"
    assert a.financial_comparison.b[0].value_text.startswith("Not available")


def test_cited_evidence_helper_walks_every_collection() -> None:
    payload = _minimal_analysis_payload()
    payload["overview_comparison"]["a"]["evidence"] = [_ev("A").model_dump()]
    payload["overview_comparison"]["b"]["evidence"] = [_ev("B", doc="Globex.pdf", sha="b" * 64, ref="B_x").model_dump()]
    payload["trends"] = [{
        "title": "Both face supply-chain risks",
        "description": "Both companies flagged supply-chain risks in FY24.",
        "kind": "derived",
        "evidence": [_ev("A").model_dump(), _ev("B", doc="Globex.pdf", sha="b" * 64, ref="B_x").model_dump()],
    }]
    payload["key_differences"] = [{
        "title": "Different growth trajectories",
        "description": "Company A grew; Company B declined.",
        "kind": "derived",
        "evidence": [_ev("A").model_dump(), _ev("B", doc="Globex.pdf", sha="b" * 64, ref="B_x").model_dump()],
    }]
    a = ComparativeAnalysis.model_validate(payload)
    seen = a.cited_evidence()
    assert len(seen) >= 4
    assert {ev.company for ev in seen} == {"A", "B"}
