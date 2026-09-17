"""Stage 3 end-to-end smoke test.

Runs the full pipeline with stubbed agents + stubbed comparator:
  upload PDFs  ->  run Agent A and Agent B  ->  run the comparator
                  ->  print the comparative JSON
                  ->  verify isolation and evidence preservation.

No network, no Ollama calls (pure stub-mode smoke test).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
os.environ["CRA_LLM_STUB"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.agents.llm_client import StubLLMClient  # noqa: E402
from app.storage import store  # noqa: E402
from app.agents import runner as agent_runner  # noqa: E402
from app.comparator import runner as comp_runner  # noqa: E402
from app.tests._fixtures import build_minimal_pdf_two_pages  # noqa: E402


def _stub_agent(company: str, doc_name: str, sha: str) -> StubLLMClient:
    payload = {
        "company": company,
        "company_overview": {
            "summary": f"{company} is an established player in its sector.",
            "evidence": [{
                "company": company, "document_name": doc_name,
                "document_sha256": sha, "page_number": 1,
                "kind": "chunk", "ref_id": f"{company}_{sha[:12]}_p001_c000",
                "snippet": f"{company} operates in its core business segment.",
            }],
        },
        "financial_performance": {"summary": "Revenue and profit figures follow the financial highlights.",
                                 "key_metrics": [{"metric": "Revenue",
                                                  "value_text": "Not available in the provided report.",
                                                  "evidence": []}],
                                 "evidence": []},
        "operational_information": {"summary": "Operations span multiple regions.", "evidence": []},
        "strategic_information": {"summary": "Strategy emphasises core markets.", "evidence": []},
        "business_information": {"summary": "Business operates in industrial goods." if company == "A" else "Business operates in logistics.",
                                  "evidence": []},
        "strengths": [{"point": "Strong brand presence.",
                       "evidence": [{
                           "company": company, "document_name": doc_name,
                           "document_sha256": sha, "page_number": 1,
                           "kind": "chunk", "ref_id": f"{company}_{sha[:12]}_p002_c000",
                           "snippet": "Brand presence is strong across regions.",
                       }]}],
        "weaknesses": [],
        "risks": [{"point": "External headwinds affect margins.",
                   "evidence": [{
                       "company": company, "document_name": doc_name,
                       "document_sha256": sha, "page_number": 2,
                       "kind": "chunk", "ref_id": f"{company}_{sha[:12]}_p002_c001",
                       "snippet": "Headwinds flagged.",
                   }]}],
        "important_observations": [],
    }
    s = StubLLMClient()
    s.expect(system_contains=f"Agent {company}", user_contains=doc_name, response=json.dumps(payload))
    return s


def _stub_comparator(a_name: str, a_sha: str, b_name: str, b_sha: str) -> StubLLMClient:
    payload = {
        "company_a_name": a_name,
        "company_b_name": b_name,
        "overview_comparison": {
            "a": {"company": "A", "summary": "Acme is a manufacturer.",
                  "evidence": [{"company": "A", "document_name": a_name, "document_sha256": a_sha,
                                "page_number": 1, "ref_kind": "chunk",
                                "ref_id": f"A_{a_sha[:12]}_p001_c000",
                                "snippet": "Acme manufactures widgets.", "kind": "fact"}]},
            "b": {"company": "B", "summary": "Globex is a logistics company.",
                  "evidence": [{"company": "B", "document_name": b_name, "document_sha256": b_sha,
                                "page_number": 1, "ref_kind": "chunk",
                                "ref_id": f"B_{b_sha[:12]}_p001_c000",
                                "snippet": "Globex provides logistics.", "kind": "fact"}]},
            "narrative": "Acme manufactures widgets; Globex provides logistics — different industries.",
            "narrative_kind": "derived", "evidence": [],
        },
        "financial_comparison": {
            "a": [{"company": "A", "metric": "Revenue",
                   "value_text": "Not available in the provided reports.",
                   "evidence": []}],
            "b": [{"company": "B", "metric": "Revenue",
                   "value_text": "Not available in the provided reports.",
                   "evidence": []}],
            "narrative": "Neither report states a comparable revenue figure.",
            "narrative_kind": "insight", "evidence": [],
        },
        "operational_comparison": {
            "a": {"company": "A", "summary": "Plants in 5 regions.", "evidence": []},
            "b": {"company": "B", "summary": "Fleet of 200 trucks.", "evidence": []},
            "narrative": "Different asset bases: factories vs fleet.",
            "narrative_kind": "derived", "evidence": [],
        },
        "business_comparison": {
            "a": {"company": "A", "summary": "Industrial goods.", "evidence": []},
            "b": {"company": "B", "summary": "Logistics services.", "evidence": []},
            "narrative": "Different industries.", "narrative_kind": "derived", "evidence": [],
        },
        "strategic_comparison": {
            "a": {"company": "A", "summary": "Expansion plan.", "evidence": []},
            "b": {"company": "B", "summary": "Cost optimisation.", "evidence": []},
            "narrative": "Acme grows, Globex tightens.",
            "narrative_kind": "derived", "evidence": [],
        },
        "strengths_comparison": {
            "a": {"company": "A", "summary": "Strong brand.",
                  "evidence": [{"company": "A", "document_name": a_name, "document_sha256": a_sha,
                                "page_number": 1, "ref_kind": "chunk",
                                "ref_id": f"A_{a_sha[:12]}_p002_c000",
                                "snippet": "Brand presence strong.", "kind": "fact"}]},
            "b": {"company": "B", "summary": "Not available in the provided reports.",
                  "evidence": []},
            "narrative": "Acme highlights a brand strength; Globex does not surface one.",
            "narrative_kind": "derived", "evidence": [],
        },
        "weaknesses_comparison": {
            "a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
            "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight", "evidence": [],
        },
        "risks_comparison": {
            "a": {"company": "A", "summary": "External headwinds.", "evidence": []},
            "b": {"company": "B", "summary": "External headwinds.", "evidence": []},
            "narrative": "Both flag external headwinds.",
            "narrative_kind": "derived", "evidence": [],
        },
        "important_observations_comparison": {
            "a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
            "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight", "evidence": [],
        },
        "trends": [{
            "title": "Both face external headwinds",
            "description": "Each company flagged margin pressure from outside forces.",
            "kind": "derived",
            "evidence": [
                {"company": "A", "document_name": a_name, "document_sha256": a_sha,
                 "page_number": 2, "ref_kind": "chunk", "ref_id": f"A_{a_sha[:12]}_p002_c001",
                 "snippet": "Headwinds flagged.", "kind": "fact"},
                {"company": "B", "document_name": b_name, "document_sha256": b_sha,
                 "page_number": 2, "ref_kind": "chunk", "ref_id": f"B_{b_sha[:12]}_p002_c001",
                 "snippet": "Headwinds flagged.", "kind": "fact"},
            ],
        }],
        "key_differences": [{
            "title": "Industry and growth direction",
            "description": "Acme manufactures widgets and is expanding; Globex runs logistics and is cutting costs.",
            "kind": "derived",
            "evidence": [
                {"company": "A", "document_name": a_name, "document_sha256": a_sha,
                 "page_number": 1, "ref_kind": "chunk", "ref_id": f"A_{a_sha[:12]}_p001_c000",
                 "snippet": "Acme is a manufacturer of widgets.", "kind": "fact"},
                {"company": "B", "document_name": b_name, "document_sha256": b_sha,
                 "page_number": 1, "ref_kind": "chunk", "ref_id": f"B_{b_sha[:12]}_p001_c000",
                 "snippet": "Globex provides logistics services.", "kind": "fact"},
            ],
        }],
        "evidence": [],
        "overall_comparative_insights": [{
            "title": "Different industries, different strengths",
            "claim": "Acme and Globex operate in distinct sectors with sector-specific strengths.",
            "kind": "insight",
            "evidence": [],
        }],
        "warnings": [],
    }
    s = StubLLMClient()
    s.expect(system_contains="COMPARATIVE ANALYSIS",
             user_contains="Acme.pdf",
             response=json.dumps(payload))
    return s


def main() -> int:
    store.reset()
    agent_runner.reset_state("A")
    agent_runner.reset_state("B")
    comp_runner.reset_comparison()

    pdf_a = build_minimal_pdf_two_pages(
        "Acme Corp Annual Report FY24. Acme is a manufacturer of widgets in EMEA and APAC.",
        "Acme faces external headwinds and supply-chain risks in FY24.",
    )
    pdf_b = build_minimal_pdf_two_pages(
        "Globex Industries Annual Report FY24. Globex provides logistics services globally.",
        "Globex faces external headwinds and regulatory pressure in FY24.",
    )

    with TestClient(app) as client:
        up_a = client.post("/api/ingest/upload", data={"company": "A"},
                           files={"file": ("Acme.pdf", pdf_a, "application/pdf")}).json()
        up_b = client.post("/api/ingest/upload", data={"company": "B"},
                           files={"file": ("Globex.pdf", pdf_b, "application/pdf")}).json()
        a_name, a_sha = up_a["document_name"], up_a["document_sha256"]
        b_name, b_sha = up_b["document_name"], up_b["document_sha256"]
        print(f"Uploaded A: {a_name}")
        print(f"Uploaded B: {b_name}")

        # Stage 2 stubbed agents.
        agent_q = iter([_stub_agent("A", a_name, a_sha), _stub_agent("B", b_name, b_sha)])
        original_agent_factory = agent_runner.make_default_client
        agent_runner.make_default_client = lambda *, force_stub=False: next(agent_q)  # type: ignore[assignment]
        try:
            r = client.post("/api/agents/run", params={"target": "both"})
            r.raise_for_status()
        finally:
            agent_runner.make_default_client = original_agent_factory  # type: ignore[assignment]
        print("Agents: OK")

        # Stage 3 stubbed comparator.
        original_comp_factory = comp_runner.make_default_client
        comp_runner.make_default_client = lambda *, force_stub=False: _stub_comparator(a_name, a_sha, b_name, b_sha)  # type: ignore[assignment]
        try:
            r = client.post("/api/comparison/run")
            r.raise_for_status()
        finally:
            comp_runner.make_default_client = original_comp_factory  # type: ignore[assignment]
        comp = r.json()
        print("Comparator: OK")

        # Verification.
        print()
        print(f"company_a_name: {comp['company_a_name']}")
        print(f"company_b_name: {comp['company_b_name']}")

        # Every section's A-side summary mentions A; B-side mentions B (or is unavailable).
        for sec in (
            "overview_comparison", "operational_comparison", "business_comparison",
            "strategic_comparison", "strengths_comparison", "weaknesses_comparison",
            "risks_comparison", "important_observations_comparison",
        ):
            assert comp[sec]["a"]["company"] == "A", sec
            assert comp[sec]["b"]["company"] == "B", sec

        # No A-only ref in any B-side evidence.
        a_ref = f"A_{a_sha[:12]}_p001_c000"
        for sec in (
            "overview_comparison", "operational_comparison", "business_comparison",
            "strategic_comparison", "strengths_comparison", "weaknesses_comparison",
            "risks_comparison", "important_observations_comparison",
        ):
            for ev in comp[sec]["b"]["evidence"]:
                assert not ev["ref_id"].startswith("A_"), f"{sec}.b contains A-prefixed ref"

        # Financials preserved as unavailable on both sides.
        for metric in comp["financial_comparison"]["a"] + comp["financial_comparison"]["b"]:
            assert metric["value_text"].startswith("Not available"), metric

        # Trends cite both sides.
        for trend in comp["trends"]:
            companies = {ev["company"] for ev in trend["evidence"]}
            assert companies == {"A", "B"}, f"trend evidence must cite both, got {companies}"

        # Key differences cite both sides.
        for kd in comp["key_differences"]:
            companies = {ev["company"] for ev in kd["evidence"]}
            assert companies == {"A", "B"}, f"key_difference evidence must cite both, got {companies}"

        # GET /api/comparison should now return completed.
        state = client.get("/api/comparison").json()
        assert state["status"] == "completed", state
        assert state["analysis"] is not None

        # DELETE /api/comparison resets state.
        r = client.delete("/api/comparison")
        assert r.status_code == 204
        state = client.get("/api/comparison").json()
        assert state["status"] == "idle", state
        assert state["analysis"] is None

        print()
        print("=== Sample comparative output structure ===")
        sample = {
            "company_a_name": comp["company_a_name"],
            "company_b_name": comp["company_b_name"],
            "overview_comparison": {
                "a": {k: comp["overview_comparison"]["a"][k] for k in ("company", "summary")},
                "b": {k: comp["overview_comparison"]["b"][k] for k in ("company", "summary")},
                "narrative": comp["overview_comparison"]["narrative"],
                "narrative_kind": comp["overview_comparison"]["narrative_kind"],
            },
            "financial_comparison": {
                "a": comp["financial_comparison"]["a"],
                "b": comp["financial_comparison"]["b"],
                "narrative": comp["financial_comparison"]["narrative"],
            },
            "trends": [
                {k: tr[k] for k in ("title", "description", "kind")} for tr in comp["trends"]
            ],
            "key_differences": [
                {k: kd[k] for k in ("title", "description", "kind")} for kd in comp["key_differences"]
            ],
            "overall_comparative_insights": [
                {k: ins[k] for k in ("title", "claim", "kind")} for ins in comp["overall_comparative_insights"]
            ],
        }
        print(json.dumps(sample, indent=2))
        print()
        print("OK -- Stage 3 smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
