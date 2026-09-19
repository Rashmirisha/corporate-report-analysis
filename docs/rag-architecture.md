# Retrieval architecture and future RAG plan

This document describes the retrieval architecture that is currently
shipped, the planned optional upgrade to semantic retrieval, and the
constraints that any future change must respect.

It is a design document. **No ChromaDB migration is implemented in the
repository at this time.** Reading this document should not give the
impression that a migration has been built; it has not been.

---

## 1. Current architecture (shipped)

```
                    Company A PDF            Company B PDF
                          |                       |
                          v                       v
                  pdfplumber text + tables   pdfplumber text + tables
                          |                       |
                          v                       v
                   page-aware chunker         page-aware chunker
                (target 220 / overlap 30 /
                 hard max 380 words)
                          |                       |
                          v                       v
               CompanyState.chunks (A)     CompanyState.chunks (B)
               CompanyState.tables (A)     CompanyState.tables (B)
                          |                       |
                          v                       v
               Retriever(state_A)          Retriever(state_B)
                   (TF-IDF, pure numpy cosine)
                          |                       |
                          +-------+ +--------------+
                                  | |
                                  v v
                  agents/runner.analyze_company(state)
                  (one runner call per company)
                          |
                          v
                  AgentAnalysis (evidence-grounded JSON)
                          |
                          v
                  comparator/runner.run_comparison(a, b)
                          |
                          v
                  ComparativeAnalysis (A/B-isolated evidence)
                          |
                          v
                  Local Ollama (qwen2.5:3b) — sole LLM
```

* **Stage 1** (`backend/app/ingest/`) — PDF reading, page-aware
  chunking, table extraction, SHA-256-hashed storage.
* **Stage 2** (`backend/app/retrieval/retriever.py`,
  `backend/app/agents/runner.py`) — TF-IDF retrieval (pure numpy, no
  extra dependencies) plus two isolated agents, one per company.
* **Stage 3** (`backend/app/comparator/`) — comparative analysis
  across both companies with strict per-company evidence matching.

All 109 tests pass; the 22-test Stage 2 verification harness passes.

## 2. Planned optional architecture (NOT implemented)

```
                    Company A PDF            Company B PDF
                          |                       |
                          v                       v
                  ... existing ingest unchanged ...
                          |                       |
                          v                       v
               ChromaStore_A              ChromaStore_B
              (persistent, on-disk,
               per-company collection,
               embeddings + metadata)
                          |                       |
                          v                       v
               ChromaRetriever(state_A)   ChromaRetriever(state_B)
               (semantic ANN search,
                same public surface as Retriever,
                TF-IDF Retriever kept as fallback)
                          |
                          v
                  agents/runner.analyze_company(state)
                          |         (UNCHANGED)
                          v
                  AgentAnalysis + ComparativeAnalysis
                          |
                          v
                  Local Ollama (qwen2.5:3b) — sole LLM
                              +
                  Local Ollama (nomic-embed-text) — sole embedder
```

The generator LLM (`qwen2.5:3b`) and the embedder (`nomic-embed-text`)
are both served by the existing local Ollama process on
`http://127.0.0.1:11434`. No new external service is introduced.

## 3. Why the current Retriever interface makes this additive

`backend/app/retrieval/retriever.py` already exposes a small, stable
public surface:

* `search_chunks(query, top_k=8)`
* `search_tables(query, top_k=4)`
* `evidence_pack(queries, top_k_chunks=6, top_k_tables=3)`
* `chunk_by_id(chunk_id)`
* `table_by_id(table_id)`

Every consumer in the codebase (`agents/runner.py`,
`agents/schemas.py`, `comparator/runner.py`, the FastAPI routes) only
talks to that surface — no consumer reaches into TF-IDF internals.

The current `Retriever` class can therefore be kept as-is (the TF-IDF
implementation) and shadowed by a sibling `ChromaRetriever` that
implements the same five methods. Switching from TF-IDF to semantic
retrieval becomes a one-line import change in `agents/runner.py`, with
the rest of the pipeline — agents, comparator, schemas, API — left
untouched.

## 4. Company A / Company B isolation requirements

The current isolation contract is enforced in three layers and must
survive any future retrieval change unchanged:

1. **Construction-time scoping.** A `Retriever` (or future
   `ChromaRetriever`) is built from exactly one `CompanyState` and
   carries an immutable `company` attribute. There is no method that
   accepts a company at query time and switches.
2. **Per-query metadata filter.** Every retrieval query must carry a
   `where={"company": "A"}` or `where={"company": "B"}` filter, or an
   equivalent post-filter that drops hits whose `company` metadata
   field does not match the expected company.
3. **Defence-in-depth re-filter.** `agents/runner._filter_hits_to_company`
   must continue to drop any hit whose `company` field does not match,
   even if a caller hands it mixed hits. This is the belt-and-braces
   guard that catches any bug in layer 1 or 2.

A future ChromaDB migration must include an isolation test file
mirroring `tests/test_retriever_isolation.py` (six tests covering
construction-time scoping, post-filtering, cross-company negative
queries, and the runner re-filter). All six must continue to pass on
both the TF-IDF and ChromaDB paths.

## 5. Evidence metadata that must remain unchanged

Every `RetrievalHit` returned to the LLM context must continue to carry
exactly these fields, in exactly these names:

* `kind` — `"chunk"` or `"table"`
* `id` — `"A_<n>"` / `"B_<n>"` (or `"A_t<n>"` / `"B_t<n>"` for
  tables)
* `company` — `"A"` or `"B"`
* `document_name` — original upload filename
* `document_sha256` — SHA-256 of the PDF bytes (already used as the
  storage key)
* `page_number` — 1-indexed page in the source PDF
* `ref_id` — chunk_id or table_id (same value as `id`)
* `snippet` — short text excerpt used in the LLM prompt

`AgentAnalysis.evidence[*]`, `ComparativeAnalysis.*.evidence[*]`, and
the comparator `kind` taxonomy (`fact`, `derived`, `insight`) are
schema-locked and must not be modified by the migration.

## 6. Local-only / no-paid-API constraint

The application must not depend on any paid or cloud LLM API, and must
not require any new paid or cloud embedding API. The generator and
embedder are both served from the same local Ollama process on
`OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`).

The application must continue to not read or modify the OpenClaw
global configuration. All configuration lives in the project-local
`backend/.env` file.

## 7. Recommended future embedding approach

If and when the migration is approved and implemented:

* **Embedding service:** Ollama on the existing
  `OLLAMA_BASE_URL`, calling `POST /api/embeddings` with
  `model=nomic-embed-text`. `nomic-embed-text` is Apache-2.0-licensed,
  ~274 MB on disk, 768-dimensional, and runs on CPU at ~1–2 s per
  small batch on a 4-core / 8 GB machine.
* **Vector store:** `chromadb>=0.5.0` in `PersistentClient` mode, one
  collection per company, persisted under
  `data/index/<company>/chroma/`. ChromaDB is MIT-licensed, runs
  in-process using SQLite + DuckDB + ONNX, and adds no new external
  service.
* **New Python dependencies:** `chromadb` only. The existing `httpx`
  client is reused for Ollama embeddings.
* **Activation:** gated behind an `EMBEDDING_PROVIDER` environment
  variable in `backend/.env`. When unset (the default), the existing
  TF-IDF `Retriever` continues to be used and nothing else changes.

Alternative embeddings (`sentence-transformers/all-MiniLM-L6-v2`,
`BAAI/bge-small-en-v1.5`, `intfloat/e5-small-v2`) were considered and
rejected for this hardware: they require pulling PyTorch and a second
model-loading framework, which raises disk and RAM use well above what
the 8 GB / 4 CPU / no-GPU development machine can comfortably absorb
alongside `qwen2.5:3b`.

## 8. TF-IDF must remain available as a fallback

The TF-IDF `Retriever` must not be deleted. It is the default retriever
when `EMBEDDING_PROVIDER` is unset, and it is the fallback used when:

* the ChromaDB index for a company has not yet been built (first
  query before the first embed pass has completed);
* `nomic-embed-text` is not yet pulled (`ollama pull nomic-embed-text`);
* the user explicitly opts out by leaving `EMBEDDING_PROVIDER`
  unset / set to `none`.

All existing tests must continue to pass against the TF-IDF path with
no changes to the tests themselves. Retiring TF-IDF is out of scope
and should only be considered after a full real-Ollama smoke cycle
showing equal-or-better metric-extraction recall on a known fixture.

## 9. Estimated future migration effort

If and when this migration is approved and implemented end-to-end:

* **Stage A — embedder + ChromaStore** (~1.5–2 h): embedder protocol,
  Ollama embedder, `ChromaStore` (add/query, metadata schema), unit
  tests.
* **Stage B — ChromaRetriever with TF-IDF fallback** (~1.5–2 h):
  sibling `ChromaRetriever` class implementing the same public
  surface as `Retriever`, internal fallback path, one-line import
  change in `agents/runner.py`, isolation tests mirroring
  `test_retriever_isolation.py`.
* **Stage C — docs and README** (~30 min): this document plus a
  short "Embedding-based retrieval (optional)" section in `README.md`.
* **Stage D — real-Ollama smoke** (~5 min, optional): embed two
  fixture PDFs, query across both companies, confirm Company A
  queries never return Company B chunks.

**Total: approximately 4–5 hours** of focused work for a full,
test-backed migration.

## 10. Status

**ChromaDB migration is NOT implemented yet.**

What is in the repository today:

* Stages 1, 2, 3 are complete and ship-tested (109/109 tests pass,
  22/22 Stage 2 verification checks pass).
* Retrieval is TF-IDF (pure numpy, no extra dependencies).
* The `Retriever` interface is interface-shaped and ready to host a
  future `ChromaRetriever` sibling, but that sibling does not exist
  in the repository.
* `chromadb` is **not** in `backend/requirements.txt`.
* `nomic-embed-text` is **not** pulled (`ollama pull` has not been
  run).
* `agents/runner.py` still imports `Retriever` from
  `app.retrieval.retriever`, not from any ChromaDB module.
* The comparator code, the agent schemas, and the FastAPI routes are
  unchanged and will remain unchanged through any future migration.

A future PR may add a ChromaDB-backed sibling retriever behind the
existing interface, but that PR is not part of the current release.
