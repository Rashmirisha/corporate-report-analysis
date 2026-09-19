/**
 * apiClient.js
 *
 * Thin wrapper around `fetch` for the dashboard. Every request goes
 * through the Vite dev-server proxy at `/api/*` -> FastAPI backend on
 * http://127.0.0.1:3101 (see vite.config.js). The frontend never talks
 * to Ollama directly — PDF + retrieval + agent + Ollama all live in
 * the backend.
 *
 * Stage 4B adds:
 *   - uploadPdf(company, file): multipart upload for /api/ingest/upload
 *   - getAgentsStatus(): /api/agents/status (per-company lifecycle)
 *   - getComparisonStatus(): /api/comparison (cached run state)
 *   - resetAll(): convenience to wipe corpus + agents + comparison
 *
 * All functions throw Error on non-2xx so callers can decide how to
 * surface failures. The status banner in DashboardPage catches these
 * and renders them inline.
 */

const API_BASE = '/api'

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`
  const init = {
    method: options.method || 'GET',
    ...options,
    // `body` / `formData` are caller-supplied. We strip headers so
    // the browser / fetch implementation can set the right Content-Type
    // (multipart with boundary for FormData, application/json otherwise).
    headers: {
      Accept: 'application/json',
      ...(options.headers || {}),
    },
  }
  // fetch must NOT have a body for GET / HEAD.
  if ((init.method === 'GET' || init.method === 'HEAD') && !('body' in init)) {
    // no-op
  }

  const response = await fetch(url, init)
  if (!response.ok) {
    let detail = ''
    try {
      // FastAPI detail fields end up as JSON for some routes; read once
      // and try JSON first, fall back to text.
      const contentType = response.headers.get('content-type') || ''
      if (contentType.includes('application/json')) {
        const errBody = await response.json().catch(() => null)
        if (errBody && typeof errBody === 'object' && 'detail' in errBody) {
          detail = String(errBody.detail)
        } else if (errBody) {
          detail = JSON.stringify(errBody)
        }
      } else {
        detail = await response.text()
      }
    } catch (_) {
      // ignore: body may already have been consumed
    }
    const err = new Error(
      detail ||
        `API ${init.method} ${path} failed: ${response.status} ${response.statusText}`,
    )
    err.status = response.status
    err.path = path
    throw err
  }

  // 204 No Content — return null.
  if (response.status === 204) {
    return null
  }

  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return response.json()
  }
  return response.text()
}

export const apiClient = {
  // Health / liveness (used by the dashboard to confirm backend reachability).
  health: () => request('/health'),

  // --- Stage 1: corpus / ingestion ---
  getCorpus: () => request('/corpus'),
  getCorpusFor: (company) => request(`/corpus/${company}`),
  resetCorpus: () => request('/corpus', { method: 'DELETE' }),
  /**
   * Upload one PDF to Company A or Company B.
   * @param {'A'|'B'} company
   * @param {File} file
   * @returns {Promise<UploadResponse>}
   */
  uploadPdf: (company, file) => {
    const form = new FormData()
    form.append('company', company)
    form.append('file', file, file.name)
    // Important: do not set Content-Type; the browser sets the boundary.
    return request('/ingest/upload', {
      method: 'POST',
      body: form,
      headers: {}, // strip Accept override — fetch still sends it
    })
  },

  // --- Stage 2: agents ---
  getAgentsStatus: () => request('/agents/status'),
  /**
   * Run Agent A and/or B.
   * @param {'A'|'B'|'both'} target
   */
  runAgents: (target = 'both') =>
    request(`/agents/run?target=${encodeURIComponent(target)}`, {
      method: 'POST',
    }),
  getAgentAnalysis: (company) => request(`/agents/${company}/analysis`),
  clearAgentAnalysis: (company) =>
    request(`/agents/${company}`, { method: 'DELETE' }),

  // --- Stage 3: comparator ---
  runComparison: () => request('/comparison/run', { method: 'POST' }),
  getComparisonStatus: () => request('/comparison'),
  clearComparison: () => request('/comparison', { method: 'DELETE' }),
}

export default apiClient
