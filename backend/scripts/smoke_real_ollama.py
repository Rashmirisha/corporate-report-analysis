"""Real local-Ollama smoke test.

Runs Agent A, Agent B, and the Stage 3 comparator end-to-end against a
local Ollama instance running ``OLLAMA_MODEL`` (default: qwen2.5:3b).

Expected runtime on a 4-core / 8 GB laptop: 1–5 minutes (CPU inference).
Use this as a one-shot confidence check, NOT in CI.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# IMPORTANT: do NOT set CRA_LLM_STUB — we want the real client.
os.environ.pop("CRA_LLM_STUB", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.storage import store  # noqa: E402
from app.agents import runner as agent_runner  # noqa: E402
from app.comparator import runner as comp_runner  # noqa: E402
from app.agents.llm_client import OllamaLLMClient, LLMConfig  # noqa: E402
from app.tests._fixtures import build_minimal_pdf_two_pages  # noqa: E402


def _check_ollama_reachable() -> None:
    cfg = LLMConfig.from_env()
    client = OllamaLLMClient(cfg)
    if not client.is_reachable():
        print(f"FAIL: Ollama not reachable at {cfg.base_url}")
        print("Start it with: ollama serve")
        raise SystemExit(2)
    print(f"Ollama UP at {cfg.base_url}; model={cfg.model}")


def _warm_up() -> None:
    """Force the model to load so the first real call isn't 30s of model-load latency."""
    cfg = LLMConfig.from_env()
    client = OllamaLLMClient(cfg)
    print("Warming up model (loads weights into RAM; one-time)...")
    t = time.time()
    _ = client.complete(
        system="You are a JSON-only assistant.",
        user='Reply with the single word "ready".',
        json_mode=False,
    )
    print(f"Warm-up done in {time.time() - t:.1f}s")


def _build_payloads(analysis_a: dict, analysis_b: dict) -> dict:
    """Tiny but real comparator prompt payload — built from the Stage-2 outputs."""
    return {
        "company_a_name": analysis_a["document_name"],
        "company_b_name": analysis_b["document_name"],
        "overview_comparison": {
            "a": {"company": "A", "summary": analysis_a["company_overview"]["summary"][:400] or "Not available in the provided reports.",
                  "evidence": analysis_a["company_overview"].get("evidence", [])[:3]},
            "b": {"company": "B", "summary": analysis_b["company_overview"]["summary"][:400] or "Not available in the provided reports.",
                  "evidence": analysis_b["company_overview"].get("evidence", [])[:3]},
            "narrative": "Real-Ollama smoke does not pre-write narratives — leave empty for the model.",
            "narrative_kind": "derived",
            "evidence": [],
        },
        # The rest of the sections will be filled by the model's actual response;
        # we leave them as the minimum-valid shape so the JSON parses cleanly.
        "financial_comparison": {"a": [], "b": [], "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "operational_comparison": {"a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
                                    "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
                                    "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "business_comparison": {"a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
                                 "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
                                 "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "strategic_comparison": {"a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
                                  "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
                                  "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "strengths_comparison": {"a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
                                  "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
                                  "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "weaknesses_comparison": {"a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
                                   "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
                                   "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "risks_comparison": {"a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
                              "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
                              "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "important_observations_comparison": {"a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
                                                "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
                                                "narrative": "Not available in the provided reports.", "narrative_kind": "insight", "evidence": []},
        "trends": [], "key_differences": [], "evidence": [], "overall_comparative_insights": [], "warnings": [],
    }


def main() -> int:
    _check_ollama_reachable()
    _warm_up()

    # Save raw Ollama responses so we can inspect the model output even when
    # parsing fails. Used only by this manual smoke test.
    raw_dump_dir = BACKEND_ROOT / "data" / "real_ollama_raw"
    raw_dump_dir.mkdir(parents=True, exist_ok=True)
    original_complete = OllamaLLMClient.complete

    def _dumping_complete(self, *, system, user, json_mode=False):
        out = original_complete(self, system=system, user=user, json_mode=json_mode)
        idx = getattr(self, "_dump_counter", 0)
        self._dump_counter = idx + 1
        (raw_dump_dir / f"call_{idx:02d}_response.txt").write_text(out, encoding="utf-8")
        (raw_dump_dir / f"call_{idx:02d}_user.txt").write_text(user, encoding="utf-8")
        return out

    OllamaLLMClient.complete = _dumping_complete  # type: ignore[assignment]

    # Reset state.
    store.reset()
    agent_runner.reset_state("A")
    agent_runner.reset_state("B")
    comp_runner.reset_comparison()

    pdf_a = build_minimal_pdf_two_pages(
        ("Acme Corp Annual Report FY24. "
         "Acme is a manufacturer of industrial widgets operating across EMEA, APAC, and the Americas. "
         "Our strategy emphasises vertical integration, automation, and brand-led growth in core markets."),
        ("In FY24 Acme reported record customer satisfaction scores and expanded the EMEA plant network by two new facilities. "
         "Key risks include supply-chain volatility, currency fluctuations in EMEA, and rising input costs. "
         "Financial highlights are presented in the audited statements section."),
    )
    pdf_b = build_minimal_pdf_two_pages(
        ("Globex Industries Annual Report FY24. "
         "Globex provides third-party logistics services including freight forwarding, warehousing, and last-mile delivery to enterprise customers. "
         "Our strategy emphasises cost optimisation, fleet modernisation, and disciplined expansion."),
        ("In FY24 Globex completed its fleet-modernisation programme and reduced operating costs by 8 percent. "
         "Key risks include regulatory headwinds in the EU, fuel-price volatility, and labour-market tightness in core hubs."),
    )

    with TestClient(app) as client:
        up_a = client.post("/api/ingest/upload", data={"company": "A"},
                           files={"file": ("Acme.pdf", pdf_a, "application/pdf")}).json()
        up_b = client.post("/api/ingest/upload", data={"company": "B"},
                           files={"file": ("Globex.pdf", pdf_b, "application/pdf")}).json()
        a_name, a_sha = up_a["document_name"], up_a["document_sha256"]
        b_name, b_sha = up_b["document_name"], up_b["document_sha256"]
        print(f"Uploaded A: {a_name} (sha12={a_sha[:12]})")
        print(f"Uploaded B: {b_name} (sha12={b_sha[:12]})")

        # ----- Agent A -----
        print("\n=== Agent A (real Ollama call) ===")
        t = time.time()
        r = client.post("/api/agents/run", params={"target": "A"})
        elapsed_a = time.time() - t
        if r.status_code != 200:
            print(f"Agent A failed: {r.status_code} {r.text[:300]}")
            return 1
        a_status = client.get("/api/agents/status").json()
        print(f"Agent A: status={a_status['A']['status']} ({elapsed_a:.1f}s)")
        analysis_a = client.get("/api/agents/A/analysis").json()
        print(f"  company={analysis_a['company']} doc={analysis_a['document_name']}")
        print(f"  overview={analysis_a['company_overview']['summary'][:120]!r}")

        # ----- Agent B -----
        print("\n=== Agent B (real Ollama call) ===")
        t = time.time()
        r = client.post("/api/agents/run", params={"target": "B"})
        elapsed_b = time.time() - t
        if r.status_code != 200:
            print(f"Agent B failed: {r.status_code} {r.text[:300]}")
            return 1
        b_status = client.get("/api/agents/status").json()
        print(f"Agent B: status={b_status['B']['status']} ({elapsed_b:.1f}s)")
        analysis_b = client.get("/api/agents/B/analysis").json()
        print(f"  company={analysis_b['company']} doc={analysis_b['document_name']}")
        print(f"  overview={analysis_b['company_overview']['summary'][:120]!r}")

        # ----- Comparator -----
        print("\n=== Stage 3 comparator (real Ollama call) ===")
        t = time.time()
        r = client.post("/api/comparison/run")
        elapsed_c = time.time() - t
        if r.status_code != 200:
            print(f"Comparator failed: {r.status_code} {r.text[:500]}")
            return 1
        comp = r.json()
        print(f"Comparator: {elapsed_c:.1f}s")
        print(f"  company_a_name={comp['company_a_name']}")
        print(f"  company_b_name={comp['company_b_name']}")
        print(f"  overview.a={comp['overview_comparison']['a']['company']}")
        print(f"  overview.b={comp['overview_comparison']['b']['company']}")

        # The overview narratives come from the real model.
        print(f"  overview.narrative={comp['overview_comparison']['narrative'][:160]!r}")

        # Save the full output for inspection.
        out_path = BACKEND_ROOT / "data" / "real_ollama_smoke.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(comp, indent=2), encoding="utf-8")
        print(f"\nFull comparative analysis written to: {out_path}")

        print(f"\nTotal wall-time: Agent A {elapsed_a:.1f}s + Agent B {elapsed_b:.1f}s + Comparator {elapsed_c:.1f}s")

    OllamaLLMClient.complete = original_complete  # type: ignore[assignment]

    print("\nOK -- real Ollama smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
