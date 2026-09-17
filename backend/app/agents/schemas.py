"""Stage 2 Pydantic models — agent output contract.

Stage 3 consumes this exact shape. Every claim has EvidenceRef objects
that point at Stage-1 chunk/table IDs.

Two ground rules enforced by the schema:

1. `evidence` is non-empty for any `Evidence`-bearing claim unless the
   claim is the literal string "Not available in the provided report."
2. Financial-style fields force every claim to carry evidence — Stage-2
   validation raises if a numeric claim lands here without a citation.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas import Company, TableRecord, TextChunk


# ---------- evidence ----------

class EvidenceRef(BaseModel):
    """Citation linking a claim back to a Stage-1 chunk or table."""
    company: Company
    document_name: str
    document_sha256: str
    page_number: int = Field(..., ge=1)
    kind: Literal["chunk", "table"] = "chunk"
    ref_id: str = Field(..., description="chunk_id or table_id from Stage 1")
    snippet: str = Field(..., min_length=1, max_length=600)


class TextWithEvidence(BaseModel):
    """A free-text claim backed by evidence."""
    claim: str = Field(..., min_length=1)
    evidence: List[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_required_unless_unavailable(self) -> "TextWithEvidence":
        stripped = self.claim.strip().lower()
        is_unavailable = stripped == "not available in the provided report." or stripped == "not available in the provided report"
        if not is_unavailable and not self.evidence:
            raise ValueError(
                "claim must include at least one evidence citation "
                "unless it is exactly 'Not available in the provided report.'"
            )
        return self


class BulletWithEvidence(BaseModel):
    """A single bullet-point observation backed by evidence."""
    point: str = Field(..., min_length=1)
    evidence: List[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_required_unless_unavailable(self) -> "BulletWithEvidence":
        stripped = self.point.strip().lower()
        is_unavailable = "not available" in stripped and "provided report" in stripped
        if not is_unavailable and not self.evidence:
            raise ValueError("bullet point must include evidence (or be marked unavailable)")
        return self


# ---------- structured sections ----------

class EvidenceBlock(BaseModel):
    """A section of the agent output: a summary plus supporting claims."""
    summary: str = Field(..., min_length=1)
    evidence: List[EvidenceRef] = Field(default_factory=list)


class FinancialMetric(BaseModel):
    """One named numeric metric. Strong evidence requirement.

    If `value_text` is "Not available in the provided report." it's accepted
    as-is without evidence. Otherwise evidence must be non-empty.
    """
    metric: str = Field(..., min_length=1)
    value_text: str = Field(..., min_length=1)
    unit: Optional[str] = None  # e.g. "INR crore", "USD millions", "%"
    year_or_period: Optional[str] = None
    evidence: List[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_unless_unavailable(self) -> "FinancialMetric":
        stripped = self.value_text.strip().lower()
        is_unavailable = "not available" in stripped
        if not is_unavailable and not self.evidence:
            raise ValueError(
                f"financial metric '{self.metric}' must include evidence; "
                "set value_text to 'Not available in the provided report.' to skip."
            )
        return self


class FinancialPerformance(BaseModel):
    summary: str = Field(..., min_length=1)
    key_metrics: List[FinancialMetric] = Field(default_factory=list)
    evidence: List[EvidenceRef] = Field(default_factory=list)


# ---------- the full agent output ----------

class AgentAnalysis(BaseModel):
    """Complete analysis output for ONE company.

    This is the contract Stage 3 consumes. It carries its own evidence;
    Stage 3 never has to re-read Stage-1 chunks to verify grounding.
    """
    company: Company
    document_name: str
    document_sha256: str
    page_count: int

    company_overview: EvidenceBlock
    financial_performance: FinancialPerformance
    operational_information: EvidenceBlock
    strategic_information: EvidenceBlock
    business_information: EvidenceBlock

    strengths: List[BulletWithEvidence]
    weaknesses: List[BulletWithEvidence]
    risks: List[BulletWithEvidence]
    important_observations: List[BulletWithEvidence]

    # The list of chunks and tables the agent actually consumed. Lets Stage
    # 3 and the dashboard trace evidence back to the source PDF without
    # re-running retrieval.
    referenced_chunk_ids: List[str] = Field(default_factory=list)
    referenced_table_ids: List[str] = Field(default_factory=list)

    warnings: List[str] = Field(default_factory=list)

    def cited_evidence(self) -> List[EvidenceRef]:
        out: List[EvidenceRef] = []
        for sec in (
            self.company_overview,
            self.operational_information,
            self.strategic_information,
            self.business_information,
        ):
            out.extend(sec.evidence)
        out.extend(self.financial_performance.evidence)
        for bm in self.financial_performance.key_metrics:
            out.extend(bm.evidence)
        for group in (self.strengths, self.weaknesses, self.risks, self.important_observations):
            for b in group:
                out.extend(b.evidence)
        return out

    def references_resolved(self, chunks: List[TextChunk], tables: List[TableRecord]) -> List[str]:
        """List of evidence refs that DID NOT resolve against the supplied
        Stage-1 state. Empty list = every citation points at a real chunk
        or table."""
        chunk_ids = {c.chunk_id for c in chunks}
        table_ids = {t.table_id for t in tables}
        unresolved: List[str] = []
        for ref in self.cited_evidence():
            if ref.kind == "chunk" and ref.ref_id not in chunk_ids:
                unresolved.append(ref.ref_id)
            elif ref.kind == "table" and ref.ref_id not in table_ids:
                unresolved.append(ref.ref_id)
        return unresolved


# ---------- call status ----------

AgentStatus = Literal["idle", "running", "completed", "failed"]


class AgentRunState(BaseModel):
    company: Company
    status: AgentStatus
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    analysis: Optional[AgentAnalysis] = None
