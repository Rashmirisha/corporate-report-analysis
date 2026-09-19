import Section from './Section'

/**
 * Side-by-side financial comparison. Stage 4B: renders the
 * `ComparativeAnalysis.financial_comparison` shape from the Stage 3
 * comparator.
 *
 * Backend contract:
 *   - a: List[ComparisonMetric]  — Company A's metrics
 *   - b: List[ComparisonMetric]  — Company B's metrics
 *   - narrative: str             — the comparator's overall summary line
 *   - narrative_kind: "fact" | "derived" | "insight"
 *   - evidence: List[ComparisonEvidence]
 *
 * Each ComparisonMetric carries `{ metric, value_text, unit?, year_or_period?, evidence[] }`.
 * Missing values use the literal "Not available in the provided reports." sentinel.
 *
 * Rules enforced here:
 *   - NEVER fabricate values. If `value_text` is unavailable, the cell
 *     shows "Not available".
 *   - Evidence IDs are preserved verbatim (`ref_id`) for traceability.
 *   - The two side tables are aligned by metric name (lowercased + trimmed).
 *     Metrics that only exist on one side are still shown in their side's column.
 */
function alignByMetric(a = [], b = []) {
  const map = new Map()
  for (const m of a) {
    map.set(`${m.company}:${m.metric}`, { a: m, b: null })
  }
  for (const m of b) {
    const key = `${m.company}:${m.metric}`
    const existing = map.get(key)
    if (existing) {
      existing.b = m
    } else {
      map.set(key, { a: null, b: m })
    }
  }
  return [...map.values()]
}

const UNAVAILABLE_SENTINELS = new Set([
  'not available in the provided reports.',
  'not available in the provided report.',
])

function isUnavailable(value) {
  if (typeof value !== 'string') return false
  const t = value.trim().toLowerCase()
  return UNAVAILABLE_SENTINELS.has(t) || t.startsWith('not available')
}

function MetricCell({ metric, isEmpty }) {
  return (
    <div>
      <div
        className={`text-sm ${
          isEmpty ? 'italic text-slate-400' : 'text-slate-800'
        }`}
      >
        {isEmpty ? 'Not available' : metric.value_text}
      </div>
      <div className="text-xs text-slate-500">
        {metric.year_or_period ? `${metric.year_or_period}` : ''}
        {metric.unit ? `${metric.year_or_period ? ' · ' : ''}${metric.unit}` : ''}
      </div>
    </div>
  )
}

export default function FinancialComparison({ comparison = null }) {
  const fc = comparison?.financial_comparison
  const isEmpty = !fc
  const a = Array.isArray(fc?.a) ? fc.a : []
  const b = Array.isArray(fc?.b) ? fc.b : []
  const rows = isEmpty ? [] : alignByMetric(a, b)

  return (
    <Section
      title="Financial comparison"
      subtitle="Side-by-side comparison of the financial metrics the comparator extracted for each company."
      isEmpty={isEmpty}
    >
      {!isEmpty ? (
        <div className="space-y-4">
          {fc.narrative ? (
            <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-800">
              {fc.narrative}
            </p>
          ) : null}

          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-slate-200 text-left">
                  <th className="w-1/3 pb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                    Metric
                  </th>
                  <th className="w-1/3 pb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                    Company A
                  </th>
                  <th className="w-1/3 pb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                    Company B
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-3 text-sm italic text-slate-400">
                      Not available
                    </td>
                  </tr>
                ) : (
                  rows.map(({ a: aM, b: bM }, idx) => {
                    const metricName = (aM?.metric || bM?.metric || '').trim() || 'Untitled metric'
                    const aEmpty = !aM || isUnavailable(aM.value_text)
                    const bEmpty = !bM || isUnavailable(bM.value_text)
                    return (
                      <tr
                        key={`${metricName}-${idx}`}
                        className="border-b border-slate-100 last:border-b-0"
                      >
                        <th
                          scope="row"
                          className="w-1/3 py-2 pr-4 text-left align-top text-sm font-medium text-slate-700"
                        >
                          {metricName}
                        </th>
                        <td className="w-1/3 py-2 pr-4 align-top">
                          {aEmpty ? (
                            <span className="text-sm italic text-slate-400">Not available</span>
                          ) : (
                            <MetricCell metric={aM} />
                          )}
                        </td>
                        <td className="w-1/3 py-2 align-top">
                          {bEmpty ? (
                            <span className="text-sm italic text-slate-400">Not available</span>
                          ) : (
                            <MetricCell metric={bM} />
                          )}
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </Section>
  )
}
