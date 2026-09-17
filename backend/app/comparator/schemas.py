"""Stage 3 comparative-analysis schemas.

Strict evidence rules:

  * Every `ComparisonSide` for a given company must carry that company's
    evidence (never the other company's).
  * Every comparative insight MUST cite at least one evidence ref OR be
    explicitly tagged as "interpretation" with no supporting evidence.
  * Financial metrics are NEVER invented: missing data uses the literal
    string ``"Not available in the provided reports."``.
  * The output preserves the three-layer distinction:
      - ``kind="fact"``    — directly quoted from the source reports.
      - ``kind="derived"`` — comparison derived from facts.
      - ``kind="insight"`` — AI interpretation (caller is responsible for
        not presenting it as fact).
"""
from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.agents.schemas import EvidenceRef


Company = Literal["A", "B"]
ClaimKind = Literal["fact", "derived", "insight"]


# ---------------- Evidence ----------------

class ComparisonEvidence(BaseModel):
    """One piece of evidence pointing at the original PDF.

    Mirrors ``EvidenceRef`` but lives in the comparator's namespace and
    carries a `kind` marker distinguishing stated fact / derived
    comparison / AI interpretation.
    """

    model_config = ConfigDict(extra="forbid")

    company: Company
    document_name: str = Field(min_length=1)
    document_sha256: str = Field(min_length=8)
    page_number: int = Field(ge=1)
    ref_kind: Literal["chunk", "table"]
    ref_id: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    kind: ClaimKind = "fact"


# ---------------- Side-by-side sections ----------------

class ComparisonSide(BaseModel):
    """What the analysis says about ONE company within one section."""

    model_config = ConfigDict(extra="forbid")

    company: Company
    summary: str = Field(min_length=1)
    evidence: List[ComparisonEvidence] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _every_evidence_matches_company(cls, v: List[ComparisonEvidence], info) -> List[ComparisonEvidence]:  # type: ignore[no-untyped-def]
        company = info.data.get("company")
        for ev in v:
            if ev.company != company:
                raise ValueError(
                    f"evidence.company={ev.company!r} does not match side.company={company!r}"
                )
        return v


class ComparisonSection(BaseModel):
    """A category of comparison: overview, financials, operations, etc.

    Each section MUST carry an `a` and `b` side. The `narrative` field
    is the comparison text the comparator produces for this section.
    """

    model_config = ConfigDict(extra="forbid")

    a: ComparisonSide
    b: ComparisonSide
    narrative: str = Field(min_length=1)
    narrative_kind: ClaimKind = "derived"
    evidence: List[ComparisonEvidence] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _evidence_matches_a_or_b(cls, v: List[ComparisonEvidence]) -> List[ComparisonEvidence]:
        for ev in v:
            if ev.company not in ("A", "B"):
                raise ValueError(f"evidence.company must be A or B, got {ev.company!r}")
        return v


# ---------------- Financials (specialised) ----------------

class ComparisonMetric(BaseModel):
    """A single numeric metric from one company.

    If the value isn't in the source, ``value_text`` is the literal
    ``"Not available in the provided reports."`` and ``evidence`` is [].
    """

    model_config = ConfigDict(extra="forbid")

    company: Company
    metric: str = Field(min_length=1)
    value_text: str = Field(min_length=1)
    unit: Optional[str] = None
    year_or_period: Optional[str] = None
    evidence: List[ComparisonEvidence] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _evidence_matches_company(cls, v: List[ComparisonEvidence], info) -> List[ComparisonEvidence]:  # type: ignore[no-untyped-def]
        company = info.data.get("company")
        for ev in v:
            if ev.company != company:
                raise ValueError(
                    f"evidence.company={ev.company!r} does not match metric.company={company!r}"
                )
        return v


class ComparisonFinancials(BaseModel):
    """Side-by-side financial comparison.

    No arithmetic is performed on values the reports do not contain.
    If both companies lack a metric, ``value_text`` is the unavailable
    sentinel for both sides.
    """

    model_config = ConfigDict(extra="forbid")

    a: List[ComparisonMetric] = Field(default_factory=list)
    b: List[ComparisonMetric] = Field(default_factory=list)
    narrative: str = Field(min_length=1)
    narrative_kind: ClaimKind = "derived"
    evidence: List[ComparisonEvidence] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _evidence_matches_a_or_b(cls, v: List[ComparisonEvidence]) -> List[ComparisonEvidence]:
        for ev in v:
            if ev.company not in ("A", "B"):
                raise ValueError(f"evidence.company must be A or B, got {ev.company!r}")
        return v


# ---------------- Trends and differences ----------------

class Trend(BaseModel):
    """A pattern observed across both reports.

    Trends are derived comparisons — they explicitly cite both sides.
    If a trend is purely interpretive, set ``evidence`` to [] and
    ``kind='insight'``.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: ClaimKind = "derived"
    evidence: List[ComparisonEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_or_insight_marker(self) -> "Trend":
        if self.kind == "insight":
            return self
        if not self.evidence:
            raise ValueError(
                "Trend with kind in {'fact','derived'} must include evidence"
            )
        return self

    @field_validator("evidence")
    @classmethod
    def _evidence_matches_a_or_b(cls, v: List[ComparisonEvidence]) -> List[ComparisonEvidence]:
        for ev in v:
            if ev.company not in ("A", "B"):
                raise ValueError(f"evidence.company must be A or B, got {ev.company!r}")
        return v


class KeyDifference(BaseModel):
    """A specific point where the two companies diverge."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: ClaimKind = "derived"
    evidence: List[ComparisonEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_or_insight_marker(self) -> "KeyDifference":
        if self.kind == "insight":
            return self
        if not self.evidence:
            raise ValueError(
                "KeyDifference with kind in {'fact','derived'} must include evidence"
            )
        return self

    @field_validator("evidence")
    @classmethod
    def _evidence_matches_a_or_b(cls, v: List[ComparisonEvidence]) -> List[ComparisonEvidence]:
        for ev in v:
            if ev.company not in ("A", "B"):
                raise ValueError(f"evidence.company must be A or B, got {ev.company!r}")
        return v


# ---------------- Top-level insights ----------------

_InsightClaim = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class ComparativeInsight(BaseModel):
    """One overall insight the comparator produced.

    The schema enforces the evidence rule: either cite at least one
    evidence ref, or mark the insight as ``insight`` kind with no
    evidence (and the user is responsible for not over-trusting it).
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    claim: _InsightClaim
    kind: ClaimKind = "derived"
    evidence: List[ComparisonEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_or_insight_marker(self) -> "ComparativeInsight":
        if self.kind == "insight":
            return self
        if not self.evidence:
            raise ValueError(
                "ComparativeInsight with kind in {'fact','derived'} must include evidence"
            )
        return self

    @field_validator("evidence")
    @classmethod
    def _evidence_matches_a_or_b(cls, v: List[ComparisonEvidence]) -> List[ComparisonEvidence]:
        for ev in v:
            if ev.company not in ("A", "B"):
                raise ValueError(f"evidence.company must be A or B, got {ev.company!r}")
        return v


# ---------------- Top-level result ----------------

class ComparativeAnalysis(BaseModel):
    """The complete Stage 3 output."""

    model_config = ConfigDict(extra="forbid")

    company_a_name: str = Field(min_length=1)
    company_b_name: str = Field(min_length=1)

    overview_comparison: ComparisonSection
    financial_comparison: ComparisonFinancials
    operational_comparison: ComparisonSection
    business_comparison: ComparisonSection
    strategic_comparison: ComparisonSection
    strengths_comparison: ComparisonSection
    weaknesses_comparison: ComparisonSection
    risks_comparison: ComparisonSection
    important_observations_comparison: ComparisonSection

    trends: List[Trend] = Field(default_factory=list)
    key_differences: List[KeyDifference] = Field(default_factory=list)
    evidence: List[ComparisonEvidence] = Field(default_factory=list)
    overall_comparative_insights: List[ComparativeInsight] = Field(default_factory=list)

    warnings: List[str] = Field(default_factory=list)

    # ---- helpers -----------------------------------------------------

    def cited_evidence(self) -> List[ComparisonEvidence]:
        """Every ComparisonEvidence reachable from this object."""
        seen: List[ComparisonEvidence] = []
        seen.extend(self.overview_comparison.a.evidence)
        seen.extend(self.overview_comparison.b.evidence)
        seen.extend(self.overview_comparison.evidence)
        seen.extend(self.financial_comparison.evidence)
        seen.extend(self.operational_comparison.a.evidence)
        seen.extend(self.operational_comparison.b.evidence)
        seen.extend(self.operational_comparison.evidence)
        seen.extend(self.business_comparison.a.evidence)
        seen.extend(self.business_comparison.b.evidence)
        seen.extend(self.business_comparison.evidence)
        seen.extend(self.strategic_comparison.a.evidence)
        seen.extend(self.strategic_comparison.b.evidence)
        seen.extend(self.strategic_comparison.evidence)
        seen.extend(self.strengths_comparison.a.evidence)
        seen.extend(self.strengths_comparison.b.evidence)
        seen.extend(self.strengths_comparison.evidence)
        seen.extend(self.weaknesses_comparison.a.evidence)
        seen.extend(self.weaknesses_comparison.b.evidence)
        seen.extend(self.weaknesses_comparison.evidence)
        seen.extend(self.risks_comparison.a.evidence)
        seen.extend(self.risks_comparison.b.evidence)
        seen.extend(self.risks_comparison.evidence)
        seen.extend(self.important_observations_comparison.a.evidence)
        seen.extend(self.important_observations_comparison.b.evidence)
        seen.extend(self.important_observations_comparison.evidence)
        seen.extend(self.trends and [ev for t in self.trends for ev in t.evidence] or [])
        seen.extend(self.key_differences and [ev for k in self.key_differences for ev in k.evidence] or [])
        seen.extend(self.evidence)
        seen.extend([ev for ins in self.overall_comparative_insights for ev in ins.evidence])
        return seen


# ---------------- Lifecycle ----------------

class ComparisonRunState(BaseModel):
    """Lifecycle state for the comparator.

    Mirrors ``AgentRunState`` so the API surface is consistent.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["idle", "running", "completed", "failed"] = "idle"
    analysis: Optional[ComparativeAnalysis] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
