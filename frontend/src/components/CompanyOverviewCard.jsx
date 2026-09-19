/**
 * Single-company overview card. Stage 4B: bound to the real
 * `AgentAnalysis` shape returned by /api/agents/{company}/analysis.
 *
 * The four sections are `EvidenceBlock` objects:
 *   { summary: str, evidence: [EvidenceRef, ...] }
 *
 * Rules enforced:
 *   - summary text is rendered verbatim from the backend.
 *   - if a section is absent, the cell shows "Not available".
 *   - evidence metadata is preserved; only the first 3 snippets are
 *     previewed inline so the card stays scannable.
 */
import { useState } from 'react'

const ACCENT = {
  A: {
    border: 'border-brand-200',
    chip: 'bg-brand-50 text-brand-700',
    label: 'Company A',
  },
  B: {
    border: 'border-emerald-200',
    chip: 'bg-emerald-50 text-emerald-700',
    label: 'Company B',
  },
}

const UNAVAILABLE_SENTINELS = new Set([
  'not available in the provided report.',
  'not available in the provided reports.',
])

function isUnavailable(text) {
  if (typeof text !== 'string') return false
  const t = text.trim().toLowerCase()
  return UNAVAILABLE_SENTINELS.has(t) || t.startsWith('not available')
}

function Field({ label, block }) {
  const summary = block?.summary
  const summaryEmpty = !summary || isUnavailable(summary)
  const evidence = Array.isArray(block?.evidence) ? block.evidence : []
  const showEvidence = !summaryEmpty && evidence.length > 0

  const [expanded, setExpanded] = useState(false)
  const visibleEvidence = expanded ? evidence : evidence.slice(0, 2)

  return (
    <div className="rounded-md border border-slate-100 bg-slate-50 p-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div
        className={`mt-1 text-sm ${
          summaryEmpty ? 'italic text-slate-400' : 'text-slate-800'
        }`}
      >
        {summaryEmpty ? 'Not available' : summary}
      </div>
      {showEvidence ? (
        <div className="mt-2 space-y-1">
          {visibleEvidence.map((ev, idx) => (
            <div
              key={`${ev.ref_id || idx}`}
              className="text-xs text-slate-500"
            >
              <span className="font-mono text-[10px] text-slate-400">
                {ev.ref_id}
              </span>
              {ev.page_number ? (
                <span className="ml-2">p.{ev.page_number}</span>
              ) : null}
              {ev.snippet ? (
                <span className="ml-2 truncate text-slate-600">
                  “{ev.snippet.length > 80 ? `${ev.snippet.slice(0, 80)}…` : ev.snippet}”
                </span>
              ) : null}
            </div>
          ))}
          {evidence.length > 2 ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-brand-700 hover:underline"
            >
              {expanded ? 'Show fewer sources' : `Show all ${evidence.length} sources`}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export default function CompanyOverviewCard({ company, analysis = null }) {
  const accent = ACCENT[company] || ACCENT.A
  const isEmpty = !analysis

  return (
    <div
      className={`rounded-lg border ${accent.border} bg-white p-5 shadow-sm`}
    >
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900">
          {accent.label} overview
        </h3>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${accent.chip}`}
        >
          Company {company}
        </span>
      </div>

      {isEmpty ? (
        <p className="text-sm italic text-slate-400">Not available</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Company overview"
            block={analysis.company_overview}
          />
          <Field
            label="Operational information"
            block={analysis.operational_information}
          />
          <Field
            label="Strategic information"
            block={analysis.strategic_information}
          />
          <Field
            label="Business information"
            block={analysis.business_information}
          />
        </div>
      )}

      {analysis?.financial_performance?.summary ||
      (Array.isArray(analysis?.financial_performance?.key_metrics) &&
        analysis.financial_performance.key_metrics.length > 0) ? (
        <div className="mt-4 rounded-md border border-slate-100 bg-slate-50 p-3">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Financial performance (per-company)
          </div>
          <div className="mt-1 text-sm text-slate-800">
            {analysis.financial_performance.summary &&
            !isUnavailable(analysis.financial_performance.summary)
              ? analysis.financial_performance.summary
              : 'Not available'}
          </div>
          {Array.isArray(analysis.financial_performance.key_metrics) &&
          analysis.financial_performance.key_metrics.length > 0 ? (
            <ul className="mt-2 space-y-1 text-xs text-slate-600">
              {analysis.financial_performance.key_metrics.map((m, idx) => (
                <li key={`${m.metric}-${idx}`}>
                  <span className="font-medium text-slate-700">{m.metric}:</span>{' '}
                  {isUnavailable(m.value_text) ? (
                    <span className="italic text-slate-400">Not available</span>
                  ) : (
                    <>
                      {m.value_text}
                      {m.unit ? ` ${m.unit}` : ''}
                      {m.year_or_period ? ` (${m.year_or_period})` : ''}
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
