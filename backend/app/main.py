"""FastAPI entry point — Stage 1 + Stage 2 + Stage 3.

Stage 1 endpoints:
- GET  /api/health            : liveness
- POST /api/ingest/upload     : multipart upload, ingest one company at a time
- GET  /api/corpus            : current Stage-1 state for both companies
- GET  /api/corpus/{company}  : just one company (A or B)
- DELETE /api/corpus          : reset (handy for re-uploading during testing)

Stage 2 endpoints:
- POST /api/agents/run        : run Agent A and/or Agent B (idempotent per company)
- GET  /api/agents/status     : run state for both companies
- GET  /api/agents/{company}/analysis     : the persisted analysis for a company
- DELETE /api/agents/{company}            : clear that company's analysis

Stage 3 endpoints:
- POST /api/comparison/run    : compare the two AgentAnalysis results
- GET  /api/comparison        : the most recent comparison
- DELETE /api/comparison      : clear the cached comparison
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app import __version__
from app.agents import (
    AgentAnalysis,
    AgentRunState,
    all_states,
    get_state,
    reset_state,
    run_analysis_for,
)
from app.comparator import (
    ComparativeAnalysis,
    ComparisonRunState,
    ComparisonUnavailableError,
    get_comparison,
    reset_comparison,
    run_comparison,
)
from app.ingest.pipeline import IngestError, ingest_pdf_bytes
from app.schemas import (
    CompanyState,
    CorpusResponse,
    HealthResponse,
    UploadResponse,
)
from app.storage import store

BACKEND_ROOT = Path(__file__).resolve().parent.parent
UPLOADS_ROOT = BACKEND_ROOT / "data" / "uploads"
UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Corporate Report Analysis",
    description=(
        "Stage 1 (PDF ingestion) + Stage 2 (two independent analysis agents, "
        "one per company, evidence-grounded) + Stage 3 (comparative analysis "
        "across A and B). All LLM calls go through CRA_LLM_* env vars."
    ),
    version=__version__,
)


# ---------- routes ----------

@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", stage=1, version=__version__)


@app.post("/api/ingest/upload", response_model=UploadResponse)
async def ingest_upload(
    company: Literal["A", "B"] = Form(..., description="'A' or 'B'"),
    file: UploadFile = File(...),
) -> UploadResponse:
    content = await file.read()
    try:
        state = ingest_pdf_bytes(
            content=content,
            company=company,
            uploads_root=UPLOADS_ROOT,
            document_name=file.filename,
        )
    except IngestError as exc:
        # 400 for validation failures — caller passed bad input.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store.set(state)

    sample_chunk_ids = [c.chunk_id for c in state.chunks[:3]]
    sample_table_ids = [t.table_id for t in state.tables[:3]]

    return UploadResponse(
        company=state.company,
        document_name=state.source.document_name,
        document_sha256=state.source.document_sha256,
        document_bytes=state.source.document_bytes,
        page_count=state.source.page_count,
        chunk_count=state.chunk_count,
        table_count=state.table_count,
        sample_chunk_ids=sample_chunk_ids,
        sample_table_ids=sample_table_ids,
    )


@app.get("/api/corpus", response_model=CorpusResponse)
def get_corpus() -> CorpusResponse:
    snap = store.corpus()
    return CorpusResponse(ready=snap.has_both(), state_a=snap.state_a, state_b=snap.state_b)


@app.get("/api/corpus/{company}", response_model=CompanyState)
def get_company_corpus(company: Literal["A", "B"]) -> CompanyState:
    state = store.get(company)
    if state is None:
        raise HTTPException(status_code=404, detail=f"no PDF ingested for company {company}")
    return state


@app.delete("/api/corpus", status_code=204)
def reset_corpus() -> JSONResponse:
    store.reset()
    # Also drop any cached Stage-2 analyses and the Stage-3 comparison
    # so a re-upload gives a clean run.
    for c in ("A", "B"):
        reset_state(c)
    reset_comparison()
    return JSONResponse(status_code=204, content=None)


# ---------- Stage 2: agents ----------

@app.get("/api/agents/status")
def agents_status() -> dict:
    return {
        c: get_state(c).model_dump(mode="json")
        for c in ("A", "B")
    }


@app.post("/api/agents/run")
def agents_run(target: Literal["A", "B", "both"] = "both") -> dict:
    """Run Agent A and/or Agent B against the currently-ingested corpora."""
    state_a = store.get("A")
    state_b = store.get("B")
    if target in ("A", "both") and state_a is None:
        raise HTTPException(
            status_code=400,
            detail="no PDF ingested for Company A — POST /api/ingest/upload first",
        )
    if target in ("B", "both") and state_b is None:
        raise HTTPException(
            status_code=400,
            detail="no PDF ingested for Company B — POST /api/ingest/upload first",
        )

    run_a = state_a if target in ("A", "both") else None
    run_b = state_b if target in ("B", "both") else None
    results = run_analysis_for(run_a, run_b)
    return {
        "ran": [c for c, r in (("A", run_a), ("B", run_b)) if r is not None],
        "skipped": [c for c, r in (("A", run_a), ("B", run_b)) if r is None],
        "results": {
            c: ({"company": c, "analysis": r.model_dump(mode="json")} if r is not None else None)
            for c, r in results.items()
        },
    }


@app.get("/api/agents/{company}/analysis", response_model=AgentAnalysis)
def get_agent_analysis(company: Literal["A", "B"]) -> AgentAnalysis:
    state = get_state(company)
    if state.analysis is None:
        raise HTTPException(
            status_code=404,
            detail=f"no analysis for company {company} — POST /api/agents/run first",
        )
    return state.analysis


@app.delete("/api/agents/{company}", status_code=204)
def clear_agent_analysis(company: Literal["A", "B"]) -> JSONResponse:
    reset_state(company)
    return JSONResponse(status_code=204, content=None)


# ---------- Stage 3: comparator ----------

@app.post("/api/comparison/run", response_model=ComparativeAnalysis)
def comparison_run() -> ComparativeAnalysis:
    """Run the comparator on Agent A + Agent B.

    Returns 400 with a clear error if either side is missing — the user
    must POST `/api/agents/run` first.
    """
    state_a = get_state("A")
    state_b = get_state("B")

    missing = []
    if state_a.analysis is None:
        missing.append("A")
    if state_b.analysis is None:
        missing.append("B")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"agent analysis unavailable for company(ies) {', '.join(missing)} — "
                "POST /api/agents/run first"
            ),
        )

    try:
        result = run_comparison(state_a.analysis, state_b.analysis)
    except ComparisonUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"comparator failed: {exc}") from exc
    return result.analysis


@app.get("/api/comparison")
def comparison_get() -> dict:
    """Return the most recent comparator run state.

    Status is one of: idle / running / completed / failed.
    """
    return get_comparison().model_dump(mode="json")


@app.delete("/api/comparison", status_code=204)
def comparison_clear() -> JSONResponse:
    reset_comparison()
    return JSONResponse(status_code=204, content=None)


# ---------- convenience for `python -m app.main` ----------

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.environ.get("PORT", "3101"))
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False)
