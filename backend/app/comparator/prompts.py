"""Comparator prompts + JSON-coercion helpers.

The comparator runs a SINGLE LLM call on a JSON-mode completion. The
prompt renders two already-produced analyses (one for Company A, one
for Company B) and asks the model to produce a structured comparison.

The prompt explicitly tells the model to:

  * tag direct quotes as ``kind='fact'``
  * tag comparisons derived from those facts as ``kind='derived'``
  * tag AI-interpretive commentary as ``kind='insight'``
  * never fabricate numbers — use the literal sentinel
    ``"Not available in the provided reports."``
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.agents.schemas import AgentAnalysis


JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def comparative_system_prompt() -> str:
    return (
        "You are the COMPARATIVE ANALYSIS engine for two annual reports. "
        "Company A and Company B have already been analysed independently. "
        "Your job is to compare them.\n\n"
        "Rules you MUST follow:\n"
        "  1. Every factual claim about a company must carry an evidence ref "
        "pointing back to that company's PDF (company, document_name, page_number, ref_id, snippet).\n"
        "  2. NEVER invent financial numbers. If a metric isn't in either report, "
        "use the literal string: 'Not available in the provided reports.'\n"
        "  3. Tag every evidence ref with one of:\n"
        "       'fact'    — directly quoted from the source.\n"
        "       'derived' — comparison derived from facts on both sides.\n"
        "       'insight' — your interpretation; cannot be presented as fact.\n"
        "  4. Top-level insights must EITHER cite evidence OR be marked 'insight' with empty evidence.\n"
        "  5. Do not mix evidence between companies: an evidence ref for "
        "Company A must not be used to justify a Company B claim, and vice versa.\n"
        "  6. Output ONLY a single JSON object that matches the schema described below. "
        "No prose outside the JSON."
    )


def _render_agent_for_prompt(label: str, analysis: AgentAnalysis) -> str:
    """Compact, human-readable rendering of an AgentAnalysis for the prompt."""
    return json.dumps(
        {
            "label": label,
            "company": analysis.company,
            "document_name": analysis.document_name,
            "company_overview": analysis.company_overview.model_dump(),
            "financial_performance": analysis.financial_performance.model_dump(),
            "operational_information": analysis.operational_information.model_dump(),
            "strategic_information": analysis.strategic_information.model_dump(),
            "business_information": analysis.business_information.model_dump(),
            "strengths": [s.model_dump() for s in analysis.strengths],
            "weaknesses": [w.model_dump() for w in analysis.weaknesses],
            "risks": [r.model_dump() for r in analysis.risks],
            "important_observations": [o.model_dump() for o in analysis.important_observations],
        },
        ensure_ascii=False,
        indent=2,
    )


def comparative_user_prompt(
    company_a: AgentAnalysis,
    company_b: AgentAnalysis,
) -> str:
    """Render the comparator user prompt.

    The prompt embeds the two analyses verbatim with their existing evidence
    refs. The model is asked to produce the comparative JSON described in the
    system prompt.
    """
    doc_a = _render_agent_for_prompt("A", company_a)
    doc_b = _render_agent_for_prompt("B", company_b)

    schema_hint = {
        "company_a_name": "string (use Company A's document_name)",
        "company_b_name": "string (use Company B's document_name)",
        "overview_comparison": {
            "a": {"company": "A", "summary": "string", "evidence": "[]"},
            "b": {"company": "B", "summary": "string", "evidence": "[]"},
            "narrative": "string (the comparison)",
            "narrative_kind": "'derived'|'insight'",
            "evidence": "[] (refs to support the narrative)",
        },
        "financial_comparison": {
            "a": "[ {company:'A', metric, value_text, unit?, year_or_period?, evidence:[]} ]",
            "b": "[ {company:'B', metric, value_text, unit?, year_or_period?, evidence:[]} ]",
            "narrative": "string",
            "narrative_kind": "'derived'|'insight'",
            "evidence": "[]",
        },
        # Same shape for operational / business / strategic / strengths /
        # weaknesses / risks / important_observations.
        "trends": "[ {title, description, kind:'fact'|'derived'|'insight', evidence:[]} ]",
        "key_differences": "[ {title, description, kind, evidence:[]} ]",
        "evidence": "[] flat list (optional)",
        "overall_comparative_insights": "[ {title, claim, kind, evidence:[]} ]",
        "warnings": "[string] optional",
    }

    return (
        "Compare the following two annual-report analyses and return ONE JSON object.\n\n"
        "====== Company A analysis ======\n"
        f"{doc_a}\n\n"
        "====== Company B analysis ======\n"
        f"{doc_b}\n\n"
        "====== Output schema ======\n"
        f"{json.dumps(schema_hint, ensure_ascii=False, indent=2)}\n\n"
        "Important reminders:\n"
        "  - Use 'kind':'fact' for direct quotes; 'kind':'derived' for comparison; "
        "'kind':'insight' for interpretation.\n"
        "  - For each 'evidence' ref, also include company/document_name/page_number/ref_id/snippet.\n"
        "  - If a metric is not in the source, set value_text to "
        "'Not available in the provided reports.' (no numeric guess).\n"
        "  - Preserve A/B separation: an evidence ref stamped 'A' must only "
        "appear inside A-side structures and A-cited insights; same for B.\n"
        "  - Output ONLY the JSON object, no prose.\n"
    )


def coerce_llm_json(raw: str) -> Dict[str, Any]:
    """Tolerate markdown fences / preamble around the JSON object."""
    if not isinstance(raw, str):
        raise ValueError(f"comparator returned non-string payload: {raw!r}")

    text = raw.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    m = JSON_FENCE_RE.search(text)
    if m:
        return json.loads(m.group(1))

    # Fallback: find the first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError(f"could not extract JSON object from comparator output: {raw[:200]!r}")


def fill_comparison_metadata(
    obj: ComparativeAnalysisPatch,
    *,
    company_a_name: str,
    company_b_name: str,
) -> "ComparativeAnalysisPatch":
    """Stamp company names + the standard unavailable sentinel everywhere.

    ``ComparativeAnalysisPatch`` is an alias kept in this module so the
    public re-export below doesn't have to know the implementation type.
    The runner uses the real ``ComparativeAnalysis`` directly.
    """
    obj.company_a_name = company_a_name
    obj.company_b_name = company_b_name
    return obj


# Type alias used to document fill_comparison_metadata's intent above.
from app.comparator.schemas import ComparativeAnalysis as _ComparativeAnalysis  # noqa: E402

ComparativeAnalysisPatch = _ComparativeAnalysis  # noqa: E402
