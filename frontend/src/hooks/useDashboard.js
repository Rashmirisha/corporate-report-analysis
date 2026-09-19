import { useCallback, useEffect, useReducer, useRef } from 'react'
import { apiClient } from '../api/apiClient'

/**
 * useDashboard — single source of truth for the dashboard data layer.
 *
 * Stage 4B wires the Stage-4A shell to the real FastAPI backend. The
 * hook owns:
 *
 *   - backend reachability (via /api/health)
 *   - corpus state (per company PDF upload status + UploadResponse)
 *   - agent analysis state (per company)
 *   - comparator state
 *   - in-flight operation flags so the UI can show "Uploading..." and
 *     disable duplicate requests.
 *
 * Architectural rules enforced:
 *
 *   - The frontend NEVER calls Ollama. All LLM traffic is proxied
 *     through FastAPI.
 *   - All data shown to the user comes from the backend's typed
 *     responses — nothing is fabricated here.
 *   - When the backend omits a field, the empty-state sentinel
 *     "Not available" is rendered by the components, never by us.
 *   - Evidence metadata (company / page / ref_id / snippet /
 *     document_name / document_sha256) is passed through unchanged.
 */

// ----------------------------- reducer -----------------------------

const initial = {
  // 'unknown' | 'online' | 'offline'
  backend: 'unknown',
  backendVersion: null,
  backendError: '',

  // { A: null | UploadResponse, B: null | UploadResponse }
  corpus: { A: null, B: null },
  corpusReady: false,

  // { A: { status, error, analysis }, B: ... } mirrors /api/agents/status
  agents: { A: { status: 'idle', error: null, analysis: null }, B: { status: 'idle', error: null, analysis: null } },

  // { status, error, analysis }
  comparison: { status: 'idle', error: null, analysis: null },

  // in-flight flags so we can disable buttons + render spinners.
  busy: {
    uploadA: false,
    uploadB: false,
    analyzeA: false,
    analyzeB: false,
    compare: false,
    reset: false,
    refresh: false,
  },

  // last user-visible error message (banner / toast).
  notice: '',
}

function reducer(state, action) {
  switch (action.type) {
    case 'BACKEND_ONLINE':
      return { ...state, backend: 'online', backendVersion: action.version || null, backendError: '' }
    case 'BACKEND_OFFLINE':
      return { ...state, backend: 'offline', backendError: action.error || 'Backend is not reachable.' }
    case 'SET_BUSY':
      return { ...state, busy: { ...state.busy, [action.flag]: action.value } }
    case 'SET_NOTICE':
      return { ...state, notice: action.message }
    case 'CORPUS_PARTIAL':
      return {
        ...state,
        corpus: { ...state.corpus, [action.company]: action.payload },
        corpusReady:
          (action.company === 'A' ? action.payload : state.corpus.A) !== null &&
          (action.company === 'B' ? action.payload : state.corpus.B) !== null,
      }
    case 'CORPUS_RESET':
      return {
        ...state,
        corpus: { A: null, B: null },
        corpusReady: false,
        agents: { A: { status: 'idle', error: null, analysis: null }, B: { status: 'idle', error: null, analysis: null } },
        comparison: { status: 'idle', error: null, analysis: null },
      }
    case 'AGENT_STATUS':
      return {
        ...state,
        agents: {
          ...state.agents,
          [action.company]: {
            status: action.payload?.status || 'idle',
            error: action.payload?.error || null,
            analysis: action.payload?.analysis ?? state.agents[action.company].analysis,
          },
        },
      }
    case 'AGENT_ANALYSIS':
      return {
        ...state,
        agents: {
          ...state.agents,
          [action.company]: {
            ...state.agents[action.company],
            status: 'completed',
            error: null,
            analysis: action.payload,
          },
        },
      }
    case 'COMPARISON_STATUS':
      return {
        ...state,
        comparison: {
          status: action.payload?.status || 'idle',
          error: action.payload?.error || null,
          analysis: action.payload?.analysis ?? state.comparison.analysis,
        },
      }
    case 'COMPARISON_ANALYSIS':
      return {
        ...state,
        comparison: { status: 'completed', error: null, analysis: action.payload },
      }
    default:
      return state
  }
}

// ----------------------------- helpers -----------------------------

const NOT_AVAILABLE = 'Not available'

function isUnavailable(text) {
  if (typeof text !== 'string') return false
  const t = text.trim().toLowerCase()
  return (
    t === NOT_AVAILABLE.toLowerCase() ||
    t === 'not available in the provided report.' ||
    t === 'not available in the provided reports.' ||
    t.startsWith('not available')
  )
}

// ------------------------------ hook ------------------------------

export function useDashboard() {
  const [state, dispatch] = useReducer(reducer, initial)
  // Prevent overlapping operations even if React batches calls.
  const guards = useRef({})

  /**
   * Wrap an async action so:
   *   - the corresponding `busy` flag toggles true/false
   *   - if the operation is already in-flight, it short-circuits
   *   - errors are surfaced via the `notice` field, not thrown
   */
  const runGuarded = useCallback(async (flag, fn) => {
    if (guards.current[flag]) {
      return null
    }
    guards.current[flag] = true
    dispatch({ type: 'SET_BUSY', flag, value: true })
    try {
      const result = await fn()
      return result
    } catch (err) {
      const message = err?.message || String(err)
      dispatch({ type: 'SET_NOTICE', message })
      return null
    } finally {
      guards.current[flag] = false
      dispatch({ type: 'SET_BUSY', flag, value: false })
    }
  }, [])

  // ---- backend reachability probe ----

  const probeBackend = useCallback(async () => {
    return runGuarded('refresh', async () => {
      try {
        const health = await apiClient.health()
        dispatch({ type: 'BACKEND_ONLINE', version: health?.version })
        return health
      } catch (err) {
        dispatch({ type: 'BACKEND_OFFLINE', error: err?.message || 'unreachable' })
        return null
      }
    })
  }, [runGuarded])

  // ---- corpus refresh ----

  const refreshCorpus = useCallback(async () => {
    return runGuarded('refresh', async () => {
      try {
        const corpus = await apiClient.getCorpus()
        // The Stage 1 corpus endpoint is keyed by state_a / state_b.
        // For the dashboard's "is the PDF ingested?" question, we only
        // need the metadata, not the full chunk text. So we map
        // state_a / state_b to a compact summary.
        const toMeta = (s) => {
          if (!s) return null
          return {
            company: s.company,
            document_name: s.source?.document_name,
            document_sha256: s.source?.document_sha256,
            page_count: s.source?.page_count || 0,
            chunk_count: s.chunk_count || 0,
            table_count: s.table_count || 0,
          }
        }
        dispatch({ type: 'CORPUS_PARTIAL', company: 'A', payload: toMeta(corpus?.state_a) })
        dispatch({ type: 'CORPUS_PARTIAL', company: 'B', payload: toMeta(corpus?.state_b) })
      } catch (err) {
        dispatch({ type: 'SET_NOTICE', message: err?.message || 'Failed to load corpus.' })
      }
    })
  }, [runGuarded])

  // ---- agents refresh ----

  const refreshAgents = useCallback(async () => {
    return runGuarded('refresh', async () => {
      try {
        const status = await apiClient.getAgentsStatus()
        for (const company of ['A', 'B']) {
          dispatch({ type: 'AGENT_STATUS', company, payload: status?.[company] })
        }
      } catch (err) {
        dispatch({ type: 'SET_NOTICE', message: err?.message || 'Failed to read agent status.' })
      }
    })
  }, [runGuarded])

  // ---- comparison refresh ----

  const refreshComparison = useCallback(async () => {
    return runGuarded('refresh', async () => {
      try {
        const status = await apiClient.getComparisonStatus()
        dispatch({ type: 'COMPARISON_STATUS', payload: status })
      } catch (err) {
        dispatch({ type: 'SET_NOTICE', message: err?.message || 'Failed to read comparison status.' })
      }
    })
  }, [runGuarded])

  /**
   * One bootstrap call: probe + corpus + agents + comparison. Called
   * once on mount, and again after every successful operation.
   */
  const refreshAll = useCallback(async () => {
    await probeBackend()
    if (state.backend === 'online') {
      await Promise.all([refreshCorpus(), refreshAgents(), refreshComparison()])
    }
  }, [probeBackend, refreshCorpus, refreshAgents, refreshComparison, state.backend])

  // Probe once on mount. If online, fetch all state.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const health = await runGuarded('refresh', async () => {
        try {
          const h = await apiClient.health()
          if (cancelled) return null
          dispatch({ type: 'BACKEND_ONLINE', version: h?.version })
          return h
        } catch (err) {
          if (!cancelled) {
            dispatch({ type: 'BACKEND_OFFLINE', error: err?.message || 'unreachable' })
          }
          return null
        }
      })
      if (health && !cancelled) {
        await Promise.all([refreshCorpus(), refreshAgents(), refreshComparison()])
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ---- actions ----

  const uploadPdf = useCallback(
    async (company, file) => {
      if (!file) {
        dispatch({ type: 'SET_NOTICE', message: 'No file selected.' })
        return null
      }
      const flag = company === 'A' ? 'uploadA' : 'uploadB'
      return runGuarded(flag, async () => {
        try {
          const res = await apiClient.uploadPdf(company, file)
          dispatch({ type: 'CORPUS_PARTIAL', company, payload: res })
          dispatch({ type: 'SET_NOTICE', message: `Uploaded ${res?.document_name || file.name} for Company ${company}.` })
          // After ingest, the agent/comparison state from before this
          // upload may be stale. Clear it on the client so the UI tells
          // the truth. The user must re-run agents on the new PDF.
          dispatch({ type: 'AGENT_STATUS', company, payload: { status: 'idle', error: null, analysis: null } })
          if (state.comparison.analysis) {
            dispatch({ type: 'COMPARISON_STATUS', payload: { status: 'idle', error: null, analysis: null } })
          }
          return res
        } catch (err) {
          dispatch({ type: 'SET_NOTICE', message: err?.message || 'Upload failed.' })
          throw err
        }
      })
    },
    [runGuarded, state.comparison.analysis],
  )

  const runAgent = useCallback(
    async (company) => {
      const flag = company === 'A' ? 'analyzeA' : 'analyzeB'
      return runGuarded(flag, async () => {
        // optimistic: mark running so UI shows spinner immediately.
        dispatch({ type: 'AGENT_STATUS', company, payload: { status: 'running', error: null } })
        try {
          await apiClient.runAgents(company)
          // After the run completes, fetch the persisted analysis so
          // the dashboard shows the full typed payload (not just the
          // condensed `results` map from /api/agents/run).
          const analysis = await apiClient.getAgentAnalysis(company)
          dispatch({ type: 'AGENT_ANALYSIS', company, payload: analysis })
          dispatch({ type: 'SET_NOTICE', message: `Agent ${company} finished.` })
          return analysis
        } catch (err) {
          dispatch({
            type: 'AGENT_STATUS',
            company,
            payload: { status: 'failed', error: err?.message || 'failed' },
          })
          dispatch({ type: 'SET_NOTICE', message: err?.message || `Agent ${company} failed.` })
          return null
        }
      })
    },
    [runGuarded],
  )

  const runComparisonAction = useCallback(async () => {
    return runGuarded('compare', async () => {
      dispatch({ type: 'COMPARISON_STATUS', payload: { status: 'running', error: null } })
      try {
        const analysis = await apiClient.runComparison()
        dispatch({ type: 'COMPARISON_ANALYSIS', payload: analysis })
        dispatch({ type: 'SET_NOTICE', message: 'Comparator finished.' })
        return analysis
      } catch (err) {
        dispatch({
          type: 'COMPARISON_STATUS',
          payload: { status: 'failed', error: err?.message || 'failed' },
        })
        dispatch({ type: 'SET_NOTICE', message: err?.message || 'Comparison failed.' })
        return null
      }
    })
  }, [runGuarded])

  const resetAll = useCallback(async () => {
    return runGuarded('reset', async () => {
      try {
        await apiClient.resetCorpus()
        dispatch({ type: 'CORPUS_RESET' })
        dispatch({ type: 'SET_NOTICE', message: 'Corpus, agents, and comparison cleared.' })
      } catch (err) {
        dispatch({ type: 'SET_NOTICE', message: err?.message || 'Reset failed.' })
      }
    })
  }, [runGuarded])

  const clearNotice = useCallback(() => dispatch({ type: 'SET_NOTICE', message: '' }), [])

  return {
    state,
    isUnavailable,
    uploadPdf,
    runAgent,
    runComparison: runComparisonAction,
    resetAll,
    refreshAll,
    refreshCorpus,
    refreshAgents,
    refreshComparison,
    probeBackend,
    clearNotice,
  }
}

export default useDashboard
