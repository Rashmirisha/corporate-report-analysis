# DD — Dashboard / Frontend Integration Work

**Person:** Person 1 — Dashboard / Frontend
**Branch:** `feature/frontend-dashboard-fix`
**Repo:** `https://github.com/Rashmirisha/corporate-report-analysis`
**Scope:** Frontend (Vite + React + Tailwind) wired to the FastAPI backend, end-to-end through `/api/*`.

---

## 1. What was actually validated

Verified against a **single, clean** backend process (see §3). All endpoints are the
ones the dashboard calls:

| Step | Endpoint | Method | Verified |
| --- | --- | --- | --- |
| 1 | `/api/health` | GET | `{"status":"ok","stage":1,"version":"0.1.0"}` |
| 2 | `/api/corpus` | DELETE | `204` (reset for clean slate) |
| 3 | `/api/ingest/upload` | POST (A) | `200` with `UploadResponse` for Mahindra fixture PDF |
| 4 | `/api/ingest/upload` | POST (B) | `200` with `UploadResponse` for Tata Motors fixture PDF |
| 5 | `/api/agents/run?target=A` | POST | `200` — agent run accepted |
| 6 | `/api/agents/run?target=B` | POST | `200` — agent run accepted |
| 7 | `/api/agents/A/analysis` | GET | `200` — Company A analysis available |
| 8 | `/api/agents/B/analysis` | GET | `200` — Company B analysis available |
| 9 | `/api/comparison/run` | POST | `200` — comparison triggered |
| 10 | `/api/comparison` | GET | `200` — comparison status |

The dashboard (`DashboardPage.jsx`, `useDashboard.js`, `AnalysisControls.jsx`,
`UploadCard.jsx`, `CompanyOverviewCard.jsx`, `FinancialComparison.jsx`,
`EvidencePanel.jsx`) consumes exactly these routes via the Vite proxy
`/api/*` → `http://127.0.0.1:3101`.

## 2. Issue found and fixed (operational, not code)

**Issue.** Two `python.exe` processes were simultaneously bound to
`127.0.0.1:3101`:

- one from `backend\venv\Scripts\python.exe` (the project's venv), and
- one from a stale system Python (e.g. `C:\Program Files\Python312\python.exe`).

Whichever process lost the port-binding race caused intermittent
`ECONNRESET` to in-flight frontend requests, which surfaced as
"Analyze disabled" / failed uploads in the dashboard.

**Fix (operational).**

1. Killed all `python.exe` processes.
2. Started **exactly one** uvicorn:
   ```
   backend\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 3101
   ```
3. Re-ran the dashboard flow against the single backend — every step above passed.

No frontend code change was required.

## 3. Code review outcome

The dashboard frontend and its backend contract are consistent:

- `frontend/src/api/apiClient.js` calls only routes that exist in
  `backend/app/main.py`.
- `backend/app/schemas.py` (`UploadResponse`, `CorpusResponse`,
  `HealthResponse`) matches what `useDashboard.js` reads.
- `UploadCard.jsx` enforces PDF-only + replace mode + local error.
- `AnalysisControls.jsx` correctly gates Analyze/Compare by `ready` flags
  with spinners.
- `useDashboard.js` deduplicates in-flight requests and passes evidence
  through.
- `DashboardPage.jsx` renders overviews, strengths/weaknesses/risks,
  financial comparison, key differences, comparative insights, trends, and
  evidence panels.

No genuine bug was introduced by this branch and none was found in the
required Mahindra→A→Analyze, Tata→B→Analyze, Compare flow. Per the rule
"If the frontend is already correct, don't make artificial changes", no
application code was modified.

## 4. Out of scope (other teammates — not touched)

- ChromaDB / semantic RAG / embeddings.
- Backend persistence beyond the in-process store.
- Ollama runtime / model selection (`qwen2.5:3b` left in place).

## 5. Files in this commit

- `docs/DD_DASHBOARD_WORK.md` (this document).

No application code, no venvs, no environment files, no
`current_working_directory.txt` are staged.

## 6. How to reproduce locally

```powershell
# 0. Kill any stale uvicorn / python
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# 1. One clean backend
cd D:\Final_Year_Project\corporate-report-analysis\backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 3101

# 2. Smoke against the routes the dashboard uses (Mahindra + Tata fixtures)
node C:\Users\dhivyadharshini\AppData\Local\Temp\dd_smoke.mjs

# 3. (Optional) Open the dev UI
cd ..\frontend
npm run dev
# Open http://127.0.0.1:5173, upload Mahindra to A, Tata to B, click through.
```
