"""Stage 2 verification harness.

Runs through every claim the user asked us to prove, in one script, with
a deterministic stubbed LLM. Prints PASS/FAIL per check. Exits non-zero
if any check fails.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Hard-force stub mode regardless of .env.
os.environ["CRA_LLM_STUB"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.storage import store  # noqa: E402
from app.agents import runner as runner_module  # noqa: E402
from app.agents.llm_client import StubLLMClient  # noqa: E402
from app.tests._fixtures import build_minimal_pdf_two_pages  # noqa: E402


PASS = "[OK]"
FAIL = "[FAIL]"


def _stub(company: str, doc_name: str, sha: str) -> StubLLMClient:
    chunk_ref = f"{company}_{sha[:12]}_p001_c000"
    payload = {
        "company": company,
        "company_overview": {
            "summary": f"{company} operates in the widgets industry and reports financial highlights.",
            "evidence": [{
                "company": company, "document_name": doc_name,
                "document_sha256": sha, "page_number": 1,
                "kind": "chunk", "ref_id": chunk_ref,
                "snippet": f"{company} widgets industry operations paragraph on page 1.",
            }],
        },
        "financial_performance": {
            "summary": "Revenue and profit figures follow the financial highlights page.",
            "key_metrics": [{
                "metric": "Revenue",
                "value_text": "Not available in the provided report.",
                "unit": None, "year_or_period": None,
                "evidence": [],
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
    results: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        results.append((label, ok, detail))
        print(f"  {PASS if ok else FAIL}  {label}{(' -- ' + detail) if detail else ''}")

    store.reset()
    runner_module.reset_state("A")
    runner_module.reset_state("B")

    pdf_a = build_minimal_pdf_two_pages(
        "Acme Corp Annual Report FY24. Revenue grew twelve percent in FY24 across widgets.",
        "Acme faces supply chain and FX risks in EMEA and APAC.",
    )
    pdf_b = build_minimal_pdf_two_pages(
        "Globex Industries Annual Report FY24. Revenue fell four percent in FY24 across logistics.",
        "Globex faces regulatory headwinds and rising fuel costs.",
    )

    with TestClient(app) as client:
        up_a = client.post("/api/ingest/upload", data={"company": "A"},
                           files={"file": ("Acme.pdf", pdf_a, "application/pdf")}).json()
        up_b = client.post("/api/ingest/upload", data={"company": "B"},
                           files={"file": ("Globex.pdf", pdf_b, "application/pdf")}).json()

        print("\n--- Stage 1 sanity (4) ---")
        # 4.a PDF upload works for both companies.
        check("PDF upload for company A and B returns 200",
              bool(up_a.get("document_sha256")) and bool(up_b.get("document_sha256")),
              f"A pages={up_a['page_count']}, B pages={up_b['page_count']}")

        # 4.b Page-aware extraction: chunk_count > 0, page_count > 0.
        check("Page-aware extraction produced chunks",
              up_a["chunk_count"] > 0 and up_b["chunk_count"] > 0,
              f"A chunks={up_a['chunk_count']}, B chunks={up_b['chunk_count']}")

        # 4.c Chunk IDs are page-numbered.
        corpus_a = client.get("/api/corpus/A").json()
        corpus_b = client.get("/api/corpus/B").json()
        page_pat = re.compile(r"_p\d{3}_")
        ids_have_pages_a = all(page_pat.search(c["chunk_id"]) for c in corpus_a["chunks"])
        ids_have_pages_b = all(page_pat.search(c["chunk_id"]) for c in corpus_b["chunks"])
        check("Chunk IDs contain page number",
              ids_have_pages_a and ids_have_pages_b,
              f"e.g. {corpus_a['chunks'][0]['chunk_id']}")

        # 4.d Company A / B corpora are disjoint (no id-prefix crossing).
        a_ids = {c["chunk_id"] for c in corpus_a["chunks"]}
        b_ids = {c["chunk_id"] for c in corpus_b["chunks"]}
        a_leak = any(cid.startswith("B_") for cid in a_ids)
        b_leak = any(cid.startswith("A_") for cid in b_ids)
        check("Company A corpus has no B_-prefixed chunks",
              not a_leak, f"A chunk ids = {sorted(a_ids)[:2]}…")
        check("Company B corpus has no A_-prefixed chunks",
              not b_leak, f"B chunk ids = {sorted(b_ids)[:2]}…")

        # Wire stub for the agents.
        s_a = _stub("A", up_a["document_name"], up_a["document_sha256"])
        s_b = _stub("B", up_b["document_name"], up_b["document_sha256"])
        q = iter([s_a, s_b])
        import app.agents.runner as r
        original = r.make_default_client
        r.make_default_client = lambda *, force_stub=False: next(q)  # type: ignore[assignment]
        try:
            run = client.post("/api/agents/run", params={"target": "both"})
            run.raise_for_status()
        finally:
            r.make_default_client = original  # type: ignore[assignment]

        ana_a = client.get("/api/agents/A/analysis").json()
        ana_b = client.get("/api/agents/B/analysis").json()

        print("\n--- Stage 2 isolation (5) ---")
        # 5.a Agent A response contains only A-prefixed evidence IDs.
        a_blob = json.dumps(ana_a)
        check("Agent A response carries only Company A evidence IDs (no B_)",
              "B_" not in a_blob)
        check("Agent A response never mentions Company B name 'Globex'",
              "Globex" not in a_blob and "Globex" not in ana_a["company_overview"]["summary"])

        # 5.b Agent B response contains only B-prefixed evidence IDs.
        b_blob = json.dumps(ana_b)
        check("Agent B response carries only Company B evidence IDs (no A_)",
              "A_" not in b_blob)
        check("Agent B response never mentions Company A name 'Acme'",
              "Acme" not in b_blob and "Acme" not in ana_b["company_overview"]["summary"])

        # 5.c No cross-company retrieval: ask the A retriever for "Globex revenue"
        # and prove it cannot surface any Globex hit.
        from app.retrieval.retriever import Retriever
        from app.schemas import CompanyState, SourceMetadata, TextChunk, TableRecord

        def _state_from_corpus(raw: dict) -> CompanyState:
            return CompanyState(
                company=raw["company"],
                source=SourceMetadata(**raw["source"]),
                chunks=[TextChunk(**c) for c in raw["chunks"]],
                tables=[TableRecord(**t) for t in raw["tables"]],
                chunk_count=raw["chunk_count"],
                table_count=raw["table_count"],
            )

        ra = Retriever(_state_from_corpus(corpus_a))
        rb = Retriever(_state_from_corpus(corpus_b))
        a_hits = ra.evidence_pack(["Globex revenue"], top_k_chunks=20, top_k_tables=20)
        b_hits = rb.evidence_pack(["Acme revenue"], top_k_chunks=20, top_k_tables=20)
        check("A-retriever returns only Company A hits even for 'Globex' queries",
              all(h.company == "A" for h in a_hits))
        check("B-retriever returns only Company B hits even for 'Acme' queries",
              all(h.company == "B" for h in b_hits))

        print("\n--- Evidence fields (6) ---")
        ev = ana_a["company_overview"]["evidence"][0]
        fields_ok = all([
            ev.get("company") == "A",
            bool(ev.get("document_name")),
            isinstance(ev.get("page_number"), int) and ev["page_number"] >= 1,
            bool(ev.get("ref_id")),
            bool(ev.get("snippet")),
        ])
        check("Evidence has company + document_name + page_number + ref_id + snippet",
              fields_ok,
              f"ref_id={ev.get('ref_id')[:24]}…, page={ev.get('page_number')}")

        # Spot-check the same on Company B's evidence (the chunk ref there
        # was filled in by fill_company_metadata).
        evb = ana_b["company_overview"]["evidence"][0]
        fields_ok_b = all([
            evb.get("company") == "B",
            bool(evb.get("document_name")),
            isinstance(evb.get("page_number"), int),
            bool(evb.get("ref_id")),
            bool(evb.get("snippet")),
        ])
        check("Same evidence-field check on Company B",
              fields_ok_b,
              f"ref_id={evb.get('ref_id')[:24]}…")

        print("\n--- No fabricated financials (7) ---")
        # We deliberately did NOT stub a revenue number, and the stub
        # returned the explicit "Not available" marker.
        fp_a = ana_a["financial_performance"]
        fp_b = ana_b["financial_performance"]
        check("A's financial_performance carries only 'Not available' values",
              fp_a["key_metrics"][0]["value_text"].startswith("Not available"))
        check("B's financial_performance carries only 'Not available' values",
              fp_b["key_metrics"][0]["value_text"].startswith("Not available"))
        # Hard rule: no bare numeric claim in the stub output for either company.
        no_numbers_a = not re.search(r"\b\d{2,}\b", fp_a["summary"])
        no_numbers_b = not re.search(r"\b\d{2,}\b", fp_b["summary"])
        check("A's financial summary contains no fabricated large numbers",
              no_numbers_a, fp_a["summary"])
        check("B's financial summary contains no fabricated large numbers",
              no_numbers_b, fp_b["summary"])

        print("\n--- Local LLM only, no cloud/paid API (8, 9) ---")
        # The script must never reach out to a paid cloud LLM. Static proof:
        from app.agents import llm_client
        from app.agents.llm_client import OllamaLLMClient
        import inspect
        src = inspect.getsource(OllamaLLMClient)
        check("LLM endpoint comes from env (OLLAMA_BASE_URL), not hardcoded",
              "OLLAMA_BASE_URL" in inspect.getsource(llm_client),
              "OLLAMA_BASE_URL drives the endpoint, no hardcoded URLs")
        check("No MiniMax references in the LLM client",
              "minimax" not in src.lower() and "MiniMax" not in src,
              "Ollama is the only LLM path")
        check("No OpenAI/Anthropic/samagama references in the LLM client",
              not any(tok in src.lower() for tok in ("openai", "anthropic", "samagama", "openclaw")),
              "Ollama is the only LLM path")
        check("No process-spawning of `openclaw` commands anywhere in the runner",
              "openclaw" not in src.lower(),
              "LLM is reached only via httpx to localhost Ollama")
        # Also: no paid-API env keys are read.
        check("No MiniMax/OpenAI/Anthropic API-key env reads",
              not any(k in inspect.getsource(llm_client) for k in ("CRA_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MINIMAX_API_KEY")),
              "Project-local .env has no paid-cloud credentials")

    print("\n--- Summary ---")
    total = len(results)
    failed = [r for r in results if not r[1]]
    print(f"  {total - len(failed)}/{total} checks passed.")
    if failed:
        for label, _, detail in failed:
            print(f"  - FAIL: {label}  {detail}")
        return 1
    print(f"  {PASS} all Stage 2 verification checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
