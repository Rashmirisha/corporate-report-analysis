"""Prompt construction for Stage 2 agents.

Why a separate module?
- Keeps the agent runner focused on flow control.
- Lets us unit-test prompt content directly (so "agent A never sees
  company B's name in its prompt" can be asserted).
"""
from __future__ import annotations

from typing import List, Sequence

from app.agents.schemas import AgentAnalysis
from app.retrieval.retriever import RetrievalHit


# ---------- system prompt ----------

def system_prompt(company: str) -> str:
    return f"""You are Agent {company}, an independent analyst that specialises in
reading ONE annual report (the entire uploaded report for Company {company}).
You never receive any other company's report or analysis.

Your job: produce a structured, fully evidence-grounded JSON analysis.

Strict rules you MUST obey:

1. ONLY use facts present in the EVIDENCE PACK you are given. Do not use
   outside knowledge. Do not invent numbers, names, percentages, or claims.
2. Every claim MUST carry at least one evidence citation (page_number +
   ref_id from the evidence pack), except the literal string
   "Not available in the provided report." (used when a section is missing).
3. For financial metrics, the `value_text` field must be either an exact
   value as written in the source (do not round, do not infer) OR the
   exact string "Not available in the provided report.".
4. Cite the closest matching chunk or table. If a metric appears in a
   table, cite the table_id; if in prose, cite the chunk_id.
5. Never mention the other company by name. You do not know about them.
6. Output strictly valid JSON that matches the schema described below.
   No prose, no markdown fences, no commentary.

JSON schema (illustrative — fields vary per section):

{{
  "company": "{company}",
  "company_overview":          {{ "summary": "...", "evidence": [...] }},
  "financial_performance":     {{
    "summary": "...",
    "key_metrics": [{{ "metric": "...", "value_text": "...", "unit": "...", "year_or_period": "...", "evidence": [...] }}],
    "evidence": [...]
  }},
  "operational_information":   {{ "summary": "...", "evidence": [...] }},
  "strategic_information":     {{ "summary": "...", "evidence": [...] }},
  "business_information":      {{ "summary": "...", "evidence": [...] }},
  "strengths":                 [{{ "point": "...", "evidence": [...] }}],
  "weaknesses":                [{{ "point": "...", "evidence": [...] }}],
  "risks":                     [{{ "point": "...", "evidence": [...] }}],
  "important_observations":    [{{ "point": "...", "evidence": [...] }}],
  "warnings":                  ["..."]
}}

Each evidence object must be exactly:
{{
  "company": "{company}",
  "document_name": "...",
  "document_sha256": "...",
  "page_number": <int>,
  "kind": "chunk" | "table",
  "ref_id": "...",
  "snippet": "..."
}}
"""


# ---------- user prompt ----------

def user_prompt(company: str, document_name: str, page_count: int, hits: Sequence[RetrievalHit]) -> str:
    sections: List[str] = [
        f"Company: Company {company}",
        f"Document: {document_name}",
        f"Total pages: {page_count}",
        "",
        "Below is the EVIDENCE PACK — the only source you may use.",
        "Cite by ref_id exactly as shown.",
        "",
    ]
    if not hits:
        sections.append("(No evidence chunks were retrieved — every section should be marked unavailable.)")
        sections.append("")
    for i, hit in enumerate(hits, start=1):
        sections.append(
            f"--- EVIDENCE #{i} ---\n"
            f"id: {hit.id}\n"
            f"kind: {hit.kind}\n"
            f"page: {hit.page_number}\n"
            f"company: {hit.company}\n"
            f"document_name: {hit.document_name}\n"
            f"document_sha256: {hit.document_sha256}\n"
            f"snippet:\n{hit.snippet}\n"
        )

    sections.append("--- END EVIDENCE PACK ---")
    sections.append("")
    sections.append("Now produce the JSON analysis. Follow the schema. Cite every claim.")
    return "\n".join(sections)


# ---------- retrieval query construction ----------

# One query per top-level section. Each is biased toward the kind of content
# the agent needs to find in the report.
DEFAULT_QUERIES = [
    "company overview business description",
    "financial performance revenue profit margin",
    "balance sheet assets liabilities",
    "operations segments products services",
    "strategy growth expansion plans",
    "strengths competitive advantages",
    "weaknesses challenges concerns",
    "risks risk factors uncertainties",
    "important observations outlook",
]


def default_queries() -> List[str]:
    return list(DEFAULT_QUERIES)


# ---------- post-processing helpers ----------

def coerce_llm_json(text: str) -> dict:
    """Parse LLM output into JSON. Tolerates markdown fences."""
    s = text.strip()
    if s.startswith("```"):
        # strip first fence line
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
    import json as _json

    try:
        return _json.loads(s)
    except _json.JSONDecodeError:
        # Last-ditch: locate the first '{' and last '}'
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            return _json.loads(s[start : end + 1])
        raise


def fill_company_metadata(analysis: AgentAnalysis, *, company: str, document_name: str, document_sha256: str, page_count: int) -> AgentAnalysis:
    """Make sure every EvidenceRef carries our company + doc metadata, even
    if the model forgot. Pydantic will then validate the rest."""
    sec_attrs = [
        "company_overview",
        "operational_information",
        "strategic_information",
        "business_information",
        "financial_performance",
    ]
    data = analysis.model_dump()
    data["company"] = company
    data["document_name"] = document_name
    data["document_sha256"] = document_sha256
    data["page_count"] = page_count

    def fix_evidence(refs):
        for r in refs or []:
            if r.get("company") != company:
                r["company"] = company
            # Always stamp document metadata onto evidence refs: the source
            # of truth is the Stage-1 state, not whatever the LLM echoed back.
            r["document_name"] = document_name
            r["document_sha256"] = document_sha256
        return refs

    for attr in sec_attrs:
        sec = data.get(attr, {})
        if isinstance(sec, dict) and "evidence" in sec:
            sec["evidence"] = fix_evidence(sec.get("evidence", []))
        if attr == "financial_performance" and isinstance(sec, dict):
            for m in sec.get("key_metrics", []) or []:
                m["evidence"] = fix_evidence(m.get("evidence", []))

    for group_name in ("strengths", "weaknesses", "risks", "important_observations"):
        for entry in data.get(group_name, []) or []:
            entry["evidence"] = fix_evidence(entry.get("evidence", []))

    return AgentAnalysis.model_validate(data)


__all__ = [
    "system_prompt",
    "user_prompt",
    "default_queries",
    "coerce_llm_json",
    "fill_company_metadata",
]
