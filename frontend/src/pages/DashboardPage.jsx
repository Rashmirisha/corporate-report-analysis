import Header from '../components/Header'
import UploadCard from '../components/UploadCard'
import AnalysisControls from '../components/AnalysisControls'
import CompanyOverviewCard from '../components/CompanyOverviewCard'
import FinancialComparison from '../components/FinancialComparison'
import ListSection from '../components/ListSection'
import EvidencePanel from '../components/EvidencePanel'
import { useDashboard } from '../hooks/useDashboard'

/**
 * Dashboard page. Stage 4B: connected to the FastAPI backend.
 *
 * Data flow:
 *   - useDashboard() owns every network call, in-flight guard, and
 *     typed backend response.
 *   - This page derives the section inputs from the hook state and
 *     wires callbacks into AnalysisControls + UploadCard.
 *
 * Hard rules enforced in this page:
 *   - NEVER invent company names. We use `company_a_name` /
 *     `company_b_name` only when the comparator returns them.
 *   - NEVER fabricate values. Empty arrays / unavailable summaries
 *     render as "Not available" via the section components.
 *   - All LLM traffic stays in the backend (FastAPI -> Ollama).
 *   - Evidence metadata is shown verbatim.
 *   - Duplicate requests are blocked by the hook's `busy` map.
 */
export default function DashboardPage() {
  const {
    state,
    uploadPdf,
    runAgent,
    runComparison,
    resetAll,
    refreshAll,
    clearNotice,
  } = useDashboard()

  const corpus = state.corpus || { A: null, B: null }
  const agents = state.agents || {}
  const comparison = state.comparison || {}
  const busy = state.busy || {}

  // Convenience booleans for AnalysisControls.
  const ready = {
    A: !!corpus.A && !busy.uploadA,
    B: !!corpus.B && !busy.uploadB,
    bothAnalyses:
      agents.A?.status === 'completed' &&
      agents.B?.status === 'completed' &&
      !busy.compare,
  }

  const uploadStatus = {
    A: busy.uploadA
      ? 'uploading'
      : corpus.A
      ? 'uploaded'
      : state.notice && state.notice.toLowerCase().includes('upload')
      ? 'error'
      : 'idle',
    B: busy.uploadB
      ? 'uploading'
      : corpus.B
      ? 'uploaded'
      : state.notice && state.notice.toLowerCase().includes('upload')
      ? 'error'
      : 'idle',
  }

  const headerSubtitle = (() => {
    const a = comparison?.analysis?.company_a_name
    const b = comparison?.analysis?.company_b_name
    if (a && b) return `${a}  vs  ${b}`
    return 'Compare two annual reports with isolated AI agents and evidence-grounded insights.'
  })()

  return (
    <div className="min-h-full bg-slate-50">
      <Header subtitle={headerSubtitle} />

      <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
        {/* Backend status / notice banner */}
        <BackendBanner
          state={state}
          onRetry={refreshAll}
          onDismiss={clearNotice}
        />

        {/* Upload row */}
        <section aria-label="Uploads" className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900">
              Upload annual reports
            </h2>
            <span className="text-xs text-slate-500">
              Each PDF is processed by an isolated agent.
            </span>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <UploadCard
              company="A"
              label="Company A PDF"
              accent="brand"
              meta={corpus.A}
              status={uploadStatus.A}
              errorMsg={state.notice}
              onUpload={uploadPdf}
              onClear={(c) => {
                // A "clear" gesture just clears local UI state — the
                // server-side corpus is only cleared via the "Reset all"
                // button in AnalysisControls, so we never silently drop
                // ingested data.
                if (state.backend !== 'online') return
              }}
            />
            <UploadCard
              company="B"
              label="Company B PDF"
              accent="emerald"
              meta={corpus.B}
              status={uploadStatus.B}
              errorMsg={state.notice}
              onUpload={uploadPdf}
              onClear={(c) => {
                if (state.backend !== 'online') return
              }}
            />
          </div>
        </section>

        {/* Analysis controls */}
        <AnalysisControls
          busy={busy}
          ready={ready}
          agents={agents}
          comparison={comparison}
          onAnalyzeA={() => runAgent('A')}
          onAnalyzeB={() => runAgent('B')}
          onCompare={runComparison}
          onReset={resetAll}
        />

        {/* Company overviews (Stage 2) */}
        <section aria-label="Company overviews" className="space-y-3">
          <h2 className="text-lg font-semibold text-slate-900">
            Company overviews
          </h2>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <CompanyOverviewCard
              company="A"
              analysis={agents.A?.analysis || null}
            />
            <CompanyOverviewCard
              company="B"
              analysis={agents.B?.analysis || null}
            />
          </div>
        </section>

        {/* Per-company strengths/weaknesses/risks (Stage 2) */}
        <section aria-label="Strengths, weaknesses, risks" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ListSection
            title="Strengths — Company A"
            items={agents.A?.analysis?.strengths}
          />
          <ListSection
            title="Strengths — Company B"
            items={agents.B?.analysis?.strengths}
          />
          <ListSection
            title="Weaknesses — Company A"
            items={agents.A?.analysis?.weaknesses}
          />
          <ListSection
            title="Weaknesses — Company B"
            items={agents.B?.analysis?.weaknesses}
          />
          <ListSection
            title="Risks — Company A"
            items={agents.A?.analysis?.risks}
          />
          <ListSection
            title="Risks — Company B"
            items={agents.B?.analysis?.risks}
          />
        </section>

        {/* Stage 3: financials + side-by-side comparisons */}
        <FinancialComparison comparison={comparison.analysis} />

        <section aria-label="Side-by-side comparison sections" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ComparisonSideSection
            title="Overview comparison"
            section={comparison.analysis?.overview_comparison}
          />
          <ComparisonSideSection
            title="Operational comparison"
            section={comparison.analysis?.operational_comparison}
          />
          <ComparisonSideSection
            title="Strategic comparison"
            section={comparison.analysis?.strategic_comparison}
          />
          <ComparisonSideSection
            title="Business comparison"
            section={comparison.analysis?.business_comparison}
          />
        </section>

        {/* Key differences + AI insights (Stage 3) */}
        <section aria-label="Key differences and insights" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ListSection
            title="Key Differences"
            subtitle="Specific points where the two companies diverge, extracted by the comparator."
            items={comparison.analysis?.key_differences}
          />
          <ListSection
            title="Comparative / AI Insights"
            subtitle="Overall insights from the comparator. Tagged 'fact', 'derived', or 'insight'."
            items={comparison.analysis?.overall_comparative_insights}
          />
        </section>

        <section aria-label="Trends">
          <ListSection
            title="Trends"
            subtitle="Patterns observed across both reports."
            items={comparison.analysis?.trends}
          />
        </section>

        {/* Evidence */}
        <section aria-label="Evidence" className="space-y-4">
          <h2 className="text-lg font-semibold text-slate-900">
            Evidence &amp; sources
          </h2>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <EvidencePanel
              title="Evidence — Company A"
              items={flattenAgentEvidence(agents.A?.analysis, ['company_overview', 'operational_information', 'strategic_information', 'business_information', 'financial_performance'])}
            />
            <EvidencePanel
              title="Evidence — Company B"
              items={flattenAgentEvidence(agents.B?.analysis, ['company_overview', 'operational_information', 'strategic_information', 'business_information', 'financial_performance'])}
            />
            <EvidencePanel
              title="Evidence — Comparator"
              items={comparison.analysis?.evidence}
            />
          </div>
        </section>

        <footer className="pt-4 text-center text-xs text-slate-500">
          Stage 4B — dashboard wired to FastAPI → retrieval → Ollama
          (qwen2.5:3b). No LLM traffic originates in the browser.
        </footer>
      </main>
    </div>
  )
}

// ----------------------------- helpers -----------------------------

function flattenAgentEvidence(analysis, sections) {
  if (!analysis) return null
  const out = []
  for (const sec of sections) {
    const block = analysis[sec]
    if (!block) continue
    if (Array.isArray(block.evidence)) out.push(...block.evidence)
    if (Array.isArray(block.key_metrics)) {
      for (const m of block.key_metrics) {
        if (Array.isArray(m.evidence)) out.push(...m.evidence)
      }
    }
  }
  for (const group of ['strengths', 'weaknesses', 'risks', 'important_observations']) {
    if (Array.isArray(analysis[group])) {
      for (const item of analysis[group]) {
        if (Array.isArray(item.evidence)) out.push(...item.evidence)
      }
    }
  }
  return out
}

function BackendBanner({ state, onRetry, onDismiss }) {
  if (state.backend === 'offline') {
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
      >
        <span>
          Backend unreachable. Start it with{' '}
          <code className="rounded bg-rose-100 px-1.5 py-0.5 text-xs">
            cd backend; .venv\Scripts\python.exe -m uvicorn app.main:app --port 3101
          </code>
          {state.backendError ? ` — ${state.backendError}` : ''}
        </span>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-rose-300 px-3 py-1 text-xs font-medium text-rose-800 hover:bg-rose-100"
        >
          Retry
        </button>
      </div>
    )
  }

  if (state.notice) {
    return (
      <div
        role="status"
        className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
      >
        <span>{state.notice}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-md border border-amber-300 px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
        >
          Dismiss
        </button>
      </div>
    )
  }

  return null
}

function ComparisonSideSection({ title, section }) {
  if (!section) {
    return (
      <ListSection
        title={title}
        subtitle="Stage 3 comparator output."
        items={null}
      />
    )
  }

  // Render a compact summary for each side, plus the narrative.
  const a = section.a
  const b = section.b

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <header className="mb-3">
        <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      </header>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SideCard side={a} />
        <SideCard side={b} />
      </div>
      {section.narrative ? (
        <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm text-slate-800">
          {section.narrative}
        </p>
      ) : null}
      {Array.isArray(section.evidence) && section.evidence.length > 0 ? (
        <EvidencePanel title="Sources" items={section.evidence} />
      ) : null}
    </div>
  )
}

function SideCard({ side }) {
  if (!side) {
    return (
      <div className="rounded-md border border-slate-100 bg-slate-50 p-3 text-sm italic text-slate-400">
        Not available
      </div>
    )
  }
  const summary = side.summary
  const empty = !summary || summary.trim().toLowerCase().startsWith('not available')
  const chip =
    side.company === 'A'
      ? 'bg-brand-50 text-brand-700'
      : side.company === 'B'
      ? 'bg-emerald-50 text-emerald-700'
      : 'bg-slate-100 text-slate-700'
  return (
    <div className="rounded-md border border-slate-100 bg-slate-50 p-3">
      <div className="flex items-center justify-between">
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${chip}`}
        >
          Company {side.company || '?'}
        </span>
        <span className="text-xs text-slate-500">
          {(side.evidence?.length || 0)} sources
        </span>
      </div>
      <div
        className={`mt-2 text-sm ${
          empty ? 'italic text-slate-400' : 'text-slate-800'
        }`}
      >
        {empty ? 'Not available' : summary}
      </div>
    </div>
  )
}
