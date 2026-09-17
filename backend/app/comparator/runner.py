"""Stage 3 comparator runner.

Public surface (mirrors ``app.agents.runner``):

    run_comparison(analysis_a, analysis_b, *, client=None) -> ComparativeAnalysis
    get_comparison() -> ComparisonRunState
    reset_comparison()
    class ComparisonUnavailableError
    class ComparativeResult              # convenience wrapper with metadata

Pipeline:

    analysis_a + analysis_b
       -> build evidence pack (rendered back to the LLM)
       -> system + user prompt -> LLMClient.complete(json_mode=True)
       -> JSON coercion + schema validation (Pydantic)
       -> fill company/document metadata onto every evidence ref
       -> second-pass validation that each side's evidence matches its company
       -> persist in `_ComparisonRegistry` (process-local)
       -> return ComparativeAnalysis

Isolation guarantees:

    * The user prompt embeds Company A's analysis verbatim under
      "====== Company A analysis ======" and Company B's under
      "====== Company B analysis ======". The model is asked not to mix
      them.
    * Pydantic validators on every ComparisonSide / ComparisonMetric /
      ComparisonEvidence enforce company-label correctness — schema
      itself rejects mismatches.
    * `fill_evidence_metadata` re-stamps `document_name` and `document_sha256`
      onto every ComparisonEvidence using the source analysis.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.agents.llm_client import LLMClient, make_default_client
from app.agents.schemas import AgentAnalysis
from app.comparator.prompts import (
    coerce_llm_json,
    comparative_system_prompt,
    comparative_user_prompt,
)
from app.comparator.schemas import (
    ComparativeAnalysis,
    ComparisonEvidence,
    ComparisonSection,
    ComparisonSide,
    ComparisonRunState,
    ComparisonFinancials,
    ComparisonMetric,
    Trend,
    KeyDifference,
    ComparativeInsight,
)


# ---------------- Errors ----------------

class ComparisonUnavailableError(Exception):
    """Raised when a comparison is requested but one or both inputs are missing."""


class IsolationViolation(Exception):
    """Raised when the comparator is asked to compare the wrong companies, etc."""


# ---------------- Result wrapper ----------------

@dataclass
class ComparativeResult:
    analysis: ComparativeAnalysis
    warnings: List[str]
    elapsed_seconds: float


# ---------------- Internal state ----------------

# A trivial thread-safe registry. Stage 4 may swap this for a DB.
_lock = threading.Lock()


class _ComparisonRegistry:
    """Process-local registry for the single most recent comparison."""

    def __init__(self) -> None:
        self._state = ComparisonRunState()

    def get(self) -> ComparisonRunState:
        return self._state

    def reset(self) -> None:
        with _lock:
            self._state = ComparisonRunState()

    def store(self, analysis: ComparativeAnalysis, warnings: List[str], elapsed: float) -> None:
        with _lock:
            self._state = ComparisonRunState(
                status="completed",
                analysis=analysis,
                error=None,
                started_at=None,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            if warnings:
                # Side-channel: warnings land on the analysis itself.
                analysis.warnings = list(analysis.warnings) + warnings

    def mark_running(self) -> None:
        with _lock:
            self._state = ComparisonRunState(
                status="running",
                analysis=None,
                error=None,
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=None,
            )

    def mark_failed(self, err: str) -> None:
        with _lock:
            self._state = ComparisonRunState(
                status="failed",
                analysis=None,
                error=err,
                started_at=None,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )


_REGISTRY = _ComparisonRegistry()


def get_comparison() -> ComparisonRunState:
    return _REGISTRY.get()


def reset_comparison() -> None:
    _REGISTRY.reset()


# ---------------- Evidence normalisation ----------------

def _stamp_evidence(
    ev: ComparisonEvidence,
    *,
    expected_company: str,
    document_name: str,
    document_sha256: str,
) -> ComparisonEvidence:
    """Re-stamp company/document metadata and double-check company label."""
    if ev.company != expected_company:  # type: ignore[comparison-overlap]
        raise IsolationViolation(
            f"evidence.company={ev.company!r} does not match expected {expected_company!r}"
        )
    return ev.model_copy(
        update={
            "company": ev.company,
            "document_name": document_name or ev.document_name,
            "document_sha256": document_sha256 or ev.document_sha256,
        }
    )


def _fill_section(
    section: ComparisonSection,
    *,
    doc_a_name: str,
    doc_a_sha: str,
    doc_b_name: str,
    doc_b_sha: str,
) -> ComparisonSection:
    new_a = section.a.model_copy(
        update={
            "evidence": [
                _stamp_evidence(
                    e, expected_company="A",
                    document_name=doc_a_name, document_sha256=doc_a_sha,
                )
                for e in section.a.evidence
            ],
            "summary": section.a.summary or "Not available in the provided reports.",
        }
    )
    new_b = section.b.model_copy(
        update={
            "evidence": [
                _stamp_evidence(
                    e, expected_company="B",
                    document_name=doc_b_name, document_sha256=doc_b_sha,
                )
                for e in section.b.evidence
            ],
            "summary": section.b.summary or "Not available in the provided reports.",
        }
    )
    new_section = section.model_copy(update={"a": new_a, "b": new_b})
    # Re-validate so the validators re-run on the rebuilt evidence.
    return ComparisonSection.model_validate(new_section.model_dump())


def _fill_financials(
    f: ComparisonFinancials,
    *,
    doc_a_name: str,
    doc_a_sha: str,
    doc_b_name: str,
    doc_b_sha: str,
) -> ComparisonFinancials:
    new_a = [
        m.model_copy(
            update={
                "evidence": [
                    _stamp_evidence(
                        e, expected_company="A",
                        document_name=doc_a_name, document_sha256=doc_a_sha,
                    )
                    for e in m.evidence
                ],
                "value_text": m.value_text or "Not available in the provided reports.",
            }
        )
        for m in f.a
    ]
    new_b = [
        m.model_copy(
            update={
                "evidence": [
                    _stamp_evidence(
                        e, expected_company="B",
                        document_name=doc_b_name, document_sha256=doc_b_sha,
                    )
                    for e in m.evidence
                ],
                "value_text": m.value_text or "Not available in the provided reports.",
            }
        )
        for m in f.b
    ]
    new_f = f.model_copy(update={"a": new_a, "b": new_b})
    return ComparisonFinancials.model_validate(new_f.model_dump())


def _fill_evidence_list(
    items: List[ComparisonEvidence],
    *,
    doc_a_name: str,
    doc_a_sha: str,
    doc_b_name: str,
    doc_b_sha: str,
) -> List[ComparisonEvidence]:
    out: List[ComparisonEvidence] = []
    for ev in items:
        if ev.company == "A":  # type: ignore[comparison-overlap]
            out.append(_stamp_evidence(ev, expected_company="A",
                                       document_name=doc_a_name, document_sha256=doc_a_sha))
        elif ev.company == "B":  # type: ignore[comparison-overlap]
            out.append(_stamp_evidence(ev, expected_company="B",
                                       document_name=doc_b_name, document_sha256=doc_b_sha))
        else:
            raise IsolationViolation(f"evidence.company must be A or B, got {ev.company!r}")
    return out


# ---------------- Shape normalisation ----------------

def _safe_section(a_dict: Dict[str, Any], b_dict: Dict[str, Any], narrative: str = "") -> Dict[str, Any]:
    return {
        "a": {
            "company": "A",
            "summary": (a_dict.get("summary") if isinstance(a_dict, dict) else None) or "Not available in the provided reports.",
            "evidence": (a_dict.get("evidence") if isinstance(a_dict, dict) else None) or [],
        },
        "b": {
            "company": "B",
            "summary": (b_dict.get("summary") if isinstance(b_dict, dict) else None) or "Not available in the provided reports.",
            "evidence": (b_dict.get("evidence") if isinstance(b_dict, dict) else None) or [],
        },
        "narrative": narrative or "Not available in the provided reports.",
        "narrative_kind": "derived",
        "evidence": [],
    }


def _empty_analysis(
    analysis_a: AgentAnalysis,
    analysis_b: AgentAnalysis,
    *,
    warnings: List[str],
) -> ComparativeAnalysis:
    """Build a fully-typed but minimal ComparativeAnalysis."""
    empty_side_a = {"company": "A", "summary": "Not available in the provided reports.", "evidence": []}
    empty_side_b = {"company": "B", "summary": "Not available in the provided reports.", "evidence": []}

    def section() -> Dict[str, Any]:
        return {
            "a": empty_side_a,
            "b": empty_side_b,
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight",
            "evidence": [],
        }

    payload: Dict[str, Any] = {
        "company_a_name": analysis_a.document_name,
        "company_b_name": analysis_b.document_name,
        "overview_comparison": section(),
        "financial_comparison": {
            "a": [], "b": [],
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight",
            "evidence": [],
        },
        "operational_comparison": section(),
        "business_comparison": section(),
        "strategic_comparison": section(),
        "strengths_comparison": section(),
        "weaknesses_comparison": section(),
        "risks_comparison": section(),
        "important_observations_comparison": section(),
        "trends": [],
        "key_differences": [],
        "evidence": [],
        "overall_comparative_insights": [],
        "warnings": warnings,
    }
    return ComparativeAnalysis.model_validate(payload)


def _normalise_compared_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Tolerate shape drift from the LLM.

    Ensures every section has both 'a' and 'b' sides, no missing keys,
    and every list is a list.
    """
    def _ensure_section(key: str) -> None:
        sec = parsed.get(key)
        if not isinstance(sec, dict):
            parsed[key] = _safe_section({}, {}, narrative="")
            return
        parsed[key] = _safe_section(
            sec.get("a") if isinstance(sec.get("a"), dict) else {},
            sec.get("b") if isinstance(sec.get("b"), dict) else {},
            narrative=sec.get("narrative", "") if isinstance(sec.get("narrative"), str) else "",
        )

    for key in (
        "overview_comparison",
        "operational_comparison",
        "business_comparison",
        "strategic_comparison",
        "strengths_comparison",
        "weaknesses_comparison",
        "risks_comparison",
        "important_observations_comparison",
    ):
        _ensure_section(key)

    fp = parsed.get("financial_comparison")
    if not isinstance(fp, dict):
        parsed["financial_comparison"] = {
            "a": [], "b": [],
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight",
            "evidence": [],
        }
    else:
        fp.setdefault("a", [])
        fp.setdefault("b", [])
        if not isinstance(fp.get("a"), list):
            fp["a"] = []
        if not isinstance(fp.get("b"), list):
            fp["b"] = []
        if not (fp.get("narrative") or "").strip():
            fp["narrative"] = "Not available in the provided reports."
        fp.setdefault("evidence", [])
        parsed["financial_comparison"] = fp

    for key in ("trends", "key_differences", "evidence", "overall_comparative_insights", "warnings"):
        if not isinstance(parsed.get(key), list):
            parsed[key] = []

    return parsed


# ---------------- Public API ----------------

def run_comparison(
    analysis_a: AgentAnalysis,
    analysis_b: AgentAnalysis,
    *,
    client: Optional[LLMClient] = None,
) -> ComparativeResult:
    """Run the comparator and return a structured result.

    Raises ComparisonUnavailableError for caller-side misuse (Stage 3 is
    called only after Stage 2 has produced both analyses).
    """
    if not isinstance(analysis_a, AgentAnalysis):
        raise ComparisonUnavailableError("company A analysis is missing or wrong type")
    if not isinstance(analysis_b, AgentAnalysis):
        raise ComparisonUnavailableError("company B analysis is missing or wrong type")
    if analysis_a.company != "A":
        raise ComparisonUnavailableError("first analysis must be for Company A")
    if analysis_b.company != "B":
        raise ComparisonUnavailableError("second analysis must be for Company B")

    _REGISTRY.mark_running()
    started = time.monotonic()
    warnings: List[str] = []

    sys_prompt = comparative_system_prompt()
    usr_prompt = comparative_user_prompt(analysis_a, analysis_b)

    if client is None:
        client = make_default_client()

    raw = client.complete(system=sys_prompt, user=usr_prompt, json_mode=True)
    try:
        parsed = coerce_llm_json(raw)
    except Exception as exc:
        _REGISTRY.mark_failed(f"could not parse comparator JSON: {exc}")
        raise

    # Pre-stamp document names so the schema accepts them.
    parsed.setdefault("company_a_name", analysis_a.document_name)
    parsed.setdefault("company_b_name", analysis_b.document_name)

    normalised = _normalise_compared_payload(parsed)

    try:
        analysis = ComparativeAnalysis.model_validate(normalised)
    except ValidationError as exc:
        _REGISTRY.mark_failed(f"comparator JSON failed schema validation: {exc}")
        raise

    # Re-stamp metadata + re-validate to enforce isolation at the object level.
    doc_a_name = analysis_a.document_name
    doc_a_sha = analysis_a.document_sha256
    doc_b_name = analysis_b.document_name
    doc_b_sha = analysis_b.document_sha256

    analysis = analysis.model_copy(
        update={
            "overview_comparison": _fill_section(
                analysis.overview_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "financial_comparison": _fill_financials(
                analysis.financial_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "operational_comparison": _fill_section(
                analysis.operational_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "business_comparison": _fill_section(
                analysis.business_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "strategic_comparison": _fill_section(
                analysis.strategic_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "strengths_comparison": _fill_section(
                analysis.strengths_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "weaknesses_comparison": _fill_section(
                analysis.weaknesses_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "risks_comparison": _fill_section(
                analysis.risks_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "important_observations_comparison": _fill_section(
                analysis.important_observations_comparison,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "trends": [
                t.model_copy(update={"evidence": _fill_evidence_list(
                    t.evidence,
                    doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                    doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
                )})
                for t in analysis.trends
            ],
            "key_differences": [
                k.model_copy(update={"evidence": _fill_evidence_list(
                    k.evidence,
                    doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                    doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
                )})
                for k in analysis.key_differences
            ],
            "evidence": _fill_evidence_list(
                analysis.evidence,
                doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
            ),
            "overall_comparative_insights": [
                i.model_copy(update={"evidence": _fill_evidence_list(
                    i.evidence,
                    doc_a_name=doc_a_name, doc_a_sha=doc_a_sha,
                    doc_b_name=doc_b_name, doc_b_sha=doc_b_sha,
                )})
                for i in analysis.overall_comparative_insights
            ],
        }
    )

    # Final re-validation — this also re-runs the validators on every ref.
    analysis = ComparativeAnalysis.model_validate(analysis.model_dump())

    elapsed = time.monotonic() - started
    _REGISTRY.store(analysis, warnings, elapsed)

    return ComparativeResult(analysis=analysis, warnings=warnings, elapsed_seconds=elapsed)
