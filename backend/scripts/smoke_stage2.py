"""Manual Stage 2 smoke test.

Runs the FastAPI app in-process (TestClient) against the stub LLM, uploads
two tiny PDFs, runs Agent A and Agent B, and prints a human-readable
summary. No network, no M3 calls.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Force the stub LLM regardless of any .env.
os.environ["CRA_LLM_STUB"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.storage import store  # noqa: E402
from app.tests._fixtures import build_minimal_pdf_two_pages  # noqa: E402
from app.agents.llm_client import StubLLMClient  # noqa: E402
from app.agents import runner as runner_module  # noqa: E402


def _stub_for(company: str, doc_name: str, sha: str) -> StubLLMClient:
    payload = {
        "company": company,
        "company_overview": {
            "summary": f"{company} operates in the widgets industry.",
            "evidence": [{
                "company": company, "document_name": doc_name,
                "document_sha256": sha, "page_number": 1,
                "kind": "chunk", "ref_id": f"{company}_{sha[:12]}_p001_c000",
                "snippet": f"{company} widgets operations",
            }],
        },
        "financial_performance": {
            "summary": "Revenue and profit figures follow the financial highlights.",
            "key_metrics": [{
                "metric": "Revenue",
                "value_text": "Not available in the provided report.",
            }],
            "evidence": [],
        },
        "operational_information": {"summary": "Not available in the provided report.", "evidence": []},
        "strategic_information": {"summary": "Not available in the provided report.", "evidence": []},
        "business_information": {"summary": "Not available in the provided report.", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }
    s = StubLLMClient()
    s.expect(
        system_contains=f"Agent {company}",
        user_contains=doc_name,
        response=json.dumps(payload),
    )
    return s


def main() -> int:
    store.reset()
    runner_module.reset_state("A")
    runner_module.reset_state("B")

    # Build tiny PDFs and ingest via the API.
    pdf_a = build_minimal_pdf_two_pages(
        "Acme Corp Annual Report FY24. Revenue grew 12 percent.",
        "Acme faces supply-chain risks.",
    )
    pdf_b = build_minimal_pdf_two_pages(
        "Globex Industries Annual Report FY24. Revenue fell 4 percent.",
        "Globex faces regulatory headwinds.",
    )

    with TestClient(app) as client:
        up_a = client.post(
            "/api/ingest/upload",
            data={"company": "A"},
            files={"file": ("Acme.pdf", pdf_a, "application/pdf")},
        )
        up_b = client.post(
            "/api/ingest/upload",
            data={"company": "B"},
            files={"file": ("Globex.pdf", pdf_b, "application/pdf")},
        )
        a = up_a.json()
        b = up_b.json()
        print(f"Uploaded A: {a['document_name']} ({a['page_count']} pages, {a['chunk_count']} chunks)")
        print(f"Uploaded B: {b['document_name']} ({b['page_count']} pages, {b['chunk_count']} chunks)")

        # Wire up the stub for each company.
        s_a = _stub_for("A", a["document_name"], a["document_sha256"])
        s_b = _stub_for("B", b["document_name"], b["document_sha256"])
        runners = {"A": s_a, "B": s_b}

        # Patch make_default_client so run_analysis_for uses our stubs.
        def factory(*, force_stub: bool = False):
            # Returned by both calls — order is A then B.
            return next(iter(runners.values()))

        # Use a queue keyed on system-prompt company to dispatch properly.
        queue = iter([s_a, s_b])

        def factory2(*, force_stub: bool = False):
            return next(queue)

        import app.agents.runner as r
        original = r.make_default_client
        r.make_default_client = factory2  # type: ignore[assignment]
        try:
            r_run = client.post("/api/agents/run", params={"target": "both"})
            r_run.raise_for_status()
        finally:
            r.make_default_client = original  # type: ignore[assignment]

        for c in ("A", "B"):
            resp = client.get(f"/api/agents/{c}/analysis")
            resp.raise_for_status()
            data = resp.json()
            print()
            print(f"=== Company {c} ===")
            print(f"  document:        {data['document_name']}")
            print(f"  overview summary: {data['company_overview']['summary'][:80]}")
            print(f"  evidence refs:   {len(data['company_overview']['evidence'])}")
            print(f"  financial sum:   {data['financial_performance']['summary'][:80]}")
            print(f"  warnings:        {data['warnings']}")

            # Guard: every evidence ref in this company's analysis must
            # carry this company's label.
            blob = json.dumps(data)
            for other in ("A", "B"):
                if other == c:
                    continue
                assert f"{other}_" not in blob, f"cross-company leak: {other}_* in {c}'s analysis"

    print()
    print("OK \u2014 Stage 2 smoke passed (stubbed LLM, no M3 calls).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
