# Corporate Report Analysis & Decision Support

Annual reports from Company A and Company B go in. Two **isolated** AI agents
(one per company) extract financial / operational / strategic findings,
grounded in the source PDF — no fabricated numbers, every insight cited to
a chunk/page. A dedicated comparator then produces a structured, evidence-
preserving comparison across both reports. Stage 4 adds an interactive
dashboard.

The LLM is **local Ollama**. There is no cloud / paid API dependency.

This repository **does not** depend on or modify any global system config
(OpenClaw or otherwise). All LLM connection details live in the project-
local `backend/.env` file.

---

## Stage status

| Stage | What it does                                | Status                                |
| ----- | ------------------------------------------- | ------------------------------------- |
| 1     | PDF ingestion, page-aware chunks + tables   | ✅ shipped                            |
| 2     | Two isolated analysis agents (one per Co.)  | ✅ shipped                            |
| 3     | Comparative analysis across A and B         | ✅ shipped                            |
| 4     | Interactive dashboard                       | ⏳ awaiting approval                  |
| 5     | Hardening, docs, end-to-end demo            | ⏳ awaiting approval                  |

---

## Architecture (Stages 1 + 2 + 3)

```
browser  ─►  frontend (Stage 4, not yet built)
                │
                ▼
   FastAPI backend (uvicorn :3101)
                │
   ┌────────────┼─────────────┐
   │            │             │
 ingest.pdf  agents.runner  comparator.runner
   │            │             │
   ▼            ▼             ▼
 local files  LLMClient   LLMClient    ← shared, but agents are isolated
                │             │
                ▼             ▼
            OllamaLLMClient (default)
            StubLLMClient   (tests only)
                │
                ▼
       Ollama running on
       http://127.0.0.1:11434
        (or another host in prod)
```

### Component layout

```
backend/
  app/
    main.py                FastAPI app: Stage 1 + 2 + 3 routes
    schemas.py             Pydantic: Company, CompanyState, TextChunk, TableRecord, ...
    storage.py             In-process CorpusStore (swap for a DB later)
    ingest/                Stage 1: pdf_reader, chunker, table_extractor, pipeline
    retrieval/retriever.py Stage 2: company-scoped TF-IDF search
    agents/
      llm_client.py        LLMClient protocol + OllamaLLMClient + StubLLMClient + factory
      prompts.py           per-company system + user prompts, JSON coercion, metadata stamp
      schemas.py           Pydantic AgentAnalysis (with evidence-required validators)
      runner.py            analyze_company(), run_analysis_for(), registry, isolation guard
    comparator/
      schemas.py           Pydantic ComparativeAnalysis (A/B-isolated evidence, kind taxonomy)
      prompts.py           comparative system+user prompts, JSON coercion
      runner.py            run_comparison(), registry, isolation guards, normalisation
    tests/                 pytest suite (109 tests)
    data/                  uploads/<company>/<sha256>.pdf  (created at runtime)
  .env.example             OLLAMA_* template (copy to .env)
  requirements.txt
  scripts/
    smoke_ingest.py        Stage 1 Python E2E
    smoke_http.mjs         Stage 1 Node/HTTP E2E
    smoke_stage2.py        Stage 2 end-to-end with stub LLM
    smoke_stage3.py        Stage 3 end-to-end with stub LLM
    smoke_real_ollama.py   Stage 3 end-to-end against the real local Ollama (slow; ~2–5 min)
    verify_stage2.py       Static + dynamic verification harness
```

---

## LLM: Ollama (local, no paid API)

The default LLM provider is **Ollama running locally**. The application
**never** reads an OpenAI / Anthropic / MiniMax / Gemini key. The
`backend/.env` file only contains an Ollama endpoint and an Ollama model
name.

### Why Ollama?

* **Zero paid API dependency.** Everything runs on your own machine.
* **Easy deployment story.** End users do not need to install Ollama —
  the deployed server hosts it and the browser just talks to the backend.
* **Same chat interface.** Ollama exposes an OpenAI-ish chat API, but we
  use Ollama's native `/api/chat` endpoint for clarity and stability.
* **CPU-runnable.** A 3B-parameter Q4-quantised model works on a typical
  laptop; a GPU is not required for this project.

### Why `qwen2.5:3b`?

* Small (≈ 2 GB on disk). Fits on a 7–8 GB RAM machine alongside the
  Python backend.
* Chat-tuned. Produces well-formed JSON when instructed.
* Same family as `qwen2.5-coder:7b` (already on the development machine).
* Good default — swap it for `llama3.2:3b`, `gemma3:4b`, or similar by
  changing the `OLLAMA_MODEL` env var.

### Hardware used for development

| Component | Value              |
| --------- | ------------------ |
| CPU       | 4 logical cores    |
| RAM       | 7.8 GB total       |
| GPU       | none               |

LLM inference on this machine: **CPU-only** via Ollama. A `qwen2.5:3b`
single round-trip ≈ 10–15 s (first call includes a one-time model load of
~30 s); full Agent A + Agent B + Comparator pass ≈ 2–5 minutes.

---

## How to run the backend

### 1. Install Ollama + pull a model

```powershell
# 1a. Download Ollama from https://ollama.com/download (Windows installer)
#     — already installed at:
#        C:\Users\ajith\AppData\Local\Programs\Ollama\ollama.exe

# 1b. Make sure it's serving:
ollama serve

# 1c. In another shell, pull the model:
ollama pull qwen2.5:3b
```

To switch models later, run `ollama pull <name>` and set
`OLLAMA_MODEL=<name>` in `backend/.env`.

### 2. Install the backend

```powershell
cd C:\Users\ajith\Desktop\projects\corp-report-analysis\backend
# one-time (venv may already exist from earlier work):
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Configure the LLM connection

```powershell
copy .env.example .env
```

The defaults are:

* `OLLAMA_BASE_URL=http://127.0.0.1:11434`
* `OLLAMA_MODEL=qwen2.5:3b`
* `OLLAMA_TIMEOUT_SECONDS=900`
* `OLLAMA_NUM_PREDICT=1536`
* `OLLAMA_TEMPERATURE=0.2`

Edit `.env` only if your Ollama endpoint differs.

### 4. Run the server

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 3101
# OpenAPI: http://127.0.0.1:3101/docs
```

---

## Stage 1 + 2 + 3: end-to-end (HTTP API)

```powershell
# 1. Ingest the two PDFs (each "company" only sees its own PDF).
curl.exe -F "company=A" -F "file=@Acme.pdf"   http://127.0.0.1:3101/api/ingest/upload
curl.exe -F "company=B" -F "file=@Globex.pdf" http://127.0.0.1:3101/api/ingest/upload

# 2. Run both agents (Stage 2). Each agent talks to Ollama — this is where
#    the actual LLM calls happen. With qwen2.5:3b on CPU, expect ~1–3 minutes.
curl.exe -X POST "http://127.0.0.1:3101/api/agents/run?target=both"

# 3. Read the analyses.
curl.exe http://127.0.0.1:3101/api/agents/A/analysis
curl.exe http://127.0.0.1:3101/api/agents/B/analysis

# 4. Run the comparator (Stage 3). One more Ollama call.
curl.exe -X POST "http://127.0.0.1:3101/api/comparison/run"
curl.exe http://127.0.0.1:3101/api/comparison
```

### Test mode (no Ollama needed)

```powershell
$env:CRA_LLM_STUB = "1"          # forces deterministic stub
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 3101
```

The `StubLLMClient` raises unless every `complete()` call has been
prepared via `.expect(...)`. The Stage 2 / Stage 3 smoke scripts and the
full pytest suite always use the stub — they never need a running Ollama.

---

## API endpoints

| Method | Path                                  | Stage | Purpose                                                 |
| ------ | ------------------------------------- | ----- | ------------------------------------------------------- |
| GET    | `/api/health`                         | 1     | Liveness (`{"status":"ok","stage":3,...}`).             |
| POST   | `/api/ingest/upload`                  | 1     | Multipart upload (`company=A\|B`, `file=...`).          |
| GET    | `/api/corpus`                         | 1     | Both companies' state.                                  |
| GET    | `/api/corpus/{A\|B}`                  | 1     | One company's state.                                    |
| DELETE | `/api/corpus`                         | 1     | Reset both corpora (and clear agents + comparison).      |
| POST   | `/api/agents/run?target=A\|B\|both`   | 2     | Run the agent(s).                                       |
| GET    | `/api/agents/status`                  | 2     | Run state for both companies.                           |
| GET    | `/api/agents/{A\|B}/analysis`         | 2     | The persisted `AgentAnalysis` JSON.                     |
| DELETE | `/api/agents/{A\|B}`                  | 2     | Clear a company's analysis.                             |
| POST   | `/api/comparison/run`                 | 3     | Run the comparator on A + B analyses.                   |
| GET    | `/api/comparison`                     | 3     | Run state + latest `ComparativeAnalysis`.               |
| DELETE | `/api/comparison`                     | 3     | Clear the cached comparison.                            |
| GET    | `/docs`                               | all   | Swagger UI (FastAPI auto-generated).                    |

---

## Environment variables

All variables live in `backend/.env` (gitignored) or are passed in the
shell. Copy `backend/.env.example` for a starter.

| Variable                  | Default                       | Meaning                                              |
| ------------------------- | ----------------------------- | ---------------------------------------------------- |
| `CRA_LLM_PROVIDER`        | `ollama`                      | Informational label only.                            |
| `OLLAMA_BASE_URL`         | `http://127.0.0.1:11434`      | Local Ollama HTTP endpoint.                          |
| `OLLAMA_MODEL`            | `qwen2.5:3b`                  | Model name as understood by Ollama.                  |
| `OLLAMA_TIMEOUT_SECONDS`  | `900`                         | Per-request HTTP timeout (CPU inference is slow).    |
| `OLLAMA_NUM_PREDICT`      | `1536`                        | Ollama `num_predict` (max tokens per call).          |
| `OLLAMA_TEMPERATURE`      | `0.2`                         | Low for evidence-stable answers.                     |
| `CRA_LLM_STUB`            | `0`                           | `1` forces deterministic stub mode (no network).     |
| `PORT`                    | `3101`                        | FastAPI port (set by uvicorn directly if you wish).  |

**What is NOT read:**

* No `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `MINIMAX_API_KEY` /
  `GEMINI_API_KEY` env vars. The factory ignores these.
* No OpenClaw global config — neither read nor written.

---

## Running the tests

```powershell
cd C:\Users\ajith\Desktop\projects\corp-report-analysis\backend
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: **109 passed** in ~2 s. Coverage by file:

* Stage 1 (`test_api.py`, `test_chunker.py`, `test_pdf_reader.py`,
  `test_pipeline.py`, `test_table_extractor.py`, `test_validate.py`):
  35 tests — PDF reading, chunking, table extraction, validation, full
  HTTP API.
* Stage 2: 33 tests
  * `test_retriever_isolation.py` (6) — retriever never yields the other company.
  * `test_agent_prompts.py` (7) — system/user prompts, JSON coercion, metadata.
  * `test_agent_schemas.py` (9) — evidence-required validators, no fabrication.
  * `test_agent_runner_isolation.py` (6) — A↔B isolation at the runner level.
  * `test_agents_api.py` (4) — Stage 2 HTTP API with stubbed LLM.
* Stage 3: 27 tests
  * `test_comparator_schemas.py` (13) — A/B evidence matching, kind taxonomy.
  * `test_comparator_runner.py` (10) — A+B handling, fact/derived/insight
    distinction, isolation.
  * `test_comparator_api.py` (4) — Stage 3 HTTP API end-to-end with stubs.
* Stage LLM-Ollama: 14 tests
  * `test_llm_client_ollama.py` — config, request shape, factory, reachability.
* All tests run with `CRA_LLM_STUB=1`, so **no Ollama process is required
  to run the suite**.

### Manual smoke scripts

```powershell
$env:CRA_LLM_STUB = "1"          # stub mode — no Ollama needed

.\.venv\Scripts\python.exe -m scripts.smoke_ingest     # Stage 1 PDF → corpus
node scripts\smoke_http.mjs                          # Stage 1 HTTP smoke
.\.venv\Scripts\python.exe -m scripts.smoke_stage2    # Stage 2 API smoke
.\.venv\Scripts\python.exe -m scripts.smoke_stage3    # Stage 3 API smoke
.\.venv\Scripts\python.exe -m scripts.verify_stage2   # 22-check verification harness
```

### Real Ollama (one-off confidence check, ~2–5 minutes)

```powershell
# Make sure Ollama is running and qwen2.5:3b is pulled.
ollama serve
ollama pull qwen2.5:3b

# Clear env stub flag and run the real smoke:
Remove-Item env:CRA_LLM_STUB -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m scripts.smoke_real_ollama
```

This uploads tiny fixture PDFs, runs Agent A + Agent B + the comparator
against the local Ollama instance, and writes the result to
`backend/data/real_ollama_smoke.json`. Slow on CPU — that's normal.

---

## Deployment architecture

```
                    User browser
                         │
                         ▼
              Frontend (Vite / static)
                         │
                         ▼
              Backend (FastAPI on host:3101)
                         │
                         ▼
              Ollama (same host, :11434)
                         │
                         ▼
              Local open-source LLM
                         │
                         ▼
              Backend → JSON over HTTP
                         │
                         ▼
                    User browser
```

End users do **not** need to install Ollama — the deployment host
runs it. The browser just talks to the backend.

---

## Configuration isolation guarantee

* The OpenClaw global config is **not** read or modified by this project.
* The application does **not** call any paid cloud LLM API.
* The only LLM HTTP traffic goes from the backend to
  `OLLAMA_BASE_URL` (by default `http://127.0.0.1:11434`).
* Stage 1 does no LLM work at all.
* Stage 2 isolation tests confirm Agent A and Agent B can never read or
  cite each other's chunks, tables, or evidence.
* Stage 3 isolation tests confirm the comparator never mixes Company A
  evidence into Company B sections or vice versa.
